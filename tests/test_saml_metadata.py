#!/usr/bin/env python3
"""
Reading an IdP's metadata on the server.

Standalone script — run from the repo root:
    python3 tests/test_saml_metadata.py

The Auth tab's "paste your IdP's metadata" box used to parse the XML in the
browser. The XML is untrusted, so the server reads it now, with a parser that
refuses DTDs and entity declarations. The properties worth proving:

  * the three fields come out right for a normal IdP, a POST-only IdP and an
    IdP with separate signing and encryption keys,
  * bad input is refused with a message fit to show, not a stack trace,
  * a document that tries to read a file, or to expand entities, is refused
    and nothing from the file reaches the response,
  * only an admin may call it, and the size is bounded.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="pktwifi-saml-"))
(TMP / "config.yaml").write_text(
    f"install_dir: {TMP}\n"
    f"secret_key: {'a' * 64}\n"
    f"credential_key: {Fernet.generate_key().decode()}\n"
    f"suite_token: ''\n"
)
os.environ["PKTWIFI_CONFIG"] = str(TMP / "config.yaml")
os.environ["PKTWIFI_INSTALL_DIR"] = str(TMP)
os.environ["PKTWIFI_ADMIN_PASSWORD"] = "admin-test-password"
sys.path.insert(0, str(REPO_ROOT))

import sqlite3                                      # noqa: E402

from fastapi.testclient import TestClient           # noqa: E402

from app.auth.local import hash_password            # noqa: E402
from app.main import app                            # noqa: E402

FAILURES: list[str] = []
NS = ('xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
      'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"')
REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
CERT_A = "MIIDdzCCAl+gAwIBAgIEAAAA"
CERT_B = "MIIEvgIBADANBgkqhkiG9w0B"


def check(label: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not passed else ""))
    if not passed:
        FAILURES.append(label)


def key(use: str | None, cert: str) -> str:
    u = f' use="{use}"' if use else ""
    return (f'<md:KeyDescriptor{u}><ds:KeyInfo><ds:X509Data>'
            f'<ds:X509Certificate>\n  {cert[:12]}\n  {cert[12:]}\n</ds:X509Certificate>'
            f'</ds:X509Data></ds:KeyInfo></md:KeyDescriptor>')


def sso(binding: str, url: str) -> str:
    return f'<md:SingleSignOnService Binding="{binding}" Location="{url}"/>'


def metadata(*parts: str, entity: str = "https://idp.example.com/metadata") -> str:
    return (f'<?xml version="1.0"?><md:EntityDescriptor {NS} entityID="{entity}">'
            f'<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
            + "".join(parts) + "</md:IDPSSODescriptor></md:EntityDescriptor>")


def main() -> int:
    with TestClient(app) as client:
        def token(user: str, pw: str) -> dict:
            r = client.post("/api/auth/login", json={"username": user, "password": pw})
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        admin = token("admin", "admin-test-password")
        conn = sqlite3.connect(str(TMP / "pktwifi.db"))
        conn.execute("INSERT INTO users (username, email, hashed_password, role) VALUES ('view', 'v@example.com', ?, 'viewer')",
                     (hash_password("viewer-pass"),))
        conn.commit()
        conn.close()
        viewer = token("view", "viewer-pass")

        def parse(xml: str, headers=admin):
            return client.post("/api/settings/saml/parse-metadata", json={"xml": xml}, headers=headers)

        print("── a normal IdP ──")
        r = parse(metadata(key("signing", CERT_A), sso(POST, "https://idp.example.com/post"),
                           sso(REDIRECT, "https://idp.example.com/redirect")))
        body = r.json()
        check("it succeeds", r.status_code == 200, r.text)
        check("the entity ID is read", body.get("entity_id") == "https://idp.example.com/metadata", str(body))
        check("the redirect endpoint is preferred", body.get("sso_url") == "https://idp.example.com/redirect", str(body))
        check("the certificate has its whitespace removed", body.get("cert") == CERT_A, str(body))

        print("\n── other shapes ──")
        r = parse(metadata(key(None, CERT_A), sso(POST, "https://idp.example.com/post")))
        check("a POST-only IdP still yields its endpoint", r.status_code == 200 and r.json()["sso_url"] == "https://idp.example.com/post", r.text)
        check("a key with no use is taken as the signing key", r.json().get("cert") == CERT_A, r.text)
        r = parse(metadata(key("encryption", CERT_B), key("signing", CERT_A), sso(REDIRECT, "https://idp.example.com/r")))
        check("with separate keys the signing one is chosen", r.json().get("cert") == CERT_A, r.text)
        r = parse(metadata(key("encryption", CERT_B), sso(REDIRECT, "https://idp.example.com/r")))
        check("an encryption-only key is better than none", r.json().get("cert") == CERT_B, r.text)

        print("\n── bad input ──")
        r = parse("this is not xml <<<")
        check("garbage is refused as invalid XML", r.status_code == 400 and "Invalid XML" in r.json()["detail"], r.text)
        r = parse(f'<md:EntityDescriptor {NS} entityID="https://sp.example.com"><md:SPSSODescriptor '
                  f'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"/></md:EntityDescriptor>')
        check("metadata without an IdP is refused", r.status_code == 400 and "No SAML IdP data" in r.json()["detail"], r.text)
        check("an empty body is refused", parse("").status_code == 422)
        check("an oversize body is refused", parse("<a>" + "x" * 600_000 + "</a>").status_code == 422)
        check("a missing body is refused", client.post("/api/settings/saml/parse-metadata", json={}, headers=admin).status_code == 422)

        print("\n── hostile input ──")
        secret = TMP / "secret.txt"
        secret.write_text("TOP-SECRET-CONTENT")
        xxe = (f'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY x SYSTEM "file://{secret}">]>'
               f'<md:EntityDescriptor {NS} entityID="&x;"><md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
               + sso(REDIRECT, "https://idp.example.com/r") + "</md:IDPSSODescriptor></md:EntityDescriptor>")
        r = parse(xxe)
        check("a document that reads a file is refused", r.status_code == 400, r.text)
        check("and nothing from the file is returned", "TOP-SECRET" not in r.text, r.text)
        laughs = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                  f'<md:EntityDescriptor {NS} entityID="&b;"/>')
        r = parse(laughs)
        check("entity expansion is refused", r.status_code == 400, r.text)
        r = parse(metadata(sso(REDIRECT, "https://idp.example.com/r"), entity="<script>alert(1)</script>"))
        check("markup in a value comes back as plain data", r.status_code in (200, 400) and "traceback" not in r.text.lower())

        print("\n── who may call it ──")
        check("a viewer is refused", parse(metadata(sso(REDIRECT, "https://idp.example.com/r")), headers=viewer).status_code == 403)
        check("an anonymous caller is refused", parse(metadata(sso(REDIRECT, "https://idp.example.com/r")), headers={}).status_code == 401)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Exception text that is safe to store or show.

An httpx error carries the URL it was calling, and a URL can carry credentials:
`user:pass@host`, or a key in the query string. Error text is saved on the
collector row and returned to the browser, so it passes through here first.
The scheme, host and path stay — they are what an admin needs to tell which
call failed — but userinfo and query values are replaced.
"""
from __future__ import annotations

import re

_USERINFO = re.compile(r"(https?://)[^/\s@'\"]+@")
_QUERY = re.compile(r"(https?://[^\s?#'\"]+)\?[^\s'\"]*")


def redact(text: str) -> str:
    return _QUERY.sub(r"\1?…", _USERINFO.sub(r"\1***@", text))


def describe_exception(exc: BaseException, *, with_type: bool = False) -> str:
    """Redacted message of an exception, falling back to its type name when it
    has none (httpx.ConnectTimeout, for one, prints as an empty string)."""
    text = redact(str(exc))
    if not text:
        return type(exc).__name__
    return f"{type(exc).__name__}: {text}" if with_type else text

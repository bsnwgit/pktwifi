// Panels and fields used by the main Settings page (auth, backups, log forwarding, resonance).
import { useEffect, useState } from 'react'
import {
  api,
} from '../../api/client'
import { copyToClipboard } from '../../utils/clipboard'
import { Field, NumberInput, TextInput } from './shared'

export function SendTestButton({ channel }: { channel: string }) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'sent' | 'failed' | 'skipped'>('idle')
  const [detail, setDetail] = useState('')

  const run = async () => {
    setStatus('loading')
    setDetail('')
    try {
      const res = await api.testNotification(channel)
      setStatus(res.status as 'sent' | 'failed' | 'skipped')
      setDetail(res.detail || '')
    } catch (e) {
      setStatus('failed')
      setDetail(String(e))
    }
  }

  return (
    <div className="flex items-center gap-3 mt-2 mb-1">
      <button
        onClick={run}
        disabled={status === 'loading'}
        className="px-3 py-1.5 text-xs rounded-lg border border-gray-600 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {status === 'loading' ? 'Sending…' : 'Send Test'}
      </button>
      {status === 'sent'    && <span className="text-xs text-green-400">✓ Sent{detail ? ` — ${detail}` : ''}</span>}
      {status === 'skipped' && <span className="text-xs text-yellow-400">⚠ Skipped — {detail}</span>}
      {status === 'failed'  && <span className="text-xs text-red-400">✗ Failed — {detail}</span>}
    </div>
  )
}

// ── Snapshot files vary per backup, so the checkbox set is derived from
// what's actually in that snapshot ──
export function SnapshotRestoreRow({ snapshot, onRestored }: {
  snapshot: { name: string; path: string; size_bytes: number; files: string[] }
  onRestored: (name: string, result: Record<string, string>) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set(snapshot.files))
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggle = (f: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(f)) next.delete(f); else next.add(f)
      return next
    })
  }

  const restore = async () => {
    if (selected.size === 0) return
    const which = selected.size === snapshot.files.length ? 'all files' : Array.from(selected).join(', ')
    if (!window.confirm(`Restore ${which} from ${snapshot.name}?\n\nThis overwrites current data and cannot be undone.`)) return
    setRunning(true)
    setError(null)
    try {
      const result = await api.restoreSnapshot(snapshot.name, Array.from(selected))
      onRestored(snapshot.name, result)
      setExpanded(false)
    } catch (e: any) {
      setError(e.message || 'Restore failed')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="text-xs text-white">
      <div className="flex items-center gap-3">
        <span className="font-mono">{snapshot.name}</span>
        <span className="text-white">{(snapshot.size_bytes / 1024 / 1024).toFixed(1)} MB</span>
        <span className="text-white">{snapshot.files.join(', ')}</span>
        <button onClick={() => setExpanded(v => !v)} className="text-blue-400 hover:text-blue-300 underline">
          {expanded ? 'Cancel' : 'Restore…'}
        </button>
      </div>
      {expanded && (
        <div className="mt-2 mb-3 ml-4 space-y-2 bg-gray-800/60 rounded-lg p-3">
          <p className="text-white">Choose which files to restore:</p>
          <div className="flex flex-wrap gap-4">
            {snapshot.files.map(f => (
              <label key={f} className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" checked={selected.has(f)} onChange={() => toggle(f)} className="accent-amber-600" />
                <span className="font-mono">{f}</span>
              </label>
            ))}
          </div>
          <button onClick={restore} disabled={running || selected.size === 0}
            className="bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs rounded-lg px-3 py-1.5 transition-colors">
            {running ? 'Restoring…' : 'Restore Selected'}
          </button>
          {error && <p className="text-red-400 mt-1">{error}</p>}
        </div>
      )}
    </div>
  )
}

export function RestartServiceRow() {
  const [state, setState] = useState<'idle' | 'restarting' | 'done' | 'error'>('idle')

  const restart = async () => {
    if (state === 'restarting') return
    setState('restarting')
    try {
      await api.restartService()
      setState('done')
      setTimeout(() => setState('idle'), 8000)
    } catch {
      setState('error')
      setTimeout(() => setState('idle'), 4000)
    }
  }

  return (
    <div className="grid grid-cols-3 gap-4 items-start py-4 border-b border-gray-800">
      <div>
        <p className="text-sm font-medium text-white">Restart Service</p>
        <p className="text-xs text-white mt-0.5">Apply backend changes or recover from errors</p>
      </div>
      <div className="col-span-2 flex items-center gap-3">
        <button
          onClick={restart}
          disabled={state === 'restarting'}
          className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:bg-gray-700 disabled:text-white text-white text-sm font-medium rounded-lg transition-colors"
        >
          {state === 'restarting' ? 'Restarting…' : 'Restart Service'}
        </button>
        {state === 'done' && <span className="text-sm text-amber-400">Service is restarting — reload the page in ~5 seconds</span>}
        {state === 'error' && <span className="text-sm text-red-400">Restart failed — check server logs</span>}
      </div>
    </div>
  )
}

// -- Port field — lives in config.yaml, not the SQLite-backed settings; value
// is lifted to the parent so it saves through the General tab's one Save button --
export function PortField({ value, onChange, loaded }: { value: number; onChange: (v: number) => void; loaded: boolean }) {
  return (
    <Field label="Port" hint="Port the app listens on. Requires a service restart — the browser will need to follow the app to the new port/URL afterward.">
      {!loaded ? (
        <p className="text-xs text-white">Loading…</p>
      ) : (
        <NumberInput value={value} onChange={onChange} min={1} max={65535} />
      )}
    </Field>
  )
}

// -- Section wrapper with Save ----------------------------------------------------
// ── Log forwarding tester ─────────────────────────────────────────────────────
// A forwarder that silently drops everything looks identical to one that works,
// so the settings page has to be able to prove the path end to end.
export function LogForwardTester({ host, port, protocol }: { host: string; port: number; protocol: string }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string>('')
  const [ok, setOk] = useState<boolean | null>(null)

  const run = async () => {
    setBusy(true); setResult(''); setOk(null)
    try {
      const r = await api.logForwardTest(host, port, protocol)
      setOk(r.ok)
      setResult(r.ok
        ? `Sent 1 message to ${r.target} — check pktLog for "pktWiFi log forwarding test message"`
        : `Failed: ${r.last_error || 'no bytes sent'}`)
    } catch (e: any) {
      setOk(false); setResult(e.message || 'Test failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Field label="Test" hint="Sends one message using the values above, without saving them">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={run}
          disabled={busy || !host}
          className="f-lbl f-lbl-gold border border-blue-500/40 px-4 py-2 hover:border-blue-500 hover:text-blue-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? 'Sending…' : 'Send test message'}
        </button>
        {result && (
          <span className={`text-xs ${ok ? 'text-green-400' : 'text-red-400'}`}>{result}</span>
        )}
        {!host && <span className="text-xs text-gray-500">Set a collector host first</span>}
      </div>
    </Field>
  )
}

// ── Resonance origin ──────────────────────────────────────────────────────────
// The one string that has to be copied onto the resonance key, so it is edited
// and copied in the same place. Showing it twice — once editable in the form and
// once read-only beside a Copy button — reliably sends people to the copy.
export function ResonanceOriginField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [detected, setDetected] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => { api.resonanceStatus().then(r => setDetected(r.detected_origin || '')).catch(() => {}) }, [])

  const effective = value.trim() || detected

  return (
    <div>
      <div className="flex items-center gap-2">
        <TextInput value={value} onChange={onChange} placeholder={detected || 'https://pktwifi.example.com'} mono />
        <button
          type="button"
          onClick={() => { navigator.clipboard?.writeText(effective); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
          className="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap px-2"
        >{copied ? 'Copied' : 'Copy'}</button>
      </div>
      {!value.trim() && detected && (
        <p className="text-xs text-gray-500 mt-1">
          Blank — using <span className="font-mono">{detected}</span>.
        </p>
      )}
    </div>
  )
}

// ── Resonance diagnostics ─────────────────────────────────────────────────────
// Everything here answers a question an admin would otherwise have to open the
// resonance console to answer: what does this key actually allow, is this
// install's origin the one the key expects, and is the widget reaching anyone.
export function ResonanceDiagnostics({ baseUrl, keyValue }: { baseUrl: string; keyValue: string }) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.resonanceTest>> | null>(null)
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.resonanceStatus>> | null>(null)

  const loadStatus = () => { api.resonanceStatus().then(setStatus).catch(() => {}) }
  useEffect(loadStatus, [])

  const runTest = async () => {
    setTesting(true)
    setResult(null)
    try {
      setResult(await api.resonanceTest(baseUrl, keyValue))
    } catch (e: any) {
      setResult({ ok: false, error: e.message || 'Test failed', origin: '' })
    } finally {
      setTesting(false)
      loadStatus()
    }
  }

  const cap = (result?.cap || {}) as Record<string, unknown>
  const failures = status?.load_failures

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden mt-5">
      <div className="px-6 py-4 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-white">Diagnostics</h2>
      </div>
      <div className="px-6 py-4 space-y-4">

        {/* getUserMedia is gated on a secure context, so the microphone cannot
            work over plain HTTP however the key is configured. */}
        {!window.isSecureContext && (
          <p className="text-xs text-amber-400">
            Served over HTTP — voice is unavailable. Text chat is unaffected.
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={runTest}
            disabled={testing}
            className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors"
          >{testing ? 'Testing…' : 'Test Connection'}</button>
          <span className="text-xs text-white">Works whether or not the widget is enabled.</span>
        </div>

        {result && !result.ok && (
          <div className="text-xs">
            <p className="text-red-400">{result.error}</p>
            {result.detail && <p className="text-gray-500 mt-0.5 font-mono">{result.detail}</p>}
          </div>
        )}

        {result?.ok && (
          <div className="text-xs text-white space-y-1">
            <p className="text-green-400">Connected — this key grants:</p>
            <p>
              ask {cap.ask ? '✓' : '✗'} &middot; mic {cap.mic ? '✓' : '✗'} &middot; speak {cap.speak ? '✓' : '✗'}
            </p>
            <p>
              Limits: {String(cap.rate_per_min ?? '?')}/min per key, {String(cap.rate_per_visitor ?? '?')}/min per person
            </p>
            <p>
              Session: {result.expires_in ? Math.round(result.expires_in / 60) : '?'} min &middot; Code: {result.code_expires_in ?? '?'}s
            </p>
            <p className="text-gray-500">Sent as {result.user_id_sent}</p>
          </div>
        )}

        {status?.breaker.open && (
          <p className="text-xs text-amber-400">
            Paused after {status.breaker.failures} failures — retrying in {status.breaker.retry_in_seconds}s.
            {status.breaker.last_error ? ` Last error: ${status.breaker.last_error}` : ''}
          </p>
        )}

        {failures && failures.events > 0 && (
          <p className="text-xs text-amber-400">
            The widget failed to load for {failures.users} user{failures.users === 1 ? '' : 's'}
            {' '}({failures.events} time{failures.events === 1 ? '' : 's'}) in the last {failures.days} days.
            Common causes are an ad blocker, a wrong server address, or resonance being unreachable.
          </p>
        )}
      </div>
    </div>
  )
}

// -- Drag-and-drop cert/key textarea ----------------------------------------------
export function CertTextarea({ value, onChange, rows = 4, placeholder = 'MIIDp…', secret = false }: {
  value: string; onChange: (v: string) => void; rows?: number; placeholder?: string; secret?: boolean
}) {
  const [dragging, setDragging] = useState(false)
  const [revealed, setRevealed] = useState(false)

  const stripPem = (raw: string) =>
    raw.replace(/-----BEGIN[^-]+-----/g, '').replace(/-----END[^-]+-----/g, '').replace(/\s+/g, '')

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => { onChange(stripPem(reader.result as string)); setRevealed(false) }
    reader.readAsText(file)
  }

  if (secret && value && !revealed) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-green-400 font-mono">
          ✓ Certificate saved
        </div>
        <button type="button" onClick={() => setRevealed(true)}
          className="text-xs text-sky-400 hover:text-sky-300 whitespace-nowrap px-2 py-1 border border-gray-700 rounded-lg bg-gray-800">Replace</button>
        <button type="button" onClick={() => onChange('')}
          className="text-xs text-red-400 hover:text-red-300 whitespace-nowrap px-2 py-1 border border-gray-700 rounded-lg bg-gray-800">Clear</button>
      </div>
    )
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`relative rounded-lg transition-colors ${dragging ? 'ring-2 ring-sky-400 bg-sky-950/30' : ''}`}
    >
      {secret && revealed && (
        <div className="flex justify-end mb-1">
          <button type="button" onClick={() => setRevealed(false)} className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
        </div>
      )}
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono resize-y"
      />
      {dragging && (
        <div className="absolute inset-0 flex items-center justify-center rounded-lg pointer-events-none">
          <p className="text-sky-300 text-sm font-medium bg-gray-900/80 px-3 py-1 rounded">Drop to import</p>
        </div>
      )}
      <p className="text-xs text-gray-600 mt-1">Paste content or drag &amp; drop a .pem / .crt / .cer file</p>
    </div>
  )
}

// -- SAML metadata paste box -------------------------------------------------------
// The XML is read by the server, not parsed here: it is untrusted input, and the
// server's SAML parser refuses DTDs and entity declarations.
export function MetadataPasteBox({ onParsed }: { onParsed: (r: { entity_id: string; sso_url: string; cert: string }) => void }) {
  const [xml, setXml] = useState('')
  const [status, setStatus] = useState<'idle' | 'ok' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!xml.trim()) { setStatus('idle'); setMsg(''); return }
    // Wait for typing or a paste to settle, and ignore an answer to text that has since changed.
    let stale = false
    const timer = setTimeout(() => {
      api.parseSamlMetadata(xml)
        .then(r => {
          if (stale) return
          onParsed(r)
          setStatus('ok')
          setMsg('Entity ID, SSO URL, and certificate populated below.')
        })
        .catch(e => {
          if (stale) return
          setStatus('error')
          setMsg(e.message || 'Could not read the metadata.')
        })
    }, 400)
    return () => { stale = true; clearTimeout(timer) }
  }, [xml])

  return (
    <div className="space-y-1.5">
      <textarea
        value={xml}
        onChange={e => setXml(e.target.value)}
        rows={5}
        placeholder={'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" …>'}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono resize-y"
      />
      {status === 'ok' && <p className="text-xs text-emerald-400">✓ {msg}</p>}
      {status === 'error' && <p className="text-xs text-red-400">✗ {msg}</p>}
    </div>
  )
}

// -- Suite token display (inbound — pktHub calling into pktWiFi) -----------------
export function SuiteTokenDisplay() {
  const [token, setToken] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [copied, setCopied] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [regenerating, setRegen] = useState(false)

  const regenerate = async () => {
    if (!confirm('Generate a new token?\n\nThe current token will stop working immediately.\nYou will need to re-register this app in pktHub with the new token.')) return
    setRegen(true)
    try {
      const d = await api.regenerateSuiteToken()
      if (d.suite_token) { setToken(d.suite_token); setRevealed(true) }
    } catch {}
    setRegen(false)
  }

  useEffect(() => {
    api.getSuiteToken().then(d => { setToken(d.suite_token || ''); setLoaded(true) }).catch(() => setLoaded(true))
  }, [])

  const masked = token ? token.slice(0, 6) + '•'.repeat(28) + token.slice(-4) : ''

  return (
    <div className="grid grid-cols-3 gap-4 items-start py-3 border-b border-gray-800">
      <div>
        <p className="text-sm font-medium text-white">Suite Token</p>
        <p className="text-xs text-gray-500 mt-0.5">Copy to pktHub when registering this app</p>
      </div>
      <div className="col-span-2">
        {!loaded && <p className="text-xs text-gray-500 animate-pulse">Loading…</p>}
        {loaded && !token && <p className="text-xs text-yellow-400">No token set — visit this page again after restarting the service.</p>}
        {loaded && token && (
          <div className="flex items-center gap-2 flex-wrap">
            <code className="flex-1 min-w-0 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs font-mono text-gray-200 break-all">
              {revealed ? token : masked}
            </code>
            <button onClick={() => setRevealed(v => !v)}
              className="px-2 py-1.5 text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg bg-gray-800 whitespace-nowrap">
              {revealed ? 'Hide' : 'Reveal'}
            </button>
            <button
              onClick={async () => { const ok = await copyToClipboard(token); if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000) } }}
              className="px-3 py-1.5 text-xs font-medium text-white rounded-lg whitespace-nowrap transition-colors"
              style={{ background: copied ? '#52cc8e' : '#469fb4' }}
            >
              {copied ? '✓ Copied' : 'Copy Token'}
            </button>
            <button onClick={regenerate} disabled={regenerating} title="Generate a new token — you must re-register in pktHub after"
              className="px-2 py-1.5 text-xs font-medium text-red-400 hover:text-red-300 border border-red-800/60 hover:border-red-600 rounded-lg whitespace-nowrap disabled:opacity-40 transition-colors">
              {regenerating ? '…' : 'Regen'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

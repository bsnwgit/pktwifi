import { useEffect, useRef, useState } from 'react'
import { api, User, Integration } from '../api/client'
import { useAuth } from '../store/auth'
import HelpButton from '../components/HelpButton'
import { copyToClipboard } from '../utils/clipboard'

// -- Generic helpers -------------------------------------------------------------
type SettingsMap = Record<string, unknown>

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-4 items-start py-4 border-b border-gray-800 last:border-0">
      <div>
        <p className="text-sm font-medium text-white">{label}</p>
        {hint && <p className="text-xs text-white mt-0.5">{hint}</p>}
      </div>
      <div className="col-span-2">{children}</div>
    </div>
  )
}

function TextInput({ value, onChange, placeholder = '', secret = false, mono = false }: {
  value: string; onChange: (v: string) => void
  placeholder?: string; secret?: boolean; mono?: boolean
}) {
  return (
    <input
      type={secret ? 'password' : 'text'}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-500 ${mono ? 'font-mono' : ''}`}
    />
  )
}

function NumberInput({ value, onChange, min, max }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number
}) {
  return (
    <input
      type="number" min={min} max={max}
      value={value}
      onChange={e => onChange(parseInt(e.target.value) || 0)}
      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500"
    />
  )
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value ? 'bg-sky-600' : 'bg-gray-700'}`}
    >
      <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${value ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  )
}

function SelectInput({ value, onChange, options }: {
  value: string; onChange: (v: string) => void; options: Array<{ value: string; label: string }>
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500"
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

function RestartServiceRow() {
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

// -- Section wrapper with Save ----------------------------------------------------
function Section({ title, help, children, onSave, saving, saved, error }: {
  title: string
  help?: { title: string; content: React.ReactNode }
  children: React.ReactNode
  onSave: () => Promise<void>
  saving: boolean
  saved: boolean
  error: string
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        {help && <HelpButton title={help.title}>{help.content}</HelpButton>}
      </div>
      <div className="px-6 py-2">{children}</div>
      <div className="px-6 py-4 border-t border-gray-800 flex items-center gap-3">
        <button
          onClick={onSave}
          disabled={saving}
          className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-5 py-2 transition-colors"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-xs text-green-400">Saved</span>}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </div>
  )
}

interface SaveState { saving: boolean; saved: boolean; error: string }
const INIT: SaveState = { saving: false, saved: false, error: '' }

function useSave(keys: string[], settings: SettingsMap, onSuccess: () => void) {
  const [state, setState] = useState<SaveState>(INIT)

  const save = async () => {
    setState({ saving: true, saved: false, error: '' })
    try {
      const subset: SettingsMap = {}
      for (const k of keys) if (k in settings) subset[k] = settings[k]
      await api.updateSettings(subset)
      setState({ saving: false, saved: true, error: '' })
      onSuccess()
      setTimeout(() => setState(s => ({ ...s, saved: false })), 3000)
    } catch (e: any) {
      setState({ saving: false, saved: false, error: e.message || 'Save failed' })
    }
  }

  return { ...state, save }
}

// -- Drag-and-drop cert/key textarea ----------------------------------------------
function CertTextarea({ value, onChange, rows = 4, placeholder = 'MIIDp…', secret = false }: {
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
function MetadataPasteBox({ onParsed }: { onParsed: (r: { entity_id: string; sso_url: string; cert: string }) => void }) {
  const [xml, setXml] = useState('')
  const [status, setStatus] = useState<'idle' | 'ok' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  const handleChange = (raw: string) => {
    setXml(raw)
    if (!raw.trim()) { setStatus('idle'); setMsg(''); return }
    const result = parseIdpMetadata(raw)
    if (result.error) { setStatus('error'); setMsg(result.error) }
    else { onParsed(result); setStatus('ok'); setMsg('Entity ID, SSO URL, and certificate populated below.') }
  }

  return (
    <div className="space-y-1.5">
      <textarea
        value={xml}
        onChange={e => handleChange(e.target.value)}
        rows={5}
        placeholder={'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" …>'}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono resize-y"
      />
      {status === 'ok' && <p className="text-xs text-emerald-400">✓ {msg}</p>}
      {status === 'error' && <p className="text-xs text-red-400">✗ {msg}</p>}
    </div>
  )
}

function parseIdpMetadata(xml: string): { entity_id: string; sso_url: string; cert: string; error?: string } {
  try {
    const doc = new DOMParser().parseFromString(xml, 'application/xml')
    if (doc.querySelector('parsererror')) return { entity_id: '', sso_url: '', cert: '', error: 'Invalid XML — check the metadata and try again.' }

    const root = doc.querySelector('EntityDescriptor') ?? doc.documentElement
    const entity_id = root.getAttribute('entityID') ?? ''

    const ssoNodes = Array.from(doc.querySelectorAll('SingleSignOnService'))
    const redirect = ssoNodes.find(n => (n.getAttribute('Binding') ?? '').includes('HTTP-Redirect'))
    const sso_url = (redirect ?? ssoNodes[0])?.getAttribute('Location') ?? ''

    const keyDescs = Array.from(doc.querySelectorAll('KeyDescriptor'))
    const signingKd = keyDescs.find(kd => !kd.getAttribute('use') || kd.getAttribute('use') === 'signing')
    const x509El = signingKd?.querySelector('X509Certificate') ?? doc.querySelector('X509Certificate')
    const cert = x509El?.textContent?.replace(/\s+/g, '') ?? ''

    if (!entity_id && !sso_url && !cert) return { entity_id: '', sso_url: '', cert: '', error: 'No SAML IdP data found in this XML.' }
    return { entity_id, sso_url, cert }
  } catch {
    return { entity_id: '', sso_url: '', cert: '', error: 'Failed to parse XML.' }
  }
}

// -- Suite token display (inbound — pktHub calling into pktWiFi) -----------------
function SuiteTokenDisplay() {
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
              style={{ background: copied ? '#16a34a' : '#0284c7' }}
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

// -- Sibling pkt app connections (outbound — pktWiFi calling into other pkt apps) --
const SIBLING_LABELS: Record<string, string> = {
  pktsnmp: 'pktSNMP — device inventory & interface metrics',
  pktflow: 'pktFlow — traffic flow context',
  pktlog: 'pktLog — AP/controller syslogs',
  pktpcap: 'pktPCAP — packet capture feeds',
}

function SiblingIntegrations() {
  const [items, setItems] = useState<Integration[]>([])
  const [edits, setEdits] = useState<Record<string, { base_url: string; suite_token: string }>>({})
  const [testResult, setTestResult] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)

  const load = () => api.getIntegrations()
    .then(ints => {
      setItems(ints)
      const e: Record<string, { base_url: string; suite_token: string }> = {}
      ints.forEach(i => { e[i.app_name] = { base_url: i.base_url, suite_token: '' } })
      setEdits(e)
    })
    .catch(() => {})
    .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const save = async (appName: string) => {
    const edit = edits[appName]
    await api.setIntegration(appName, { base_url: edit.base_url, suite_token: edit.suite_token, enabled: true })
    load()
  }

  const test = async (appName: string) => {
    const result = await api.testIntegration(appName)
    setTestResult(prev => ({ ...prev, [appName]: result.healthy ? `OK — ${result.detail}` : `Failed — ${result.detail}` }))
  }

  if (loading) return <p className="text-xs text-gray-500 animate-pulse py-3">Loading…</p>

  return (
    <div className="space-y-4 py-3">
      {items.map(i => (
        <div key={i.app_name} className="bg-gray-800/40 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-medium text-white">{SIBLING_LABELS[i.app_name] ?? i.app_name}</p>
            <span className={i.health_status === 'ok' ? 'text-xs text-green-400' : 'text-xs text-gray-500'}>{i.health_status}</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-white block mb-1">Base URL</label>
              <input
                value={edits[i.app_name]?.base_url ?? ''}
                onChange={e => setEdits(prev => ({ ...prev, [i.app_name]: { ...prev[i.app_name], base_url: e.target.value } }))}
                placeholder="https://server:port"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="text-xs text-white block mb-1">Suite Token (from that app's Settings)</label>
              <input
                value={edits[i.app_name]?.suite_token ?? ''}
                onChange={e => setEdits(prev => ({ ...prev, [i.app_name]: { ...prev[i.app_name], suite_token: e.target.value } }))}
                placeholder={i.has_token ? '•••••••• (already set)' : 'paste token'}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
              />
            </div>
          </div>
          <div className="flex items-center gap-3 mt-3">
            <button onClick={() => save(i.app_name)} className="text-xs bg-sky-600 hover:bg-sky-500 text-white rounded-lg px-3 py-1.5">Save</button>
            <button onClick={() => test(i.app_name)} className="text-xs text-white border border-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-800">Test Connection</button>
            {testResult[i.app_name] && <span className="text-xs text-gray-400">{testResult[i.app_name]}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

// -- Users tab ---------------------------------------------------------------------
function UsersTab() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [newUser, setNewUser] = useState({ username: '', email: '', password: '', role: 'viewer' })

  const load = () => {
    setLoading(true)
    api.getUsers().then(setUsers).catch(e => setError(e.message)).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const createUser = async () => {
    try {
      await api.createUser(newUser)
      setNewUser({ username: '', email: '', password: '', role: 'viewer' })
      load()
    } catch (e: any) { setError(e.message) }
  }
  const updateRole = async (id: number, role: string) => { await api.updateUser(id, { role }); load() }
  const toggleActive = async (u: User) => { await api.updateUser(u.id, { is_active: !u.is_active }); load() }
  const removeUser = async (id: number) => { if (confirm('Delete this user?')) { await api.deleteUser(id); load() } }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
      <div className="flex items-center gap-2">
        <p className="text-sm font-semibold text-white">Users</p>
        <HelpButton title="Users — How It Works">
          <p>Three roles: <span className="text-gray-300 font-medium">admin</span> (full access, including this Users tab, Collectors, and Integrations), <span className="text-gray-300 font-medium">analyst</span> (can edit access points, ack/resolve alerts), and <span className="text-gray-300 font-medium">viewer</span> (read-only).</p>
          <p>This tab only manages <span className="text-gray-300 font-medium">local accounts</span> — SAML SSO users are auto-provisioned on first login.</p>
        </HelpButton>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-400 text-sm rounded-lg px-4 py-2 flex items-center justify-between">
          {error}<button onClick={() => setError('')} className="ml-4 text-red-600 hover:text-red-400">✕</button>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-white">Loading…</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-gray-400 text-left">
            <tr>
              <th className="py-1 font-medium">Username</th>
              <th className="py-1 font-medium">Email</th>
              <th className="py-1 font-medium">Role</th>
              <th className="py-1 font-medium">Active</th>
              <th className="py-1 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} className="border-t border-gray-800">
                <td className="py-1.5 text-white">{u.username}</td>
                <td className="py-1.5 text-gray-300">{u.email}</td>
                <td className="py-1.5">
                  <select value={u.role} onChange={e => updateRole(u.id, e.target.value)}
                    className="bg-gray-800 border border-gray-700 text-white text-xs rounded-lg px-2 py-1">
                    <option value="admin">admin</option>
                    <option value="analyst">analyst</option>
                    <option value="viewer">viewer</option>
                  </select>
                </td>
                <td className="py-1.5">
                  <button onClick={() => toggleActive(u)} className={`text-xs px-2 py-1 rounded-md ${u.is_active ? 'bg-green-500/20 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
                    {u.is_active ? 'Active' : 'Disabled'}
                  </button>
                </td>
                <td className="py-1.5 text-right">
                  <button onClick={() => removeUser(u.id)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-2">
        <input placeholder="username" value={newUser.username} onChange={e => setNewUser({ ...newUser, username: e.target.value })}
          className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-white" />
        <input placeholder="email" value={newUser.email} onChange={e => setNewUser({ ...newUser, email: e.target.value })}
          className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-white" />
        <input placeholder="password" type="password" value={newUser.password} onChange={e => setNewUser({ ...newUser, password: e.target.value })}
          className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-white" />
        <select value={newUser.role} onChange={e => setNewUser({ ...newUser, role: e.target.value })}
          className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-white">
          <option value="admin">admin</option>
          <option value="analyst">analyst</option>
          <option value="viewer">viewer</option>
        </select>
      </div>
      <button onClick={createUser} className="text-xs bg-sky-600 hover:bg-sky-500 text-white rounded-lg px-3 py-1.5">Add user</button>
    </div>
  )
}

// -- Main page ---------------------------------------------------------------------
type TabId = 'general' | 'auth' | 'backup' | 'integrations' | 'users' | 'system'

const TABS: Array<{ id: TabId; label: string; adminOnly?: boolean }> = [
  { id: 'general',      label: 'General' },
  { id: 'auth',         label: 'Authentication' },
  { id: 'backup',       label: 'Backup' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'users',        label: 'Users', adminOnly: true },
  { id: 'system',       label: 'System' },
]

export default function Settings() {
  const { user: me } = useAuth()
  const isAdmin = me?.role === 'admin'
  const [tab, setTab] = useState<TabId>('general')
  const [settings, setSettings] = useState<SettingsMap>({})
  const [loading, setLoading] = useState(true)
  const dirtyRef = useRef(false)

  const load = async () => {
    setLoading(true)
    try { setSettings(await api.getSettings()) } finally { setLoading(false); dirtyRef.current = false }
  }
  useEffect(() => { load() }, [])

  const set = (key: string, value: unknown) => { dirtyRef.current = true; setSettings(s => ({ ...s, [key]: value })) }
  const str  = (k: string, fallback = '') => (settings[k] as string) ?? fallback
  const num  = (k: string, fallback = 0)  => (settings[k] as number) ?? fallback
  const bool = (k: string, fallback = false) => (settings[k] as boolean) ?? fallback

  const generalSave = useSave(['app_name', 'base_url', 'timezone'], settings, load)
  const authSave = useSave([
    'auth_local_enabled',
    'okta_saml_enabled', 'okta_saml_idp_entity_id', 'okta_saml_idp_sso_url',
    'okta_saml_idp_cert', 'okta_saml_sp_entity_id', 'okta_saml_sp_cert', 'okta_saml_sp_key',
  ], settings, load)
  const backupSave = useSave(['backup_enabled', 'backup_interval_hours', 'backup_rotation_count', 'backup_path'], settings, load)

  const [backupRunning, setBackupRunning] = useState(false)
  const [backupResult, setBackupResult] = useState<string | null>(null)
  const [backups, setBackups] = useState<Array<{ name: string; path: string; size_bytes: number; files: string[] }>>([])
  const [backupsLoaded, setBackupsLoaded] = useState(false)
  const [systemInfo, setSystemInfo] = useState<{ version: string; install_dir: string; port: number } | null>(null)

  useEffect(() => { api.getSystemInfo().then(setSystemInfo).catch(() => {}) }, [])

  const runBackupNow = async () => {
    setBackupRunning(true)
    setBackupResult(null)
    try {
      const r = await api.runBackupNow()
      setBackupResult(`Saved to ${r.path} — ${r.files.join(', ')}`)
      setBackups(await api.listBackups())
      setBackupsLoaded(true)
    } catch (e: any) {
      setBackupResult(`Error: ${e.message}`)
    } finally { setBackupRunning(false) }
  }
  const loadBackups = async () => {
    try { setBackups(await api.listBackups()); setBackupsLoaded(true) } catch {}
  }

  if (loading) {
    return <div className="flex items-center justify-center h-48 text-white"><p className="text-sm">Loading settings…</p></div>
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-white">Settings</h1>

      <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-xl p-1 w-fit overflow-x-auto">
        {TABS.filter(t => !t.adminOnly || isAdmin).map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`text-sm px-4 py-1.5 rounded-lg whitespace-nowrap transition-colors ${tab === t.id ? 'bg-gray-700 text-white' : 'text-white hover:text-white'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'general' && (
        <Section title="General" onSave={generalSave.save} saving={generalSave.saving} saved={generalSave.saved} error={generalSave.error}
          help={{
            title: 'General — How It Works',
            content: <p><span className="text-gray-300 font-medium">Base URL</span> feeds the SAML ACS/metadata URLs on the Authentication tab — set it to the actual externally-reachable address before configuring SSO, or those will point at the wrong place.</p>,
          }}
        >
          <Field label="App name" hint="Displayed in browser tab and header">
            <TextInput value={str('app_name', 'pktWiFi')} onChange={v => set('app_name', v)} />
          </Field>
          <Field label="Base URL" hint="Used for SAML redirect URIs">
            <TextInput value={str('base_url')} onChange={v => set('base_url', v)} placeholder="http://SERVER-IP:8769" />
          </Field>
          <Field label="Timezone" hint="Affects display of timestamps in the UI">
            <SelectInput
              value={str('timezone', 'UTC')}
              onChange={v => set('timezone', v)}
              options={[
                { value: 'UTC', label: 'UTC' },
                { value: 'America/New_York', label: 'Eastern (ET)' },
                { value: 'America/Chicago', label: 'Central (CT)' },
                { value: 'America/Denver', label: 'Mountain (MT)' },
                { value: 'America/Los_Angeles', label: 'Pacific (PT)' },
              ]}
            />
          </Field>
        </Section>
      )}

      {tab === 'auth' && (
        <Section title="Authentication" onSave={authSave.save} saving={authSave.saving} saved={authSave.saved} error={authSave.error}
          help={{
            title: 'Authentication — How It Works',
            content: <>
              <p><span className="text-gray-300 font-medium">Local auth</span> and <span className="text-gray-300 font-medium">SAML SSO</span> aren't mutually exclusive — both can be on at once.</p>
              <p>SAML users are <span className="text-gray-300 font-medium">auto-provisioned</span> on first successful login — no separate "create user" step.</p>
              <p>Paste your IdP's metadata XML to auto-fill the fields below, then register the <span className="text-gray-300 font-medium">ACS URL</span> shown here as the Single Sign-On URL in your IdP. Both the ACS URL and SP metadata link derive from <span className="text-gray-300 font-medium">Base URL</span> on the General tab — set that correctly first.</p>
            </>,
          }}
        >
          <Field label="Local auth" hint="Username/password login using local accounts">
            <Toggle value={bool('auth_local_enabled', true)} onChange={v => set('auth_local_enabled', v)} />
          </Field>

          <div className="pt-4 pb-2">
            <p className="text-xs font-semibold text-white uppercase tracking-wider">SAML 2.0 SSO</p>
          </div>
          <Field label="Enable SAML SSO">
            <Toggle value={bool('okta_saml_enabled')} onChange={v => set('okta_saml_enabled', v)} />
          </Field>
          {bool('okta_saml_enabled') && (
            <>
              <Field label="Paste IdP Metadata XML" hint="Paste the full XML from your IdP's SAML app configuration. Fields below will auto-fill.">
                <MetadataPasteBox onParsed={r => {
                  if (r.entity_id) set('okta_saml_idp_entity_id', r.entity_id)
                  if (r.sso_url) set('okta_saml_idp_sso_url', r.sso_url)
                  if (r.cert) set('okta_saml_idp_cert', r.cert)
                }} />
              </Field>
              <Field label="IdP Entity ID">
                <TextInput value={str('okta_saml_idp_entity_id')} onChange={v => set('okta_saml_idp_entity_id', v)} placeholder="https://idp.example.com/..." mono />
              </Field>
              <Field label="IdP SSO URL">
                <TextInput value={str('okta_saml_idp_sso_url')} onChange={v => set('okta_saml_idp_sso_url', v)} placeholder="https://idp.example.com/sso/saml" mono />
              </Field>
              <Field label="IdP X.509 Certificate" hint="PEM headers are stripped automatically">
                <CertTextarea value={str('okta_saml_idp_cert')} onChange={v => set('okta_saml_idp_cert', v)} rows={4} secret />
              </Field>
              <Field label="SP Entity ID" hint="Leave blank to use the auto-generated metadata URL">
                <TextInput value={str('okta_saml_sp_entity_id')} onChange={v => set('okta_saml_sp_entity_id', v)} placeholder={`${str('base_url')}/api/auth/saml/metadata`} mono />
              </Field>
              <Field label="ACS URL (read-only)" hint="Register this URL as the Single Sign-On URL in your IdP">
                <div className="flex items-center gap-2">
                  <input readOnly value={`${str('base_url')}/api/auth/saml/callback`}
                    className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-400 font-mono cursor-default" />
                  <a href={`${str('base_url')}/api/auth/saml/metadata`} target="_blank" rel="noreferrer"
                    className="text-xs text-sky-400 hover:text-sky-300 whitespace-nowrap">View SP metadata ↗</a>
                </div>
              </Field>
              <Field label="SP Certificate" hint="Optional: for signed authentication requests">
                <CertTextarea value={str('okta_saml_sp_cert')} onChange={v => set('okta_saml_sp_cert', v)} rows={3} placeholder="Leave blank if not signing requests" secret />
              </Field>
              <Field label="SP Private Key" hint="Optional: private key for signing requests (kept secret)">
                <CertTextarea value={str('okta_saml_sp_key')} onChange={v => set('okta_saml_sp_key', v)} rows={3} placeholder="Leave blank if not signing requests" secret />
              </Field>
            </>
          )}
        </Section>
      )}

      {tab === 'backup' && (
        <Section title="Backup" onSave={backupSave.save} saving={backupSave.saving} saved={backupSave.saved} error={backupSave.error}
          help={{
            title: 'Backup — How It Works',
            content: <>
              <p>A backup includes the SQLite database (settings, access points, collectors, alert rules, users) and <code className="text-gray-400">config.yaml</code>.</p>
              <p><span className="text-gray-300 font-medium">Rotation count</span> caps how many snapshots stay on disk — the oldest is deleted automatically once you exceed it.</p>
            </>,
          }}
        >
          <Field label="Auto backup" hint="Run a scheduled backup on the server at the configured interval">
            <Toggle value={bool('backup_enabled')} onChange={v => set('backup_enabled', v)} />
          </Field>
          <Field label="Interval" hint="Hours between automatic backup runs">
            <div className="flex items-center gap-3">
              <NumberInput value={num('backup_interval_hours', 24)} onChange={v => set('backup_interval_hours', v)} min={1} max={720} />
              <span className="text-sm text-white">hours</span>
            </div>
          </Field>
          <Field label="Rotation count" hint="Number of snapshots to keep — oldest deleted when exceeded">
            <NumberInput value={num('backup_rotation_count', 5)} onChange={v => set('backup_rotation_count', v)} min={1} max={100} />
          </Field>
          <Field label="Backup path" hint="Directory on server where snapshots are stored">
            <TextInput value={str('backup_path')} onChange={v => set('backup_path', v)} mono placeholder="<install_dir>/backups" />
          </Field>
          <Field label="Manual backup" hint="Trigger a backup run immediately using current settings">
            <div className="space-y-3">
              <div className="flex items-center gap-3 flex-wrap">
                <button onClick={runBackupNow} disabled={backupRunning}
                  className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded-lg px-4 py-2 transition-colors">
                  {backupRunning ? 'Running…' : 'Run Backup Now'}
                </button>
                {!backupsLoaded && !backupRunning && (
                  <button onClick={loadBackups} className="text-xs text-white hover:text-white underline">Show snapshots</button>
                )}
              </div>
              {backupResult && (
                <p className={`text-xs ${backupResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>{backupResult}</p>
              )}
              {backupsLoaded && (
                <div className="space-y-1">
                  {backups.length === 0 ? <p className="text-xs text-white">No snapshots found.</p> : backups.map(b => (
                    <div key={b.name} className="flex items-center gap-3 text-xs text-white">
                      <span className="font-mono">{b.name}</span>
                      <span className="text-white">{(b.size_bytes / 1024 / 1024).toFixed(1)} MB</span>
                      <span className="text-white">{b.files.join(', ')}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Field>
        </Section>
      )}

      {tab === 'integrations' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-800 flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">Integrations</h2>
            <HelpButton title="Integrations — How It Works">
              <p><span className="text-gray-300 font-medium">Suite Token</span> is one-directional discovery: copy it into pktHub's App Manager when registering this app, so pktHub can proxy into it with users already signed in.</p>
              <p><span className="text-gray-300 font-medium">Sibling pkt apps</span> below is the other direction: pktWiFi calling into pktsnmp/pktflow/pktlog/pktpcap to reuse data they've already collected. Paste each app's own suite token (from that app's Settings → Integrations) here.</p>
            </HelpButton>
          </div>
          <div className="px-6 py-2">
            <SuiteTokenDisplay />
            <div className="pt-4 pb-1">
              <p className="text-xs font-semibold text-white uppercase tracking-wider">Sibling pkt Apps</p>
            </div>
            <SiblingIntegrations />
          </div>
        </div>
      )}

      {tab === 'users' && isAdmin && <UsersTab />}

      {tab === 'system' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-800">
            <h2 className="text-sm font-semibold text-white">System</h2>
          </div>
          <div className="px-6 py-2">
            <Field label="Version">
              <p className="text-sm text-white">{systemInfo?.version ?? '—'}</p>
            </Field>
            <Field label="Install directory">
              <p className="text-sm text-white font-mono">{systemInfo?.install_dir ?? '—'}</p>
            </Field>
            <Field label="Port">
              <p className="text-sm text-white">{systemInfo?.port ?? '—'}</p>
            </Field>
            <RestartServiceRow />
          </div>
        </div>
      )}
    </div>
  )
}

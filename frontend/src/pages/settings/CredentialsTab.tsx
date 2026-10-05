// Settings -> Credentials.
import { useEffect, useState } from 'react'
import {
  CredType,
  WifiCredential,
  WifiCredentialInput,
  api,
} from '../../api/client'
import HelpButton from '../../components/HelpButton'

export const CRED_TYPE_OPTIONS: Array<{ value: CredType; label: string }> = [
  { value: 'userpass', label: 'Username & password' },
  { value: 'api_key',  label: 'API key / token' },
  { value: 'snmp_v2c', label: 'SNMP v2c' },
  { value: 'snmp_v3',  label: 'SNMP v3' },
]

export function credTypeBadge(t: CredType): string {
  const map: Record<CredType, string> = {
    userpass: 'bg-sky-900/40 text-sky-300 border border-sky-700/40',
    api_key:  'bg-emerald-900/40 text-emerald-300 border border-emerald-700/40',
    snmp_v2c: 'bg-blue-900/40 text-blue-300 border border-blue-700/40',
    snmp_v3:  'bg-purple-900/40 text-purple-300 border border-purple-700/40',
  }
  return map[t] ?? 'bg-gray-700 text-gray-300'
}

export function credTypeLabel(t: CredType): string {
  return CRED_TYPE_OPTIONS.find(o => o.value === t)?.label ?? t
}

export function CredentialFormModal({ cred, onClose, onSaved }: {
  cred: WifiCredential | null
  onClose: () => void
  onSaved: () => void
}) {
  const editing = !!cred
  const [name, setName] = useState(cred?.name ?? '')
  const [description, setDescription] = useState(cred?.description ?? '')
  const [credType, setCredType] = useState<CredType>(cred?.cred_type ?? 'userpass')
  const [username, setUsername] = useState(cred?.username ?? '')
  const [password, setPassword] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [community, setCommunity] = useState('')
  const [authProtocol, setAuthProtocol] = useState(cred?.auth_protocol ?? 'SHA')
  const [authPassword, setAuthPassword] = useState('')
  const [privProtocol, setPrivProtocol] = useState(cred?.priv_protocol ?? 'AES')
  const [privPassword, setPrivPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const inp = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-500'
  const secretPlaceholder = (has: boolean | undefined) => (editing && has ? '•••••••• (unchanged)' : '')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const body: WifiCredentialInput = {
        name, description, cred_type: credType,
        username: credType === 'userpass' || credType === 'snmp_v3' ? username : null,
        password: password || null,
        api_key: apiKey || null,
        community: community || null,
        auth_protocol: credType === 'snmp_v3' ? authProtocol : null,
        auth_password: authPassword || null,
        priv_protocol: credType === 'snmp_v3' ? privProtocol : null,
        priv_password: privPassword || null,
      }
      if (editing) await api.updateCredential(cred!.id, body)
      else await api.createCredential(body)
      onSaved()
    } catch (e: any) {
      setError(e.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 overflow-y-auto py-8" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-white mb-5">{editing ? `Edit — ${cred!.name}` : 'New Credential'}</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-white block mb-1">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} required className={inp} placeholder="lab-unifi-admin" />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Description</label>
            <input value={description} onChange={e => setDescription(e.target.value)} className={inp} />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Type</label>
            <select value={credType} onChange={e => setCredType(e.target.value as CredType)} disabled={editing} className={inp}>
              {CRED_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {editing && <p className="text-xs text-white mt-1">Type can't change after creation — add a new credential instead.</p>}
          </div>

          {credType === 'userpass' && (
            <>
              <div>
                <label className="text-xs text-white block mb-1">Username</label>
                <input value={username} onChange={e => setUsername(e.target.value)} required className={inp} />
              </div>
              <div>
                <label className="text-xs text-white block mb-1">Password</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                  required={!editing} placeholder={secretPlaceholder(cred?.has_password)} className={inp} />
              </div>
            </>
          )}

          {credType === 'api_key' && (
            <div>
              <label className="text-xs text-white block mb-1">API key / token</label>
              <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                required={!editing} placeholder={secretPlaceholder(cred?.has_api_key)} className={inp} />
            </div>
          )}

          {credType === 'snmp_v2c' && (
            <div>
              <label className="text-xs text-white block mb-1">Community string</label>
              <input type="password" value={community} onChange={e => setCommunity(e.target.value)}
                required={!editing} placeholder={secretPlaceholder(cred?.has_community) || 'public'} className={inp} />
            </div>
          )}

          {credType === 'snmp_v3' && (
            <>
              <div>
                <label className="text-xs text-white block mb-1">Security name (username)</label>
                <input value={username} onChange={e => setUsername(e.target.value)} required className={inp} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-white block mb-1">Auth protocol</label>
                  <select value={authProtocol} onChange={e => setAuthProtocol(e.target.value)} className={inp}>
                    <option value="SHA">SHA</option><option value="MD5">MD5</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-white block mb-1">Auth password</label>
                  <input type="password" value={authPassword} onChange={e => setAuthPassword(e.target.value)}
                    required={!editing} placeholder={secretPlaceholder(cred?.has_auth_password)} className={inp} />
                </div>
                <div>
                  <label className="text-xs text-white block mb-1">Privacy protocol</label>
                  <select value={privProtocol} onChange={e => setPrivProtocol(e.target.value)} className={inp}>
                    <option value="AES">AES</option><option value="DES">DES</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-white block mb-1">Privacy password</label>
                  <input type="password" value={privPassword} onChange={e => setPrivPassword(e.target.value)}
                    required={!editing} placeholder={secretPlaceholder(cred?.has_priv_password)} className={inp} />
                </div>
              </div>
            </>
          )}

          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-white">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg disabled:opacity-50">
              {saving ? 'Saving…' : (editing ? 'Save Changes' : 'Create Credential')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function CredentialsTab() {
  const [credentials, setCredentials] = useState<WifiCredential[]>([])
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState<WifiCredential | null | 'new'>(null)
  const [confirm, setConfirm] = useState<WifiCredential | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      setCredentials(await api.getCredentials())
    } catch (e: any) {
      setError(e.message ?? 'Failed to load credentials')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])

  const del = async (c: WifiCredential) => {
    try {
      await api.deleteCredential(c.id)
      setConfirm(null)
      await load()
    } catch (e: any) {
      setConfirm(null)
      setError(e.message ?? 'Delete failed')
    }
  }

  const details = (c: WifiCredential): string => {
    switch (c.cred_type) {
      case 'userpass': return `${c.username ?? '—'} / ••••••••`
      case 'api_key': return '••••••••'
      case 'snmp_v2c': return '••••••••'
      case 'snmp_v3': return `${c.username ?? '—'} / ${c.auth_protocol ?? '—'}+${c.priv_protocol ?? '—'}`
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">Credentials</h2>
            <HelpButton title="Credentials — How It Works">
              <p>A credential is a <span className="text-gray-300 font-medium">named, reusable auth set</span> — a controller username &amp; password, an API key/token, or SNMP v2c/v3 auth. Create it once here, then pick it from the dropdown when adding a controller instead of re-typing auth per controller.</p>
              <p>Secrets are <span className="text-gray-300 font-medium">encrypted at rest and never shown again</span> — editing a credential with a blank secret field keeps the stored value.</p>
              <p>A credential that's referenced by a controller can't be deleted — reassign the controller first.</p>
            </HelpButton>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">Named auth sets referenced by controllers — manage all auth here, assign it in the Controllers tab</p>
        </div>
        <button onClick={() => setModal('new')}
          className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg transition-colors">
          + Add Credential
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-400 text-sm rounded-lg px-4 py-2 flex items-center justify-between">
          {error}<button onClick={() => setError('')} className="ml-4 text-red-600 hover:text-red-400">✕</button>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-24 text-white text-sm">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-400">Name</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-400">Type</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-400 hidden sm:table-cell">Details</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-400 hidden md:table-cell">Description</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {credentials.map(c => (
                <tr key={c.id} className="hover:bg-gray-800/30 transition-colors">
                  <td className="px-5 py-3">
                    <p className="text-white font-medium text-sm">{c.name}</p>
                  </td>
                  <td className="px-5 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-mono ${credTypeBadge(c.cred_type)}`}>{credTypeLabel(c.cred_type)}</span>
                  </td>
                  <td className="px-5 py-3 text-gray-400 text-xs hidden sm:table-cell font-mono">{details(c)}</td>
                  <td className="px-5 py-3 text-gray-500 text-xs hidden md:table-cell">{c.description || '—'}</td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3 justify-end">
                      <button onClick={() => setModal(c)} className="text-xs text-gray-400 hover:text-sky-400 transition-colors">Edit</button>
                      <button onClick={() => setConfirm(c)} className="text-xs text-gray-400 hover:text-red-400 transition-colors">Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {credentials.length === 0 && (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-sm text-gray-500">No credentials defined</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {(modal === 'new' || (modal && typeof modal === 'object')) && (
        <CredentialFormModal
          cred={modal === 'new' ? null : modal as WifiCredential}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); void load() }}
        />
      )}

      {confirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setConfirm(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-white mb-2">Delete credential?</h3>
            <p className="text-sm text-gray-300 mb-5">Remove <span className="text-white font-medium">{confirm.name}</span>? Controllers still using it will block the delete.</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirm(null)} className="px-4 py-2 text-sm text-gray-400 hover:text-white">Cancel</button>
              <button onClick={() => del(confirm)} className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

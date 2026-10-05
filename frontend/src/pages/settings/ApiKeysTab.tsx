// Settings -> Security -> API Keys.
import { useEffect, useState } from 'react'
import {
  User,
  UserApiKey,
  api,
} from '../../api/client'
import HelpButton from '../../components/HelpButton'
import { useAuth } from '../../store/auth'

// Providers whose response the user can filter down to specific sections in
// the IP Lookup modal. Keyed by provider id; each entry's field keys match
// what the backend's IPINFO_FIELDS / IPAPI_IS_FIELDS constants accept.
export const FIELD_SETS: Record<string, { key: string; label: string }[]> = {
  ipinfo: [
    { key: 'geolocation', label: 'Geolocation' },
    { key: 'asn',         label: 'ASN / Org' },
    { key: 'company',     label: 'Company' },
    { key: 'privacy',     label: 'Privacy Detection (VPN/Proxy/Tor)' },
    { key: 'abuse',       label: 'Abuse Contact' },
    { key: 'domains',     label: 'Hosted Domains' },
  ],
  ipapi_is: [
    { key: 'geolocation', label: 'Geolocation' },
    { key: 'asn',         label: 'ASN / Org' },
    { key: 'company',     label: 'Company' },
    { key: 'detection',   label: 'Threat Detection (VPN/Proxy/Tor/Datacenter)' },
    { key: 'abuse',       label: 'Abuse Contact' },
  ],
  mxtoolbox: [
    { key: 'ptr',       label: 'Reverse DNS (PTR)' },
    { key: 'asn',       label: 'ASN' },
    { key: 'blacklist', label: 'Blacklist Check' },
  ],
}

export const setFieldsApi: Record<string, (fields: string[]) => Promise<UserApiKey>> = {
  ipinfo: api.setIpinfoFields,
  ipapi_is: api.setIpapiIsFields,
  mxtoolbox: api.setMxtoolboxFields,
}

// The 4 providers with a section in the IP Lookup modal — AbuseIPDB has no
// per-field checkboxes (single score, not multiple sections) but still gets
// the modal-section on/off toggle. IPQualityScore isn't wired into the modal
// at all, so it gets neither.
export const MODAL_PROVIDERS = ['ipinfo', 'ipapi_is', 'abuseipdb', 'mxtoolbox', 'ipqualityscore']

// -- User Keys tab (personal, per-user external API keys) -------------------------
export function ApiKeysTab({ lucidToken, onLucidChange, lucidSave }: {
  lucidToken: string
  onLucidChange: (v: string) => void
  lucidSave: { saving: boolean; saved: boolean; error: string; save: () => Promise<void> }
}) {
  const { user } = useAuth()
  const [keys, setKeys]       = useState<UserApiKey[]>([])
  const [loading, setLoading] = useState(true)
  const [drafts, setDrafts]   = useState<Record<string, string>>({})
  const [saving, setSaving]   = useState<Record<string, boolean>>({})
  const [saved, setSaved]     = useState<Record<string, boolean>>({})
  const [error, setError]     = useState<Record<string, string>>({})
  const [testing, setTesting] = useState<Record<string, boolean>>({})
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; detail: string }>>({})
  const [fieldsError, setFieldsError] = useState('')

  async function handleToggleField(provider: string, fieldKey: string, checked: boolean) {
    const providerKey = keys.find(k => k.provider === provider)
    const current = providerKey?.enabled_fields ?? FIELD_SETS[provider].map(f => f.key)
    const next = checked ? [...current, fieldKey] : current.filter(f => f !== fieldKey)
    setFieldsError('')
    try {
      const updated = await setFieldsApi[provider](next)
      setKeys(prev => prev.map(k => k.provider === provider ? updated : k))
    } catch (err: any) {
      setFieldsError(err.message ?? 'Failed to save')
    }
  }

  async function handleToggleFreeTier(checked: boolean) {
    setFieldsError('')
    try {
      const updated = await api.setIpapiIsFreeTier(checked)
      setKeys(prev => prev.map(k => k.provider === 'ipapi_is' ? updated : k))
    } catch (err: any) {
      setFieldsError(err.message ?? 'Failed to save')
    }
  }

  async function handleToggleEnabled(provider: string, checked: boolean) {
    setFieldsError('')
    try {
      const updated = await api.setProviderEnabled(provider, checked)
      setKeys(prev => prev.map(k => k.provider === provider ? updated : k))
    } catch (err: any) {
      setFieldsError(err.message ?? 'Failed to save')
    }
  }

  function load() {
    setLoading(true)
    api.getUserApiKeys()
      .then(rows => { setKeys(rows); setDrafts(Object.fromEntries(rows.map(r => [r.provider, r.api_key]))) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  async function handleSave(provider: string) {
    setSaving(s => ({ ...s, [provider]: true }))
    setError(e => ({ ...e, [provider]: '' }))
    try {
      const updated = await api.setUserApiKey(provider, drafts[provider] ?? '')
      setKeys(prev => prev.map(k => k.provider === provider ? updated : k))
      setSaved(s => ({ ...s, [provider]: true }))
      setTimeout(() => setSaved(s => ({ ...s, [provider]: false })), 2000)
    } catch (err: any) {
      setError(e => ({ ...e, [provider]: err.message ?? 'Save failed' }))
    } finally {
      setSaving(s => ({ ...s, [provider]: false }))
    }
  }

  async function handleTest(provider: string) {
    setTesting(t => ({ ...t, [provider]: true }))
    setTestResult(r => ({ ...r, [provider]: undefined as any }))
    try {
      const res = await api.testUserApiKey(provider, drafts[provider] ?? '')
      setTestResult(r => ({ ...r, [provider]: { ok: res.status === 'ok', detail: res.detail } }))
    } catch (err: any) {
      setTestResult(r => ({ ...r, [provider]: { ok: false, detail: err.message ?? 'Test failed' } }))
    } finally {
      setTesting(t => ({ ...t, [provider]: false }))
    }
  }

  const inp = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono'

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-white">User Keys</h2>
        <HelpButton title="User Keys — How It Works">
          <p>External API keys for lookup tools (IP reputation, geolocation, etc.) are <span className="text-gray-300 font-medium">personal, not shared</span> — each user stores their own key here under their own account, and only that user's own requests use it. Nobody else, including admins, can see the key's value.</p>
          <p>Leave a field blank and save to clear a key.</p>
        </HelpButton>
      </div>
      <p className="text-sm text-white">
        Signed in as <span className="text-white font-medium">{user?.username}</span> — these keys apply to your account only.
      </p>

      {loading ? (
        <p className="text-sm text-white">Loading…</p>
      ) : (
        <div className="space-y-4 max-w-lg">
          {keys.map(k => {
            const isFreeTier = k.provider === 'ipapi_is' && k.free_tier
            return (
            <div key={k.provider} className="pb-4 border-b-2 border-gray-600 last:border-0 last:pb-0">
              <label className="block text-xs text-white mb-1">{k.label}</label>
              {MODAL_PROVIDERS.includes(k.provider) && (
                <label className="flex items-center gap-2 text-xs text-white cursor-pointer mb-1.5">
                  <input
                    type="checkbox"
                    checked={k.enabled}
                    onChange={e => handleToggleEnabled(k.provider, e.target.checked)}
                    className="accent-sky-600"
                  />
                  Show this provider in the IP Lookup modal
                </label>
              )}
              {k.provider === 'ipapi_is' && (
                <label className="flex items-center gap-2 text-xs text-white cursor-pointer mb-1.5">
                  <input
                    type="checkbox"
                    checked={k.free_tier}
                    onChange={e => handleToggleFreeTier(e.target.checked)}
                    className="accent-sky-600"
                  />
                  Use free tier (no key required, ~1,000 lookups/day)
                </label>
              )}
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={drafts[k.provider] ?? ''}
                  onChange={e => setDrafts(d => ({ ...d, [k.provider]: e.target.value }))}
                  placeholder="Not set"
                  disabled={isFreeTier}
                  className={`${inp} ${isFreeTier ? 'opacity-40 cursor-not-allowed' : ''}`}
                />
                <button
                  onClick={() => handleTest(k.provider)}
                  disabled={isFreeTier || testing[k.provider] || !(drafts[k.provider] ?? '').trim()}
                  className="shrink-0 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors disabled:opacity-50"
                >
                  {testing[k.provider] ? 'Testing…' : 'Test'}
                </button>
                <button
                  onClick={() => handleSave(k.provider)}
                  disabled={isFreeTier || saving[k.provider]}
                  className="shrink-0 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors"
                >
                  {saving[k.provider] ? 'Saving…' : 'Save'}
                </button>
              </div>
              {saved[k.provider] && <p className="text-xs text-green-400 mt-1">Saved</p>}
              {error[k.provider] && <p className="text-xs text-red-400 mt-1">{error[k.provider]}</p>}
              {testResult[k.provider] && (
                <p className={`text-xs mt-1 ${testResult[k.provider].ok ? 'text-green-400' : 'text-red-400'}`}>
                  {testResult[k.provider].ok ? '✓ ' : '✗ '}{testResult[k.provider].detail}
                </p>
              )}
              {FIELD_SETS[k.provider] && (
                <div className="mt-3 pl-1">
                  <p className="text-xs text-gray-500 mb-1.5">Shown in the IP Lookup modal:</p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                    {FIELD_SETS[k.provider].map(f => (
                      <label key={f.key} className="flex items-center gap-2 text-xs text-white cursor-pointer">
                        <input
                          type="checkbox"
                          checked={k.enabled_fields ? k.enabled_fields.includes(f.key) : true}
                          onChange={e => handleToggleField(k.provider, f.key, e.target.checked)}
                          className="accent-sky-600"
                        />
                        {f.label}
                      </label>
                    ))}
                  </div>
                  {fieldsError && <p className="text-xs text-red-400 mt-1">{fieldsError}</p>}
                </div>
              )}
            </div>
          )})}
        </div>
      )}

      <div className="pt-2 border-t border-gray-800 max-w-lg">
        <p className="text-xs font-semibold text-white uppercase tracking-wider mt-4 mb-1">Lucidchart</p>
        <label className="block text-xs text-white mb-1">API token</label>
        <div className="flex items-center gap-2">
          <input
            type="password"
            value={lucidToken}
            onChange={e => onLucidChange(e.target.value)}
            placeholder="eyJ…"
            className={inp}
          />
          <button
            onClick={lucidSave.save}
            disabled={lucidSave.saving}
            className="shrink-0 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors"
          >
            {lucidSave.saving ? 'Saving…' : 'Save'}
          </button>
        </div>
        {lucidSave.saved && <p className="text-xs text-green-400 mt-1">Saved</p>}
        {lucidSave.error && <p className="text-xs text-red-400 mt-1">{lucidSave.error}</p>}
        <p className="text-xs text-gray-500 mt-1">Personal Access Token from lucid.co → Account → API Tokens. Enables exporting diagrams into Lucidchart.</p>
      </div>
    </div>
  )
}

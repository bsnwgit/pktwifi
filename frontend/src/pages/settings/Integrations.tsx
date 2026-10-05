// Settings -> Security -> Integrations: suite token and sibling-app connections.
import { useEffect, useState } from 'react'
import {
  Integration,
  IntegrationInput,
  api,
} from '../../api/client'

// -- Sibling pkt app connections (outbound — pktWiFi calling into other pkt apps) --
export const SIBLING_LABELS: Record<string, string> = {
  pktsnmp: 'pktSNMP — device inventory & interface metrics',
  pktflow: 'pktFlow — traffic flow context',
  pktlog: 'pktLog — AP/controller syslogs',
  pktpcap: 'pktPCAP — packet capture feeds',
  pktipam: 'pktIPAM — subnet/DHCP/DNS inventory',
  pkthub: 'pktHub',
}

export interface IntegrationFormState {
  name: string; app_name: string; base_url: string; suite_token: string; verify_tls: boolean
}

// verify_tls defaults on for anything added here. Existing connections keep
// whatever they were saved with — see migration 013.
export const EMPTY_INTEGRATION: IntegrationFormState = {
  name: '', app_name: 'pktsnmp', base_url: '', suite_token: '', verify_tls: true,
}

export function IntegrationFormModal({ integration, onClose, onSaved }: {
  integration: Integration | null; onClose: () => void; onSaved: () => void
}) {
  const editing = !!integration
  const [form, setForm] = useState<IntegrationFormState>(
    editing ? { name: integration!.name, app_name: integration!.app_name, base_url: integration!.base_url,
                suite_token: '', verify_tls: integration!.verify_tls }
            : { ...EMPTY_INTEGRATION }
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const setF = <K extends keyof IntegrationFormState>(k: K, v: IntegrationFormState[K]) => setForm(f => ({ ...f, [k]: v }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (editing) {
        const body: Partial<IntegrationInput> = {
          name: form.name, base_url: form.base_url, verify_tls: form.verify_tls,
        }
        if (form.suite_token) body.suite_token = form.suite_token
        await api.updateIntegration(integration!.id, body)
      } else {
        await api.createIntegration(form)
      }
      onSaved()
    } catch (e: any) {
      setError(e.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const inp = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500'

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-sm p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-white mb-5">{editing ? `Edit — ${integration!.name}` : 'Add Connection'}</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-white block mb-1">Name *</label>
            <input value={form.name} onChange={e => setF('name', e.target.value)} required autoFocus
              placeholder="e.g. Main pktsnmp" className={inp} />
          </div>
          {!editing && (
            <div>
              <label className="text-xs text-white block mb-1">App *</label>
              <select value={form.app_name} onChange={e => setF('app_name', e.target.value)} className={inp}>
                {Object.keys(SIBLING_LABELS).map(app => (
                  <option key={app} value={app}>{SIBLING_LABELS[app]}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="text-xs text-white block mb-1">Base URL *</label>
            <input value={form.base_url} onChange={e => setF('base_url', e.target.value)} required
              placeholder="https://server:port" className={inp} />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Suite Token {editing ? '(leave blank to keep)' : '*'}</label>
            <input type="password" value={form.suite_token} onChange={e => setF('suite_token', e.target.value)}
              required={!editing} placeholder="From that app's Settings -> Security -> Suite Integration" className={inp} />
          </div>
          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.verify_tls} onChange={e => setF('verify_tls', e.target.checked)}
                className="accent-sky-600" />
              <span className="text-xs text-white">Verify TLS certificate</span>
            </label>
            <p className="text-xs text-gray-500 mt-1">
              Every call to this app carries its suite token. Turn this off only for an on-prem
              sibling behind a self-signed certificate.
            </p>
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-white">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg disabled:opacity-50">
              {saving ? 'Saving…' : (editing ? 'Save Changes' : 'Add Connection')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function SiblingIntegrations() {
  const [items, setItems] = useState<Integration[]>([])
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState<'new' | Integration | null>(null)
  const [confirm, setConfirm] = useState<Integration | null>(null)
  const [testResult, setTestResult] = useState<Record<number, string>>({})
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    api.getIntegrations().then(setItems).catch(e => setError(e.message)).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const del = async (i: Integration) => {
    try {
      await api.deleteIntegration(i.id)
      setConfirm(null)
      load()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const test = async (i: Integration) => {
    try {
      const result = await api.testIntegration(i.id)
      setTestResult(prev => ({ ...prev, [i.id]: result.healthy ? `OK — ${result.detail}` : `Failed — ${result.detail}` }))
    } catch (e: any) {
      setTestResult(prev => ({ ...prev, [i.id]: `Failed — ${e.message}` }))
    }
    load()
  }

  if (loading) return <p className="text-xs text-gray-500 animate-pulse py-3">Loading…</p>

  return (
    <div className="space-y-3 py-3">
      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-400 text-sm rounded-lg px-4 py-2 flex items-center justify-between">
          {error}<button onClick={() => setError('')} className="ml-4 text-red-600 hover:text-red-400">✕</button>
        </div>
      )}

      {items.map(i => (
        <div key={i.id} className="bg-gray-800/40 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <div>
              <p className="text-sm font-medium text-white">{i.name}</p>
              <p className="text-xs text-gray-500">{SIBLING_LABELS[i.app_name] ?? i.app_name} · {i.base_url || 'no URL set'}</p>
            </div>
            <span className={i.health_status === 'ok' ? 'text-xs text-green-400' : 'text-xs text-gray-500'}>{i.health_status}</span>
          </div>
          <div className="flex items-center gap-3 mt-2">
            <button onClick={() => test(i)} className="text-xs text-white border border-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-800">Test Connection</button>
            <button onClick={() => setModal(i)} className="text-xs text-white hover:text-sky-400">Edit</button>
            <button onClick={() => setConfirm(i)} className="text-xs text-white hover:text-red-400">Delete</button>
            {testResult[i.id] && <span className="text-xs text-gray-400">{testResult[i.id]}</span>}
          </div>
        </div>
      ))}
      {items.length === 0 && <p className="text-sm text-gray-500 py-2">No sibling pkt app connections yet.</p>}

      <button onClick={() => setModal('new')}
        className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg transition-colors">
        <span className="text-base leading-none">+</span> Add Connection
      </button>

      {modal !== null && (
        <IntegrationFormModal integration={modal === 'new' ? null : modal} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load() }} />
      )}

      {confirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setConfirm(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <h3 className="text-white font-semibold mb-2">Delete connection?</h3>
            <p className="text-white text-sm mb-5">
              Remove <strong className="text-white">{confirm.name}</strong>? Any feature using it (e.g. AP inventory
              from pktsnmp, syslog proxying from pktLog) will stop working until reconfigured.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirm(null)} className="px-4 py-2 text-sm text-white">Cancel</button>
              <button onClick={() => del(confirm)} className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Settings -> Controllers.
import { useEffect, useState } from 'react'
import {
  Collector,
  CollectorType,
  CredentialTestInput,
  FieldSchema,
  Site,
  WifiCredential,
  api,
} from '../../api/client'
import HelpButton from '../../components/HelpButton'
import CollectorConfigForm from '../../components/CollectorConfigForm'
import { copyToClipboard } from '../../utils/clipboard'

export function defaultConfigFor(fields: FieldSchema[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of fields) {
    if (f.default !== undefined) out[f.key] = f.default
    else if (f.type === 'string_list') out[f.key] = []
    else if (f.type === 'host_list') out[f.key] = []
    else if (f.type === 'multiselect') out[f.key] = []
  }
  return out
}

export function ControllerModal({ controller, types, sites, credentials, onClose, onSaved }: {
  controller?: (Collector & { config?: Record<string, unknown> }) | null
  types: CollectorType[]
  sites: Site[]
  credentials: WifiCredential[]
  onClose: () => void
  onSaved: () => void
}) {
  const editing = !!controller
  const [collectorType, setCollectorType] = useState(controller?.collector_type ?? '')
  const [name, setName] = useState(controller?.name ?? '')
  const [pollInterval, setPollInterval] = useState(controller?.poll_interval_sec ?? 60)
  const [enabled, setEnabled] = useState(controller?.enabled ?? true)
  const [config, setConfig] = useState<Record<string, unknown>>(controller?.config ?? {})
  const [showJson, setShowJson] = useState(false)
  const [jsonText, setJsonText] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const selectedType = types.find(t => t.type === collectorType)

  useEffect(() => {
    if (!editing && types.length && !collectorType) {
      const first = types.find(t => t.implemented) ?? types[0]
      setCollectorType(first.type)
      setConfig(defaultConfigFor(first.fields))
    }
  }, [types])

  const selectType = (type: string) => {
    setCollectorType(type)
    if (!editing) {
      const meta = types.find(t => t.type === type)
      setConfig(meta ? defaultConfigFor(meta.fields) : {})
    }
  }

  const setField = (key: string, v: unknown) => { setTestResult(null); setConfig(c => ({ ...c, [key]: v })) }

  // -- Test credentials against the controller being configured -----------------
  // The form already holds the target (controller URL / SNMP host), so the test
  // exercises the selected library credential against exactly this controller.
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null)

  const credTestBody = (): CredentialTestInput | null => {
    switch (collectorType) {
      case 'unifi':
        return config.auth_method === 'api_key'
          ? { vendor: 'unifi', target_url: (config.controller_url as string) ?? '', verify_tls: config.verify_tls !== false }
          : { target_url: (config.controller_url as string) ?? '', udm: !!config.udm, verify_tls: config.verify_tls !== false }
      case 'cisco_meraki':
        return { vendor: 'meraki' }
      case 'snmp_generic': {
        const first = (config.hosts as Array<Record<string, string>> | undefined)?.[0]
        return { host: first?.ip ?? '', port: (config.port as number) ?? 161 }
      }
      default:
        return null
    }
  }

  const canTest = !!config.credential_id && credTestBody() !== null

  const runTest = async () => {
    const body = credTestBody()
    if (!body || !config.credential_id) return
    setTesting(true)
    setTestResult(null)
    try {
      setTestResult(await api.testCredential(Number(config.credential_id), body))
    } catch (e: any) {
      setTestResult({ ok: false, detail: e.message ?? 'Test failed' })
    } finally {
      setTesting(false)
    }
  }

  const openJsonView = () => {
    setJsonText(JSON.stringify(config, null, 2))
    setShowJson(true)
  }

  const closeJsonView = () => {
    try {
      setConfig(JSON.parse(jsonText || '{}'))
      setShowJson(false)
      setError('')
    } catch {
      setError('Config JSON is invalid — fix it or discard changes to go back to the form')
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    let finalConfig = config
    if (showJson) {
      try {
        finalConfig = JSON.parse(jsonText || '{}')
      } catch {
        setError('Config JSON is invalid')
        return
      }
    }
    setSaving(true)
    try {
      const body = { name, collector_type: collectorType, config: finalConfig, poll_interval_sec: pollInterval, enabled }
      if (editing) await api.updateCollector(controller!.id, body)
      else await api.createCollector(body)
      onSaved()
    } catch (e: any) {
      setError(e.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const inp = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500'

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 overflow-y-auto py-8" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-white mb-5">{editing ? `Edit — ${controller!.name}` : 'New Controller'}</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-white block mb-1">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} required className={inp} />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Type</label>
            <select value={collectorType} onChange={e => selectType(e.target.value)} disabled={editing} className={inp}>
              {types.map(t => (
                <option key={t.type} value={t.type}>{t.label}{!t.implemented ? ' (not implemented)' : ''}</option>
              ))}
            </select>
          </div>
          {selectedType && !selectedType.implemented && (
            <p className="text-xs text-amber-400">This controller type is a documented stub — creating it will fail on poll until it's implemented.</p>
          )}

          {selectedType && (
            <div className="bg-gray-800/40 border border-gray-800 rounded-lg px-3">
              <div className="flex items-center justify-between pt-2">
                <p className="text-xs font-semibold text-white uppercase tracking-wider">Configuration</p>
                <button type="button" onClick={showJson ? closeJsonView : openJsonView}
                  className="text-xs text-sky-400 hover:text-sky-300">
                  {showJson ? '← Back to form' : 'Edit as JSON'}
                </button>
              </div>
              {showJson ? (
                <div className="py-3">
                  <textarea value={jsonText} onChange={e => setJsonText(e.target.value)} rows={10}
                    className={inp + ' font-mono resize-y'} spellCheck={false} />
                </div>
              ) : (
                <CollectorConfigForm fields={selectedType.fields} value={config} onChange={setField} sites={sites} credentials={credentials} />
              )}
            </div>
          )}

          {canTest && !showJson && (
            <div className="space-y-2">
              <button type="button" onClick={runTest} disabled={testing}
                className="text-xs text-sky-400 hover:text-sky-300 border border-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-50">
                {testing ? 'Testing…' : '⚡ Test Credentials'}
              </button>
              {testResult && (
                testResult.ok ? (
                  <p className="text-xs text-emerald-400">✓ {testResult.detail}</p>
                ) : (
                  <div className="bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
                    <p className="text-xs text-red-400 font-mono whitespace-pre-wrap break-all">{testResult.detail}</p>
                  </div>
                )
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-white block mb-1">Poll interval (sec)</label>
              <input type="number" min={15} value={pollInterval} onChange={e => setPollInterval(Number(e.target.value))} className={inp} />
            </div>
            <div className="flex items-end pb-2">
              <label className="flex items-center gap-2 text-sm text-white">
                <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Enabled
              </label>
            </div>
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-white">Cancel</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg disabled:opacity-50">
              {saving ? 'Saving…' : (editing ? 'Save Changes' : 'Create Controller')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function PollErrorModal({ message, onClose }: { message: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await copyToClipboard(message)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable — user can still select the text manually
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 py-8 px-4" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-lg w-full" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-white mb-3">Poll failed</h3>
        <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 max-h-64 overflow-y-auto mb-4">
          <p className="text-xs text-red-400 font-mono whitespace-pre-wrap break-all">{message}</p>
        </div>
        <div className="flex items-center justify-between">
          <button onClick={copy} className="text-xs text-sky-400 hover:text-sky-300 transition-colors">
            {copied ? '✓ Copied' : '⧉ Copy to clipboard'}
          </button>
          <button onClick={onClose} className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg">Close</button>
        </div>
      </div>
    </div>
  )
}

export function ControllersTab() {
  const [controllers, setControllers] = useState<Collector[]>([])
  const [types, setTypes] = useState<CollectorType[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [credentials, setCredentials] = useState<WifiCredential[]>([])
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState<'create' | (Collector & { config?: Record<string, unknown> }) | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Collector | null>(null)
  const [polling, setPolling] = useState<number | null>(null)
  const [pollResult, setPollResult] = useState<Record<number, string>>({})
  const [pollErrors, setPollErrors] = useState<Record<number, string>>({})
  const [errorModalFor, setErrorModalFor] = useState<number | null>(null)

  const load = () => {
    setLoading(true)
    Promise.all([api.getCollectors(), api.getCollectorTypes(), api.getSites(), api.getCredentials()])
      .then(([c, t, s, cr]) => { setControllers(c); setTypes(t); setSites(s); setCredentials(cr) })
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const openEdit = async (c: Collector) => {
    const full = await api.getCollector(c.id)
    setModal(full)
  }

  const del = async (c: Collector) => { await api.deleteCollector(c.id); setConfirmDelete(null); load() }

  const pollNow = async (c: Collector) => {
    setPolling(c.id)
    setPollResult(r => ({ ...r, [c.id]: '' }))
    try {
      const res = await api.pollCollectorNow(c.id)
      setPollResult(r => ({ ...r, [c.id]: `OK — ${res.access_points} AP(s), ${res.clients} client(s)` }))
    } catch (e: any) {
      const message = e.message ?? 'Poll failed'
      setPollResult(r => ({ ...r, [c.id]: 'Failed — see error' }))
      setPollErrors(r => ({ ...r, [c.id]: message }))
      setErrorModalFor(c.id)
    } finally {
      setPolling(null)
      load()
    }
  }

  const typeLabel = (type: string) => types.find(t => t.type === type)?.label ?? type

  if (loading) return <div className="flex items-center justify-center h-48 text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-white">Controllers</h2>
          <HelpButton title="Controllers — How It Works">
            <p>A controller is a <span className="text-gray-300 font-medium">WiFi data source</span> pktWiFi polls on an interval — a UniFi controller, a Meraki organization, or standalone SNMP access points. Each poll refreshes the Access Points, Clients, and RF metric data across the app.</p>
            <p>Controller auth comes from the <span className="text-gray-300 font-medium">Credentials</span> tab — pick a saved credential in the controller's form instead of typing usernames/passwords/API keys inline.</p>
            <p><span className="text-gray-300 font-medium">Poll Now</span> runs a real poll immediately and shows the result — the fastest way to verify a new controller's connection.</p>
          </HelpButton>
        </div>
        <button onClick={() => setModal('create')} className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg">
          <span className="text-base leading-none">+</span> Add Controller
        </button>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-5 py-3 text-xs font-medium text-white uppercase tracking-wider">Name</th>
              <th className="text-left px-5 py-3 text-xs font-medium text-white uppercase tracking-wider">Type</th>
              <th className="text-left px-5 py-3 text-xs font-medium text-white uppercase tracking-wider">Status</th>
              <th className="text-left px-5 py-3 text-xs font-medium text-white uppercase tracking-wider">Last Poll</th>
              <th></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60">
            {controllers.map(c => (
              <tr key={c.id} className="hover:bg-gray-800/30">
                <td className="px-5 py-3 text-white">{c.name}{!c.enabled && <span className="text-xs text-white ml-2">(disabled)</span>}</td>
                <td className="px-5 py-3 text-white text-xs">{typeLabel(c.collector_type)}</td>
                <td className="px-5 py-3">
                  <span className={`text-xs font-medium ${c.status === 'ok' ? 'text-emerald-400' : c.status === 'error' ? 'text-red-400' : 'text-white'}`}>
                    {c.status}
                  </span>
                  {c.last_error && <p className="text-xs text-red-400 mt-0.5 max-w-xs truncate" title={c.last_error}>{c.last_error}</p>}
                </td>
                <td className="px-5 py-3 text-white text-xs">{c.last_poll_at ?? 'never'}</td>
                <td className="px-5 py-3 text-right space-x-2 whitespace-nowrap">
                  {pollResult[c.id] && (
                    pollErrors[c.id] ? (
                      <button onClick={() => setErrorModalFor(c.id)} className="text-xs text-red-400 hover:text-red-300 mr-2 underline decoration-dotted">
                        {pollResult[c.id]}
                      </button>
                    ) : (
                      <span className="text-xs text-white mr-2">{pollResult[c.id]}</span>
                    )
                  )}
                  <button onClick={() => pollNow(c)} disabled={polling === c.id} className="text-xs text-white hover:text-sky-400 disabled:opacity-50">
                    {polling === c.id ? 'Polling…' : 'Poll Now'}
                  </button>
                  <button onClick={() => openEdit(c)} className="text-xs text-white hover:text-sky-400">Edit</button>
                  <button onClick={() => setConfirmDelete(c)} className="text-xs text-white hover:text-red-400">Delete</button>
                </td>
              </tr>
            ))}
            {controllers.length === 0 && <tr><td colSpan={5} className="px-5 py-8 text-center text-white">No controllers configured yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {modal !== null && (
        <ControllerModal controller={modal === 'create' ? null : modal} types={types} sites={sites} credentials={credentials}
          onClose={() => setModal(null)} onSaved={() => { setModal(null); load() }} />
      )}

      {errorModalFor !== null && pollErrors[errorModalFor] && (
        <PollErrorModal message={pollErrors[errorModalFor]} onClose={() => setErrorModalFor(null)} />
      )}

      {confirmDelete && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-sm w-full">
            <h3 className="text-white font-semibold mb-2">Delete controller?</h3>
            <p className="text-white text-sm mb-5"><strong>{confirmDelete.name}</strong> will be removed along with its access points/clients.</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDelete(null)} className="px-4 py-2 text-sm text-white">Cancel</button>
              <button onClick={() => del(confirmDelete)} className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// -- Sites tab (pktWiFi-specific) --------------------------------------------------
// The Sites list formerly at the top-level /sites nav page — populates the
// Site dropdowns in controller config forms.

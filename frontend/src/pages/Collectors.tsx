import { useEffect, useState } from 'react'
import { api, Collector, CollectorType } from '../api/client'
import clsx from 'clsx'

export default function Collectors() {
  const [collectors, setCollectors] = useState<Collector[]>([])
  const [types, setTypes] = useState<CollectorType[]>([])
  const [loading, setLoading] = useState(true)
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('snmp_generic')
  const [configText, setConfigText] = useState('{}')
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = () => Promise.all([api.getCollectors(), api.getCollectorTypes()])
    .then(([c, t]) => { setCollectors(c); setTypes(t); if (t.length) setNewType(t.find(x => x.implemented)?.type ?? t[0].type) })
    .catch(() => {})
    .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const createCollector = async () => {
    setError('')
    try {
      const config = JSON.parse(configText || '{}')
      await api.createCollector({ name: newName, collector_type: newType, config, poll_interval_sec: 60, enabled: true })
      setShowNew(false)
      setNewName('')
      setConfigText('{}')
      load()
    } catch (e: any) {
      setError(e.message || 'Failed to create collector — check config is valid JSON')
    }
  }

  const pollNow = async (id: number) => {
    setBusyId(id)
    try { await api.pollCollectorNow(id) } catch {} finally { setBusyId(null); load() }
  }

  const toggle = async (c: Collector) => { await api.updateCollector(c.id, { enabled: !c.enabled }); load() }
  const remove = async (id: number) => { if (confirm('Delete this collector?')) { await api.deleteCollector(id); load() } }

  if (loading) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Collectors</h1>
        <button onClick={() => setShowNew(true)} className="text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg px-3 py-1.5">
          Add Collector
        </button>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50 text-gray-400 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Last Poll</th>
              <th className="px-4 py-2 font-medium">Enabled</th>
              <th className="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {collectors.map(c => (
              <tr key={c.id} className="border-t border-gray-800">
                <td className="px-4 py-2 text-white">{c.name}</td>
                <td className="px-4 py-2 text-gray-300">{types.find(t => t.type === c.collector_type)?.label ?? c.collector_type}</td>
                <td className="px-4 py-2">
                  <span className={clsx('text-xs', c.status === 'ok' ? 'text-green-400' : c.status === 'error' ? 'text-red-400' : 'text-gray-500')}>
                    {c.status}{c.last_error ? ` — ${c.last_error}` : ''}
                  </span>
                </td>
                <td className="px-4 py-2 text-gray-500">{c.last_poll_at ?? 'never'}</td>
                <td className="px-4 py-2">
                  <button onClick={() => toggle(c)} className={clsx('text-xs px-2 py-1 rounded-md', c.enabled ? 'bg-green-500/20 text-green-300' : 'bg-gray-700 text-gray-400')}>
                    {c.enabled ? 'On' : 'Off'}
                  </button>
                </td>
                <td className="px-4 py-2 text-right space-x-3">
                  <button onClick={() => pollNow(c.id)} disabled={busyId === c.id} className="text-xs text-sky-400 hover:text-sky-300 disabled:opacity-50">
                    {busyId === c.id ? 'Polling…' : 'Poll now'}
                  </button>
                  <button onClick={() => remove(c.id)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
                </td>
              </tr>
            ))}
            {collectors.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No collectors configured yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-medium text-white mb-2">Available collector types</h2>
        <ul className="text-sm space-y-1">
          {types.map(t => (
            <li key={t.type} className="flex justify-between">
              <span className="text-gray-300">{t.label}</span>
              <span className={t.implemented ? 'text-green-400 text-xs' : 'text-gray-600 text-xs'}>
                {t.implemented ? 'available' : 'not yet implemented'}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {showNew && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowNew(false)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold text-white mb-4">Add Collector</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-white block mb-1">Name</label>
                <input value={newName} onChange={e => setNewName(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white" />
              </div>
              <div>
                <label className="text-xs text-white block mb-1">Type</label>
                <select value={newType} onChange={e => setNewType(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white">
                  {types.map(t => <option key={t.type} value={t.type} disabled={!t.implemented}>{t.label}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-white block mb-1">Config (JSON) — fields: {types.find(t => t.type === newType)?.fields.join(', ')}</label>
                <textarea value={configText} onChange={e => setConfigText(e.target.value)} rows={6}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs font-mono text-white" />
              </div>
              {error && <p className="text-red-400 text-xs">{error}</p>}
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <button onClick={() => setShowNew(false)} className="px-4 py-2 text-sm text-white">Cancel</button>
              <button onClick={createCollector} className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg">Create</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

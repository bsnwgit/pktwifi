import { useEffect, useState } from 'react'
import { api, AccessPoint, Radio } from '../api/client'
import clsx from 'clsx'

function StatusDot({ status }: { status: string }) {
  const color = status === 'online' ? 'bg-green-400' : status === 'offline' ? 'bg-red-400' : 'bg-gray-500'
  return <span className={clsx('inline-block w-2 h-2 rounded-full', color)} />
}

export default function AccessPoints() {
  const [aps, setAps] = useState<AccessPoint[]>([])
  const [selected, setSelected] = useState<(AccessPoint & { radios: Radio[] }) | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => api.getAccessPoints().then(setAps).catch(() => {}).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  const openDetail = async (id: number) => {
    const detail = await api.getAccessPoint(id)
    setSelected(detail)
  }

  if (loading) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-white">Access Points</h1>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50 text-gray-400 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Vendor</th>
              <th className="px-4 py-2 font-medium">IP</th>
              <th className="px-4 py-2 font-medium">Site / Floor</th>
              <th className="px-4 py-2 font-medium">Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {aps.map(ap => (
              <tr key={ap.id} className="border-t border-gray-800 hover:bg-gray-800/40 cursor-pointer" onClick={() => openDetail(ap.id)}>
                <td className="px-4 py-2"><StatusDot status={ap.status} /></td>
                <td className="px-4 py-2 text-white">{ap.name}{ap.is_rogue && <span className="ml-2 text-xs text-amber-400">rogue</span>}</td>
                <td className="px-4 py-2 text-gray-300">{ap.vendor ?? '—'}</td>
                <td className="px-4 py-2 text-gray-300">{ap.ip_address ?? '—'}</td>
                <td className="px-4 py-2 text-gray-300">{[ap.site, ap.floor].filter(Boolean).join(' / ') || '—'}</td>
                <td className="px-4 py-2 text-gray-500">{ap.last_seen ?? 'never'}</td>
              </tr>
            ))}
            {aps.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No access points yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold text-white mb-1">{selected.name}</h2>
            <p className="text-xs text-gray-500 mb-4">{selected.mac_address ?? 'no MAC recorded'} · {selected.model ?? 'unknown model'}</p>
            <div className="space-y-2">
              {selected.radios.length === 0 && <p className="text-sm text-gray-500">No radio data reported.</p>}
              {selected.radios.map(r => (
                <div key={r.id} className="bg-gray-800/50 rounded-lg px-3 py-2 text-sm flex justify-between">
                  <span className="text-white">{r.band}</span>
                  <span className="text-gray-400">
                    ch {r.channel ?? '—'} · {r.utilization_pct != null ? `${r.utilization_pct.toFixed(0)}%` : '—'} util · {r.client_count} clients
                  </span>
                </div>
              ))}
            </div>
            <button onClick={() => setSelected(null)} className="mt-4 text-sm text-sky-400 hover:text-sky-300">Close</button>
          </div>
        </div>
      )}
    </div>
  )
}

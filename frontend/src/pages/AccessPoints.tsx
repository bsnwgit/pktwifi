import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, AccessPoint, Radio, WifiClient, MetricPoint } from '../api/client'
import clsx from 'clsx'
import IpLink from '../components/IpLink'
import Pagination from '../components/Pagination'
import MetricChart from '../components/MetricChart'
import HelpButton from '../components/HelpButton'

const PAGE_SIZE = 50

const METRIC_WINDOWS = [
  { value: 60,    label: '1h' },
  { value: 360,   label: '6h' },
  { value: 1440,  label: '24h' },
  { value: 10080, label: '7d' },
]

function StatusDot({ status }: { status: string }) {
  const color = status === 'online' ? 'bg-green-400' : status === 'offline' ? 'bg-red-400' : 'bg-gray-500'
  return <span className={clsx('inline-block w-2 h-2 rounded-full', color)} />
}

export default function AccessPoints() {
  const navigate = useNavigate()

  const [aps, setAps]         = useState<AccessPoint[]>([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [search, setSearch]   = useState('')
  const [status, setStatus]   = useState('')
  const [loading, setLoading] = useState(true)

  const [selected, setSelected]     = useState<(AccessPoint & { radios: Radio[] }) | null>(null)
  const [selClients, setSelClients] = useState<WifiClient[]>([])
  const [detailLoading, setDetailLoading] = useState(false)

  const [metricsWindow, setMetricsWindow] = useState(360)
  const [metrics, setMetrics]             = useState<Record<string, MetricPoint[]> | null>(null)
  const [metricsLoading, setMetricsLoading] = useState(false)

  const load = useCallback((toPage = 1) => {
    setLoading(true)
    setPage(toPage)
    const filters = { search: search || undefined, status: status || undefined }
    Promise.all([
      api.getAccessPoints({ ...filters, limit: PAGE_SIZE, offset: (toPage - 1) * PAGE_SIZE }),
      api.countAccessPoints(filters),
    ])
      .then(([rows, countRes]) => { setAps(rows); setTotal(countRes.total) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [search, status])

  useEffect(() => { load(1) }, [load])

  const loadMetrics = (apId: number, minutes: number) => {
    setMetricsLoading(true)
    api.getAccessPointMetrics(apId, minutes)
      .then(setMetrics)
      .catch(() => setMetrics(null))
      .finally(() => setMetricsLoading(false))
  }

  const openDetail = async (id: number) => {
    setDetailLoading(true)
    setMetrics(null)
    try {
      const [detail, clients] = await Promise.all([
        api.getAccessPoint(id),
        api.getClients({ access_point_id: id }),
      ])
      setSelected(detail)
      setSelClients(clients)
      loadMetrics(id, metricsWindow)
    } finally {
      setDetailLoading(false)
    }
  }

  const changeMetricsWindow = (minutes: number) => {
    setMetricsWindow(minutes)
    if (selected) loadMetrics(selected.id, minutes)
  }

  const goToClients = () => {
    if (!selected) return
    setSelected(null)
    navigate(`/clients?access_point_id=${selected.id}&access_point_name=${encodeURIComponent(selected.name)}`)
  }

  if (loading && aps.length === 0) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-white">Access Points</h1>
            <HelpButton title="Access Points — How It Works">
              <p>Click a row to open <span className="text-gray-300 font-medium">radio detail, connected clients, and metric history</span> for that AP.</p>
              <p>Clicking any client in the detail panel jumps to the Clients page filtered to that AP.</p>
            </HelpButton>
          </div>
          <p className="text-sm text-white mt-0.5">{total.toLocaleString()} access point{total === 1 ? '' : 's'}</p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search name, MAC, IP, vendor, model…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 text-white placeholder-gray-500 rounded-lg px-3 py-1.5 w-64 focus:outline-none focus:border-sky-500"
        />
        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 text-gray-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
        >
          <option value="">All statuses</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
        </select>
        {(search || status) && (
          <button onClick={() => { setSearch(''); setStatus('') }} className="text-xs text-white hover:text-white">
            Clear filters
          </button>
        )}
      </div>

      <Pagination page={page} totalPages={Math.max(1, Math.ceil(total / PAGE_SIZE))} onChange={load} />

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
                <td className="px-4 py-2 text-gray-300">{ap.ip_address ? <IpLink ip={ap.ip_address} /> : '—'}</td>
                <td className="px-4 py-2 text-gray-300">{[ap.site, ap.floor].filter(Boolean).join(' / ') || '—'}</td>
                <td className="px-4 py-2 text-gray-500">{ap.last_seen ?? 'never'}</td>
              </tr>
            ))}
            {aps.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                {search || status ? 'No access points match your filters.' : 'No access points yet.'}
              </td></tr>
            )}
          </tbody>
        </table>
        {aps.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-800 text-xs text-gray-500">
            Showing {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{((page - 1) * PAGE_SIZE + aps.length).toLocaleString()} of {total.toLocaleString()} access points
          </div>
        )}
      </div>

      {selected && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 overflow-y-auto py-8" onClick={() => setSelected(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-2xl p-6 max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold text-white mb-1">{selected.name}</h2>
            <p className="text-xs text-gray-500 mb-4">{selected.mac_address ?? 'no MAC recorded'} · {selected.model ?? 'unknown model'}</p>

            {/* Radios */}
            <div className="space-y-2">
              {selected.radios.length === 0 && <p className="text-sm text-gray-500">No radio data reported.</p>}
              {selected.radios.map(r => (
                // An "unknown"-band row is the client bucket UniFi API-key
                // mode produces (clients aren't attributed to a radio there) —
                // render it as a clients line, not a broken-looking radio.
                r.band === 'unknown' ? (
                  <div key={r.id} className="bg-gray-800/50 rounded-lg px-3 py-2 text-sm flex justify-between">
                    <span className="text-white">Clients</span>
                    <span className="text-gray-400">{r.client_count} connected · per-radio breakdown not reported</span>
                  </div>
                ) : (
                  <div key={r.id} className="bg-gray-800/50 rounded-lg px-3 py-2 text-sm flex justify-between">
                    <span className="text-white">{r.band}</span>
                    <span className="text-gray-400">
                      ch {r.channel ?? '—'}{r.channel_width_mhz ? ` @ ${r.channel_width_mhz}MHz` : ''} · {r.utilization_pct != null ? `${r.utilization_pct.toFixed(0)}%` : '—'} util
                      {!selected.radios.some(x => x.band === 'unknown') && <> · {r.client_count} clients</>}
                    </span>
                  </div>
                )
              ))}
            </div>

            {/* Metrics */}
            <div className="mt-5">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-white uppercase tracking-wider">Metrics</p>
                <select
                  value={metricsWindow}
                  onChange={e => changeMetricsWindow(Number(e.target.value))}
                  className="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded-lg px-2 py-1 focus:outline-none focus:border-sky-500"
                >
                  {METRIC_WINDOWS.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}
                </select>
              </div>
              {metricsLoading ? (
                <div className="h-20 flex items-center justify-center text-xs text-gray-500">Loading…</div>
              ) : metrics && Object.keys(metrics).length > 0 ? (
                <div className="space-y-4">
                  {Object.entries(metrics).map(([band, points]) => (
                    <div key={band} className="bg-gray-800/30 rounded-lg p-3">
                      <p className="text-xs text-sky-400 font-medium mb-2">{band === 'unknown' ? 'Client bucket' : band}</p>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {band !== 'unknown' && (
                          <MetricChart data={points} dataKey="utilization_pct" label="Channel Utilization" color="#38bdf8" unit="%" />
                        )}
                        <MetricChart data={points} dataKey="client_count" label="Client Count" color="#34d399" />
                        {band !== 'unknown' && (
                          <MetricChart data={points} dataKey="retry_pct" label="Retry Rate" color="#f59e0b" unit="%" />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-500">No metric history for this window yet.</p>
              )}
            </div>

            {/* Clients */}
            <div className="mt-5">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-white uppercase tracking-wider">Clients ({selClients.length})</p>
                {selClients.length > 0 && (
                  <button onClick={goToClients} className="text-xs text-sky-400 hover:text-sky-300">
                    View all in Clients →
                  </button>
                )}
              </div>
              {detailLoading ? (
                <div className="h-16 flex items-center justify-center text-xs text-gray-500">Loading…</div>
              ) : selClients.length === 0 ? (
                <p className="text-xs text-gray-500">No clients currently attached.</p>
              ) : (
                <div className="space-y-1">
                  {selClients.map(c => (
                    <button
                      key={c.id}
                      onClick={goToClients}
                      title="View this AP's clients in the Clients page"
                      className="w-full text-left bg-gray-800/40 hover:bg-gray-800 rounded-lg px-3 py-1.5 text-sm flex items-center justify-between transition-colors"
                    >
                      <span className="text-white truncate">{c.hostname || c.mac_address}</span>
                      <span className="text-xs text-gray-400 flex items-center gap-2 shrink-0 ml-2">
                        {c.ssid && <span>{c.ssid}</span>}
                        {c.rssi_dbm != null && <span>{c.rssi_dbm} dBm</span>}
                        <span>→</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <button onClick={() => setSelected(null)} className="mt-5 text-sm text-sky-400 hover:text-sky-300">Close</button>
          </div>
        </div>
      )}
    </div>
  )
}

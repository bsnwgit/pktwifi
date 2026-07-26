import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, AccessPoint, Radio, WifiClient } from '../api/client'
import clsx from 'clsx'
import IpLink from '../components/IpLink'
import Pagination from '../components/Pagination'
import HelpButton from '../components/HelpButton'

const PAGE_SIZE = 50

function StatusDot({ status }: { status: string }) {
  const color = status === 'online' ? 'bg-green-400' : status === 'offline' ? 'bg-red-400' : 'bg-gray-500'
  return <span className={clsx('inline-block w-2 h-2 rounded-full', color)} />
}

function ClientRow({ c, onClick }: { c: WifiClient; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
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
  )
}

/**
 * Groups clients by the radio they're actually attached to, so each channel
 * gets its own list instead of one flat AP-wide list. Clients with no
 * radio_id (a collector that never attributes a client to any radio) fall
 * into a separate "Unassigned" bucket rather than being silently dropped.
 */
function groupClientsByRadio(clients: WifiClient[], radios: Radio[]) {
  const byRadio = new Map<number, WifiClient[]>()
  const unassigned: WifiClient[] = []
  for (const c of clients) {
    if (c.radio_id != null) {
      const list = byRadio.get(c.radio_id) ?? []
      list.push(c)
      byRadio.set(c.radio_id, list)
    } else {
      unassigned.push(c)
    }
  }
  const groups = radios
    .map(radio => ({ radio, clients: byRadio.get(radio.id) ?? [] }))
    .filter(g => g.clients.length > 0)
  return { groups, unassigned }
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

  const openDetail = async (id: number) => {
    setDetailLoading(true)
    try {
      const [detail, clients] = await Promise.all([
        api.getAccessPoint(id),
        api.getClients({ access_point_id: id }),
      ])
      setSelected(detail)
      setSelClients(clients)
    } finally {
      setDetailLoading(false)
    }
  }

  const goToClients = () => {
    if (!selected) return
    setSelected(null)
    navigate(`/clients?access_point_id=${selected.id}&access_point_name=${encodeURIComponent(selected.name)}`)
  }

  const goToMetrics = () => {
    if (!selected) return
    navigate(`/metrics?ap=${selected.id}`)
  }

  if (loading && aps.length === 0) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-white">Access Points</h1>
            <HelpButton title="Access Points — How It Works">
              <p>Click a row to open <span className="text-gray-300 font-medium">radio detail and connected clients</span> for that AP — clients are grouped by the actual channel they're attached to, where the controller reports it.</p>
              <p>Clicking any client in the detail panel jumps to the Clients page filtered to that AP. <span className="text-gray-300 font-medium">View Metrics →</span> opens the Metrics page pre-selected to this AP.</p>
            </HelpButton>
          </div>
          <p className="text-sm text-white mt-0.5">{total.toLocaleString()} access point{total === 1 ? '' : 's'}</p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search name, MAC, IP, vendor, model, status, site, floor…"
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
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h2 className="text-lg font-semibold text-white mb-1">{selected.name}</h2>
                <p className="text-xs text-gray-500">{selected.mac_address ?? 'no MAC recorded'} · {selected.model ?? 'unknown model'}</p>
              </div>
              <button onClick={goToMetrics} className="shrink-0 text-xs text-sky-400 hover:text-sky-300 border border-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-800 transition-colors">
                View Metrics →
              </button>
            </div>

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
              ) : (() => {
                const { groups, unassigned } = groupClientsByRadio(selClients, selected.radios)
                return (
                  <div className="space-y-4">
                    {groups.map(({ radio, clients }) => (
                      <div key={radio.id}>
                        <p className="text-xs text-gray-400 mb-1.5">
                          {radio.band === 'unknown'
                            ? 'No per-radio breakdown reported'
                            : `${radio.band} · ch ${radio.channel ?? '—'}`}
                          <span className="text-gray-600"> ({clients.length})</span>
                        </p>
                        <div className="space-y-1">
                          {clients.map(c => <ClientRow key={c.id} c={c} onClick={goToClients} />)}
                        </div>
                      </div>
                    ))}
                    {unassigned.length > 0 && (
                      <div>
                        <p className="text-xs text-gray-400 mb-1.5">
                          Unassigned<span className="text-gray-600"> ({unassigned.length})</span>
                        </p>
                        <div className="space-y-1">
                          {unassigned.map(c => <ClientRow key={c.id} c={c} onClick={goToClients} />)}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })()}
            </div>

            <button onClick={() => setSelected(null)} className="mt-5 text-sm text-sky-400 hover:text-sky-300">Close</button>
          </div>
        </div>
      )}
    </div>
  )
}

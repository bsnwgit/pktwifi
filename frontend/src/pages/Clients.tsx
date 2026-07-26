import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, WifiClient } from '../api/client'
import Pagination from '../components/Pagination'
import HelpButton from '../components/HelpButton'

const PAGE_SIZE = 50

function fmtConnected(iso: string | null): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z').getTime()
  if (ms < 0) return 'just now'
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ${mins % 60}m`
  return `${Math.floor(hrs / 24)}d ${hrs % 24}h`
}

export default function Clients() {
  const [searchParams, setSearchParams] = useSearchParams()
  const apFilterId   = searchParams.get('access_point_id')
  const apFilterName = searchParams.get('access_point_name')

  const [clients, setClients] = useState<WifiClient[]>([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [search, setSearch]   = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback((toPage = 1) => {
    setLoading(true)
    setPage(toPage)
    const filters = {
      access_point_id: apFilterId ? Number(apFilterId) : undefined,
      search: search || undefined,
    }
    Promise.all([
      api.getClients({ ...filters, limit: PAGE_SIZE, offset: (toPage - 1) * PAGE_SIZE }),
      api.countClients(filters),
    ])
      .then(([rows, countRes]) => { setClients(rows); setTotal(countRes.total) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [apFilterId, search])

  useEffect(() => { load(1) }, [load])

  const clearApFilter = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('access_point_id')
    next.delete('access_point_name')
    setSearchParams(next)
  }

  if (loading && clients.length === 0) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-white">Clients</h1>
          <HelpButton title="Clients — How It Works">
            <p>Every station currently or recently associated to a controller, across all bands and APs.</p>
            <p>SSID, signal, and rate columns are blank for controllers polled in a mode that doesn't report per-client RF detail (e.g. UniFi Integration API-key mode) — switch that controller to username/password auth under Settings → Controllers for full detail.</p>
          </HelpButton>
        </div>
        <p className="text-sm text-white mt-0.5">{total.toLocaleString()} client{total === 1 ? '' : 's'}</p>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search hostname, MAC, IP, SSID…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 text-white placeholder-gray-500 rounded-lg px-3 py-1.5 w-64 focus:outline-none focus:border-sky-500"
        />
        {apFilterId && (
          <div className="flex items-center gap-1.5 bg-sky-900/30 border border-sky-700/40 rounded-lg px-3 py-1.5 text-xs text-sky-300">
            <span>AP: {apFilterName || `#${apFilterId}`}</span>
            <button onClick={clearApFilter} className="text-sky-500 hover:text-sky-200 ml-1" title="Clear AP filter">✕</button>
          </div>
        )}
        {search && !apFilterId && (
          <button onClick={() => setSearch('')} className="text-xs text-white hover:text-white">Clear</button>
        )}
      </div>

      <Pagination page={page} totalPages={Math.max(1, Math.ceil(total / PAGE_SIZE))} onChange={load} />

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50 text-gray-400 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Client</th>
              <th className="px-4 py-2 font-medium">SSID</th>
              <th className="px-4 py-2 font-medium">Band</th>
              <th className="px-4 py-2 font-medium">Signal</th>
              <th className="px-4 py-2 font-medium">Rate (tx/rx)</th>
              <th className="px-4 py-2 font-medium">Connected</th>
              <th className="px-4 py-2 font-medium">Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {clients.map(c => (
              <tr key={c.id} className="border-t border-gray-800">
                <td className="px-4 py-2 text-white">{c.hostname || c.mac_address}</td>
                <td className="px-4 py-2 text-gray-300">{c.ssid ?? '—'}</td>
                <td className="px-4 py-2 text-gray-300">{c.band ?? '—'}</td>
                <td className="px-4 py-2 text-gray-300">
                  {c.rssi_dbm != null ? `${c.rssi_dbm} dBm` : '—'}{c.snr_db != null ? ` (${c.snr_db.toFixed(0)} dB SNR)` : ''}
                </td>
                <td className="px-4 py-2 text-gray-300">
                  {c.tx_rate_mbps ?? '—'} / {c.rx_rate_mbps ?? '—'} Mbps
                </td>
                <td className="px-4 py-2 text-gray-300">{fmtConnected(c.connected_at)}</td>
                <td className="px-4 py-2 text-gray-500">{c.last_seen}</td>
              </tr>
            ))}
            {clients.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                {search || apFilterId ? 'No clients match your filters.' : 'No clients seen yet.'}
              </td></tr>
            )}
          </tbody>
        </table>
        {clients.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-800 text-xs text-gray-500">
            Showing {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{((page - 1) * PAGE_SIZE + clients.length).toLocaleString()} of {total.toLocaleString()} clients
          </div>
        )}
      </div>
    </div>
  )
}

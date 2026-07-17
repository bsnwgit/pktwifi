import { useEffect, useState } from 'react'
import { api, WifiClient } from '../api/client'

export default function Clients() {
  const [clients, setClients] = useState<WifiClient[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getClients().then(setClients).catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-white">Clients</h1>
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50 text-gray-400 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Client</th>
              <th className="px-4 py-2 font-medium">SSID</th>
              <th className="px-4 py-2 font-medium">Band</th>
              <th className="px-4 py-2 font-medium">Signal</th>
              <th className="px-4 py-2 font-medium">Rate (tx/rx)</th>
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
                <td className="px-4 py-2 text-gray-500">{c.last_seen}</td>
              </tr>
            ))}
            {clients.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No clients seen yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

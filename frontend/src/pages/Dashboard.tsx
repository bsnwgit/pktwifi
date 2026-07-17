import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, DevicesSummary, AlertEvent, AccessPoint } from '../api/client'

function StatTile({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`text-2xl font-semibold mt-1 ${accent ?? 'text-white'}`}>{value}</p>
    </div>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState<DevicesSummary | null>(null)
  const [alerts, setAlerts] = useState<AlertEvent[]>([])
  const [aps, setAps] = useState<AccessPoint[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.getDevicesSummary(),
      api.getAlertEvents({ active: true, limit: 10 }),
      api.getAccessPoints(),
    ])
      .then(([s, a, d]) => { setSummary(s); setAlerts(a); setAps(d) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-white">Dashboard</h1>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatTile label="Access Points" value={summary?.total ?? 0} />
        <StatTile label="Online" value={summary?.online ?? 0} accent="text-green-400" />
        <StatTile label="Offline" value={summary?.offline ?? 0} accent="text-red-400" />
        <StatTile label="Rogue APs" value={summary?.rogue ?? 0} accent={summary?.rogue ? 'text-amber-400' : undefined} />
        <StatTile label="Connected Clients" value={summary?.total_clients ?? 0} accent="text-sky-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h2 className="text-sm font-medium text-white mb-3">Active Alerts</h2>
          {alerts.length === 0 ? (
            <p className="text-sm text-gray-500">No active alerts.</p>
          ) : (
            <ul className="space-y-2">
              {alerts.map(a => (
                <li key={a.id} className="text-sm flex items-start gap-2">
                  <span className={
                    a.severity === 'critical' ? 'text-red-400' : a.severity === 'warning' ? 'text-amber-400' : 'text-gray-400'
                  }>●</span>
                  <span className="text-white">{a.message}</span>
                </li>
              ))}
            </ul>
          )}
          <Link to="/alerts" className="text-xs text-sky-400 hover:text-sky-300 mt-3 inline-block">View all alerts →</Link>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h2 className="text-sm font-medium text-white mb-3">Access points by vendor</h2>
          {summary?.by_vendor.length ? (
            <ul className="space-y-1.5">
              {summary.by_vendor.map(v => (
                <li key={v.vendor} className="flex justify-between text-sm">
                  <span className="text-white">{v.vendor}</span>
                  <span className="text-gray-400">{v.count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-500">No access points yet — add a collector under Collectors.</p>
          )}
          <Link to="/access-points" className="text-xs text-sky-400 hover:text-sky-300 mt-3 inline-block">View all access points →</Link>
        </div>
      </div>

      {aps.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-sm text-gray-400">
          No access points reporting yet. Configure a collector (Settings → Collectors) or connect the pktsnmp
          integration (Settings → Integrations) to start seeing data.
        </div>
      )}
    </div>
  )
}

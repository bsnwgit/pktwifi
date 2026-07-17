import { useEffect, useState } from 'react'
import { api, AppLog } from '../api/client'

export default function Logs() {
  const [logs, setLogs] = useState<AppLog[]>([])
  const [level, setLevel] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => api.getAppLogs({ level: level || undefined, limit: 300 }).then(setLogs).catch(() => {}).finally(() => setLoading(false))
  useEffect(() => { load() }, [level])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold text-white">Application Logs</h1>
        <select value={level} onChange={e => setLevel(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-2 py-1">
          <option value="">All levels</option>
          <option value="WARNING">Warning+</option>
          <option value="ERROR">Error+</option>
        </select>
      </div>

      {loading ? <div className="text-white">Loading…</div> : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm font-mono">
            <tbody>
              {logs.map(l => (
                <tr key={l.id} className="border-t border-gray-800 align-top">
                  <td className="px-3 py-1.5 text-gray-500 whitespace-nowrap">{l.created_at}</td>
                  <td className={`px-3 py-1.5 whitespace-nowrap ${l.level === 'ERROR' || l.level === 'CRITICAL' ? 'text-red-400' : 'text-amber-400'}`}>{l.level}</td>
                  <td className="px-3 py-1.5 text-gray-400 whitespace-nowrap">{l.logger}</td>
                  <td className="px-3 py-1.5 text-white">{l.message}</td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-500 font-sans">No log entries.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

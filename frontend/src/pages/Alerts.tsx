import { useEffect, useState } from 'react'
import { api, AlertEvent, AlertRule, AlertConditionType } from '../api/client'
import clsx from 'clsx'

const CONDITION_LABELS: Record<AlertConditionType, string> = {
  ap_down: 'Access point unreachable',
  high_channel_util: 'High channel utilization',
  low_snr: 'Low client SNR',
  high_retry_rate: 'High retry rate',
  high_client_count: 'High client count on radio',
  rogue_ap: 'Rogue access point detected',
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium', {
      'bg-red-500/20 text-red-300': severity === 'critical',
      'bg-amber-500/20 text-amber-300': severity === 'warning',
      'bg-gray-500/20 text-gray-300': severity === 'info',
    })}>{severity}</span>
  )
}

export default function Alerts() {
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [rules, setRules] = useState<AlertRule[]>([])
  const [tab, setTab] = useState<'events' | 'rules'>('events')
  const [loading, setLoading] = useState(true)

  const load = () => Promise.all([api.getAlertEvents({ limit: 200 }), api.getAlertRules()])
    .then(([e, r]) => { setEvents(e); setRules(r) })
    .catch(() => {})
    .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const ack = async (id: number) => { await api.ackAlertEvent(id); load() }
  const resolve = async (id: number) => { await api.resolveAlertEvent(id); load() }
  const toggleRule = async (rule: AlertRule) => { await api.updateAlertRule(rule.id, { ...rule, enabled: !rule.enabled }); load() }

  if (loading) return <div className="text-white">Loading…</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-semibold text-white">Alerts</h1>
        <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1">
          <button onClick={() => setTab('events')} className={clsx('px-3 py-1 text-sm rounded-md', tab === 'events' ? 'bg-sky-600 text-white' : 'text-gray-400')}>Events</button>
          <button onClick={() => setTab('rules')} className={clsx('px-3 py-1 text-sm rounded-md', tab === 'rules' ? 'bg-sky-600 text-white' : 'text-gray-400')}>Rules</button>
        </div>
      </div>

      {tab === 'events' ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/50 text-gray-400 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Severity</th>
                <th className="px-4 py-2 font-medium">Message</th>
                <th className="px-4 py-2 font-medium">Created</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {events.map(e => (
                <tr key={e.id} className="border-t border-gray-800">
                  <td className="px-4 py-2"><SeverityBadge severity={e.severity} /></td>
                  <td className="px-4 py-2 text-white">{e.message}</td>
                  <td className="px-4 py-2 text-gray-500">{e.created_at}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {e.resolved ? 'resolved' : e.acked ? 'acknowledged' : 'active'}
                  </td>
                  <td className="px-4 py-2 text-right space-x-2">
                    {!e.acked && !e.resolved && <button onClick={() => ack(e.id)} className="text-xs text-sky-400 hover:text-sky-300">Ack</button>}
                    {!e.resolved && <button onClick={() => resolve(e.id)} className="text-xs text-gray-400 hover:text-white">Resolve</button>}
                  </td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">No alert events.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/50 text-gray-400 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Condition</th>
                <th className="px-4 py-2 font-medium">Threshold</th>
                <th className="px-4 py-2 font-medium">Severity</th>
                <th className="px-4 py-2 font-medium">Enabled</th>
              </tr>
            </thead>
            <tbody>
              {rules.map(r => (
                <tr key={r.id} className="border-t border-gray-800">
                  <td className="px-4 py-2 text-white">{r.name}</td>
                  <td className="px-4 py-2 text-gray-300">{CONDITION_LABELS[r.condition_type]}</td>
                  <td className="px-4 py-2 text-gray-300">{r.threshold ?? '—'}</td>
                  <td className="px-4 py-2"><SeverityBadge severity={r.severity} /></td>
                  <td className="px-4 py-2">
                    <button onClick={() => toggleRule(r)} className={clsx('text-xs px-2 py-1 rounded-md', r.enabled ? 'bg-green-500/20 text-green-300' : 'bg-gray-700 text-gray-400')}>
                      {r.enabled ? 'On' : 'Off'}
                    </button>
                  </td>
                </tr>
              ))}
              {rules.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">No alert rules configured.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

import { useEffect, useState, useCallback, useMemo } from 'react'
import clsx from 'clsx'
import { api, AlertEvent, AlertRule, AlertConditionType, NotifyChannel } from '../api/client'
import HelpButton from '../components/HelpButton'

// ── Time range ────────────────────────────────────────────────────────────────

const TIME_RANGES = [
  { value: '1h',     label: '1h' },
  { value: '6h',     label: '6h' },
  { value: '24h',    label: '24h' },
  { value: '7d',     label: '7d' },
  { value: '30d',    label: '30d' },
  { value: 'all',    label: 'All time' },
  { value: 'custom', label: 'Custom range…' },
] as const
type TimeRange = typeof TIME_RANGES[number]['value']

const TIME_RANGE_MS: Record<Exclude<TimeRange, 'all' | 'custom'>, number> = {
  '1h':  60 * 60 * 1000,
  '6h':  6 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '7d':  7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
}

interface TimeWindow {
  since?: string
  until?: string
}

// datetime-local values are local wall-clock time with no timezone info, so
// format from local (not UTC) date components — a plain toISOString() would
// shift the displayed clock time by the browser's UTC offset.
function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function todayStart(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return toLocalInputValue(d)
}
function todayEnd(): string {
  const d = new Date()
  d.setHours(23, 59, 0, 0)
  return toLocalInputValue(d)
}
/** Never allow a future moment — clamp back to right now instead. */
function clampFuture(value: string): string {
  if (!value) return value
  const now = new Date()
  return new Date(value).getTime() > now.getTime() ? toLocalInputValue(now) : value
}

/** Preset + custom date/time range picker. Reports the resolved {since, until} ISO bounds up to the parent. */
function TimeRangeControl({ onChange }: { onChange: (window: TimeWindow) => void }) {
  const [preset, setPreset]         = useState<TimeRange>('all')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo]     = useState('')
  const [rangeError, setRangeError] = useState('')

  const emit = (p: TimeRange, from: string, to: string) => {
    if (p === 'custom') {
      onChange({
        since: from ? new Date(from).toISOString() : undefined,
        until: to ? new Date(to).toISOString() : undefined,
      })
    } else if (p === 'all') {
      onChange({})
    } else {
      onChange({ since: new Date(Date.now() - TIME_RANGE_MS[p]).toISOString() })
    }
  }

  const applyCustom = (from: string, to: string) => {
    if (from && to && new Date(to).getTime() < new Date(from).getTime()) {
      setRangeError('End date/time must be after the start date/time.')
      return
    }
    setRangeError('')
    emit('custom', from, to)
  }

  const nowLocal = toLocalInputValue(new Date())

  return (
    <div className="flex items-center gap-1.5">
      <select
        value={preset}
        onChange={e => {
          const p = e.target.value as TimeRange
          setPreset(p)
          setRangeError('')
          if (p === 'custom') {
            const from = customFrom || todayStart()
            const to   = clampFuture(customTo || todayEnd())
            setCustomFrom(from)
            setCustomTo(to)
            applyCustom(from, to)
          } else {
            emit(p, customFrom, customTo)
          }
        }}
        className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
      >
        {TIME_RANGES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
      </select>
      {preset === 'custom' && (
        <>
          <input
            type="datetime-local"
            value={customFrom}
            max={nowLocal}
            onChange={e => {
              const v = clampFuture(e.target.value)
              setCustomFrom(v)
              applyCustom(v, customTo)
            }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
          <span className="text-xs text-gray-500">to</span>
          <input
            type="datetime-local"
            value={customTo}
            max={nowLocal}
            onChange={e => {
              const v = clampFuture(e.target.value)
              setCustomTo(v)
              applyCustom(customFrom, v)
            }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
          {rangeError && <span className="text-xs text-red-400">{rangeError}</span>}
        </>
      )}
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(ts: string): string {
  // created_at is stored as naive UTC (SQLite's datetime('now'), no 'Z') —
  // without forcing UTC interpretation here the browser parses it as local time.
  const utc = ts.includes('T') || ts.endsWith('Z') ? ts : ts.replace(' ', 'T') + 'Z'
  return new Date(utc).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

const SEV_STYLES: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border border-red-500/40',
  warning:  'bg-yellow-500/20 text-yellow-400 border border-yellow-500/40',
  info:     'bg-blue-500/20 text-blue-400 border border-blue-500/40',
}

const CONDITION_LABELS: Record<AlertConditionType, string> = {
  ap_down: 'Access point unreachable',
  high_channel_util: 'High channel utilization',
  low_snr: 'Low client SNR',
  high_retry_rate: 'High retry rate',
  high_client_count: 'High client count on radio',
  rogue_ap: 'Rogue access point detected',
}

const PAGE_SIZE_DEFAULT = 25
const PAGE_SIZE_OPTIONS = [25, 50, 75, 100]

function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (p: number) => void }) {
  if (totalPages <= 1) return null
  const blockStart = Math.floor((page - 1) / 5) * 5 + 1
  const blockEnd   = Math.min(blockStart + 4, totalPages)
  const pages = Array.from({ length: blockEnd - blockStart + 1 }, (_, i) => blockStart + i)
  const btn = (p: number) => [
    'text-xs min-w-[1.75rem] px-2 py-1 rounded-lg border transition-colors',
    p === page
      ? 'bg-sky-600/30 border-sky-500 text-sky-200'
      : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white',
  ].join(' ')
  return (
    <div className="flex items-center gap-1.5">
      <button onClick={() => onChange(Math.max(1, page - 1))} disabled={page === 1}
        className="text-xs px-2.5 py-1 rounded-lg border border-gray-700 bg-gray-800 text-gray-300 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        ← Prev
      </button>
      {blockStart > 1 && (<><button onClick={() => onChange(1)} className={btn(1)}>1</button><span className="px-1 text-gray-500 text-xs">..</span></>)}
      {pages.map(p => <button key={p} onClick={() => onChange(p)} className={btn(p)}>{p}</button>)}
      {blockEnd < totalPages && (<><span className="px-1 text-gray-500 text-xs">..</span><button onClick={() => onChange(totalPages)} className={btn(totalPages)}>{totalPages}</button></>)}
      <button onClick={() => onChange(Math.min(totalPages, page + 1))} disabled={page === totalPages}
        className="text-xs px-2.5 py-1 rounded-lg border border-gray-700 bg-gray-800 text-gray-300 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        Next →
      </button>
    </div>
  )
}

function EventCard({ event, onAck }: { event: AlertEvent; onAck: (id: number) => void }) {
  const isAcked    = event.acked
  const isResolved = event.resolved && !isAcked

  return (
    <div className={`bg-gray-900 border rounded-xl p-4 transition-opacity ${
      isAcked ? 'opacity-40 border-gray-800' : isResolved ? 'opacity-70 border-gray-700' : 'border-gray-700'
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium capitalize ${SEV_STYLES[event.severity] ?? SEV_STYLES.info}`}>
            {event.severity}
          </span>
          {event.auto_resolved && (
            <span className="shrink-0 text-xs px-2 py-0.5 rounded-full font-medium bg-green-500/20 text-green-400 border border-green-500/40">
              auto-resolved
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm text-white">{event.message}</p>
            <div className="flex items-center gap-3 mt-0.5">
              {event.access_point_id != null && <span className="text-xs text-gray-500">AP #{event.access_point_id}</span>}
              {event.client_mac && <span className="text-xs text-gray-500 font-mono">{event.client_mac}</span>}
              {event.value != null && event.threshold != null && (
                <span className="text-xs text-gray-500">{event.value} (threshold {event.threshold})</span>
              )}
            </div>
            {isResolved && event.resolved_at && (
              <p className="text-xs text-green-500/70 mt-0.5">Resolved {fmtTime(event.resolved_at)}</p>
            )}
          </div>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-xs text-white">{fmtTime(event.created_at)}</span>
          {!isAcked && (
            <button onClick={() => onAck(event.id)}
              className="text-xs bg-gray-800 hover:bg-gray-700 text-white border border-gray-700 rounded px-2.5 py-1 transition-colors">
              Ack
            </button>
          )}
          {isAcked && <span className="text-xs text-green-500">✓ Acked</span>}
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
type Tab = 'active' | 'history' | 'rules'

// Labels for the notification channels a rule can dispatch on. Configuring a
// channel lives in Settings → Notifications; this is only which of them a given
// rule uses, which is the half the engine reads.
const CHANNEL_LABELS: Record<NotifyChannel, string> = {
  slack:     'Slack',
  email:     'Email',
  pagerduty: 'PagerDuty',
  webhook:   'Webhook',
  tracecat:  'TraceCat',
}

function RuleModal({ rule, onClose, onSaved }: { rule?: AlertRule | null; onClose: () => void; onSaved: () => void }) {
  const editing = !!rule
  // Annotated, not inferred: `rule?.channels ?? []` infers as
  // `NotifyChannel[] | never[]`, and .includes() against that union narrows its
  // own parameter to `never`.
  const initialChannels: NotifyChannel[] = rule?.channels ?? []
  const [form, setForm] = useState({
    name: rule?.name ?? '',
    condition_type: rule?.condition_type ?? ('ap_down' as AlertConditionType),
    threshold: rule?.threshold != null ? String(rule.threshold) : '',
    severity: rule?.severity ?? 'warning',
    enabled: rule?.enabled ?? true,
    channels: initialChannels,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const toggleChannel = (c: NotifyChannel) =>
    setForm(f => ({
      ...f,
      channels: f.channels.includes(c) ? f.channels.filter(x => x !== c) : [...f.channels, c],
    }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const body = {
        name: form.name,
        condition_type: form.condition_type,
        threshold: form.threshold ? parseFloat(form.threshold) : null,
        severity: form.severity,
        enabled: form.enabled,
        channels: form.channels,
      }
      if (editing) await api.updateAlertRule(rule!.id, body)
      else await api.createAlertRule(body)
      onSaved()
    } catch (err: any) {
      setError(err.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-white mb-5">{editing ? `Edit — ${rule!.name}` : 'New Rule'}</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-white block mb-1">Name</label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} required
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500" />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Condition</label>
            <select value={form.condition_type} onChange={e => setForm(f => ({ ...f, condition_type: e.target.value as AlertConditionType }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500">
              {(Object.keys(CONDITION_LABELS) as AlertConditionType[]).map(c => <option key={c} value={c}>{CONDITION_LABELS[c]}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Threshold (optional)</label>
            <input type="number" value={form.threshold} onChange={e => setForm(f => ({ ...f, threshold: e.target.value }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500" />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Severity</label>
            <select value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value as 'critical' | 'warning' | 'info' }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500">
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Notify on</label>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(CHANNEL_LABELS) as NotifyChannel[]).map(c => {
                const on = form.channels.includes(c)
                return (
                  <button type="button" key={c} onClick={() => toggleChannel(c)}
                    className={clsx(
                      'px-3 py-1.5 text-xs border transition-colors',
                      on
                        ? 'bg-sky-600 border-sky-500 text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white hover:border-gray-600',
                    )}>
                    {CHANNEL_LABELS[c]}
                  </button>
                )
              })}
            </div>
            <p className="text-xs text-gray-500 mt-1.5">
              {form.channels.length === 0
                ? 'No channels — this rule records events here but notifies no one.'
                : 'Each channel must also be enabled and configured under Settings → Notifications.'}
            </p>
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-white hover:text-white transition-colors">Cancel</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg transition-colors disabled:opacity-50">
              {saving ? 'Saving…' : (editing ? 'Save Changes' : 'Create Rule')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Alerts() {
  const [tab, setTab]         = useState<Tab>('active')
  const [events, setEvents]   = useState<AlertEvent[]>([])
  const [history, setHistory] = useState<AlertEvent[]>([])
  const [rules, setRules]     = useState<AlertRule[]>([])
  const [loading, setLoading] = useState(true)
  const [editRule, setEditRule]     = useState<AlertRule | null>(null)
  const [addingRule, setAddingRule] = useState(false)

  const [eventsFilter, setEventsFilter]         = useState('')
  const [eventsSevFilter, setEventsSevFilter]   = useState('')
  const [eventsWindow, setEventsWindow]         = useState<TimeWindow>({})
  const [historyFilter, setHistoryFilter]       = useState('')
  const [historySevFilter, setHistorySevFilter] = useState('')
  const [historyWindow, setHistoryWindow]       = useState<TimeWindow>({})
  const [eventsPage, setEventsPage]             = useState(1)
  const [eventsPageSize, setEventsPageSize]     = useState(PAGE_SIZE_DEFAULT)
  const [historyPage, setHistoryPage]           = useState(1)
  const [historyPageSize, setHistoryPageSize]   = useState(PAGE_SIZE_DEFAULT)
  const [rulesFilter, setRulesFilter]           = useState('')

  const loadEvents = useCallback(async () => {
    setLoading(true)
    try {
      const [active, acked] = await Promise.all([
        api.getAlertEvents({ acked: false, limit: 200, since: eventsWindow.since, until: eventsWindow.until }),
        api.getAlertEvents({ acked: true, limit: 200, since: historyWindow.since, until: historyWindow.until }),
      ])
      setEvents(active)
      setHistory(acked)
    } finally {
      setLoading(false)
    }
  }, [eventsWindow, historyWindow])

  const loadRules = useCallback(async () => {
    try { setRules(await api.getAlertRules()) } catch {}
  }, [])

  useEffect(() => { loadEvents() }, [loadEvents])
  useEffect(() => { loadRules() }, [loadRules])

  const handleAck = async (id: number) => { await api.ackAlertEvent(id); await loadEvents() }
  const handleAckAll = async () => { await api.ackAllAlertEvents(); await loadEvents() }
  const handleToggle = async (rule: AlertRule) => {
    setRules(rs => rs.map(r => r.id === rule.id ? { ...r, enabled: !r.enabled } : r))
    try {
      await api.updateAlertRule(rule.id, { ...rule, enabled: !rule.enabled })
    } catch {
      setRules(rs => rs.map(r => r.id === rule.id ? { ...r, enabled: rule.enabled } : r))
    }
  }
  const handleDeleteRule = async (id: number) => {
    if (!confirm('Delete this alert rule?')) return
    await api.deleteAlertRule(id)
    await loadRules()
  }
  const changeEventsPageSize = (size: number) => {
    setEventsPageSize(size)
    setEventsPage(1)
  }
  const changeHistoryPageSize = (size: number) => {
    setHistoryPageSize(size)
    setHistoryPage(1)
  }

  const filteredEvents = useMemo(() => events.filter(e =>
    (!eventsSevFilter || e.severity === eventsSevFilter) &&
    (!eventsFilter || e.message.toLowerCase().includes(eventsFilter.toLowerCase()))
  ), [events, eventsSevFilter, eventsFilter])
  const eventsTotalPages = Math.max(1, Math.ceil(filteredEvents.length / eventsPageSize))
  const eventsPageClamped = Math.min(eventsPage, eventsTotalPages)
  const pagedEvents = filteredEvents.slice((eventsPageClamped - 1) * eventsPageSize, eventsPageClamped * eventsPageSize)

  const filteredHistory = useMemo(() => history.filter(e =>
    (!historySevFilter || e.severity === historySevFilter) &&
    (!historyFilter || e.message.toLowerCase().includes(historyFilter.toLowerCase()))
  ), [history, historySevFilter, historyFilter])
  const historyTotalPages = Math.max(1, Math.ceil(filteredHistory.length / historyPageSize))
  const historyPageClamped = Math.min(historyPage, historyTotalPages)
  const pagedHistory = filteredHistory.slice((historyPageClamped - 1) * historyPageSize, historyPageClamped * historyPageSize)

  const displayedRules = useMemo(() => rules.filter(r => {
    if (!rulesFilter) return true
    const q = rulesFilter.toLowerCase()
    return r.name.toLowerCase().includes(q) || r.condition_type.toLowerCase().includes(q) || r.severity.toLowerCase().includes(q)
  }), [rules, rulesFilter])

  const unackedCount = events.filter(e => !e.acked).length

  if (loading && events.length === 0 && history.length === 0) return <div className="text-white text-sm">Loading…</div>

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-white">Alerts</h1>
            <HelpButton title="Alerts — How It Works">
              <p>Six fixed condition types: <span className="text-gray-300 font-medium">access point unreachable</span>, <span className="text-gray-300 font-medium">high channel utilization</span>, <span className="text-gray-300 font-medium">low client SNR</span>, <span className="text-gray-300 font-medium">high retry rate</span>, <span className="text-gray-300 font-medium">high client count</span>, and <span className="text-gray-300 font-medium">rogue AP detected</span>.</p>
              <p>Auto-resolve means an open alert closes itself the next time its rule evaluates and the condition no longer holds — no need to manually clear it.</p>
            </HelpButton>
          </div>
          <p className="text-sm text-white mt-0.5">
            {unackedCount > 0 ? `${unackedCount} active alert${unackedCount !== 1 ? 's' : ''}` : 'No active alerts'}
          </p>
        </div>
        {tab === 'active' && events.length > 0 && (
          <button onClick={handleAckAll} className="text-sm border border-gray-700 hover:border-gray-500 text-white rounded-lg px-4 py-2 transition-colors">
            Ack all
          </button>
        )}
        {tab === 'rules' && (
          <button onClick={() => setAddingRule(true)} className="bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors">
            + New rule
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-xl p-1 w-fit">
        {(['active', 'history', 'rules'] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`text-sm px-4 py-1.5 rounded-lg transition-colors capitalize ${tab === t ? 'bg-gray-700 text-white' : 'text-white hover:text-white'}`}>
            {t}
            {t === 'active' && unackedCount > 0 && (
              <span className="ml-1.5 bg-red-500 text-white text-xs rounded-full px-1.5 py-0.5">{unackedCount}</span>
            )}
          </button>
        ))}
      </div>

      {/* Active events */}
      {tab === 'active' && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <input
              value={eventsFilter}
              onChange={e => { setEventsFilter(e.target.value); setEventsPage(1) }}
              placeholder="Filter by message…"
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-white placeholder-gray-600 w-56 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
            {eventsFilter && <button onClick={() => { setEventsFilter(''); setEventsPage(1) }} className="text-xs text-white hover:text-white">✕</button>}
            <select value={eventsSevFilter} onChange={e => { setEventsSevFilter(e.target.value); setEventsPage(1) }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-sky-500">
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
            {eventsSevFilter && <button onClick={() => { setEventsSevFilter(''); setEventsPage(1) }} className="text-xs text-white hover:text-white">✕</button>}
            <TimeRangeControl onChange={w => { setEventsWindow(w); setEventsPage(1) }} />
            {(eventsFilter || eventsSevFilter) && (
              <span className="text-xs text-white ml-auto">{filteredEvents.length} result{filteredEvents.length !== 1 ? 's' : ''}</span>
            )}
          </div>
          {loading && <p className="text-sm text-white">Loading…</p>}
          {!loading && events.length === 0 && (
            <div className="flex flex-col items-center justify-center h-32 text-white">
              <p className="text-2xl mb-2">✓</p>
              <p className="text-sm">No unacknowledged alerts</p>
            </div>
          )}
          {!loading && events.length > 0 && filteredEvents.length === 0 && (
            <p className="text-sm text-white text-center py-8">No alerts match this filter</p>
          )}
          {filteredEvents.length > 0 && (
            <div className="flex items-center justify-center gap-6">
              <Pagination page={eventsPageClamped} totalPages={eventsTotalPages} onChange={setEventsPage} />
              <div className="flex items-center gap-2">
                <label htmlFor="active-alerts-per-page" className="text-xs text-gray-400">Alerts per page:</label>
                <select
                  id="active-alerts-per-page"
                  value={eventsPageSize}
                  onChange={e => changeEventsPageSize(Number(e.target.value))}
                  className="text-sm bg-gray-800 border border-gray-700 text-white rounded-lg px-2 py-1 focus:outline-none focus:border-sky-500"
                >
                  {PAGE_SIZE_OPTIONS.map(size => (
                    <option key={size} value={size}>{size}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
          {pagedEvents.map(e => <EventCard key={e.id} event={e} onAck={handleAck} />)}
          {filteredEvents.length > 0 && (
            <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
              <span>Showing {((eventsPageClamped - 1) * eventsPageSize + 1).toLocaleString()}–{((eventsPageClamped - 1) * eventsPageSize + pagedEvents.length).toLocaleString()} of {filteredEvents.length.toLocaleString()} alerts</span>
              <Pagination page={eventsPageClamped} totalPages={eventsTotalPages} onChange={setEventsPage} />
            </div>
          )}
        </div>
      )}

      {/* History */}
      {tab === 'history' && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <input
              value={historyFilter}
              onChange={e => { setHistoryFilter(e.target.value); setHistoryPage(1) }}
              placeholder="Filter by message…"
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-white placeholder-gray-600 w-56 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
            {historyFilter && <button onClick={() => { setHistoryFilter(''); setHistoryPage(1) }} className="text-xs text-white hover:text-white">✕</button>}
            <select value={historySevFilter} onChange={e => { setHistorySevFilter(e.target.value); setHistoryPage(1) }}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-sky-500">
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
            {historySevFilter && <button onClick={() => { setHistorySevFilter(''); setHistoryPage(1) }} className="text-xs text-white hover:text-white">✕</button>}
            <TimeRangeControl onChange={w => { setHistoryWindow(w); setHistoryPage(1) }} />
            {(historyFilter || historySevFilter) && (
              <span className="text-xs text-white ml-auto">{filteredHistory.length} result{filteredHistory.length !== 1 ? 's' : ''}</span>
            )}
          </div>
          {history.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center h-32 text-white"><p className="text-sm">No alert history</p></div>
          )}
          {history.length > 0 && filteredHistory.length === 0 && (
            <p className="text-sm text-white text-center py-8">No alerts match this filter</p>
          )}
          {filteredHistory.length > 0 && (
            <div className="flex items-center justify-center gap-6">
              <Pagination page={historyPageClamped} totalPages={historyTotalPages} onChange={setHistoryPage} />
              <div className="flex items-center gap-2">
                <label htmlFor="alert-history-per-page" className="text-xs text-gray-400">Alerts per page:</label>
                <select
                  id="alert-history-per-page"
                  value={historyPageSize}
                  onChange={e => changeHistoryPageSize(Number(e.target.value))}
                  className="text-sm bg-gray-800 border border-gray-700 text-white rounded-lg px-2 py-1 focus:outline-none focus:border-sky-500"
                >
                  {PAGE_SIZE_OPTIONS.map(size => (
                    <option key={size} value={size}>{size}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
          {pagedHistory.map(e => <EventCard key={e.id} event={e} onAck={handleAck} />)}
          {filteredHistory.length > 0 && (
            <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
              <span>Showing {((historyPageClamped - 1) * historyPageSize + 1).toLocaleString()}–{((historyPageClamped - 1) * historyPageSize + pagedHistory.length).toLocaleString()} of {filteredHistory.length.toLocaleString()} alerts</span>
              <Pagination page={historyPageClamped} totalPages={historyTotalPages} onChange={setHistoryPage} />
            </div>
          )}
        </div>
      )}

      {/* Rules */}
      {tab === 'rules' && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-800 flex items-center gap-3 flex-wrap">
            <input
              value={rulesFilter}
              onChange={e => setRulesFilter(e.target.value)}
              placeholder="Filter by name, condition, severity…"
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-white placeholder-gray-600 w-56 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
            {rulesFilter && <button onClick={() => setRulesFilter('')} className="text-xs text-white hover:text-white">✕</button>}
            <span className="text-xs text-white ml-auto">{displayedRules.length} rule{displayedRules.length !== 1 ? 's' : ''}</span>
          </div>
          <table className="f-tbl-cards w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="px-4 py-3 text-left text-xs font-medium text-white">Enabled</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-white">Rule</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-white">Condition</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-white">Threshold</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-white">Severity</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-white">Notifies</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-white"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {displayedRules.map(rule => (
                <tr key={rule.id} className="hover:bg-gray-800/30 transition-colors">
                  <td data-label="Enabled" className="px-4 py-3">
                    <button onClick={() => handleToggle(rule)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${rule.enabled ? 'bg-sky-600' : 'bg-gray-700'}`}>
                      <span className={`inline-block h-3 w-3 rounded-full bg-white transition-transform ${rule.enabled ? 'translate-x-5' : 'translate-x-1'}`} />
                    </button>
                  </td>
                  <td data-label="Rule" className="px-4 py-3"><p className="font-medium text-white">{rule.name}</p></td>
                  <td data-label="Condition" className="px-4 py-3 text-white text-xs">
                    <span className="bg-gray-800 px-2 py-0.5 rounded">{CONDITION_LABELS[rule.condition_type]}</span>
                  </td>
                  <td data-label="Threshold" className="px-4 py-3 text-gray-300">{rule.threshold ?? '—'}</td>
                  <td data-label="Severity" className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${SEV_STYLES[rule.severity] ?? SEV_STYLES.info}`}>{rule.severity}</span>
                  </td>
                  <td data-label="Notifies" className="px-4 py-3 text-xs">
                    {rule.channels?.length
                      ? <span className="text-gray-300">{rule.channels.map(c => CHANNEL_LABELS[c] ?? c).join(', ')}</span>
                      : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <button onClick={() => setEditRule(rule)} className="text-xs text-white hover:text-sky-400 transition-colors">Edit</button>
                      <button onClick={() => handleDeleteRule(rule.id)} className="text-xs text-white hover:text-red-400 transition-colors">Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {displayedRules.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-white">
                  {rulesFilter ? 'No rules match this filter' : 'No alert rules yet — click "+ New rule" to add one'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {addingRule && <RuleModal onClose={() => setAddingRule(false)} onSaved={() => { setAddingRule(false); loadRules() }} />}
      {editRule && <RuleModal rule={editRule} onClose={() => setEditRule(null)} onSaved={() => { setEditRule(null); loadRules() }} />}
    </div>
  )
}

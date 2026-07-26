import { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, AccessPoint, MetricPoint } from '../api/client'
import MetricChart from '../components/MetricChart'
import HelpButton from '../components/HelpButton'
import clsx from 'clsx'

const TIME_WINDOWS = [
  { value: 60,    label: '1h' },
  { value: 360,   label: '6h' },
  { value: 1440,  label: '24h' },
  { value: 10080, label: '7d' },
]

function StatusDot({ status }: { status: string }) {
  const color = status === 'online' ? 'bg-green-400' : status === 'offline' ? 'bg-red-400' : 'bg-gray-500'
  return <span className={clsx('inline-block w-2 h-2 rounded-full shrink-0', color)} />
}

export default function Metrics() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [aps, setAps]         = useState<AccessPoint[]>([])
  const [apsLoading, setApsLoading] = useState(true)
  const [apSearch, setApSearch]     = useState('')

  const [selectedId, setSelectedId] = useState<number | null>(
    searchParams.get('ap') ? Number(searchParams.get('ap')) : null,
  )
  const [windowMinutes, setWindowMinutes] = useState(
    Number(searchParams.get('since')) || 360,
  )

  const [metrics, setMetrics] = useState<Record<string, MetricPoint[]> | null>(null)
  const [metricsLoading, setMetricsLoading] = useState(false)
  const [metricsError, setMetricsError] = useState('')
  // The chart X-axis domain — captured once per successful fetch, not
  // recomputed from the data itself. Deriving the domain from dataMin/
  // dataMax instead of the actual selected window was the bug behind
  // "even with less data the graph should show a compressed version with
  // proper ratio": 45 minutes of real points would stretch to fill the
  // whole chart width no matter whether the window was 1h or 7d, since the
  // axis only ever spanned whatever data happened to exist. Anchoring the
  // domain to [fetchedAt - windowMinutes, fetchedAt] makes a small amount
  // of data render as a small, correctly-proportioned slice of the chart
  // instead of being stretched to fill it.
  const [chartRange, setChartRange] = useState<[number, number] | null>(null)

  // Guards against an in-flight request from a previous AP/window selection
  // resolving *after* a newer one and clobbering it with stale data — this
  // is exactly the bug where changing the time range appeared to do nothing:
  // the fetch kicked off when the AP was first selected (at the old window)
  // could still be pending, land second, and silently overwrite the fresh
  // result.
  const requestSeq = useRef(0)

  useEffect(() => {
    api.getAccessPoints().then(setAps).catch(() => {}).finally(() => setApsLoading(false))
  }, [])

  const selected = aps.find(a => a.id === selectedId) ?? null

  const filteredAps = apSearch.trim()
    ? aps.filter(a => a.name.toLowerCase().includes(apSearch.toLowerCase()) || (a.vendor ?? '').toLowerCase().includes(apSearch.toLowerCase()))
    : aps

  const selectAp = (id: number) => {
    setSelectedId(id)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('ap', String(id))
      next.set('since', String(windowMinutes))
      return next
    }, { replace: true })
  }

  const changeWindow = (minutes: number) => {
    setWindowMinutes(minutes)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('since', String(minutes))
      return next
    }, { replace: true })
  }

  const loadMetrics = useCallback(() => {
    if (selectedId == null) { setMetrics(null); setChartRange(null); return }
    const seq = ++requestSeq.current
    setMetricsLoading(true)
    setMetricsError('')
    api.getAccessPointMetrics(selectedId, windowMinutes)
      .then(data => {
        if (seq !== requestSeq.current) return // a newer request already landed — discard this stale one
        const end = Date.now()
        setChartRange([end - windowMinutes * 60_000, end])
        setMetrics(data)
      })
      .catch(e => {
        if (seq !== requestSeq.current) return
        setMetricsError(e.message ?? 'Failed to load metrics')
        setMetrics(null)
      })
      .finally(() => {
        if (seq === requestSeq.current) setMetricsLoading(false)
      })
  }, [selectedId, windowMinutes])

  useEffect(() => { loadMetrics() }, [loadMetrics])

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-white">Metrics</h1>
          <HelpButton title="Metrics — How It Works">
            <p>Pick an access point on the left to see its <span className="text-gray-300 font-medium">radio detail (channel utilization, retry rate) and client count</span> over the selected time window, broken out per band.</p>
            <p>The time window applies immediately when changed — no separate reload needed.</p>
          </HelpButton>
        </div>
        <p className="text-sm text-white mt-0.5">Radio and client-count history for a selected access point</p>
      </div>

      <div className="flex gap-4 items-start">
        {/* AP picker */}
        <div className="w-64 shrink-0 bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="p-2 border-b border-gray-800">
            <input
              type="text"
              placeholder="Search access points…"
              value={apSearch}
              onChange={e => setApSearch(e.target.value)}
              className="w-full text-sm bg-gray-800 border border-gray-700 text-white placeholder-gray-500 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
            />
          </div>
          <div className="max-h-[65vh] overflow-y-auto">
            {apsLoading ? (
              <div className="p-4 text-center text-xs text-gray-500">Loading…</div>
            ) : filteredAps.length === 0 ? (
              <div className="p-4 text-center text-xs text-gray-500">No access points found.</div>
            ) : (
              filteredAps.map(ap => (
                <button
                  key={ap.id}
                  onClick={() => selectAp(ap.id)}
                  className={clsx(
                    'w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors border-l-2',
                    ap.id === selectedId
                      ? 'bg-sky-900/20 border-sky-500 text-white'
                      : 'border-transparent text-gray-300 hover:bg-gray-800/60',
                  )}
                >
                  <StatusDot status={ap.status} />
                  <span className="truncate">{ap.name}</span>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Chart panel */}
        <div className="flex-1 min-w-0 space-y-4">
          {!selected ? (
            <div className="flex items-center justify-center h-64 text-gray-500 text-sm bg-gray-900 border border-gray-800 rounded-xl">
              Select an access point to view its metrics
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between flex-wrap gap-2 bg-gray-900 border border-gray-800 rounded-xl px-4 py-3">
                <div className="flex items-center gap-2">
                  <StatusDot status={selected.status} />
                  <span className="text-white font-medium">{selected.name}</span>
                  <span className="text-xs text-gray-500">{selected.mac_address ?? 'no MAC recorded'} · {selected.model ?? 'unknown model'}</span>
                </div>
                <div className="flex items-center gap-1">
                  {TIME_WINDOWS.map(w => (
                    <button
                      key={w.value}
                      onClick={() => changeWindow(w.value)}
                      className={clsx(
                        'text-xs px-2.5 py-1 rounded-lg border transition-colors',
                        windowMinutes === w.value
                          ? 'bg-sky-600/30 border-sky-500 text-sky-200'
                          : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white',
                      )}
                    >
                      {w.label}
                    </button>
                  ))}
                </div>
              </div>

              {metricsError && (
                <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-2 text-sm text-red-300">
                  {metricsError}
                </div>
              )}

              {metricsLoading ? (
                <div className="flex items-center justify-center h-40 text-gray-500 text-sm bg-gray-900 border border-gray-800 rounded-xl">
                  Loading…
                </div>
              ) : metrics && Object.keys(metrics).length > 0 && chartRange ? (
                <div className="space-y-4">
                  {Object.entries(metrics).map(([band, points]) => (
                    <div key={band} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                      <p className="text-sm text-sky-400 font-medium mb-3">{band === 'unknown' ? 'Client bucket (no per-radio breakdown reported)' : band}</p>
                      <div className="space-y-4">
                        {band !== 'unknown' && (
                          <MetricChart data={points} dataKey="utilization_pct" label="Channel Utilization" color="#38bdf8" unit="%" range={chartRange} />
                        )}
                        <MetricChart data={points} dataKey="client_count" label="Client Count" color="#34d399" range={chartRange} />
                        {band !== 'unknown' && (
                          <MetricChart data={points} dataKey="retry_pct" label="Retry Rate" color="#f59e0b" unit="%" range={chartRange} />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-center justify-center h-40 text-gray-500 text-sm bg-gray-900 border border-gray-800 rounded-xl">
                  No metric history for this window yet.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

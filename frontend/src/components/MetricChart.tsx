import { useMemo } from 'react'
import { LineChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts'
import { MetricPoint } from '../api/client'

function toMs(ts: string): number {
  return new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z').getTime()
}

function tsShort(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Small time-series line chart for one radio_metrics field — shared by the
 * Metrics page for both "radio detail" metrics (utilization, retry %) and
 * client count over time.
 *
 * The X axis must be a real numeric time scale (type="number" scale="time"
 * domain={['dataMin','dataMax']}), same as pktsnmp's MetricsPage chart —
 * without it, recharts defaults XAxis to type="category", which just
 * evenly spaces whatever points happen to be in the array with no regard
 * to their actual timestamps. That made every time-window selection look
 * nearly identical: switching 1h -> 7d didn't visibly change anything
 * because the points were never positioned by real elapsed time in the
 * first place.
 */
export default function MetricChart({ data, dataKey, label, color, unit = '' }: {
  data: MetricPoint[]
  dataKey: 'utilization_pct' | 'retry_pct' | 'client_count'
  label: string
  color: string
  unit?: string
}) {
  const points = useMemo(
    () => data.filter(p => p[dataKey] != null).map(p => ({ ...p, tMs: toMs(p.ts) })),
    [data, dataKey],
  )

  if (points.length === 0) {
    return (
      <div>
        <p className="text-xs text-gray-400 mb-1">{label}</p>
        <div className="h-20 flex items-center justify-center text-xs text-gray-600 bg-gray-800/30 rounded-lg">
          No data yet
        </div>
      </div>
    )
  }
  const last = points[points.length - 1][dataKey]
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-400">{label}</span>
        <span className="text-xs font-mono text-white">{last != null ? `${Math.round(last)}${unit}` : '—'}</span>
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <LineChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="tMs"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={tsShort}
            tick={{ fontSize: 10, fill: '#6b7280' }}
            minTickGap={40}
          />
          <YAxis hide domain={[0, 'auto']} />
          <Tooltip
            labelFormatter={(v: number) => new Date(v).toLocaleString()}
            formatter={(v: number) => [`${Math.round(v)}${unit}`, label]}
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }}
            labelStyle={{ color: '#9ca3af' }}
          />
          <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

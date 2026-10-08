/**
 * Dashboard — the estate at a glance, drawn as instruments.
 *
 * Everything on the page comes from one /api/dashboard read, so the readouts,
 * the spectrum and the scope all describe the same poll. The window picker
 * moves only the two trends and the client-activity counts; every other panel
 * is the estate as of its latest poll, and its chip says "now".
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { api, DashboardData } from '../api/client'
import HelpButton from '../components/HelpButton'
import Spectrum from '../components/Spectrum'
import SignalScope from '../components/SignalScope'
import {
  axisProps, tooltipProps, gridProps, glow, INSTRUMENT,
  InstrumentFrame, RadialRing, FlowDefs, NodeRail, LinePulseGradient, liveEdgeDot,
} from '../components/instrument'
import { ALARM, SIGNAL_COLOR, SignalClass, bandColor, bandLabel, bandRank, signalClass } from '../utils/rf'

// ── Constants ──────────────────────────────────────────────────────────────────

const WINDOWS = [
  { hours: 1,   label: '1h' },
  { hours: 6,   label: '6h' },
  { hours: 24,  label: '24h' },
  { hours: 168, label: '7d' },
]
const DEFAULT_HOURS = 6
const REFRESH_MS = 30_000
const TREND_H = 180
const MONO = 'ui-monospace, SF Mono, Menlo, monospace'

// Hues for things that are not bands (SSIDs), from the console's own palette
// and never from the alarm colours.
const SERIES = ['#d8b46e', '#8ad8ea', '#a78bfa', '#9aeabd', '#e9cd95', '#6fb7d8', '#c9b3f5', '#7fc8c0']
const CATCH_ALL = new Set(['Other SSIDs', 'Not reported'])

const GENERATIONS: Array<[string, string]> = [
  ['Wi-Fi 7', '#a78bfa'],
  ['Wi-Fi 6', INSTRUMENT.ice],
  ['Wi-Fi 5', INSTRUMENT.gold],
  ['Wi-Fi 4', '#a9a294'],
  ['Legacy',  '#77705f'],
  ['Other',   '#565046'],
  ['Unknown', '#565046'],
]

const COLLECTOR_LABEL: Record<string, string> = {
  snmp_generic: 'SNMP', cisco_meraki: 'Meraki', unifi: 'UniFi',
  aruba_central: 'Aruba', cisco_catalyst: 'Catalyst', ruckus: 'Ruckus',
}

const EVENT_LABEL: Record<string, string> = {
  associate: 'Associations', roam: 'Roams', disassociate: 'Disassociations',
  deauth: 'Deauths', auth_fail: 'Auth failures',
}

const UTIL_SERIES = [
  { key: 'util_2g', band: '2.4GHz' },
  { key: 'util_5g', band: '5GHz' },
  { key: 'util_6g', band: '6GHz' },
] as const

// ── Helpers ────────────────────────────────────────────────────────────────────

type TrendRow = {
  tMs: number
  clients: number | null
  util_2g: number | null
  util_5g: number | null
  util_6g: number | null
}

/** One row per bucket across the whole window. A bucket with no samples stays
 *  null, so an outage draws as a gap instead of a line straight across it. */
function fillTrend(d: DashboardData): TrendRow[] {
  const { since, until, step_sec: step } = d.window
  const byT = new Map(d.trend.map(p => [p.t, p]))
  const rows: TrendRow[] = []
  for (let t = Math.floor(since / step) * step; t <= until; t += step) {
    const p = byT.get(t)
    rows.push({
      tMs: t * 1000,
      clients: p?.clients ?? null,
      util_2g: p?.util_2g ?? null,
      util_5g: p?.util_5g ?? null,
      util_6g: p?.util_6g ?? null,
    })
  }
  return rows
}

function lastIndexWith(rows: TrendRow[], key: Exclude<keyof TrendRow, 'tMs'>): number {
  for (let i = rows.length - 1; i >= 0; i--) if (rows[i][key] != null) return i
  return -1
}

/** Tick labels carry the date once the window is wider than a day. */
function timeTick(spanMs: number) {
  const withDate = spanMs > 24 * 3600 * 1000
  return (ms: number) => new Date(ms).toLocaleString([], withDate
    ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' })
}

function parseUtc(ts: string): Date {
  return new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z')
}

function fmtAgo(ts: string | null): string {
  if (!ts) return 'never'
  const s = Math.max(0, Math.round((Date.now() - parseUtc(ts).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function dotFor(status: string): string {
  if (status === 'online' || status === 'ok') return 'f-dot-up'
  if (status === 'offline' || status === 'error') return 'f-dot-down'
  return 'f-dot-off'
}

function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    if (!ref.current) return
    const obs = new ResizeObserver(entries => {
      const w = entries[0].contentRect.width
      if (w > 50) setWidth(w)
    })
    obs.observe(ref.current)
    return () => obs.disconnect()
  }, [])
  return [ref, width] as const
}

// ── Chrome ─────────────────────────────────────────────────────────────────────

function Card({ title, chip, children, className = '' }: {
  title: string
  chip?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`bg-gray-900 rounded-xl border border-gray-800 p-4 flex flex-col min-w-0 ${className}`}>
      <div className="flex items-center justify-between gap-3 mb-3 flex-shrink-0">
        <h2 className="text-sm font-semibold text-white truncate">{title}</h2>
        {chip}
      </div>
      <div className="flex-1 min-h-0">{children}</div>
    </section>
  )
}

const NowChip = () => <span className="f-chip">now</span>
const WindowChip = ({ label }: { label: string }) => <span className="f-chip f-chip-ice">last {label}</span>

function Empty({ msg, height = 120 }: { msg: string; height?: number }) {
  return <div className="grid place-items-center text-center text-xs text-gray-500 px-4" style={{ height }}>{msg}</div>
}

/** A readout cell: hairline grid, corner ticks on hover, optional arc gauge. */
function Readout({ label, value, unit, sub, tone = 'ink', gauge, onClick }: {
  label: string
  value: ReactNode
  unit?: string
  sub?: ReactNode
  tone?: 'ink' | 'gold' | 'ice' | 'alarm' | 'good' | 'fair'
  gauge?: number
  onClick?: () => void
}) {
  const R = 19
  const C = 2 * Math.PI * R
  const toneClass = { ink: 'text-white', gold: 'f-num-gold', ice: 'f-num-ice', alarm: 'f-num-alarm', good: 'f-num-good', fair: 'f-num-fair' }[tone]
  return (
    <div
      className={`f-tick relative bg-gray-950 px-4 py-3.5 min-h-[104px] flex flex-col min-w-0 transition-colors ${
        gauge !== undefined ? 'pr-[62px]' : ''
      } ${onClick ? 'cursor-pointer hover:bg-blue-500/[0.03]' : ''}`}
      onClick={onClick}
    >
      <div className="f-lbl f-lbl-gold">{label}</div>
      {gauge !== undefined && (
        <svg className="absolute top-3 right-3" width="46" height="46" viewBox="0 0 46 46" fill="none" aria-hidden="true">
          <circle cx="23" cy="23" r={R} stroke="rgba(216,180,110,.20)" strokeWidth="2" />
          <circle
            cx="23" cy="23" r={R}
            stroke={tone === 'alarm' ? ALARM : INSTRUMENT.gold} strokeWidth="2" strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - Math.max(0, Math.min(100, gauge)) / 100)}
            transform="rotate(-90 23 23)"
            style={{ filter: 'drop-shadow(0 0 5px rgba(216,180,110,.5))', transition: 'stroke-dashoffset .6s ease' }}
          />
          <circle cx="23" cy="23" r="12" stroke="rgba(216,180,110,.44)" />
        </svg>
      )}
      <div className={`f-num text-[clamp(24px,2.3vw,34px)] mt-2.5 mb-2 ${toneClass}`}>
        {value}
        {unit && <span className="text-[11px] text-gray-500 ml-1">{unit}</span>}
      </div>
      {sub && (
        <div className="font-mono text-[9.5px] text-gray-500 mt-auto truncate" title={typeof sub === 'string' ? sub : undefined}>
          {sub}
        </div>
      )}
    </div>
  )
}

// ── Trends ─────────────────────────────────────────────────────────────────────

/** liveEdgeDot, keyed. Recharts calls a dot renderer as a plain function and
 *  passes the key in its props, so the element that comes back must carry it. */
function keyedEdgeDot(dataLength: number, color: string) {
  const edge = liveEdgeDot(dataLength, color)
  return (props: any) => <g key={props.key}>{edge(props)}</g>
}

/** Whether every sample in a series is the same value. The travelling pulse is
 *  a gradient sized to the line's bounding box, and a perfectly flat line has
 *  no height — the browser then paints nothing — so a steady series would
 *  vanish. Flat series take a solid stroke instead. */
function isFlat(rows: TrendRow[], key: Exclude<keyof TrendRow, 'tMs'>): boolean {
  const values = rows.flatMap(r => (r[key] == null ? [] : [r[key] as number]))
  return values.length > 0 && Math.min(...values) === Math.max(...values)
}

function ClientsTrend({ rows, spanMs }: { rows: TrendRow[]; spanMs: number }) {
  const last = lastIndexWith(rows, 'clients')
  if (last < 0) return <Empty msg="No client history in this window yet" height={TREND_H} />
  const flat = isFlat(rows, 'clients')
  return (
    <InstrumentFrame height={TREND_H} live>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 10, right: 10, bottom: 4, left: 0 }}>
          <defs>
            <LinePulseGradient id="dash-pulse-clients" color={INSTRUMENT.ice} />
            <linearGradient id="dash-fill-clients" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={INSTRUMENT.ice} stopOpacity={0.3} />
              <stop offset="95%" stopColor={INSTRUMENT.ice} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="tMs" type="number" scale="time" domain={['dataMin', 'dataMax']}
                 tickFormatter={timeTick(spanMs)} minTickGap={48} {...axisProps} />
          <YAxis width={36} allowDecimals={false} domain={[0, 'auto']} {...axisProps} />
          <Tooltip
            contentStyle={tooltipProps.contentStyle}
            labelStyle={tooltipProps.labelStyle}
            cursor={tooltipProps.cursor}
            labelFormatter={(v: number) => new Date(v).toLocaleString()}
            formatter={(v: number) => [Math.round(v).toLocaleString(), 'Clients']}
          />
          <Area type="monotone" dataKey="clients" isAnimationActive={false}
                stroke={flat ? INSTRUMENT.ice : 'url(#dash-pulse-clients)'} strokeWidth={2}
                style={glow(INSTRUMENT.ice, 5)} fill="url(#dash-fill-clients)"
                dot={keyedEdgeDot(last + 1, INSTRUMENT.ice)}
                activeDot={{ r: 3, strokeWidth: 0, fill: INSTRUMENT.ice }} />
        </AreaChart>
      </ResponsiveContainer>
    </InstrumentFrame>
  )
}

function AirtimeTrend({ rows, spanMs, hotPct }: { rows: TrendRow[]; spanMs: number; hotPct: number }) {
  const series = UTIL_SERIES
    .map(s => ({ ...s, color: bandColor(s.band), last: lastIndexWith(rows, s.key), flat: isFlat(rows, s.key) }))
    .filter(s => s.last >= 0)
  if (!series.length) return <Empty msg="No radio reported utilization in this window" height={TREND_H} />
  return (
    <div>
      <InstrumentFrame height={TREND_H} live>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 10, right: 10, bottom: 4, left: 0 }}>
            {/* One pulse per band, all on the same beat — a single scan across
                the time axis, so no band is made to look faster than another. */}
            <defs>
              {series.map(s => <LinePulseGradient key={s.key} id={`dash-pulse-${s.key}`} color={s.color} />)}
            </defs>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="tMs" type="number" scale="time" domain={['dataMin', 'dataMax']}
                   tickFormatter={timeTick(spanMs)} minTickGap={48} {...axisProps} />
            <YAxis width={36} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]}
                   tickFormatter={(v: number) => `${v}%`} {...axisProps} />
            <Tooltip
              contentStyle={tooltipProps.contentStyle}
              labelStyle={tooltipProps.labelStyle}
              cursor={tooltipProps.cursor}
              labelFormatter={(v: number) => new Date(v).toLocaleString()}
              formatter={(v: number, key: string) => [`${v}%`, bandLabel(UTIL_SERIES.find(s => s.key === key)?.band)]}
            />
            {hotPct <= 100 && <ReferenceLine y={hotPct} stroke={ALARM} strokeOpacity={0.6} strokeDasharray="2 4" />}
            {series.map(s => (
              <Line key={s.key} type="monotone" dataKey={s.key} isAnimationActive={false}
                    stroke={s.flat ? s.color : `url(#dash-pulse-${s.key})`} strokeWidth={1.8}
                    style={glow(s.color, 5)}
                    dot={keyedEdgeDot(s.last + 1, s.color)}
                    activeDot={{ r: 3, strokeWidth: 0, fill: s.color }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </InstrumentFrame>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2">
        {series.map(s => (
          <span key={s.key} className="flex items-center gap-1.5 font-mono text-[10px] text-gray-400">
            <span className="w-3 h-0.5" style={{ background: s.color, boxShadow: `0 0 5px ${s.color}` }} />
            {bandLabel(s.band)} <span className="text-white">{Math.round(rows[s.last][s.key] ?? 0)}%</span>
          </span>
        ))}
        {hotPct <= 100 && (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-gray-500">
            <span className="w-3 border-t border-dashed" style={{ borderColor: ALARM }} />
            alert at {hotPct}%
          </span>
        )}
      </div>
    </div>
  )
}

// ── Client flow: SSID → band ───────────────────────────────────────────────────

function ClientFlow({ flows }: { flows: DashboardData['ssid_band'] }) {
  const [ref, W] = useWidth(420)
  const H = 240

  const layout = useMemo(() => {
    const total = flows.reduce((s, f) => s + f.clients, 0)
    if (!total) return null
    const ssidTotal = new Map<string, number>()
    const bandTotal = new Map<string, number>()
    for (const f of flows) {
      ssidTotal.set(f.ssid, (ssidTotal.get(f.ssid) ?? 0) + f.clients)
      bandTotal.set(f.band, (bandTotal.get(f.band) ?? 0) + f.clients)
    }
    // Real SSIDs largest first; the catch-alls always sink to the bottom.
    const ssids = [...ssidTotal.keys()].sort((a, b) =>
      Number(CATCH_ALL.has(a)) - Number(CATCH_ALL.has(b)) || ssidTotal.get(b)! - ssidTotal.get(a)!)
    const bands = [...bandTotal.keys()].sort((a, b) => bandRank(a) - bandRank(b))

    const GAP = 8
    // One scale for both columns, so a ribbon is as thick where it arrives at
    // its band as where it leaves its SSID.
    const scale = Math.min(
      (H - 8 - GAP * (ssids.length - 1)) / total,
      (H - 8 - GAP * (bands.length - 1)) / total,
    )
    const column = (keys: string[], totals: Map<string, number>) => {
      let y = (H - total * scale - GAP * (keys.length - 1)) / 2
      return new Map(keys.map(k => {
        const node = { y, h: totals.get(k)! * scale }
        y += node.h + GAP
        return [k, node] as const
      }))
    }
    const src = column(ssids, ssidTotal)
    const dst = column(bands, bandTotal)

    // Leave each SSID in band order and arrive at each band in SSID order —
    // the ordering that keeps ribbons from crossing more than they must.
    const ssidRank = (s: string) => ssids.indexOf(s)
    const pos = new Map<(typeof flows)[number], { y0: number; y1: number; h: number }>()
    const offset = new Map<string, number>()
    for (const f of [...flows].sort((a, b) => ssidRank(a.ssid) - ssidRank(b.ssid) || bandRank(a.band) - bandRank(b.band))) {
      const o = offset.get(`s:${f.ssid}`) ?? 0
      pos.set(f, { y0: src.get(f.ssid)!.y + o, y1: 0, h: f.clients * scale })
      offset.set(`s:${f.ssid}`, o + f.clients * scale)
    }
    for (const f of [...flows].sort((a, b) => bandRank(a.band) - bandRank(b.band) || ssidRank(a.ssid) - ssidRank(b.ssid))) {
      const o = offset.get(`d:${f.band}`) ?? 0
      pos.get(f)!.y1 = dst.get(f.band)!.y + o
      offset.set(`d:${f.band}`, o + f.clients * scale)
    }
    return { ssids, bands, ssidTotal, bandTotal, src, dst, links: flows.map(f => ({ f, ...pos.get(f)! })) }
  }, [flows])

  if (!layout) return <div ref={ref}><Empty msg="No client carries SSID and band detail" height={H} /></div>

  const xL = Math.round(Math.min(150, W * 0.34))
  const xR = Math.round(W - Math.min(96, W * 0.25))
  const colour = (ssid: string) =>
    CATCH_ALL.has(ssid) ? INSTRUMENT.inkDim : SERIES[layout.ssids.indexOf(ssid) % SERIES.length]
  const busiest = Math.max(...flows.map(f => f.clients))
  const chars = Math.max(5, Math.floor((xL - 14) / 6) - 3)

  return (
    <div ref={ref}>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible"
           role="img" aria-label="Connected clients by SSID and band">
        <FlowDefs ribbons={layout.links.map(l => ({ from: colour(l.f.ssid), to: bandColor(l.f.band) }))} />

        {/* ribbons: clients in the width, share in the travelling dash's speed */}
        {layout.links.map((l, i) => {
          const x0 = xL + 3, x1 = xR, mx = (x0 + x1) / 2
          const { y0, y1, h } = l
          return (
            <g key={i}>
              <path d={`M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} L${x1},${y1 + h} C${mx},${y1 + h} ${mx},${y0 + h} ${x0},${y0 + h} Z`}
                    fill={`url(#f-ribbon-${i})`}>
                <title>{`${l.f.ssid} → ${bandLabel(l.f.band)}: ${l.f.clients} client${l.f.clients === 1 ? '' : 's'}`}</title>
              </path>
              <path d={`M${x0},${y0 + h / 2} C${mx},${y0 + h / 2} ${mx},${y1 + h / 2} ${x1},${y1 + h / 2}`}
                    fill="none" stroke={colour(l.f.ssid)} strokeWidth={Math.min(Math.max(h * 0.34, 0.8), 3)}
                    strokeLinecap="round" opacity={0.9} className="f-ribbon-pulse" filter="url(#f-ribbon-glow)"
                    pointerEvents="none"
                    style={{
                      animationDelay: `${(i % 7) * 0.45}s`,
                      animationDuration: `${(9 - Math.sqrt(l.f.clients / busiest) * 7.4).toFixed(2)}s`,
                    }} />
            </g>
          )
        })}

        {layout.ssids.map(s => {
          const n = layout.src.get(s)!
          const name = s.length > chars ? `${s.slice(0, chars - 1)}…` : s
          return (
            <g key={s}>
              <NodeRail x={xL} y={n.y} h={Math.max(n.h, 2)} color={colour(s)} side="src" />
              <text x={xL - 8} y={n.y + n.h / 2} textAnchor="end" dominantBaseline="middle"
                    fontSize={9.5} fontFamily={MONO} fill={INSTRUMENT.ink} opacity={0.85}>
                {name}<tspan fill={INSTRUMENT.inkDim}> {layout.ssidTotal.get(s)}</tspan>
                <title>{s}</title>
              </text>
            </g>
          )
        })}

        {layout.bands.map(b => {
          const n = layout.dst.get(b)!
          return (
            <g key={b}>
              <NodeRail x={xR} y={n.y} h={Math.max(n.h, 2)} color={bandColor(b)} side="dst" />
              <text x={xR + 11} y={n.y + n.h / 2} dominantBaseline="middle"
                    fontSize={9.5} fontFamily={MONO} fill={INSTRUMENT.ink} opacity={0.85}>
                {bandLabel(b)}<tspan fill={INSTRUMENT.inkDim}> {layout.bandTotal.get(b)}</tspan>
              </text>
            </g>
          )
        })}
      </svg>
      <div className="mt-2 font-mono text-[9.5px] text-gray-500">width = clients · dash speed = share</div>
    </div>
  )
}

// ── Client mix: band + Wi-Fi generation ────────────────────────────────────────

function ClientMix({ clients, generations }: {
  clients: DashboardData['clients']
  generations: DashboardData['generations']
}) {
  if (!clients.total) return <Empty msg="No clients connected" height={220} />
  const segments = clients.by_band.map(b => ({ name: bandLabel(b.band), value: b.clients, color: bandColor(b.band) }))
  const counts = new Map(generations.map(g => [g.generation, g.clients]))
  const gens = GENERATIONS.filter(([g]) => counts.get(g))
  const genTotal = generations.reduce((s, g) => s + g.clients, 0)

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        <RadialRing segments={segments} size={148} label="clients" total={clients.total.toLocaleString()} />
        <div className="flex-1 min-w-0 space-y-1.5">
          {segments.map(s => (
            <div key={s.name} className="flex items-center gap-2">
              <span className="w-2 h-2 flex-none" style={{ background: s.color, boxShadow: `0 0 6px ${s.color}88` }} />
              <span className="font-mono text-[10.5px] text-gray-300 truncate">{s.name}</span>
              <span className="flex-1" />
              <span className="font-mono text-[10.5px] text-white">{s.value}</span>
              <span className="font-mono text-[10px] text-gray-500 w-9 text-right">
                {Math.round((s.value / clients.total) * 100)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="flex items-center gap-2.5 mb-2">
          <span className="f-lbl">Wi-Fi generation</span>
          <span className="f-rule" />
        </div>
        {genTotal === 0 ? (
          <div className="text-xs text-gray-500">No client reports its PHY</div>
        ) : (
          <>
            <div className="flex h-2 w-full overflow-hidden" style={{ background: 'rgba(216,180,110,.10)' }}>
              {gens.map(([g, c]) => (
                <span key={g} title={`${g}: ${counts.get(g)}`}
                      style={{ width: `${((counts.get(g) ?? 0) / genTotal) * 100}%`, background: c, boxShadow: `0 0 6px ${c}55` }} />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
              {gens.map(([g, c]) => (
                <span key={g} className="flex items-center gap-1.5 font-mono text-[10px] text-gray-400">
                  <span className="w-1.5 h-1.5 flex-none" style={{ background: c }} />
                  {g} <span className="text-white">{counts.get(g)}</span>
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Signal quality ─────────────────────────────────────────────────────────────

function SignalQuality({ signal, onOpen }: { signal: DashboardData['signal']; onOpen: (c: SignalClass) => void }) {
  const [ref, W] = useWidth(360)
  const H = 128, PAD_T = 14, PAD_B = 18
  const bins = signal.histogram
  const peak = Math.max(1, ...bins.map(b => b.clients))
  const lo = bins.length ? bins[0].dbm : -95
  const bw = W / Math.max(1, bins.length)
  const plotH = H - PAD_T - PAD_B
  const xAt = (dbm: number) => ((dbm - lo) / 5) * bw

  return (
    <div ref={ref}>
      {signal.measured === 0 ? (
        <Empty msg="No client reports signal strength" height={210} />
      ) : (
        <>
          <div className="flex items-end justify-between gap-3 mb-3 flex-wrap">
            <div>
              <span className="f-num text-[26px] text-white">
                {signal.median_dbm != null ? Math.round(signal.median_dbm) : '—'}
              </span>
              <span className="text-[10px] text-gray-500 ml-1.5">dBm median</span>
            </div>
            {/* Weakest first, so the ledger reads in the same direction as the bars. */}
            <div className="flex items-center gap-3">
              {(['poor', 'fair', 'good'] as const).map(c => (
                <button key={c} onClick={() => onOpen(c)} title={`Show ${c} signal clients`}
                        className="flex items-center gap-1.5 hover:opacity-80">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: SIGNAL_COLOR[c], boxShadow: `0 0 6px ${SIGNAL_COLOR[c]}` }} />
                  <span className="font-mono text-[11px] text-white">{signal[c]}</span>
                  <span className="f-lbl">{c}</span>
                </button>
              ))}
            </div>
          </div>

          <InstrumentFrame height={H} ticks={0}>
            <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Clients by signal strength">
              {bins.map(b => {
                const h = (b.clients / peak) * plotH
                const c = SIGNAL_COLOR[signalClass(b.dbm, signal.good_dbm, signal.fair_dbm)]
                return (
                  <g key={b.dbm} onClick={b.clients ? () => onOpen(signalClass(b.dbm, signal.good_dbm, signal.fair_dbm)) : undefined}
                     style={b.clients ? { cursor: 'pointer' } : undefined}>
                    <rect x={xAt(b.dbm) + 2} y={PAD_T + plotH - h} width={Math.max(1, bw - 4)} height={h}
                          fill={c} fillOpacity={0.72} style={b.clients ? glow(c, 4) : undefined}>
                      <title>{`${b.dbm} to ${b.dbm + 5} dBm: ${b.clients} client${b.clients === 1 ? '' : 's'}${b.clients ? ' — click to list' : ''}`}</title>
                    </rect>
                    {b.clients > 0 && (
                      <text x={xAt(b.dbm) + bw / 2} y={PAD_T + plotH - h - 3} textAnchor="middle"
                            fontSize={8.5} fontFamily={MONO} fill={INSTRUMENT.ink} opacity={0.8}>{b.clients}</text>
                    )}
                  </g>
                )
              })}
              {[signal.good_dbm, signal.fair_dbm].map(t => (
                <line key={t} x1={xAt(t)} x2={xAt(t)} y1={PAD_T - 6} y2={PAD_T + plotH}
                      stroke={INSTRUMENT.gold} strokeOpacity={0.45} strokeDasharray="2 3" />
              ))}
              <line x1={0} x2={W} y1={PAD_T + plotH} y2={PAD_T + plotH} stroke="rgba(216,180,110,.34)" />
              {bins.filter((_, i) => i % 2 === 1).map(b => (
                <text key={b.dbm} x={xAt(b.dbm)} y={H - 5} textAnchor="middle"
                      fontSize={8.5} fontFamily={MONO} fill={INSTRUMENT.inkDim}>{b.dbm}</text>
              ))}
            </svg>
          </InstrumentFrame>
          <div className="flex justify-between gap-2 mt-1.5 font-mono text-[9.5px] text-gray-500">
            <span>weaker</span>
            <span className="truncate">fair ≥ {signal.fair_dbm} · good ≥ {signal.good_dbm} dBm</span>
            <span>stronger</span>
          </div>
        </>
      )}
    </div>
  )
}

// ── Busiest access points ──────────────────────────────────────────────────────

function BusiestAccessPoints({ aps, hotPct, onOpen }: {
  aps: DashboardData['top_aps']
  hotPct: number
  onOpen: (id: number) => void
}) {
  if (!aps.length) return <Empty msg="No access point is reporting radios" />
  const most = Math.max(1, ...aps.map(a => a.clients))
  return (
    <div>
      {aps.map((a, i) => {
        const hot = a.peak_util_pct != null && a.peak_util_pct >= hotPct
        const share = (a.clients / most) * 100
        return (
          <button key={a.id} type="button" onClick={() => onOpen(a.id)} title={`Open ${a.name} in Metrics`}
                  className="w-full flex items-center gap-2.5 py-1.5 border-b border-gray-900 text-left hover:bg-blue-500/[0.035] transition-colors">
            <span className="font-mono text-[9px] text-gray-500 w-4 flex-none">{String(i + 1).padStart(2, '0')}</span>
            <span className={`f-dot ${dotFor(a.status)} w-1.5 h-1.5 flex-none`} />
            <span className="font-mono text-[10.5px] text-gray-300 truncate w-[36%] min-w-0">{a.name}</span>
            <span className="flex-1 h-px relative" style={{ background: 'rgba(216,180,110,.22)' }}>
              <span className="absolute left-0 -top-px h-[3px]"
                    style={{
                      width: `${share}%`,
                      background: `linear-gradient(90deg, rgba(138,216,234,.18), ${INSTRUMENT.ice})`,
                      boxShadow: `0 0 6px ${INSTRUMENT.ice}55`,
                    }} />
              <span className="absolute -top-[2px] w-px h-[5px]"
                    style={{ left: `${share}%`, background: INSTRUMENT.goldHi, boxShadow: `0 0 5px ${INSTRUMENT.goldHi}` }} />
            </span>
            <span className="font-mono text-[10px] text-cyan-400 w-7 text-right flex-none">{a.clients}</span>
            <span className={`font-mono text-[9.5px] w-9 text-right flex-none ${hot ? 'text-red-400' : 'text-gray-500'}`}>
              {a.peak_util_pct != null ? `${Math.round(a.peak_util_pct)}%` : '—'}
            </span>
          </button>
        )
      })}
      <div className="flex items-center justify-between gap-3 mt-2">
        <span className="font-mono text-[9.5px] text-gray-500">clients · busiest radio's airtime</span>
        <Link to="/access-points" className="text-xs text-sky-400 hover:text-sky-300 whitespace-nowrap">All access points →</Link>
      </div>
    </div>
  )
}

// ── Collection ─────────────────────────────────────────────────────────────────

function Collection({ collectors, events, windowLabel }: {
  collectors: DashboardData['collectors']
  events: DashboardData['events']
  windowLabel: string
}) {
  const shown = ['associate', 'roam', ...Object.keys(events).filter(k => k !== 'associate' && k !== 'roam')]
  return (
    <div className="space-y-5">
      {collectors.length === 0 ? (
        <div className="text-xs text-gray-500">No controllers configured — an admin adds one under Settings → Controllers.</div>
      ) : (
        <div>
          {collectors.map(c => (
            <div key={c.id} className="flex items-center gap-2.5 py-1.5 border-b border-gray-900">
              <span className={`f-dot ${c.enabled ? dotFor(c.status) : 'f-dot-off'} w-1.5 h-1.5 flex-none`} />
              <span className="font-mono text-[10.5px] text-gray-300 truncate flex-1 min-w-0">{c.name}</span>
              <span className="f-chip">{COLLECTOR_LABEL[c.collector_type] ?? c.collector_type}</span>
              <span className={`font-mono text-[9.5px] w-16 text-right flex-none ${
                !c.enabled ? 'text-gray-600' : c.status === 'error' ? 'text-red-400' : 'text-gray-500'
              }`}>
                {c.enabled ? (c.status === 'error' ? 'failing' : fmtAgo(c.last_poll_at)) : 'disabled'}
              </span>
            </div>
          ))}
        </div>
      )}

      <div>
        <div className="flex items-center gap-2.5 mb-2">
          <span className="f-lbl">Client activity · {windowLabel}</span>
          <span className="f-rule" />
        </div>
        <div className="grid grid-cols-2 f-grid-keep gap-px border"
             style={{ background: 'rgba(216,180,110,.08)', borderColor: 'rgba(216,180,110,.08)' }}>
          {shown.map(key => (
            <div key={key} className="bg-gray-950 px-3 py-2.5 min-w-0">
              <div className="f-num text-[20px] text-white">{(events[key] ?? 0).toLocaleString()}</div>
              <div className="f-lbl mt-1.5 truncate">{EVENT_LABEL[key] ?? key}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Active alerts ──────────────────────────────────────────────────────────────

function ActiveAlerts({ alerts }: { alerts: DashboardData['alerts'] }) {
  if (!alerts.active) {
    return (
      <div className="h-full min-h-[160px] grid place-items-center">
        <div className="flex items-center gap-2">
          <span className="f-dot f-dot-up w-2 h-2" />
          <span className="f-lbl">All clear — no active alerts</span>
        </div>
      </div>
    )
  }
  return (
    <div>
      <div className="grid grid-cols-3 f-grid-keep gap-px border mb-3"
           style={{ background: 'rgba(216,180,110,.08)', borderColor: 'rgba(216,180,110,.08)' }}>
        {([['critical', 'f-num-alarm'], ['warning', 'text-yellow-400'], ['info', 'text-white']] as const).map(([sev, cls]) => (
          <div key={sev} className="bg-gray-950 px-3 py-2.5 min-w-0">
            <div className={`f-num text-[20px] ${alerts[sev] ? cls : 'text-gray-600'}`}>{alerts[sev]}</div>
            <div className="f-lbl mt-1.5">{sev}</div>
          </div>
        ))}
      </div>
      {alerts.recent.map(a => (
        <div key={a.id} className="flex items-start gap-2.5 py-1.5 border-b border-gray-900">
          <span className={`f-dot ${a.severity === 'critical' ? 'f-dot-down' : a.severity === 'warning' ? 'f-dot-warn' : 'f-dot-off'} w-1.5 h-1.5 flex-none mt-1.5`} />
          <div className="min-w-0 flex-1">
            <div className="text-[11px] text-gray-300 leading-snug line-clamp-2">{a.message}</div>
            <div className="font-mono text-[9px] text-gray-500 mt-0.5">
              {a.ap_name ? `${a.ap_name} · ` : ''}{fmtAgo(a.created_at)}{a.acked ? ' · acknowledged' : ''}
            </div>
          </div>
        </div>
      ))}
      <div className="flex items-center justify-between gap-3 mt-2">
        <span className="font-mono text-[9.5px] text-gray-500">{alerts.unacked} unacknowledged</span>
        <Link to="/alerts" className="text-xs text-sky-400 hover:text-sky-300 whitespace-nowrap">All alerts →</Link>
      </div>
    </div>
  )
}

// ── The estate ─────────────────────────────────────────────────────────────────

function Estate({ data }: { data: DashboardData }) {
  const navigate = useNavigate()
  // Named from the reading, not the picker: the two differ while a newly
  // picked window is still loading, or has failed to.
  const windowLabel = WINDOWS.find(w => w.hours === data.window.hours)?.label ?? `${data.window.hours}h`
  const rows = useMemo(() => fillTrend(data), [data])
  const spanMs = (data.window.until - data.window.since) * 1000

  const ap = data.access_points
  const availability = ap.total ? (ap.online / ap.total) * 100 : 0
  const air = data.airtime
  const sig = data.signal
  const goodShare = sig.measured ? Math.round((sig.good / sig.measured) * 100) : 0
  const alerts = data.alerts
  // Share-based service level: 75%+ green, 50-75% amber, under 50% red.
  const shareTone = (share: number) => share >= 0.75 ? 'good' : share >= 0.5 ? 'fair' : 'alarm'
  const apTone = ap.total ? shareTone(ap.online / ap.total) : 'ink'
  const clientTone = sig.measured ? shareTone(sig.good / sig.measured) : 'ice'
  const openMetrics = (id: number) => navigate(`/metrics?ap=${id}`)

  return (
    <>
      <div className="grid grid-cols-3 gap-px border"
           style={{ background: 'rgba(216,180,110,.08)', borderColor: 'rgba(216,180,110,.08)' }}>
        <Readout
          label="Access Points"
          value={ap.total.toLocaleString()}
          tone={apTone}
          sub={<>{ap.online} online · {ap.offline} offline{ap.rogue > 0 && <span className="text-red-400"> · {ap.rogue} rogue</span>}</>}
          onClick={() => navigate('/access-points')}
        />
        <Readout
          label="Clients"
          value={data.clients.total.toLocaleString()}
          tone={clientTone}
          sub={data.clients.by_band.map(b => `${bandLabel(b.band)} ${b.clients}`).join(' · ') || 'none connected'}
          onClick={() => navigate('/clients')}
        />
        <Readout
          label="Active Alerts"
          value={alerts.active}
          tone={alerts.active ? 'alarm' : 'good'}
          sub={alerts.active ? `${alerts.unacked} unacknowledged` : 'all clear'}
          onClick={() => navigate('/alerts')}
        />
        <Readout
          label="Availability"
          value={Math.round(availability)}
          unit="%"
          tone="gold"
          gauge={availability}
          sub={`${ap.online} of ${ap.total} online`}
        />
        <Readout
          label="Airtime · mean"
          value={air.mean_pct != null ? Math.round(air.mean_pct) : '—'}
          unit={air.mean_pct != null ? '%' : undefined}
          tone={air.hot_radios ? 'alarm' : 'ink'}
          gauge={air.mean_pct ?? undefined}
          sub={air.peak_pct != null
            ? `peak ${Math.round(air.peak_pct)}% · ${air.peak_ap}`
            : 'no radio reports utilization'}
        />
        <Readout
          label="Signal · median"
          value={sig.median_dbm != null ? Math.round(sig.median_dbm) : '—'}
          unit={sig.median_dbm != null ? 'dBm' : undefined}
          tone={sig.median_dbm != null && sig.median_dbm < sig.fair_dbm ? 'alarm' : 'ink'}
          sub={sig.measured ? `${goodShare}% good · ${sig.poor} poor` : 'no client reports RSSI'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Connected Clients" chip={<WindowChip label={windowLabel} />}>
          <ClientsTrend rows={rows} spanMs={spanMs} />
        </Card>
        <Card title="Airtime by Band" chip={<WindowChip label={windowLabel} />}>
          <AirtimeTrend rows={rows} spanMs={spanMs} hotPct={air.hot_pct} />
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4">
        <Card title="RF Spectrum" chip={<NowChip />}>
          <Spectrum bands={data.spectrum.bands} radios={data.spectrum.radios} hotPct={air.hot_pct}
                    onSelect={r => openMetrics(r.ap_id)} />
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 font-mono text-[9.5px] text-gray-500">
            <span>height = channel utilization</span>
            <span>dashed = width not reported, or position approximate</span>
            {data.spectrum.unplaced > 0 && (
              <span className="text-yellow-400">
                {data.spectrum.unplaced} radio{data.spectrum.unplaced === 1 ? '' : 's'} without a usable channel
              </span>
            )}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Signal Scope" chip={<NowChip />}>
          <div className="w-full max-h-[460px]" style={{ aspectRatio: '19 / 15' }}>
            <SignalScope
              sectors={data.scope}
              goodDbm={sig.good_dbm}
              fairDbm={sig.fair_dbm}
              onSelectSector={s => navigate(`/clients?access_point_id=${s.ap_id}&access_point_name=${encodeURIComponent(s.ap_name)}`)}
            />
          </div>
        </Card>
        <Card title="Client Flow" chip={<NowChip />}>
          <ClientFlow flows={data.ssid_band} />
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Client Mix" chip={<NowChip />}>
          <ClientMix clients={data.clients} generations={data.generations} />
        </Card>
        <Card title="Signal Quality" chip={<NowChip />}>
          <SignalQuality signal={sig} onOpen={c => navigate(`/clients?signal=${c}`)} />
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Busiest Access Points" chip={<NowChip />}>
          <BusiestAccessPoints aps={data.top_aps} hotPct={air.hot_pct} onOpen={openMetrics} />
        </Card>
        <Card title="Collection">
          <Collection collectors={data.collectors} events={data.events} windowLabel={windowLabel} />
        </Card>
        <Card title="Active Alerts" chip={<NowChip />}>
          <ActiveAlerts alerts={alerts} />
        </Card>
      </div>
    </>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const hours = WINDOWS.find(w => String(w.hours) === searchParams.get('hours'))?.hours ?? DEFAULT_HOURS

  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  // A refresh still in flight when the window changes must not land on top of
  // the newer window's reading.
  const requestSeq = useRef(0)

  const load = useCallback(() => {
    const seq = ++requestSeq.current
    api.getDashboard(hours)
      .then(d => { if (seq === requestSeq.current) { setData(d); setError('') } })
      .catch(e => { if (seq === requestSeq.current) setError(e.message ?? 'Failed to load') })
  }, [hours])

  useEffect(() => {
    load()
    // A background tab has nobody to show a fresh reading to.
    const id = setInterval(() => { if (!document.hidden) load() }, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  const setHours = (h: number) => setSearchParams(prev => {
    const next = new URLSearchParams(prev)
    next.set('hours', String(h))
    return next
  }, { replace: true })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-white">Dashboard</h1>
          <HelpButton title="Dashboard — How It Works">
            <p>Every panel reads the same poll, and counts include only what each access point's <span className="text-gray-300 font-medium">latest poll</span> reported. A client that has left, or a band a controller has stopped reporting, drops off here straight away — the Clients page still keeps its history.</p>
            <p>The <span className="text-gray-300 font-medium">1h/6h/24h/7d</span> picker moves the two trends and the client-activity counts. Panels marked <span className="text-gray-300 font-medium">now</span> always show the latest poll. The page refreshes every 30 seconds while it is on screen.</p>
            <p><span className="text-gray-300 font-medium">RF Spectrum</span> draws each radio where it sits on air, one lane per band, with its height set by channel utilization. Shapes that overlap are radios contending for the same airtime. A dashed outline means the controller did not report the channel width (20 MHz is assumed) or the channel plan leaves the position approximate; a bracket on the floor is a radio with no utilization reading. The red dashed line is the threshold your <span className="text-gray-300 font-medium">High channel utilization</span> alert rule fires at — 80% when there is no such rule. Click a radio to open its Metrics.</p>
            <p><span className="text-gray-300 font-medium">Signal Scope</span> puts each connected client in its access point's sector, closer to the centre the stronger its signal. Where a client sits around its sector means nothing — it only keeps clients from stacking. The 16 busiest access points get a sector each; any others share one. Click a sector to see its clients.</p>
            <p><span className="text-gray-300 font-medium">Client Flow</span>, <span className="text-gray-300 font-medium">Client Mix</span>, <span className="text-gray-300 font-medium">Signal Quality</span> and the scope rely on per-client detail that some collection modes do not report (UniFi API-key auth, for one). Those clients then show as not reported, never as zero.</p>
          </HelpButton>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.2em] text-gray-500 whitespace-nowrap">
            <span className={`w-1.5 h-1.5 rounded-full ${error ? 'bg-red-400' : 'bg-green-400 f-breathe'}`} />
            {error ? 'stale' : 'live · 30s'}
          </span>
          <div className="flex bg-gray-800 rounded-lg p-0.5 gap-0.5">
            {WINDOWS.map(w => (
              <button key={w.hours} onClick={() => setHours(w.hours)}
                      className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                        hours === w.hours ? 'bg-sky-600 text-white' : 'text-gray-400 hover:text-white'
                      }`}>
                {w.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && data && (
        <div className="border border-red-500/40 bg-red-500/[0.06] px-3 py-2 text-xs text-red-300">
          Refresh failed ({error}) — showing the reading from {new Date(data.window.until * 1000).toLocaleTimeString()}.
        </div>
      )}

      {!data ? (
        <div className="f-panel px-5 py-16 text-center">
          {error
            ? <span className="text-sm text-red-300">Dashboard unavailable — {error}</span>
            : <span className="f-lbl">Acquiring…</span>}
        </div>
      ) : data.access_points.total === 0 ? (
        <div className="f-panel px-5 py-12 text-center space-y-2">
          <div className="f-lbl f-lbl-gold">No access points reporting</div>
          <p className="text-sm text-gray-400">
            An admin adds a controller under Settings → Controllers; access points, radios and clients fill this page from its first poll.
          </p>
        </div>
      ) : (
        <Estate data={data} />
      )}
    </div>
  )
}

/**
 * Spectrum — every radio on air, drawn where it actually sits.
 *
 * One lane per band: frequency across, channel utilisation up. Each radio is
 * the block of spectrum it occupies, resolved server-side from its channel and
 * width (app/wifi/rf.py), so two radios that share or straddle a channel
 * visibly overlap — which is exactly what a channel plan is trying to avoid.
 *
 * Where the collector left something out, the shape says so instead of
 * pretending: a dashed outline is a width that was assumed or a position the
 * channel plan cannot pin down, and a radio with no utilisation reading is a
 * bracket on the floor of the lane, not a hump of made-up height.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { DashboardBandAxis, DashboardRadio } from '../api/client'
import { INSTRUMENT, InstrumentFrame, glow } from './instrument'
import { ALARM, bandColor, bandLabel } from '../utils/rf'

const PAD_L = 32, PAD_R = 10
const TOP = 18        // headroom for AP labels over a full-height radio
const PLOT_H = 96
const AXIS_H = 22
const LANE_H = TOP + PLOT_H + AXIS_H
const LABEL_LIMIT = 16 // past this many radios in a lane, names move to the hover readout
const MONO = 'ui-monospace, SF Mono, Menlo, monospace'

/** A radio's outline: a flat top with rounded shoulders, the shape Wi-Fi analysers draw. */
function hat(x0: number, x1: number, top: number, base: number) {
  const s = Math.min((x1 - x0) * 0.22, 14)
  return `M${x0},${base} C${x0 + s * 0.55},${base} ${x0 + s * 0.35},${top} ${x0 + s},${top} ` +
         `L${x1 - s},${top} C${x1 - s * 0.35},${top} ${x1 - s * 0.55},${base} ${x1},${base} Z`
}

type Track = (e: React.MouseEvent, radio: DashboardRadio) => void

function Lane({
  axis, members, width, hotPct, hovered, onTrack, onLeave, onSelect,
}: {
  axis: DashboardBandAxis
  members: DashboardRadio[]
  width: number
  hotPct: number
  hovered: number | null
  onTrack: Track
  onLeave: () => void
  onSelect?: (radio: DashboardRadio) => void
}) {
  const plotW = Math.max(40, width - PAD_L - PAD_R)
  const x = (mhz: number) => PAD_L + ((mhz - axis.lo_mhz) / (axis.hi_mhz - axis.lo_mhz)) * plotW
  const y = (pct: number) => TOP + PLOT_H * (1 - Math.max(0, Math.min(100, pct)) / 100)
  const base = TOP + PLOT_H
  const color = bandColor(axis.band)
  const gid = `spec-${axis.band.replace('.', '_')}`
  const inUse = new Set(members.map(r => r.channel))

  // Tallest first, so a small radio sitting inside a big one is drawn on top
  // and stays hoverable.
  const ordered = useMemo(
    () => [...members].sort((a, b) => (b.utilization_pct ?? -1) - (a.utilization_pct ?? -1)),
    [members],
  )

  // Channel labels, placed in priority order: channels in use, then the band's
  // landmark channels, then the rest only where there is room to spare. Room
  // is measured from each label's own width — a three-digit channel needs more.
  const extents: Array<[number, number]> = []
  const labelled = new Set<number>()
  const passes: Array<[(t: DashboardBandAxis['ticks'][number]) => boolean, number]> = [
    [t => inUse.has(t.channel), 3],
    [t => t.major && !inUse.has(t.channel), 3],
    [t => !t.major && !inUse.has(t.channel), 10],
  ]
  for (const [wanted, pad] of passes) {
    for (const t of axis.ticks.filter(wanted)) {
      const tx = x(t.mhz)
      const half = (String(t.channel).length * 5.2) / 2
      if (extents.every(([a, b]) => tx + half + pad <= a || tx - half - pad >= b)) {
        extents.push([tx - half, tx + half])
        labelled.add(t.channel)
      }
    }
  }
  const ticks = axis.ticks.map(t => ({ ...t, tx: x(t.mhz), label: labelled.has(t.channel) }))

  // AP names over their radios, skipping any that would collide.
  const names: Array<{ id: number; x: number; y: number; text: string }> = []
  if (members.length <= LABEL_LIMIT) {
    const boxes: Array<[number, number, number]> = []
    for (const r of ordered) {
      const text = r.ap_name.length > 14 ? `${r.ap_name.slice(0, 13)}…` : r.ap_name
      const w = text.length * 5.6
      const cx = (x(r.lo_mhz) + x(r.hi_mhz)) / 2
      const ly = Math.max(10, (r.utilization_pct != null ? y(r.utilization_pct) : base - 8) - 5)
      const x0 = Math.max(PAD_L, Math.min(width - PAD_R - w, cx - w / 2))
      if (boxes.some(([a, b, by]) => x0 < b + 4 && a < x0 + w + 4 && Math.abs(by - ly) < 11)) continue
      boxes.push([x0, x0 + w, ly])
      names.push({ id: r.id, x: x0 + w / 2, y: ly, text })
    }
  }

  return (
    <InstrumentFrame height={LANE_H} ticks={0} sweep>
      <svg width="100%" height={LANE_H} viewBox={`0 0 ${width} ${LANE_H}`}
           role="img" aria-label={`${bandLabel(axis.band)} spectrum`}>
        <defs>
          {([['', color], ['-hot', ALARM]] as const).map(([suffix, c]) => (
            <linearGradient key={suffix} id={`${gid}${suffix}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c} stopOpacity={0.36} />
              <stop offset="100%" stopColor={c} stopOpacity={0.04} />
            </linearGradient>
          ))}
        </defs>

        {[25, 50, 75].map(p => (
          <line key={p} x1={PAD_L} x2={width - PAD_R} y1={y(p)} y2={y(p)}
                stroke="rgba(216,180,110,.22)" strokeDasharray="1 5" />
        ))}
        <line x1={PAD_L} x2={width - PAD_R} y1={base} y2={base} stroke="rgba(216,180,110,.34)" />
        {[0, 50, 100].map(p => (
          <text key={p} x={PAD_L - 6} y={y(p) + 3} textAnchor="end"
                fontSize={8.5} fontFamily={MONO} fill={INSTRUMENT.inkDim}>{p}%</text>
        ))}

        {hotPct <= 100 && (
          <g>
            <line x1={PAD_L} x2={width - PAD_R} y1={y(hotPct)} y2={y(hotPct)}
                  stroke={ALARM} strokeOpacity={0.55} strokeDasharray="2 4" />
            <text x={width - PAD_R} y={y(hotPct) - 3} textAnchor="end"
                  fontSize={8} fontFamily={MONO} fill={ALARM} opacity={0.85}>alert {hotPct}%</text>
          </g>
        )}

        {ticks.map(t => (
          <g key={t.channel}>
            <line x1={t.tx} x2={t.tx} y1={base} y2={base + (t.major || inUse.has(t.channel) ? 5 : 3)}
                  stroke={inUse.has(t.channel) ? color : INSTRUMENT.gold}
                  strokeOpacity={inUse.has(t.channel) ? 0.95 : t.major ? 0.55 : 0.28} />
            {t.label && (
              <text x={t.tx} y={base + 14} textAnchor="middle" fontSize={8.5} fontFamily={MONO}
                    fill={inUse.has(t.channel) ? INSTRUMENT.ink : INSTRUMENT.inkDim}>{t.channel}</text>
            )}
          </g>
        ))}

        {ordered.map(r => {
          let x0 = x(r.lo_mhz), x1 = x(r.hi_mhz)
          if (x1 - x0 < 6) { const c = (x0 + x1) / 2; x0 = c - 3; x1 = c + 3 }
          const util = r.utilization_pct
          const hot = util != null && util >= hotPct
          const stroke = hot ? ALARM : color
          const lit = hovered === r.id
          const events = {
            onMouseEnter: (e: React.MouseEvent) => onTrack(e, r),
            onMouseMove: (e: React.MouseEvent) => onTrack(e, r),
            onMouseLeave: onLeave,
            onClick: () => onSelect?.(r),
            style: { cursor: onSelect ? 'pointer' : 'default' },
          }
          if (util == null) {
            return (
              <g key={r.id} {...events}>
                <path d={`M${x0},${base - 7} L${x0},${base} L${x1},${base} L${x1},${base - 7}`}
                      fill="none" stroke={stroke} strokeWidth={lit ? 2 : 1.3} strokeDasharray="2 2" />
                <rect x={x0} y={base - 12} width={x1 - x0} height={12} fill="transparent" />
              </g>
            )
          }
          const top = y(util)
          return (
            <g key={r.id} {...events}>
              <path d={hat(x0, x1, top, base)} fill={`url(#${gid}${hot ? '-hot' : ''})`}
                    stroke={stroke} strokeWidth={lit ? 2.2 : 1.3} strokeLinejoin="round"
                    strokeDasharray={!r.width_reported || r.approximate ? '4 3' : undefined}
                    style={glow(stroke, lit ? 7 : 4)} />
              {/* a low radio is a sliver; give the pointer something to land on */}
              <rect x={x0} y={Math.min(top, base - 10)} width={x1 - x0}
                    height={base - Math.min(top, base - 10)} fill="transparent" />
            </g>
          )
        })}

        {names.map(n => (
          <text key={n.id} x={n.x} y={n.y} textAnchor="middle" fontSize={9} fontFamily={MONO}
                fill={INSTRUMENT.ink} opacity={hovered === n.id ? 1 : 0.72} pointerEvents="none">{n.text}</text>
        ))}
      </svg>
    </InstrumentFrame>
  )
}

export default function Spectrum({
  bands, radios, hotPct, onSelect,
}: {
  bands: DashboardBandAxis[]
  radios: DashboardRadio[]
  hotPct: number
  onSelect?: (radio: DashboardRadio) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  const [hover, setHover] = useState<{ radio: DashboardRadio; x: number; y: number } | null>(null)

  useEffect(() => {
    if (!wrapRef.current) return
    const obs = new ResizeObserver(entries => {
      const w = entries[0].contentRect.width
      if (w > 50) setWidth(w)
    })
    obs.observe(wrapRef.current)
    return () => obs.disconnect()
  }, [])

  const lanes = useMemo(() => bands.map(axis => {
    const members = radios.filter(r => r.band === axis.band)
    const overlapping = members.filter(a =>
      members.some(b => b !== a && a.lo_mhz < b.hi_mhz && b.lo_mhz < a.hi_mhz)).length
    return { axis, members, overlapping }
  }), [bands, radios])

  const track: Track = (e, radio) => {
    const box = wrapRef.current?.getBoundingClientRect()
    if (box) setHover({ radio, x: e.clientX - box.left, y: e.clientY - box.top })
  }

  const r = hover?.radio
  const boxW = wrapRef.current?.clientWidth ?? width
  const boxH = wrapRef.current?.clientHeight ?? 0

  return (
    <div ref={wrapRef} className="relative space-y-3" onMouseLeave={() => setHover(null)}>
      {lanes.length === 0 && (
        <div className="h-40 grid place-items-center text-xs text-gray-500">No radio is reporting a channel</div>
      )}
      {lanes.map(({ axis, members, overlapping }) => (
        <div key={axis.band}>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="w-2 h-2 flex-none"
                  style={{ background: bandColor(axis.band), boxShadow: `0 0 6px ${bandColor(axis.band)}88` }} />
            <span className="f-lbl f-lbl-gold">{bandLabel(axis.band)}</span>
            <span className="font-mono text-[10px] text-gray-500 truncate">
              {members.length} radio{members.length === 1 ? '' : 's'}
              {overlapping > 0 && <span className="text-yellow-400"> · {overlapping} overlapping</span>}
            </span>
          </div>
          <Lane axis={axis} members={members} width={width} hotPct={hotPct}
                hovered={r?.id ?? null} onTrack={track} onLeave={() => setHover(null)} onSelect={onSelect} />
        </div>
      ))}

      {r && hover && (
        <div className="absolute z-20 pointer-events-none bg-gray-900/95 border border-gray-700 px-2.5 py-2
                        text-[10.5px] font-mono leading-[1.6] whitespace-nowrap"
             style={{
               left: Math.max(0, Math.min(hover.x + 14, boxW - 210)),
               top: hover.y + 150 > boxH ? Math.max(0, hover.y - 130) : hover.y + 14,
             }}>
          <div className="text-white">{r.ap_name}</div>
          <div><span className="inline-block w-14 text-gray-500">Radio</span>{bandLabel(r.band)} · ch {r.channel}</div>
          <div><span className="inline-block w-14 text-gray-500">Width</span>
            {r.width_mhz} MHz{r.width_reported ? '' : ' (not reported — assumed)'}</div>
          <div><span className="inline-block w-14 text-gray-500">Span</span>
            {r.lo_mhz}–{r.hi_mhz} MHz{r.approximate ? ' (approximate)' : ''}</div>
          <div><span className="inline-block w-14 text-gray-500">Airtime</span>
            {r.utilization_pct != null ? `${Math.round(r.utilization_pct)}% utilised` : 'not reported'}</div>
          <div><span className="inline-block w-14 text-gray-500">Clients</span>{r.clients}</div>
        </div>
      )}
    </div>
  )
}

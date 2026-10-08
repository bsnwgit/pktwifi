/**
 * Signal scope — every connected client, by the access point it is on and how
 * well that access point hears it.
 *
 * It borrows pktFlow's radar face, but the axes mean different things and the
 * key under the face says so: each sector is one access point, and range is
 * signal strength, strongest at the core. Where a client sits around its sector
 * means nothing — clients are only spread out so they do not stack.
 *
 * Text and blip sizes are divided by the face's on-screen scale, so the scope
 * reads the same on a phone as on a wall display instead of shrinking with it.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { DashboardScopePoint, DashboardScopeSector } from '../api/client'
import { INSTRUMENT } from './instrument'
import { SIGNAL_COLOR, SignalClass, bandLabel, signalClass } from '../utils/rf'

const VW = 760, VH = 600, CX = 380, CY = 300
const R_CORE = 30, R_MAX = 228
const STRONG = -30, WEAK = -95
const SWEEP_S = 8
const GLOW_LIMIT = 240 // past this many blips, drop the per-blip glow to keep the sweep smooth
const MONO = 'ui-monospace, SF Mono, Menlo, monospace'

const rad = (d: number) => (d * Math.PI) / 180
const polar = (brg: number, r: number): [number, number] =>
  [CX + r * Math.sin(rad(brg)), CY - r * Math.cos(rad(brg))]

/** Range from RSSI: STRONG at the core, WEAK at the rim, linear in dB between. */
const rangeR = (rssi: number) =>
  R_CORE + ((R_MAX - R_CORE) * (STRONG - Math.max(WEAK, Math.min(STRONG, rssi)))) / (STRONG - WEAK)

/** The band between two radii, for shading the fair and poor zones. */
function annulus(r0: number, r1: number) {
  const circle = (r: number) =>
    `M${CX - r},${CY} A${r},${r} 0 1 0 ${CX + r},${CY} A${r},${r} 0 1 0 ${CX - r},${CY} Z`
  return `${circle(r1)} ${circle(r0)}`
}

/** FNV-1a, folded into [0, 1). */
function unitHash(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0) / 0x100000000
}

function arc(r: number, a0: number, a1: number) {
  const [x0, y0] = polar(a0, r)
  const [x1, y1] = polar(a1, r)
  return `M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)},${y1.toFixed(1)}`
}

interface Blip {
  key: string
  point: DashboardScopePoint
  sector: DashboardScopeSector
  brg: number
  x: number
  y: number
  cls: SignalClass
}

export default function SignalScope({
  sectors, goodDbm, fairDbm, onSelectSector,
}: {
  sectors: DashboardScopeSector[]
  goodDbm: number
  fairDbm: number
  onSelectSector?: (sector: DashboardScopeSector) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [k, setK] = useState(0.55) // on-screen pixels per viewBox unit
  const [hover, setHover] = useState<{ blip: Blip; x: number; y: number } | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const obs = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      if (width > 50 && height > 50) setK(Math.min(width / VW, height / VH))
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const n = sectors.length
  const span = 360 / Math.max(1, n)
  const gap = n > 1 ? Math.min(3, span * 0.12) : 0

  const blips = useMemo<Blip[]>(() => sectors.flatMap((sector, i) => {
    const start = i * span + gap / 2
    const width = span - gap
    return sector.points.map((point, j) => {
      // Bearing comes from a hash of the client's name, so a client holds its
      // place from one refresh to the next — and, unlike spacing clients out
      // in any sorted order, it cannot line up with signal strength and draw
      // a spiral that means nothing.
      const brg = start + width * (0.06 + 0.88 * unitHash(point.label))
      const [x, y] = polar(brg, rangeR(point.rssi_dbm))
      return { key: `${i}:${j}`, point, sector, brg, x, y, cls: signalClass(point.rssi_dbm, goodDbm, fairDbm) }
    })
  }), [sectors, span, gap, goodDbm, fairDbm])

  const px = (v: number) => v / k
  const clickable = (s: DashboardScopeSector) => s.ap_id != null && !!onSelectSector
  const select = (s: DashboardScopeSector) => { if (s.ap_id != null) onSelectSector?.(s) }
  const total = sectors.reduce((sum, s) => sum + s.clients, 0)
  const rings = [...new Set([-50, goodDbm, fairDbm, -85])].sort((a, b) => b - a)

  function track(e: React.MouseEvent, blip: Blip) {
    const box = wrapRef.current?.getBoundingClientRect()
    if (box) setHover({ blip, x: e.clientX - box.left, y: e.clientY - box.top })
  }

  // The sweep's afterglow: thin wedges fading out behind the leading edge.
  const trail = Array.from({ length: 24 }, (_, i) => {
    const a0 = -i * 3.4, a1 = a0 - 3.5
    const [ax, ay] = polar(a0, R_MAX), [bx, by] = polar(a1, R_MAX)
    return (
      <path key={i} d={`M${CX} ${CY} L${ax.toFixed(1)} ${ay.toFixed(1)} A${R_MAX} ${R_MAX} 0 0 0 ${bx.toFixed(1)} ${by.toFixed(1)} Z`}
            fill={INSTRUMENT.gold} opacity={0.14 * (1 - i / 24) ** 1.7} />
    )
  })

  const hovered = hover?.blip
  const boxW = wrapRef.current?.clientWidth ?? 0
  const boxH = wrapRef.current?.clientHeight ?? 0

  return (
    <div className="w-full h-full flex flex-col">
      <div ref={wrapRef} className="relative flex-1 min-h-0" onMouseLeave={() => setHover(null)}>
        {n === 0 ? (
          <div className="absolute inset-0 grid place-items-center text-xs text-gray-500">No client reports signal strength</div>
        ) : (
          <>
            <style>{`
              @keyframes pw-scope-spin { to { transform: rotate(360deg); } }
              @keyframes pw-scope-phos { 0% { opacity: 1 } 8% { opacity: .95 } 60% { opacity: .5 } 100% { opacity: .42 } }
              .pw-scope-sweep { transform-origin: ${CX}px ${CY}px; animation: pw-scope-spin ${SWEEP_S}s linear infinite; }
              .pw-scope-blip  { animation: pw-scope-phos ${SWEEP_S}s linear infinite; }
              @media (prefers-reduced-motion: reduce) {
                .pw-scope-sweep { animation: none; opacity: .3; }
                .pw-scope-blip  { animation: none; opacity: .92; }
              }
            `}</style>

            <svg width="100%" height="100%" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet"
                 role="img" aria-label="Signal scope — connected clients by access point and signal strength">
              {/* zones: fair, then poor out to the rim */}
              <path d={annulus(rangeR(goodDbm), rangeR(fairDbm))} fill={SIGNAL_COLOR.fair} fillOpacity={0.04} fillRule="evenodd" />
              <path d={annulus(rangeR(fairDbm), R_MAX)} fill={SIGNAL_COLOR.poor} fillOpacity={0.05} fillRule="evenodd" />
              <circle cx={CX} cy={CY} r={R_MAX} fill="none" stroke="rgba(216,180,110,.3)" strokeWidth={px(1)} />

              {rings.map(dbm => (
                <g key={dbm}>
                  <circle cx={CX} cy={CY} r={rangeR(dbm)} fill="none" strokeWidth={px(1)}
                          stroke={dbm === goodDbm ? SIGNAL_COLOR.good : dbm === fairDbm ? SIGNAL_COLOR.fair : INSTRUMENT.gold}
                          strokeOpacity={dbm === goodDbm || dbm === fairDbm ? 0.32 : 0.16} strokeDasharray={`${px(1)} ${px(5)}`} />
                  <text x={CX + px(4)} y={CY - rangeR(dbm) + px(11)} fontFamily={MONO} fontSize={px(8.5)}
                        letterSpacing={px(0.8)} fill={INSTRUMENT.inkDim} opacity={0.85}>{dbm}</text>
                </g>
              ))}

              {/* every other sector tinted, so each AP's wedge reads as a block */}
              {n > 2 && sectors.map((_, i) => {
                if (i % 2 === 0) return null
                const [ax, ay] = polar(i * span, R_MAX), [bx, by] = polar((i + 1) * span, R_MAX)
                return <path key={`t${i}`} fill={INSTRUMENT.gold} fillOpacity={0.05}
                             d={`M${CX} ${CY} L${ax.toFixed(1)} ${ay.toFixed(1)} A${R_MAX} ${R_MAX} 0 ${span > 180 ? 1 : 0} 1 ${bx.toFixed(1)} ${by.toFixed(1)} Z`} />
              })}

              {n > 1 && sectors.map((_, i) => {
                const [x1, y1] = polar(i * span, R_CORE)
                const [x2, y2] = polar(i * span, R_MAX)
                return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={INSTRUMENT.goldHi} strokeOpacity={0.7} strokeWidth={px(1.6)} />
              })}

              <g className="pw-scope-sweep" aria-hidden="true">
                {trail}
                <line x1={CX} y1={CY} x2={CX} y2={CY - R_MAX} stroke={INSTRUMENT.goldHi} strokeWidth={px(1)} opacity={0.5} />
              </g>

              {/* each sector's rail and name, just outside the rim */}
              {sectors.map((s, i) => {
                const a0 = i * span + gap / 2, a1 = (i + 1) * span - gap / 2
                const mid = n === 1 ? 0 : (i + 0.5) * span
                const lit = hovered?.sector === s
                const rr = R_MAX + px(7)
                const labelR = R_MAX + px(20)
                const [lx, ly] = polar(mid, labelR)
                const anchor = mid > 15 && mid < 165 ? 'start' : mid > 195 && mid < 345 ? 'end' : 'middle'
                const fs = px(10)
                // A side name can run out to the edge of the face. A name centred
                // above or below it only has the gap to its neighbours, and when
                // that will not hold even a clipped name the count stands alone —
                // the full name is still in the tooltip.
                const gapToNext = n > 1 ? 2 * labelR * Math.sin(rad(span) / 2) : Infinity
                const room = anchor === 'start' ? VW - lx - 4
                           : anchor === 'end' ? lx - 4
                           : Math.min(240, gapToNext * 0.85)
                const count = String(s.clients)
                const chars = Math.floor(room / (fs * 0.62))
                const name = chars < count.length + 5 ? ''
                           : s.ap_name.length + 1 + count.length > chars ? `${s.ap_name.slice(0, chars - count.length - 2)}… `
                           : `${s.ap_name} `
                const dy = anchor !== 'middle' ? fs * 0.35 : mid > 90 && mid < 270 ? fs * 0.9 : 0
                return (
                  <g key={i} style={{ cursor: clickable(s) ? 'pointer' : 'default' }} onClick={() => select(s)}>
                    {n === 1
                      ? <circle cx={CX} cy={CY} r={rr} fill="none" stroke={INSTRUMENT.gold} strokeOpacity={0.5} strokeWidth={px(2)} />
                      : <path d={arc(rr, a0, a1)} fill="none" stroke={INSTRUMENT.gold} strokeLinecap="round"
                              strokeOpacity={lit ? 0.95 : 0.5} strokeWidth={px(lit ? 3 : 2)} />}
                    <text x={lx} y={ly + dy} textAnchor={anchor} fontFamily={MONO} fontSize={fs}
                          fill={lit ? INSTRUMENT.goldHi : INSTRUMENT.ink} opacity={lit ? 1 : 0.78}>
                      {name}<tspan fill={INSTRUMENT.inkDim}>{count}</tspan>
                      <title>{`${s.ap_name} — ${s.clients} client${s.clients === 1 ? '' : 's'}${s.points.length < s.clients ? `, ${s.points.length} drawn` : ''}`}</title>
                    </text>
                  </g>
                )
              })}

              <circle cx={CX} cy={CY} r={R_CORE} fill="rgba(4,6,10,.6)" stroke="rgba(216,180,110,.3)" strokeWidth={px(1)} />
              <circle cx={CX} cy={CY} r={px(3.5)} fill={INSTRUMENT.goldHi} style={{ filter: 'drop-shadow(0 0 6px #d8b46e)' }} />
              <text x={CX} y={CY + px(15)} textAnchor="middle" fontFamily={MONO} fontSize={px(8)}
                    letterSpacing={px(2)} fill={INSTRUMENT.gold} opacity={0.85}>AP</text>

              {blips.map(b => {
                const lit = hovered?.key === b.key
                const colour = SIGNAL_COLOR[b.cls]
                return (
                  <g key={b.key} style={{ cursor: clickable(b.sector) ? 'pointer' : 'default' }}
                     onMouseEnter={e => track(e, b)} onMouseMove={e => track(e, b)}
                     onMouseLeave={() => setHover(null)} onClick={() => select(b.sector)}>
                    <circle className="pw-scope-blip" cx={b.x} cy={b.y} r={px(lit ? 5 : 3.4)} fill={colour} fillOpacity={0.9}
                            stroke={lit ? INSTRUMENT.goldHi : 'none'} strokeWidth={px(1.2)}
                            style={{
                              // Brightest as the sweep crosses the blip's own bearing.
                              animationDelay: `${-((360 - b.brg) / 360) * SWEEP_S}s`,
                              filter: blips.length > GLOW_LIMIT ? undefined : `drop-shadow(0 0 ${px(4)}px ${colour}aa)`,
                            }} />
                    <circle cx={b.x} cy={b.y} r={px(8)} fill="transparent" />
                  </g>
                )
              })}
            </svg>
          </>
        )}

        {hovered && hover && (
          <div className="absolute z-20 pointer-events-none bg-gray-900/95 border border-gray-700 px-2.5 py-2
                          text-[10.5px] font-mono leading-[1.6] whitespace-nowrap"
               style={{ left: Math.max(0, Math.min(hover.x + 14, boxW - 210)), top: Math.max(0, Math.min(hover.y + 14, boxH - 100)) }}>
            <div className="text-white">{hovered.point.label}</div>
            <div><span className="inline-block w-12 text-gray-500">AP</span>{hovered.sector.ap_name}</div>
            {hovered.point.ssid && <div><span className="inline-block w-12 text-gray-500">SSID</span>{hovered.point.ssid}</div>}
            <div><span className="inline-block w-12 text-gray-500">Band</span>{bandLabel(hovered.point.band)}</div>
            <div><span className="inline-block w-12 text-gray-500">Signal</span>
              <span style={{ color: SIGNAL_COLOR[hovered.cls] }}>{hovered.point.rssi_dbm} dBm · {hovered.cls}</span></div>
          </div>
        )}
      </div>

      {n > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 pt-2 flex-shrink-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {(['good', 'fair', 'poor'] as const).map(c => (
              <span key={c} className="flex items-center gap-1.5 font-mono text-[9.5px] text-gray-400">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: SIGNAL_COLOR[c], boxShadow: `0 0 5px ${SIGNAL_COLOR[c]}` }} />
                {c === 'good' ? `≥ ${goodDbm}` : c === 'fair' ? `≥ ${fairDbm}` : `< ${fairDbm}`} dBm
              </span>
            ))}
          </div>
          <span className="font-mono text-[9.5px] text-gray-500">
            sector = AP · range = signal · {total} client{total === 1 ? '' : 's'}
          </span>
        </div>
      )}
    </div>
  )
}

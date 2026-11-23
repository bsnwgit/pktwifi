// A floor plan with the access points and clients drawn over it.
//
// The overlay is SVG in the plan's own pixel space, so a position from the API
// lands on the same spot at any display size. Only the plan is an image; every
// device name is rendered as text, never as markup.
import { useMemo } from 'react'
import type { FloorLocation, LocatedClient, TrailPoint } from '../api/client'
import { SIGNAL_COLOR } from '../utils/rf'
import { INSTRUMENT } from './instrument'

export interface FloorMapProps {
  planUrl: string
  width: number
  height: number
  aps: FloorLocation['access_points']
  clients: LocatedClient[]
  selectedMac: string | null
  onSelect: (mac: string | null) => void
  trail: TrailPoint[]
  showRings: boolean
}

/** Clients joined to one AP all sit at its position, so they are fanned out
 *  around it to stay visible. That spread is layout, not location: the legend
 *  says so, and the selected client's ring is drawn at the AP itself. */
function fanOut(clients: LocatedClient[], unit: number): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>()
  const nextAt = new Map<string, number>()
  const GOLDEN = Math.PI * (3 - Math.sqrt(5))
  for (const c of clients) {
    if (c.method === 'trilateration') {
      out.set(c.mac_address, { x: c.x_px, y: c.y_px })
      continue
    }
    const key = `${c.x_px},${c.y_px}`
    const i = nextAt.get(key) ?? 0
    nextAt.set(key, i + 1)
    // The AP marker itself is at i = 0's centre, so the first client starts one step out.
    const r = unit * 2.6 * Math.sqrt(i + 1)
    const a = i * GOLDEN
    out.set(c.mac_address, { x: c.x_px + r * Math.cos(a), y: c.y_px + r * Math.sin(a) })
  }
  return out
}

export default function FloorMap({
  planUrl, width, height, aps, clients, selectedMac, onSelect, trail, showRings,
}: FloorMapProps) {
  const unit = Math.max(width, height) / 160
  const spots = useMemo(() => fanOut(clients, unit), [clients, unit])
  const selected = clients.find(c => c.mac_address === selectedMac) ?? null
  const trailPoints = trail.filter(p => p.x_px != null && p.y_px != null)

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto block bg-gray-950 border border-gray-800"
      role="img"
      aria-label="Floor plan with access points and clients"
      onClick={() => onSelect(null)}
    >
      <image href={planUrl} width={width} height={height} />

      {trailPoints.length > 1 && (
        <polyline
          points={trailPoints.map(p => `${p.x_px},${p.y_px}`).join(' ')}
          fill="none" stroke={INSTRUMENT.ice} strokeWidth={unit * 0.5} strokeDasharray={`${unit * 1.5} ${unit}`}
        />
      )}
      {trailPoints.map((p, i) => (
        <circle key={`${p.ts}-${i}`} cx={p.x_px!} cy={p.y_px!} r={unit * 0.8} fill={INSTRUMENT.ice}>
          <title>{`${p.event_type} · ${p.access_point_name} · ${p.ts}`}</title>
        </circle>
      ))}

      {showRings && selected && selected.accuracy_px != null && (
        <circle
          cx={selected.method === 'trilateration' ? selected.x_px : (aps.find(a => a.id === selected.access_point_id)?.x_px ?? selected.x_px)}
          cy={selected.method === 'trilateration' ? selected.y_px : (aps.find(a => a.id === selected.access_point_id)?.y_px ?? selected.y_px)}
          r={selected.accuracy_px}
          fill={INSTRUMENT.gold} fillOpacity={0.07}
          stroke={INSTRUMENT.gold} strokeOpacity={0.7} strokeWidth={unit * 0.4} strokeDasharray={`${unit} ${unit}`}
        />
      )}

      {aps.map(a => (
        <g key={a.id} className={a.status === 'online' ? undefined : 'opacity-50'}>
          <polygon
            points={`${a.x_px},${a.y_px - unit * 1.8} ${a.x_px + unit * 1.8},${a.y_px} ${a.x_px},${a.y_px + unit * 1.8} ${a.x_px - unit * 1.8},${a.y_px}`}
            fill={INSTRUMENT.gold} stroke={INSTRUMENT.goldHi} strokeWidth={unit * 0.25}
          >
            <title>{`${a.name} (${a.status})`}</title>
          </polygon>
          <text x={a.x_px + unit * 2.4} y={a.y_px + unit * 0.6} fontSize={unit * 1.7} fill={INSTRUMENT.ink}>{a.name}</text>
        </g>
      ))}

      {clients.map(c => {
        const spot = spots.get(c.mac_address)!
        const isSel = c.mac_address === selectedMac
        const fill = c.signal_class ? SIGNAL_COLOR[c.signal_class] : INSTRUMENT.inkDim
        return (
          <circle
            key={c.mac_address} cx={spot.x} cy={spot.y} r={isSel ? unit * 1.3 : unit}
            fill={fill} fillOpacity={c.method === 'trilateration' ? 1 : 0.8}
            stroke={isSel ? INSTRUMENT.goldHi : c.method === 'trilateration' ? INSTRUMENT.ink : 'none'}
            strokeWidth={unit * 0.3}
            className="cursor-pointer"
            onClick={e => { e.stopPropagation(); onSelect(c.mac_address) }}
          >
            <title>{`${c.hostname || c.mac_address}${c.rssi_dbm != null ? ` · ${c.rssi_dbm} dBm` : ''}`}</title>
          </circle>
        )
      })}
    </svg>
  )
}

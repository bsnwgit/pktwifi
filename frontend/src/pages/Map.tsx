// Map — where clients are on a floor plan.
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Floor, FloorLocation, TrailPoint } from '../api/client'
import { useAuth } from '../store/auth'
import { SIGNAL_COLOR } from '../utils/rf'
import FloorMap from '../components/FloorMap'
import HelpButton from '../components/HelpButton'

const REFRESH_MS = 15_000

function method(c: FloorLocation['clients'][number]): string {
  if (c.method === 'trilateration') {
    return `Heard by ${c.anchors} APs${c.accuracy_m != null ? `, probably within about ${Math.round(c.accuracy_m)} m` : ''}`
  }
  return c.accuracy_m != null
    ? `Joined to ${c.access_point_name}, somewhere within about ${Math.round(c.accuracy_m)} m of it`
    : `Joined to ${c.access_point_name}, distance unknown`
}

export default function MapPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [floors, setFloors] = useState<Floor[] | null>(null)
  const [siteId, setSiteId] = useState<number | null>(null)
  const [floorId, setFloorId] = useState<number | null>(null)
  const [planUrl, setPlanUrl] = useState<string | null>(null)
  const [planError, setPlanError] = useState('')
  const [loc, setLoc] = useState<FloorLocation | null>(null)
  const [error, setError] = useState('')
  const [selectedMac, setSelectedMac] = useState<string | null>(null)
  const [trail, setTrail] = useState<TrailPoint[]>([])
  const [search, setSearch] = useState('')

  useEffect(() => {
    api.getFloors().then(setFloors).catch(e => { setFloors([]); setError(e.message ?? 'Could not load floors') })
  }, [])

  const sites = useMemo(() => {
    const seen = new Map<number, string>()
    for (const f of floors ?? []) seen.set(f.site_id, f.site_name)
    return [...seen.entries()].map(([id, name]) => ({ id, name }))
  }, [floors])

  const siteFloors = useMemo(
    () => (floors ?? []).filter(f => f.site_id === siteId).sort((a, b) => a.level - b.level || a.name.localeCompare(b.name)),
    [floors, siteId],
  )
  const floor = siteFloors.find(f => f.id === floorId) ?? null

  // Pick a site, then a floor, as soon as there are some; prefer one with a plan.
  useEffect(() => {
    if (!floors || floors.length === 0) return
    if (siteId === null || !floors.some(f => f.site_id === siteId)) {
      const first = floors.find(f => f.has_plan) ?? floors[0]
      setSiteId(first.site_id)
      setFloorId(first.id)
    }
  }, [floors, siteId])
  useEffect(() => {
    if (siteId === null || siteFloors.length === 0) return
    if (!siteFloors.some(f => f.id === floorId)) setFloorId((siteFloors.find(f => f.has_plan) ?? siteFloors[0]).id)
  }, [siteId, siteFloors, floorId])

  // The plan image, fetched with the token and released when the floor changes.
  useEffect(() => {
    setPlanUrl(null)
    setPlanError('')
    if (!floor || !floor.has_plan) return
    let url: string | null = null
    let cancelled = false
    api.floorPlanUrl(floor.id)
      .then(u => { if (cancelled) URL.revokeObjectURL(u); else { url = u; setPlanUrl(u) } })
      .catch(e => { if (!cancelled) setPlanError(e.message ?? 'Could not load the plan') })
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [floor?.id, floor?.has_plan])

  // Client positions, refreshed while the tab is in view.
  useEffect(() => {
    setLoc(null)
    setSelectedMac(null)
    if (!floor || !floor.has_plan) return
    let live = true
    const load = () => {
      if (document.hidden) return
      api.locateFloor(floor.id)
        .then(r => { if (live) { setLoc(r); setError('') } })
        .catch(e => { if (live) setError(e.message ?? 'Could not load client positions') })
    }
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => { live = false; clearInterval(t) }
  }, [floor?.id, floor?.has_plan])

  useEffect(() => {
    setTrail([])
    if (!selectedMac || !floor) return
    let live = true
    api.clientTrail(selectedMac).then(r => {
      if (live) setTrail(r.points.filter(p => p.floor_id === floor.id))
    }).catch(() => { /* the trail is an extra; the map stands without it */ })
    return () => { live = false }
  }, [selectedMac, floor?.id])

  const clients = loc?.clients ?? []
  const selected = clients.find(c => c.mac_address === selectedMac) ?? null
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return clients
    return clients.filter(c => [c.hostname, c.mac_address, c.ip_address, c.ssid, c.access_point_name]
      .some(v => (v ?? '').toLowerCase().includes(q)))
  }, [clients, search])

  const inp = 'text-sm bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-1.5 focus:outline-none focus:border-sky-500'

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-white">Map</h1>
          <HelpButton title="Map — How It Works">
            <p>Each dot is a client, coloured by its signal to the access point it is joined to. Diamonds are access points.</p>
            <p>Wi-Fi alone cannot say exactly where a device is. A client heard by <span className="text-gray-300 font-medium">three or more placed access points</span> is placed between them, usually within several metres. A client heard by <span className="text-gray-300 font-medium">only one</span> is shown next to its access point, and its ring is how far away its signal suggests it is. It could be anywhere on that ring, in any direction.</p>
            <p>Click a client to see its ring and where it has roamed in the last 24 hours. Most controllers report only the access point a client is joined to, so most dots are the second kind.</p>
          </HelpButton>
        </div>
        <p className="text-sm text-white mt-0.5">
          {loc ? `${clients.length} client${clients.length === 1 ? '' : 's'} on this floor` : 'Client locations from Wi-Fi signal'}
          {loc && loc.unplaced_clients > 0 && ` · ${loc.unplaced_clients} on access points that are not placed on any floor`}
        </p>
      </div>

      {floors === null && <div className="text-white text-sm">Loading…</div>}

      {floors !== null && floors.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 p-6 text-sm text-white space-y-2">
          <p>There are no floor plans yet.</p>
          {isAdmin
            ? <p>Add a floor, upload its plan and place your access points under <Link to="/settings?tab=floors" className="text-sky-400 hover:text-sky-300">Settings → Floors</Link>.</p>
            : <p>An administrator can add floor plans under Settings → Floors.</p>}
        </div>
      )}

      {floors !== null && floors.length > 0 && (
        <>
          <div className="flex items-center gap-3 flex-wrap">
            {sites.length > 1 && (
              <select value={siteId ?? ''} onChange={e => setSiteId(Number(e.target.value))} className={inp} aria-label="Site">
                {sites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            )}
            <div className="flex items-center gap-1 flex-wrap">
              {siteFloors.map(f => (
                <button key={f.id} onClick={() => setFloorId(f.id)}
                  className={`text-sm px-4 py-1.5 rounded-lg whitespace-nowrap ${f.id === floorId ? 'bg-gray-700 text-white' : 'text-white hover:bg-gray-800'}`}>
                  {f.name}
                </button>
              ))}
            </div>
            <input type="text" placeholder="Search hostname, MAC, IP, SSID, AP…" value={search}
              onChange={e => setSearch(e.target.value)} className={`${inp} w-64 placeholder-gray-500`} />
          </div>

          {error && <div className="text-red-400 text-sm">{error}</div>}

          {floor && !floor.has_plan && (
            <div className="bg-gray-900 border border-gray-800 p-6 text-sm text-white">
              {floor.name} has no plan image yet.{isAdmin && <> Upload one under <Link to="/settings?tab=floors" className="text-sky-400 hover:text-sky-300">Settings → Floors</Link>.</>}
            </div>
          )}
          {planError && <div className="text-red-400 text-sm">{planError}</div>}

          {floor && floor.has_plan && floor.image_w && floor.image_h && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
              <div className="space-y-2 min-w-0">
                {planUrl
                  ? <FloorMap planUrl={planUrl} width={floor.image_w} height={floor.image_h}
                      aps={loc?.access_points ?? []} clients={clients} selectedMac={selectedMac}
                      onSelect={setSelectedMac} trail={trail} showRings={!!floor.scale_px_per_m} />
                  : <div className="h-48 flex items-center justify-center text-white text-sm bg-gray-900 border border-gray-800">Loading plan…</div>}
                <div className="flex items-center gap-4 flex-wrap text-xs text-white">
                  {(['good', 'fair', 'poor'] as const).map(k => (
                    <span key={k} className="flex items-center gap-1.5">
                      <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: SIGNAL_COLOR[k] }} />{k} signal
                    </span>
                  ))}
                  <span>Outlined dot: placed from 3+ APs</span>
                  <span>Plain dot next to an AP: joined to it, spread out to stay visible. Not a position.</span>
                </div>
                {!floor.scale_px_per_m && (
                  <p className="text-xs text-amber-300">This floor has no scale, so distances and accuracy rings are not shown. Set one under Settings → Floors.</p>
                )}
                {loc && loc.access_points.length === 0 && (
                  <p className="text-xs text-amber-300">No access points are placed on this floor yet, so no client can be drawn.</p>
                )}
              </div>

              <div className="space-y-3 min-w-0">
                <div className="bg-gray-900 border border-gray-800 p-4 text-sm text-white">
                  {selected ? (
                    <div className="space-y-1.5">
                      <div className="font-semibold break-words">{selected.hostname || selected.mac_address}</div>
                      <div className="text-xs text-gray-400 break-all">{selected.mac_address}{selected.ip_address ? ` · ${selected.ip_address}` : ''}</div>
                      <div>{method(selected)}</div>
                      <div className="text-xs text-gray-400">
                        {selected.rssi_dbm != null ? `${selected.rssi_dbm} dBm` : 'no signal reading'}
                        {selected.ssid ? ` · ${selected.ssid}` : ''}{selected.band ? ` · ${selected.band}` : ''}
                      </div>
                      <div className="text-xs text-gray-400">
                        {trail.length > 1 ? `${trail.length} stops in the last 24 h (dashed line)` : 'No roaming on this floor in the last 24 h'}
                      </div>
                    </div>
                  ) : <span className="text-gray-400">Click a client to see how it was placed.</span>}
                </div>

                <div className="bg-gray-900 border border-gray-800 max-h-96 overflow-auto">
                  <table className="w-full text-xs">
                    <tbody className="divide-y divide-gray-800/60">
                      {shown.map(c => (
                        <tr key={c.mac_address} onClick={() => setSelectedMac(c.mac_address)}
                          className={`cursor-pointer hover:bg-gray-800/40 ${c.mac_address === selectedMac ? 'bg-gray-800/60' : ''}`}>
                          <td className="pl-3 py-1.5 w-4">
                            <span className="inline-block w-2 h-2 rounded-full"
                              style={{ background: c.signal_class ? SIGNAL_COLOR[c.signal_class] : undefined }} />
                          </td>
                          <td className="px-2 py-1.5 text-white break-all">{c.hostname || c.mac_address}</td>
                          <td className="pr-3 py-1.5 text-gray-400 text-right whitespace-nowrap">{c.access_point_name}</td>
                        </tr>
                      ))}
                      {shown.length === 0 && <tr><td className="px-3 py-4 text-center text-gray-400">{loc ? 'No clients.' : 'Loading…'}</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

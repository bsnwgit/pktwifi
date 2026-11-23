// Settings -> Floors.
//
// A floor is a plan image belonging to a site. Three jobs happen here: upload
// the plan, tell the app how big it is (click two points, enter the real
// distance between them) and put each access point where it hangs. Client
// location on the Map page is only as good as these three.
import { useEffect, useRef, useState } from 'react'
import { api, AccessPoint, Floor, Site } from '../../api/client'
import HelpButton from '../../components/HelpButton'
import { INSTRUMENT } from '../../components/instrument'

const inp = 'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500'
const btn = 'px-4 py-2 text-sm bg-sky-600 hover:bg-sky-500 text-white rounded-lg disabled:opacity-50'

function FloorModal({ sites, onClose, onSaved }: { sites: Site[]; onClose: () => void; onSaved: () => void }) {
  const [siteId, setSiteId] = useState<number | ''>(sites[0]?.id ?? '')
  const [name, setName] = useState('')
  const [level, setLevel] = useState('0')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (siteId === '') return
    setSaving(true)
    setError('')
    try {
      await api.createFloor({ site_id: siteId, name, level: Number(level) || 0 })
      onSaved()
    } catch (err: any) {
      setError(err.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-sm p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-white mb-5">New Floor</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-white block mb-1">Site</label>
            <select value={siteId} onChange={e => setSiteId(Number(e.target.value))} required className={inp}>
              {sites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} required autoFocus maxLength={80} className={inp} />
          </div>
          <div>
            <label className="text-xs text-white block mb-1">Level (orders the floor tabs, lowest first)</label>
            <input type="number" value={level} onChange={e => setLevel(e.target.value)} min={-50} max={200} className={inp} />
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-white">Cancel</button>
            <button type="submit" disabled={saving || siteId === ''} className={btn}>{saving ? 'Saving…' : 'Create Floor'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

type Pt = { x: number; y: number }

function FloorEditor({ floor, onChanged, onClose }: { floor: Floor; onChanged: () => void; onClose: () => void }) {
  const [planUrl, setPlanUrl] = useState<string | null>(null)
  const [rev, setRev] = useState(0)
  const [aps, setAps] = useState<AccessPoint[]>([])
  const [mode, setMode] = useState<'place' | 'scale'>('place')
  const [armed, setArmed] = useState<number | null>(null)
  const [drag, setDrag] = useState<{ id: number } & Pt | null>(null)
  const [scalePts, setScalePts] = useState<Pt[]>([])
  const [distance, setDistance] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const svgRef = useRef<SVGSVGElement>(null)

  const loadAps = () => api.getAccessPoints().then(setAps).catch(e => setError(e.message ?? 'Could not load access points'))
  useEffect(() => { loadAps() }, [])

  useEffect(() => {
    setPlanUrl(null)
    if (!floor.has_plan) return
    let url: string | null = null
    let cancelled = false
    api.floorPlanUrl(floor.id)
      .then(u => { if (cancelled) URL.revokeObjectURL(u); else { url = u; setPlanUrl(u) } })
      .catch(e => { if (!cancelled) setError(e.message ?? 'Could not load the plan') })
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [floor.id, floor.has_plan, rev])

  const w = floor.image_w ?? 0
  const h = floor.image_h ?? 0
  const unit = Math.max(w, h) / 160

  const toImage = (e: { clientX: number; clientY: number }): Pt | null => {
    const svg = svgRef.current
    const ctm = svg?.getScreenCTM()
    if (!svg || !ctm) return null
    const p = svg.createSVGPoint()
    p.x = e.clientX
    p.y = e.clientY
    const q = p.matrixTransform(ctm.inverse())
    return { x: Math.min(Math.max(q.x, 0), w), y: Math.min(Math.max(q.y, 0), h) }
  }

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true)
    setError('')
    setMsg('')
    try {
      await fn()
      if (done) setMsg(done)
    } catch (e: any) {
      setError(e.message ?? 'Failed')
    } finally {
      setBusy(false)
    }
  }

  const upload = (file: File | undefined) => {
    if (!file) return
    run(async () => {
      const f = await api.uploadFloorPlan(floor.id, file)
      setRev(r => r + 1)
      onChanged()
      if (f.scale_reset) setMsg('The new plan is a different size, so its scale was cleared. Set it again.')
      else setMsg('Plan uploaded.')
    })
  }

  const clickPlan = (e: React.MouseEvent) => {
    const p = toImage(e)
    if (!p) return
    if (mode === 'scale') {
      setScalePts(prev => (prev.length >= 2 ? [p] : [...prev, p]))
      return
    }
    if (armed === null) return
    const id = armed
    run(async () => {
      await api.placeAccessPoint(id, { floor_id: floor.id, x_px: Math.round(p.x), y_px: Math.round(p.y) })
      setArmed(null)
      await loadAps()
      onChanged()
    })
  }

  const finishDrag = () => {
    if (!drag) return
    const d = drag
    setDrag(null)
    run(async () => {
      await api.placeAccessPoint(d.id, { floor_id: floor.id, x_px: Math.round(d.x), y_px: Math.round(d.y) })
      await loadAps()
    })
  }

  const saveScale = () => {
    const m = Number(distance)
    if (scalePts.length !== 2 || !(m > 0)) return
    run(async () => {
      await api.setFloorScale(floor.id, { x1: scalePts[0].x, y1: scalePts[0].y, x2: scalePts[1].x, y2: scalePts[1].y, distance_m: m })
      setScalePts([])
      setDistance('')
      onChanged()
    }, 'Scale saved.')
  }

  const here = aps.filter(a => a.floor_id === floor.id && a.x_px != null && a.y_px != null)
  const stateOf = (a: AccessPoint) =>
    a.floor_id === floor.id && a.x_px != null ? 'on this floor' : a.floor_id != null ? 'on another floor' : 'not placed'

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h3 className="text-sm font-semibold text-white">{floor.site_name} · {floor.name}</h3>
        <button onClick={onClose} className="text-sm text-white hover:text-sky-400">Close</button>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <label className={`${btn} cursor-pointer`}>
          {floor.has_plan ? 'Replace plan' : 'Upload plan'}
          <input type="file" accept="image/png,image/jpeg" className="hidden" disabled={busy}
            onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }} />
        </label>
        <span className="text-xs text-gray-400">PNG or JPEG, up to 8 MB.</span>
        {floor.has_plan && (
          <div className="flex gap-1 ml-auto">
            {(['place', 'scale'] as const).map(m => (
              <button key={m} onClick={() => { setMode(m); setArmed(null); setScalePts([]) }}
                className={`text-sm px-4 py-1.5 rounded-lg ${mode === m ? 'bg-gray-700 text-white' : 'text-white hover:bg-gray-800'}`}>
                {m === 'place' ? 'Place access points' : 'Set scale'}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <p className="text-red-400 text-xs">{error}</p>}
      {msg && <p className="text-emerald-300 text-xs">{msg}</p>}

      {floor.has_plan && w > 0 && h > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
          <div className="min-w-0 space-y-2">
            {planUrl ? (
              <svg ref={svgRef} viewBox={`0 0 ${w} ${h}`} className={`w-full h-auto block bg-gray-950 border border-gray-800 ${mode === 'scale' || armed !== null ? 'cursor-crosshair' : ''}`}
                onClick={clickPlan}
                onPointerMove={e => { if (drag) { const p = toImage(e); if (p) setDrag({ id: drag.id, ...p }) } }}
                onPointerUp={finishDrag}>
                <image href={planUrl} width={w} height={h} />
                {here.map(a => {
                  const x = drag?.id === a.id ? drag.x : a.x_px!
                  const y = drag?.id === a.id ? drag.y : a.y_px!
                  return (
                    <g key={a.id} className={mode === 'place' ? 'cursor-move' : undefined}
                      onClick={e => e.stopPropagation()}
                      onPointerDown={e => { if (mode === 'place') { (e.target as Element).setPointerCapture?.(e.pointerId); setDrag({ id: a.id, x, y }) } }}>
                      <polygon points={`${x},${y - unit * 2} ${x + unit * 2},${y} ${x},${y + unit * 2} ${x - unit * 2},${y}`}
                        fill={INSTRUMENT.gold} stroke={INSTRUMENT.goldHi} strokeWidth={unit * 0.3} />
                      <text x={x + unit * 2.6} y={y + unit * 0.7} fontSize={unit * 1.8} fill={INSTRUMENT.ink} pointerEvents="none">{a.name}</text>
                    </g>
                  )
                })}
                {scalePts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={unit} fill={INSTRUMENT.ice} />)}
                {scalePts.length === 2 && (
                  <line x1={scalePts[0].x} y1={scalePts[0].y} x2={scalePts[1].x} y2={scalePts[1].y}
                    stroke={INSTRUMENT.ice} strokeWidth={unit * 0.5} />
                )}
              </svg>
            ) : <div className="h-40 flex items-center justify-center text-white text-sm bg-gray-950 border border-gray-800">Loading plan…</div>}
            <p className="text-xs text-gray-400">
              {mode === 'place'
                ? (armed !== null ? 'Click the plan where the selected access point hangs.' : 'Pick an access point on the right, then click the plan. Drag a diamond to move it.')
                : 'Click one end of a distance you know (a wall, a corridor), then the other end, then enter its real length.'}
            </p>
          </div>

          <div className="space-y-3 min-w-0">
            {mode === 'scale' ? (
              <div className="space-y-2 text-sm text-white">
                <div className="text-xs text-gray-400">
                  Current scale: {floor.scale_px_per_m ? `${floor.scale_px_per_m.toFixed(2)} px per metre` : 'not set'}
                </div>
                <label className="text-xs text-white block">Real distance between the two points (metres)</label>
                <input type="number" min="0" step="0.1" value={distance} onChange={e => setDistance(e.target.value)} className={inp} />
                <button onClick={saveScale} disabled={busy || scalePts.length !== 2 || !(Number(distance) > 0)} className={btn}>Save scale</button>
              </div>
            ) : (
              <div className="max-h-96 overflow-auto border border-gray-800 divide-y divide-gray-800/60">
                {aps.map(a => (
                  <div key={a.id} className={`px-3 py-2 text-xs ${armed === a.id ? 'bg-gray-800' : 'hover:bg-gray-800/40'}`}>
                    <button className="text-left w-full text-white" onClick={() => setArmed(armed === a.id ? null : a.id)}>
                      <div className="break-words">{a.name}</div>
                      <div className="text-gray-400">{stateOf(a)}</div>
                    </button>
                    {a.floor_id === floor.id && a.x_px != null && (
                      <button className="text-gray-400 hover:text-red-400 mt-1"
                        onClick={() => run(async () => { await api.placeAccessPoint(a.id, { floor_id: null }); await loadAps(); onChanged() })}>
                        Remove from this floor
                      </button>
                    )}
                  </div>
                ))}
                {aps.length === 0 && <div className="px-3 py-4 text-center text-gray-400 text-xs">No access points yet.</div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export function FloorsTab() {
  const [floors, setFloors] = useState<Floor[]>([])
  const [sites, setSites] = useState<Site[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Floor | null>(null)
  const [error, setError] = useState('')

  const load = () => {
    api.getFloors().then(setFloors).catch(e => setError(e.message ?? 'Could not load floors')).finally(() => setLoading(false))
  }
  useEffect(() => { load(); api.getSites().then(setSites).catch(() => { /* the Add button simply has no sites to offer */ }) }, [])

  const del = async (f: Floor) => {
    try { await api.deleteFloor(f.id); if (editingId === f.id) setEditingId(null); setConfirmDelete(null); load() }
    catch (e: any) { setError(e.message ?? 'Delete failed'); setConfirmDelete(null) }
  }

  const editing = floors.find(f => f.id === editingId) ?? null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-white">Floors</h2>
            <HelpButton title="Floors — How It Works">
              <p>A floor is a <span className="text-gray-300 font-medium">plan image</span> for one level of a site. Add one, upload its plan, set its scale, then place your access points on it. The Map page then shows where clients are.</p>
              <p>The scale is what turns signal strength into metres: click two points on the plan whose real distance you know. Without it clients are still drawn at their access points, but no distances or rings.</p>
              <p>Placements survive polls and controller changes. Deleting a floor removes its image and clears its placements; the access points themselves stay.</p>
            </HelpButton>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">Floor plans and where access points are on them</p>
        </div>
        <button onClick={() => setCreating(true)} disabled={sites.length === 0} title={sites.length === 0 ? 'Add a site first' : undefined}
          className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg disabled:opacity-50">
          <span className="text-base leading-none">+</span> Add Floor
        </button>
      </div>
      {sites.length === 0 && !loading && <p className="text-xs text-amber-300">Add a site on the Sites tab first; a floor belongs to a site.</p>}
      {error && <p className="text-red-400 text-xs">{error}</p>}

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-32 text-white text-sm">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                {['Site', 'Floor', 'Level', 'Plan', 'Scale', 'APs placed'].map(h => (
                  <th key={h} className="text-left px-5 py-3 text-xs font-medium text-white uppercase tracking-wider">{h}</th>
                ))}
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {floors.map(f => (
                <tr key={f.id} className="hover:bg-gray-800/30">
                  <td className="px-5 py-3 text-white">{f.site_name}</td>
                  <td className="px-5 py-3 text-white">{f.name}</td>
                  <td className="px-5 py-3 text-white">{f.level}</td>
                  <td className="px-5 py-3 text-white">{f.has_plan ? `${f.image_w}×${f.image_h}` : '—'}</td>
                  <td className="px-5 py-3 text-white">{f.scale_px_per_m ? `${f.scale_px_per_m.toFixed(1)} px/m` : '—'}</td>
                  <td className="px-5 py-3 text-white">{f.placed_aps}</td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    <button onClick={() => setEditingId(f.id === editingId ? null : f.id)} className="p-1.5 text-white hover:text-sky-400">Edit plan</button>
                    <button onClick={() => setConfirmDelete(f)} className="p-1.5 text-white hover:text-red-400 ml-1">Delete</button>
                  </td>
                </tr>
              ))}
              {floors.length === 0 && <tr><td colSpan={7} className="px-5 py-8 text-center text-white">No floors yet.</td></tr>}
            </tbody>
          </table>
        )}
      </div>

      {editing && <FloorEditor key={editing.id} floor={editing} onChanged={load} onClose={() => setEditingId(null)} />}

      {creating && <FloorModal sites={sites} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load() }} />}

      {confirmDelete && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-sm w-full">
            <h3 className="text-white font-semibold mb-2">Delete floor?</h3>
            <p className="text-white text-sm mb-5">
              <strong>{confirmDelete.name}</strong> and its plan image will be removed, and its access points lose their
              position on it. The access points themselves are not deleted.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDelete(null)} className="px-4 py-2 text-sm text-white">Cancel</button>
              <button onClick={() => del(confirmDelete)} className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

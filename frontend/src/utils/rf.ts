/**
 * RF display vocabulary shared by the Dashboard's instruments — one colour per
 * band and per signal class, so a band reads the same on the spectrum, the
 * trend lines and the flow ribbons.
 */
import { INSTRUMENT } from '../components/instrument'

export const BANDS = ['2.4GHz', '5GHz', '6GHz'] as const

const BAND_COLOR: Record<string, string> = {
  '2.4GHz': INSTRUMENT.gold,
  '5GHz':   INSTRUMENT.ice,
  '6GHz':   '#a78bfa',
}

export function bandColor(band: string | null | undefined): string {
  return (band && BAND_COLOR[band]) || INSTRUMENT.inkDim
}

/** '2.4GHz' → '2.4 GHz'. Anything off the band list is a client tally a
 *  collector could not attribute to a radio, so it is not named as a band. */
export function bandLabel(band: string | null | undefined): string {
  return band && BAND_COLOR[band] ? band.replace('GHz', ' GHz') : 'Unattributed'
}

export function bandRank(band: string): number {
  const i = (BANDS as readonly string[]).indexOf(band)
  return i < 0 ? BANDS.length : i
}

/** The status-dot palette from index.css, so client signal and AP health share one language. */
export const SIGNAL_COLOR = { good: '#7ee0a8', fair: '#f3c265', poor: '#ff6b5e' } as const
export type SignalClass = keyof typeof SIGNAL_COLOR

export const ALARM = SIGNAL_COLOR.poor

/** Cut-offs come from the API, so the page never disagrees with the server about "good". */
export function signalClass(rssi: number, goodDbm: number, fairDbm: number): SignalClass {
  return rssi >= goodDbm ? 'good' : rssi >= fairDbm ? 'fair' : 'poor'
}

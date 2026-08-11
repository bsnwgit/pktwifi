/**
 * Brand — pktWIFI identity in the Foundation visual language.
 *
 * The functional idea of the original mark is preserved: the diagram still
 * says the same thing about what this app does. Only the execution changes —
 * hairline strokes and a concentric survey ring instead of filled shapes,
 * gold as the system channel, and a single ice-blue element marking the
 * live/data part of the diagram.
 */

export function BrandMark({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      aria-hidden="true"
    >
  <circle cx="32" cy="32" r="30" stroke="rgba(216,180,110,.16)"/>
  <circle cx="32" cy="32" r="30" stroke="rgba(216,180,110,.5)" strokeDasharray="1.5 11"/>
  <rect x="27" y="42" width="10" height="10" stroke="#f5e2b6" strokeWidth="1.3"/>
  <circle cx="32" cy="47" r="1.6" fill="#f5e2b6"/>
  <path d="M24.5 37.5 a11 11 0 0 1 15 0" stroke="rgba(216,180,110,.85)" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
  <path d="M19.5 31.5 a19.5 19.5 0 0 1 25 0" stroke="rgba(216,180,110,.45)" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
  <path d="M14.5 25.5 a28 28 0 0 1 35 0" stroke="rgba(138,216,234,.75)" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
  <circle cx="32" cy="14.5" r="1.5" fill="#8ad8ea"/>
    </svg>
  )
}

/** Full lockup — mark + wordmark. Pass descriptor={null} for tight spots. */
export function BrandLockup({
  markSize = 30,
  className = '',
  descriptor = 'Wireless',
}: {
  markSize?: number
  className?: string
  descriptor?: string | null
}) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <BrandMark size={markSize} className="flex-none" />
      <div className="leading-tight min-w-0">
        <div className="flex items-baseline gap-[3px]">
          <span className="font-mono text-[10px] text-gray-400" style={{ letterSpacing: '0.26em' }}>
            pkt
          </span>
          <span className="font-mono text-blue-300" style={{ fontSize: '15px', letterSpacing: '0.2em' }}>
            WIFI
          </span>
        </div>
        {descriptor && (
          <div className="f-lbl mt-[3px]" style={{ letterSpacing: '0.32em' }}>
            {descriptor}
          </div>
        )}
      </div>
    </div>
  )
}

export default BrandLockup

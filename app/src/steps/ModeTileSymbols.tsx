// The symbols of the six mode tiles (UX 5.3, screens): 28 px line icons in ink, sun discs filled in the sun colour.
import type { ReactNode } from "react";

const SUN_DISC = { fill: "var(--colour-sun)", stroke: "currentColor" } as const;

function SunRays({ x, y, inner, outer }: { x: number; y: number; inner: number; outer: number }) {
  const rays = Array.from({ length: 8 }, (_, index) => {
    const angle = (index * Math.PI) / 4;
    const [dx, dy] = [Math.cos(angle), Math.sin(angle)];
    return `M${x + inner * dx} ${y + inner * dy}L${x + outer * dx} ${y + outer * dy}`;
  });
  return <path d={rays.join("")} />;
}

const SYMBOLS: Record<string, ReactNode> = {
  // sun with a clock
  sun_with_clock: (
    <>
      <circle cx="10" cy="10" r="4" {...SUN_DISC} />
      <SunRays x={10} y={10} inner={6} outer={8.5} />
      <circle cx="19" cy="19" r="6" fill="var(--colour-panel)" />
      <path d="M19 15.5V19l2.5 1.5" />
    </>
  ),
  // sun over heat waves
  sun_over_heat_waves: (
    <>
      <circle cx="14" cy="9" r="4" {...SUN_DISC} />
      <SunRays x={14} y={9} inner={6} outer={8} />
      <path d="M5 19c2-1.6 4-1.6 6 0s4 1.6 6 0 4-1.6 6 0M5 24c2-1.6 4-1.6 6 0s4 1.6 6 0 4-1.6 6 0" />
    </>
  ),
  // sun with a thermometer
  sun_with_thermometer: (
    <>
      <circle cx="10" cy="11" r="4" {...SUN_DISC} />
      <SunRays x={10} y={11} inner={6} outer={8.5} />
      <path d="M20 4.5a2 2 0 0 1 2 2V17a3.6 3.6 0 1 1-4 0V6.5a2 2 0 0 1 2-2z" />
      <path d="M20 11v8" />
    </>
  ),
  // overcast sky dome
  overcast_sky_dome: (
    <>
      <path d="M3 21h22" />
      <path d="M5 21a9 9 0 0 1 18 0" />
      <path d="M8.5 15.5c0-1.7 1.3-3 3-3 .6-1.5 2-2.5 3.6-2.5 2.2 0 4 1.8 4 4a2.5 2.5 0 0 1-.6 4.9H10a1.8 1.8 0 0 1-1.5-3.4z" />
    </>
  ),
  // a facade with a dashed angled line
  facade_with_angled_line: (
    <>
      <path d="M3 24h22" />
      <path d="M5 24V8h5v16" />
      <path d="M10 24 24 7" strokeDasharray="2.5 2" />
      <path d="M15.5 24a5.5 5.5 0 0 0-1.9-4.2" />
    </>
  ),
  // a crescent moon with an upward arrow
  crescent_moon_with_arrow: (
    <>
      <path d="M13 4.5a6 6 0 1 0 6.5 8A5 5 0 0 1 13 4.5z" />
      <path d="M21 25V15M17.5 18.5 21 15l3.5 3.5" />
      <path d="M4 25h12" />
    </>
  ),
};

export function ModeTileSymbol({ symbol }: { symbol: string }) {
  return (
    <svg className="mode-tile-symbol" width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {SYMBOLS[symbol]}
    </svg>
  );
}

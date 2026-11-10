// The legend of UX 8.1 and 8.2, bottom right of the 3D view: the colourings on screen and their units.
import { messages } from "../messages";
import { formattedNumber, withUnit } from "../format_numbers";
import { cividis, keptScoreRange, sunRamp } from "../viewer/colour_scales";
import type { ViewportTheme } from "../viewer/scene";
import "./overlays.css";

export interface LegendContent {
  keptVoxels?: { title: string; mode?: string; cutoff: number; unit?: string; thinningStep: number };
  skyDome?: { title: string; lowestWeight: number; highestWeight: number };
  sunPath?: string;                               // sunPathLegend(sunPath)
  carvedByCriterion?: { criteria: { name: string; colour: string }[]; thinningStep: number };     // one swatch and name per criterion that was on
}

interface LegendProps {
  content: LegendContent;
  theme: ViewportTheme;
}

const RAMP_STOPS = 11;

function rampGradient(colourAt: (t: number) => string): string {
  const stops = Array.from({ length: RAMP_STOPS }, (_, stop) => colourAt(stop / (RAMP_STOPS - 1)));
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

function Ramp({ colourAt, low, high }: { colourAt: (t: number) => string; low: string; high: string }) {
  return (
    <>
      <div className="viewer-legend-ramp" style={{ background: rampGradient(colourAt) }} aria-hidden="true" />
      <div className="viewer-legend-ramp-ends"><span>{low}</span><span>{high}</span></div>
    </>
  );
}

/** The range of the kept voxels: a ramp from 0 to the cutoff, or, when the range is a single value, that value for all of them. */
function KeptVoxelsRange({ cutoff, unit }: { cutoff: number; unit?: string }) {
  const [low, high] = keptScoreRange(cutoff);
  if (low === high) {
    return <p className="viewer-legend-single-value">{messages.keptVoxelsSingleValue(withUnit(formattedNumber(low), unit))}</p>;
  }
  return <Ramp colourAt={cividis} low={formattedNumber(low)} high={formattedNumber(high)} />;
}

export function Legend({ content, theme }: LegendProps) {
  const { keptVoxels, skyDome, sunPath, carvedByCriterion } = content;
  if (!keptVoxels && !skyDome && !sunPath && !carvedByCriterion) return null;
  return (
    <div className="viewer-overlay viewer-legend" data-viewport-theme={theme} role="group" aria-label={messages.legend}>
      {keptVoxels && (
        <section>
          {keptVoxels.mode === "tilted_plane" || (keptVoxels.mode === "time-based" && keptVoxels.cutoff === 0) ? (
            <>
              <h3>{messages.keptVoxelsPlain}</h3>
              {keptVoxels.mode === "time-based" && <p className="viewer-muted">{messages.keptVoxelsCastNoShade}</p>}
            </>
          ) : (
            <>
              <h3>{keptVoxels.title}</h3>
              <KeptVoxelsRange cutoff={keptVoxels.cutoff} unit={keptVoxels.unit} />
              <p className="viewer-muted">{messages.keptVoxelsNote(withUnit(formattedNumber(keptVoxels.cutoff), keptVoxels.unit))}</p>
            </>
          )}
          {keptVoxels.thinningStep > 1 && <p className="viewer-muted">{messages.thinnedVoxels(keptVoxels.thinningStep)}</p>}
        </section>
      )}
      {carvedByCriterion && (
        <section>
          <h3>{messages.carvedByCriterionLegend}</h3>
          <ul className="viewer-criterion-legend">
            {carvedByCriterion.criteria.map((criterion, position) => (
              <li key={position}>
                <span className="viewer-criterion-swatch" style={{ background: criterion.colour }} aria-hidden="true" />
                {criterion.name}
              </li>
            ))}
          </ul>
          {carvedByCriterion.thinningStep > 1 && <p className="viewer-muted">{messages.thinnedVoxels(carvedByCriterion.thinningStep)}</p>}
        </section>
      )}
      {skyDome && (
        <section>
          <h3>{skyDome.title}</h3>
          <Ramp colourAt={(t) => sunRamp(t, theme)} low={formattedNumber(skyDome.lowestWeight)} high={formattedNumber(skyDome.highestWeight)} />
        </section>
      )}
      {sunPath && (
        <section>
          <p><span className="viewer-sun-path-swatch" aria-hidden="true" />{sunPath}</p>
        </section>
      )}
    </div>
  );
}

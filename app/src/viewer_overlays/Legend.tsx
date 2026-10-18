// The legend of UX 8.1 and 8.2, bottom right of the 3D view: the colourings on screen and their units.
import { messages } from "../messages";
import { formattedNumber, withUnit } from "../steps/format_numbers";
import { cividis, colourToken, keptScoreRange, storeyColour, sunRamp } from "../viewer/colour_scales";
import type { ScorePointsHeader } from "../viewer/score_points_decoder";
import type { ViewportTheme } from "../viewer/scene";
import "./overlays.css";

export interface LegendContent {
  keptVoxels?: { title: string; cutoff: number; unit?: string; thinningStep: number };
  skyDome?: { title: string; lowestWeight: number; highestWeight: number };
  sunPath?: string;                               // sunPathLegend(sunPath)
  buildingMassing?: { storeyCount: number };
}

interface LegendProps {
  content: LegendContent;
  theme: ViewportTheme;
}

const RAMP_STOPS = 11;

/** The score unit of the kept voxels: "Shading caused, m²·h" for Solar time-based, "Obstruction score (relative)" for weighted modes. */
export function keptVoxelsLegendTitle(scoresKind: ScorePointsHeader["scores_kind"], weightUnit: string): string {
  if (scoresKind === "weighted_sum") return messages.keptVoxelsObstructionScore;
  return weightUnit.startsWith("m²·h") ? messages.keptVoxelsShadingCaused : messages.keptVoxelsScoreIn(weightUnit);
}

/**
 * The unit written after a kept score: "m²·h" for Solar time-based, none for the relative obstruction score, else the unit of the
 * weights.
 */
export function keptVoxelsLegendUnit(scoresKind: ScorePointsHeader["scores_kind"], weightUnit: string): string | undefined {
  if (scoresKind === "weighted_sum") return undefined;
  return weightUnit.startsWith(messages.units.shadeHours) ? messages.units.shadeHours : weightUnit;
}

function relativeLuminance(hex: string): number {
  const channels = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16) / 255)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/** Ink or white (the panel colour), whichever has the higher contrast on the background (WCAG 2.1 contrast ratio). */
function textColourOn(background: string): string {
  const contrast = (first: string, second: string) => {
    const [lighter, darker] = [relativeLuminance(first), relativeLuminance(second)].sort((a, b) => b - a);
    return (lighter + 0.05) / (darker + 0.05);
  };
  const ink = colourToken("ink"), white = colourToken("panel");
  return contrast(background, white) > contrast(background, ink) ? white : ink;
}

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
  const { keptVoxels, skyDome, sunPath, buildingMassing } = content;
  if (!keptVoxels && !skyDome && !sunPath && !buildingMassing) return null;
  return (
    <div className="viewer-overlay viewer-legend" data-viewport-theme={theme} role="group" aria-label={messages.legend}>
      {keptVoxels && (
        <section>
          <h3>{keptVoxels.title}</h3>
          <KeptVoxelsRange cutoff={keptVoxels.cutoff} unit={keptVoxels.unit} />
          <p className="viewer-muted">{messages.keptVoxelsNote(formattedNumber(keptVoxels.cutoff))}</p>
          {keptVoxels.thinningStep > 1 && <p className="viewer-muted">{messages.thinnedVoxels(keptVoxels.thinningStep)}</p>}
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
      {buildingMassing && (
        <section>
          <h3>{messages.buildingMassingLegend}</h3>
          <div className="viewer-storey-swatches">
            {Array.from({ length: buildingMassing.storeyCount }, (_, storey) => {
              const background = storeyColour(storey, buildingMassing.storeyCount);
              return (
                <span key={storey} className="viewer-storey-swatch" style={{ background, color: textColourOn(background) }}>
                  {storey + 1}
                </span>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

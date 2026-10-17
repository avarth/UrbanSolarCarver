// The histogram of the Carving step (UX 5.5, 9, 12): the scores the engine compared with the cutoff, for the occupied voxels
// sent, each bar split into its kept part (accent) and its carved part (carved colour) stacked on top, the cutoff as a dashed
// ink line with its value on an ink label. Log counts by default, with a Log / Linear switch at the title's right. Hovering a
// bar, or moving along the bars with the arrow keys, shows its range and its counts. Drawn in the browser as SVG.
import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { messages } from "../messages";
import { formattedNumber, groupedDigits } from "./format_numbers";
import { histogramBins, logAxisDecades, stackedBarHeights, type HistogramBin, type HistogramScale } from "./score_histogram";
import "./steps.css";

const BIN_COUNT = 40;
const CHART_WIDTH = 300;
const CHART_HEIGHT = 170;
const PLOT_LEFT = 50;
const PLOT_RIGHT = 8;
const PLOT_TOP = 24;          // room for the cutoff label
const PLOT_BOTTOM = 20;       // room for the x tick labels
const DECADES_PER_LOG_TICK = 2;
const LINEAR_TICKS = 2;
const BAR_GAP = 0.5;

const PLOT_WIDTH = CHART_WIDTH - PLOT_LEFT - PLOT_RIGHT;
const PLOT_HEIGHT = CHART_HEIGHT - PLOT_TOP - PLOT_BOTTOM;

interface ScoreHistogramProps {
  comparedScores: Float32Array;
  kept: Uint8Array;
  cutoff: number;
  /** Sun at set hours: the scores are shading in m²·h; the weighted modes compare relative scores. */
  isShadowTolerated: boolean;
  slopeLimitVoxelsRemoved: number;
}

/** A round count at or above *count* for the top of the linear axis: 1, 2 or 5 times a power of ten. */
function roundedAxisTop(count: number): number {
  if (count <= 1) return 1;
  const power = 10 ** Math.floor(Math.log10(count));
  return [1, 2, 5, 10].map((multiple) => multiple * power).find((top) => top >= count)!;
}

function yTicks(scale: HistogramScale, axisTop: number): { count: number; height: number }[] {
  if (scale === "log") {
    return Array.from({ length: Math.floor(axisTop / DECADES_PER_LOG_TICK) + 1 }, (_, tick) => {
      const decade = tick * DECADES_PER_LOG_TICK;
      return { count: 10 ** decade, height: (decade / axisTop) * PLOT_HEIGHT };
    });
  }
  return Array.from({ length: LINEAR_TICKS + 1 }, (_, tick) => ({ count: (axisTop * tick) / LINEAR_TICKS, height: (tick / LINEAR_TICKS) * PLOT_HEIGHT }));
}

export function ScoreHistogram({ comparedScores, kept, cutoff, isShadowTolerated, slopeLimitVoxelsRemoved }: ScoreHistogramProps) {
  const [scale, setScale] = useState<HistogramScale>("log");
  const [activeBin, setActiveBin] = useState<number | null>(null);
  const titleId = useId();
  const bins = useMemo(() => histogramBins(comparedScores, kept, BIN_COUNT), [comparedScores, kept]);
  const unit = isShadowTolerated ? "m²·h" : "";
  if (bins.length === 0) return null;

  const lowest = Math.min(bins[0].lower, cutoff), highest = Math.max(bins[bins.length - 1].upper, cutoff);
  const span = highest > lowest ? highest - lowest : 1;
  const xOf = (value: number) => PLOT_LEFT + ((value - lowest) / span) * PLOT_WIDTH;
  const largestBar = Math.max(...bins.map((bin) => bin.keptCount + bin.carvedCount));
  const axisTop = scale === "log" ? logAxisDecades(largestBar) : roundedAxisTop(largestBar);
  const baseline = PLOT_TOP + PLOT_HEIGHT;
  // A one-bin histogram (every score the same) gets a bar a fortieth of the plot wide around its score.
  const barEdges = (bin: HistogramBin) => (bin.upper > bin.lower ? [xOf(bin.lower), xOf(bin.upper)]
    : [xOf(bin.lower) - PLOT_WIDTH / BIN_COUNT / 2, xOf(bin.lower) + PLOT_WIDTH / BIN_COUNT / 2]);
  const cutoffX = xOf(cutoff);
  const cutoffText = formattedNumber(cutoff);
  const voxelCount = bins.reduce((count, bin) => count + bin.keptCount + bin.carvedCount, 0);

  const binAt = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * CHART_WIDTH;
    const index = bins.findIndex((bin) => {
      const [left, right] = barEdges(bin);
      return x >= left && x <= right;
    });
    setActiveBin(index >= 0 ? index : null);
  };
  const moveWithKeys = (event: KeyboardEvent<SVGSVGElement>) => {
    const step = { ArrowRight: 1, ArrowLeft: -1, Home: -bins.length, End: bins.length }[event.key];
    if (step === undefined) {
      if (event.key === "Escape") setActiveBin(null);
      return;
    }
    event.preventDefault();
    setActiveBin((index) => Math.min(bins.length - 1, Math.max(0, (index ?? (step > 0 ? -1 : bins.length)) + step)));
  };

  const shown = activeBin === null ? null : bins[activeBin];
  const readoutLeft = shown === null ? 0 : ((barEdges(shown)[0] + barEdges(shown)[1]) / 2 / CHART_WIDTH) * 100;
  return (
    <figure className="score-histogram">
      <div className="score-histogram-title-row">
        <h3 id={titleId} className="score-histogram-title">{messages.histogramTitle}</h3>
        <div className="segmented-switch" role="group" aria-label={messages.histogramScaleLabel}>
          {(["log", "linear"] as const).map((choice) => (
            <button key={choice} type="button" aria-pressed={scale === choice} onClick={() => setScale(choice)}>
              {choice === "log" ? messages.logScale : messages.linearScale}
            </button>
          ))}
        </div>
      </div>
      <div className="score-histogram-chart">
        <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} role="img" tabIndex={0} aria-labelledby={titleId}
             aria-description={messages.histogramDescription(voxelCount, cutoffText)}
             onPointerMove={binAt} onPointerLeave={() => setActiveBin(null)} onKeyDown={moveWithKeys} onBlur={() => setActiveBin(null)}>
          {yTicks(scale, axisTop).map((tick) => (
            <g key={tick.count}>
              <line className="histogram-grid-line" x1={PLOT_LEFT} x2={CHART_WIDTH - PLOT_RIGHT} y1={baseline - tick.height} y2={baseline - tick.height} />
              <text className="histogram-tick" x={PLOT_LEFT - 4} y={baseline - tick.height} textAnchor="end" dominantBaseline="middle">
                {groupedDigits(Math.round(tick.count))}
              </text>
            </g>
          ))}
          {bins.map((bin, index) => {
            const [left, right] = barEdges(bin);
            const heights = stackedBarHeights(bin.keptCount, bin.carvedCount, scale, PLOT_HEIGHT, axisTop);
            const width = Math.max(0.5, right - left - BAR_GAP);
            return (
              <g key={index} className={index === activeBin ? "histogram-bar histogram-bar-active" : "histogram-bar"}>
                {heights.kept > 0 && <rect className="histogram-kept" x={left} width={width} y={baseline - heights.kept} height={heights.kept} />}
                {heights.carved > 0 && (
                  <rect className="histogram-carved" x={left} width={width} y={baseline - heights.kept - heights.carved} height={heights.carved} />
                )}
              </g>
            );
          })}
          <line className="histogram-axis" x1={PLOT_LEFT} x2={CHART_WIDTH - PLOT_RIGHT} y1={baseline} y2={baseline} />
          <text className="histogram-tick" x={PLOT_LEFT} y={baseline + 4} dominantBaseline="hanging">{formattedNumber(lowest)}</text>
          <text className="histogram-tick" x={CHART_WIDTH - PLOT_RIGHT} y={baseline + 4} textAnchor="end" dominantBaseline="hanging">{formattedNumber(highest)}</text>
          <line className="histogram-cutoff" x1={cutoffX} x2={cutoffX} y1={PLOT_TOP - 4} y2={baseline} />
          <g className="histogram-cutoff-label">
            <rect x={cutoffX - (cutoffText.length * 3.6 + 6)} y={2} width={cutoffText.length * 7.2 + 12} height={16} rx={3} />
            <text x={cutoffX} y={10} textAnchor="middle" dominantBaseline="middle">{cutoffText}</text>
          </g>
        </svg>
        {shown !== null && (
          <div className="score-histogram-readout" style={{ left: `${Math.min(80, Math.max(20, readoutLeft))}%` }}>
            <span>{messages.histogramBinRange(formattedNumber(shown.lower), formattedNumber(shown.upper), unit)}</span>
            <span>{messages.histogramBinCounts(shown.keptCount, shown.carvedCount)}</span>
          </div>
        )}
      </div>
      <figcaption className="score-histogram-caption">
        <span className="score-histogram-axis-title">{isShadowTolerated ? messages.histogramAxisShadowTolerated : messages.histogramAxisRelative}</span>
        <span className="score-histogram-key">
          <span><span className="histogram-swatch histogram-swatch-kept" aria-hidden="true" />{messages.histogramKept}</span>
          <span><span className="histogram-swatch histogram-swatch-carved" aria-hidden="true" />{messages.histogramCarved}</span>
        </span>
        {slopeLimitVoxelsRemoved > 0 && <span className="score-histogram-note">{messages.slopeLimitNote(slopeLimitVoxelsRemoved)}</span>}
      </figcaption>
    </figure>
  );
}

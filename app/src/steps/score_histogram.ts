// The numbers behind the histogram of a criterion's carving rule (UX 5.5): the scores the engine compared with the cutoff, in bins of
// equal width over their range, each bin split into its kept and carved voxels, and the bar heights on a log or linear axis.

export interface HistogramBin {
  lower: number;
  upper: number;
  keptCount: number;
  carvedCount: number;
}

export type HistogramScale = "log" | "linear";

/**
 * *binCount* bins of equal width from the lowest to the highest compared score of the voxels sent; a score on a bin edge
 * belongs to the bin above it, the highest score to the last bin. Scores that are all the same make one bin.
 */
export function histogramBins(compared: Float32Array, kept: Uint8Array, binCount: number): HistogramBin[] {
  let lowest = Infinity, highest = -Infinity;
  for (const score of compared) {
    if (!Number.isFinite(score)) continue;
    lowest = Math.min(lowest, score);
    highest = Math.max(highest, score);
  }
  if (lowest > highest) return [];
  const count = highest > lowest ? Math.max(1, binCount) : 1;
  const width = (highest - lowest) / count;
  const bins: HistogramBin[] = Array.from({ length: count }, (_, index) => ({
    lower: lowest + index * width,
    upper: index === count - 1 ? highest : lowest + (index + 1) * width,
    keptCount: 0,
    carvedCount: 0,
  }));
  compared.forEach((score, voxel) => {
    if (!Number.isFinite(score)) return;
    const index = width > 0 ? Math.min(count - 1, Math.floor((score - lowest) / width)) : 0;
    if (kept[voxel]) bins[index].keptCount += 1;
    else bins[index].carvedCount += 1;
  });
  return bins;
}

/** Decades of counts the log axis spans: up to the next even power of ten above *largestCount*, at least 100. */
export function logAxisDecades(largestCount: number): number {
  const decades = largestCount > 1 ? Math.ceil(Math.log10(largestCount)) : 0;
  return Math.max(2, decades + (decades % 2));
}

// The log axis starts at half a voxel, below its first tick (1), so a bar or a kept part of one voxel still has a height.
const LOG_AXIS_BOTTOM_COUNT = 0.5;

/**
 * The height of a count on the log axis, from its bottom (half a voxel) to 10 to the power *decades* at *plotHeight*; 0 for
 * no voxels. The ticks (1, 100, 10 000) are placed with it too.
 */
export function logAxisHeight(count: number, decades: number, plotHeight: number): number {
  if (count <= 0) return 0;
  const bottom = Math.log10(LOG_AXIS_BOTTOM_COUNT);
  return ((Math.log10(count) - bottom) / (decades - bottom)) * plotHeight;
}

/**
 * The heights of a bar's kept part and of its carved part stacked on top of it. On the log scale (*axisTop* in decades, the
 * axis starting at half a voxel) the kept part runs from the axis to log(kept) and the carved part from log(kept) to
 * log(kept + carved); on the linear scale (*axisTop* the count at the top of the axis) each part is its share of *axisTop*.
 */
export function stackedBarHeights(keptCount: number, carvedCount: number, scale: HistogramScale, plotHeight: number,
                                  axisTop: number): { kept: number; carved: number } {
  if (scale === "linear") {
    return { kept: (keptCount / axisTop) * plotHeight, carved: (carvedCount / axisTop) * plotHeight };
  }
  const kept = logAxisHeight(keptCount, axisTop, plotHeight);
  return { kept, carved: logAxisHeight(keptCount + carvedCount, axisTop, plotHeight) - kept };
}

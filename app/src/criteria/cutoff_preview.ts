// What a cutoff on the histogram of a criterion's carving rule would carve, worked out in the browser from the score points of the last
// carving (UX proposal 1), before any run: the share of the volume it keeps and the carve amount it stands for. The points are
// ranked by the score the engine compared with the cutoff, highest first, with the sum of their own scores above each rank.
// The run gives the exact numbers: it applies the slope limit, counts the smoothed scores and sees every voxel where the points
// are thinned (over a million voxels).

export interface RankedScorePoints {
  /** The compared scores, highest first; points without a finite compared score are left out. */
  comparedDescending: Float64Array;
  /** scoreAboveRank[k] is the sum of the scores of the k points ranked highest (length: points + 1). */
  scoreAboveRank: Float64Array;
}

/** The points ranked by *compared*, each counting its own score from *scores* (a score that is not finite counts 0). */
export function rankScorePoints(compared: Float32Array, scores: Float32Array): RankedScorePoints {
  const ranked: number[] = [];
  compared.forEach((score, point) => { if (Number.isFinite(score)) ranked.push(point); });
  ranked.sort((first, second) => compared[second] - compared[first]);
  const comparedDescending = Float64Array.from(ranked, (point) => compared[point]);
  const scoreAboveRank = new Float64Array(ranked.length + 1);
  ranked.forEach((point, rank) => {
    const score = scores[point];
    scoreAboveRank[rank + 1] = scoreAboveRank[rank] + (Number.isFinite(score) && score > 0 ? score : 0);
  });
  return { comparedDescending, scoreAboveRank };
}

/** How many points score above *cutoff* (the ones it carves): a binary search of the descending scores. */
function countAbove({ comparedDescending }: RankedScorePoints, cutoff: number): number {
  let low = 0, high = comparedDescending.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (comparedDescending[middle] > cutoff) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** The share of the points, 0 to 1, that *cutoff* keeps: the volume kept before the slope limit. All of it without points. */
export function keptShareAt(ranked: RankedScorePoints, cutoff: number): number {
  const count = ranked.comparedDescending.length;
  return count === 0 ? 1 : (count - countAbove(ranked, cutoff)) / count;
}

/** The share of the points' total score, 0 to 1, held by the points *cutoff* carves: the carve amount it stands for. */
export function carveAmountAt(ranked: RankedScorePoints, cutoff: number): number {
  const total = ranked.scoreAboveRank[ranked.scoreAboveRank.length - 1];
  return total > 0 ? ranked.scoreAboveRank[countAbove(ranked, cutoff)] / total : 0;
}

/**
 * The cutoff a carve amount (0 to 1) gives, by the engine's rule (scoring.carve_fraction_threshold): the compared score of the
 * first point whose running sum of scores, from the highest down, passes the amount of the total. No amount carves nothing (the
 * highest score); an amount past the total carves everything but the lowest. Null without points.
 */
export function cutoffForCarveAmount(ranked: RankedScorePoints, amount: number): number | null {
  const { comparedDescending, scoreAboveRank } = ranked;
  if (comparedDescending.length === 0) return null;
  const target = amount * scoreAboveRank[scoreAboveRank.length - 1];
  if (target <= 0) return comparedDescending[0];
  // The running sums never fall, so the first rank past the target is found by a binary search.
  let low = 0, high = comparedDescending.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (scoreAboveRank[middle + 1] > target) high = middle;
    else low = middle + 1;
  }
  return comparedDescending[Math.min(low, comparedDescending.length - 1)];
}

/** A step for a cutoff up to *highest*: a hundredth of it or less, rounded down to a power of ten (1 when there is no range). */
export function cutoffStep(highest: number): number {
  return highest > 0 ? 10 ** Math.floor(Math.log10(highest / 100)) : 1;
}

/** *value* rounded to a whole number of *step*, without the floating point noise of the division (0.30000000000000004). */
export function roundedToStep(value: number, step: number): number {
  return Number((Math.round(value / step) * step).toPrecision(12));
}

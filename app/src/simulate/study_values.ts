// What Simulate computes from a study's values (study_values_decoder.ts): the statistics of the result card, the change from the
// maximum volume that Change colours, and the tolerance under which a change counts as none. Each is one pass over the points (the
// percentile sorts a copy): the first build found the tolerance once per point and froze the browser on 527,633 points.
import type { StudyValues } from "./study_values_decoder";

/** The geometries a study's values are traced against; the names of the service's columns. */
export type StudyGeometry = "max_volume" | "envelope" | "massing";
export const STUDY_GEOMETRIES: readonly StudyGeometry[] = ["max_volume", "envelope", "massing"];

/** The column of the values without any geometry, which the change tolerance is measured on. */
export const OPEN_COLUMN = "open";

/**
 * How the values are coloured when Change is off: by each point's share of its open-site value (its value with nothing built, the open
 * column), one 0 to 100 % scale for every geometry, or by the value in the study's unit. Share is the default: the spread of values
 * follows the surfaces' orientation (roofs far above facades), which a value scale shows instead of what the building takes away
 * (user, 2026-10-28).
 */
export type ColourBy = "share" | "value";

/** The study the 3D view draws: its values on the geometry shown, by share, by value or by change from the maximum volume. */
export interface StudyView {
  values: StudyValues;
  geometry: StudyGeometry;
  /** Colour by the change from the maximum volume, whatever colourBy says. */
  change: boolean;
  colourBy: ColourBy;
  /** Points below it are drawn in one muted colour; null without a target. */
  target: number | null;
  unit: string;
  /** The study is out of date: its values are drawn dimmed. */
  dimmed: boolean;
}

export interface StudyStatistics {
  mean: number;
  /** The 10th percentile, interpolated between the two nearest points as numpy does. */
  lowestTenth: number;
  /** The share of points (0 to 1) at or above the target; null without one. Every point stands for about the same test area. */
  shareAtTarget: number | null;
  /** The sum of the values over the sum of the open-site values (0 to 1): what the geometry keeps of what the site gives with nothing
   * built; null when the open site gives nothing. */
  keptShare: number | null;
}

/** What *values* keep of the open-site values: their sum over the open column's (0 to 1); null when the open column sums to nothing. */
export function keptShareOf(values: Float32Array, open: Float32Array): number | null {
  let kept = 0, possible = 0;
  for (let point = 0; point < values.length; point++) {
    kept += values[point];
    possible += open[point];
  }
  return possible > 0 ? kept / possible : null;
}

/** A point's value as a share (0 to 1) of its open-site value; null where the open site gives it nothing (within *tolerance*). */
export function shareOfOpen(value: number, open: number, tolerance: number): number | null {
  return open > tolerance ? Math.min(1, Math.max(0, value / open)) : null;
}

/** The value at *share* (0 to 1) of the sorted values, interpolated between the two nearest points as numpy does. */
export function percentile(sortedValues: Float32Array, share: number): number {
  if (sortedValues.length === 0) return NaN;
  const position = share * (sortedValues.length - 1);
  const below = Math.floor(position), above = Math.ceil(position);
  return sortedValues[below] + (sortedValues[above] - sortedValues[below]) * (position - below);
}

/** The mean and the lowest tenth: the part of the statistics that does not depend on the target. */
export function distributionOf(values: Float32Array): Omit<StudyStatistics, "shareAtTarget" | "keptShare"> {
  let sum = 0;
  for (let point = 0; point < values.length; point++) sum += values[point];
  return { mean: values.length ? sum / values.length : NaN, lowestTenth: percentile(Float32Array.from(values).sort(), 0.1) };
}

/** The share of points at or above *target*; null without a target or without points. */
export function shareAtOrAbove(values: Float32Array, target: number | null): number | null {
  if (target === null || values.length === 0) return null;
  let atTarget = 0;
  for (let point = 0; point < values.length; point++) if (values[point] >= target) atTarget += 1;
  return atTarget / values.length;
}

export function statisticsOf(values: Float32Array, target: number | null, open?: Float32Array): StudyStatistics {
  return { ...distributionOf(values), shareAtTarget: shareAtOrAbove(values, target), keptShare: open === undefined ? null : keptShareOf(values, open) };
}

/** Each point's value less the baseline's (the maximum volume's). */
export function changeOf(values: Float32Array, baseline: Float32Array): Float32Array {
  const change = new Float32Array(values.length);
  for (let point = 0; point < values.length; point++) change[point] = values[point] - baseline[point];
  return change;
}

/** The highest value; 0 for no values (a scale from 0 to 0). */
export function highestOf(values: Float32Array): number {
  let highest = 0;
  for (let point = 0; point < values.length; point++) if (values[point] > highest) highest = values[point];
  return highest;
}

/** A change smaller than this counts as none: a thousandth of the highest value of the open column or the maximum volume. */
export function changeTolerance(open: Float32Array | undefined, maxVolume: Float32Array | undefined): number {
  return 1e-3 * Math.max(highestOf(open ?? new Float32Array(0)), highestOf(maxVolume ?? new Float32Array(0)), 1e-9);
}

// What Simulate computes from a study's values (study_values_decoder.ts): the statistics of the result card, the facade direction of
// each point on the study's geometry, and the tolerance under which a no-build value counts as none. Each is one pass over the points
// (the percentile sorts a copy): the first build found the tolerance once per point and froze the browser on 527,633 points.
import type { StudyPalette } from "./study_palettes";
import type { StudyValues } from "./study_values_decoder";

/** The geometries a study can stand on the plot; the names of the service's columns. */
export type StudyGeometry = "max_volume" | "envelope" | "massing";
/** What a study stands on the plot (its setting "geometry"): nothing, or one of the geometries. */
export type StudyStand = "none" | StudyGeometry;
export const STUDY_STANDS: readonly StudyStand[] = ["none", "max_volume", "envelope", "massing"];

/** The column of the values without any geometry: the no-build case, and the column a study on nothing shows. */
export const OPEN_COLUMN = "open";

/** The column of the values a study on *stand* shows. */
export const columnOf = (stand: StudyStand): string => (stand === "none" ? OPEN_COLUMN : stand);

/**
 * How the values are coloured: by the value in the study's unit (the default, user 2026-10-28), or by each point's share of its
 * no-build value (its value with nothing built on the plot, the open column; the surroundings and terrain still block), one 0 to 100 %
 * scale for every geometry, which shows what the building takes away rather than the spread the surfaces' orientation gives the
 * values (roofs far above facades).
 */
export type ColourBy = "share" | "value";

/** The study the 3D view draws: its values with its geometry standing, by share or by value. */
export interface StudyView {
  values: StudyValues;
  /** The column of the values drawn: the study's geometry, or the open column for a study on nothing. */
  column: string;
  colourBy: ColourBy;
  /** The low and high ends of the colour range: percent of the no-build value by share, the study's unit by value. The palette runs
   * between them; a value below the low end takes its colour, above the high end the high end's colour. */
  range: [number, number];
  palette: StudyPalette;
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
  /** The sum of the values over the sum of the no-build values (0 to 1): what the geometry keeps of what the site gives with nothing
   * built; null when the no-build case gives nothing. */
  keptShare: number | null;
}

/** What *values* keep of the no-build values: their sum over the open column's (0 to 1); null when the open column sums to nothing. */
export function keptShareOf(values: Float32Array, open: Float32Array): number | null {
  let kept = 0, possible = 0;
  for (let point = 0; point < values.length; point++) {
    kept += values[point];
    possible += open[point];
  }
  return possible > 0 ? kept / possible : null;
}

/** A point's value as a share (0 to 1) of its no-build value. Where the no-build case gives it nothing (within *tolerance*) it loses
 * nothing, so its share is 1: it is drawn as fully kept rather than in a colour of its own (user, 2026-10-28). */
export function shareOfOpen(value: number, open: number, tolerance: number): number {
  return open > tolerance ? Math.min(1, Math.max(0, value / open)) : 1;
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

/** The highest value; 0 for no values (a scale from 0 to 0). */
export function highestOf(values: Float32Array): number {
  let highest = 0;
  for (let point = 0; point < values.length; point++) if (values[point] > highest) highest = values[point];
  return highest;
}

/** A no-build value smaller than this counts as none (shareOfOpen): a thousandth of the highest value of the open column. */
export function noBuildTolerance(open: Float32Array | undefined): number {
  return 1e-3 * Math.max(highestOf(open ?? new Float32Array(0)), 1e-9);
}

/** The groups of the points on a study's geometry by the way they face: roofs, and the facades by the compass point they face. */
export type FacingGroup = "roof" | "N" | "E" | "S" | "W";
export const FACING_GROUPS: readonly FacingGroup[] = ["roof", "N", "E", "S", "W"];
/** A point whose normal has an upward part above this faces up enough to count as a roof (about 45 degrees or flatter). */
export const ROOF_NORMAL_Z = 0.7;

/**
 * The indices of the points *from* to *to* (the points on the study's geometry, which the service puts last) in each facing group. A
 * point's normal is that of its patch (the cross product of its first three corners, which wind around the normal); a facade is
 * grouped by the azimuth of its normal from north (*northDegrees*, clockwise from +y, as the project's north), in 90 degree sectors
 * centred on N, E, S and W.
 */
export function facingGroups(quads: Float32Array, from: number, to: number, northDegrees: number): Record<FacingGroup, Uint32Array> {
  const members: Record<FacingGroup, number[]> = { roof: [], N: [], E: [], S: [], W: [] };
  const sectors: FacingGroup[] = ["N", "E", "S", "W"];
  for (let point = from; point < to; point++) {
    const at = point * 12;
    const ax = quads[at + 3] - quads[at], ay = quads[at + 4] - quads[at + 1], az = quads[at + 5] - quads[at + 2];
    const bx = quads[at + 6] - quads[at], by = quads[at + 7] - quads[at + 1], bz = quads[at + 8] - quads[at + 2];
    const nx = ay * bz - az * by, ny = az * bx - ax * bz, nz = ax * by - ay * bx;
    const length = Math.hypot(nx, ny, nz);
    if (length === 0) continue;
    if (nz / length > ROOF_NORMAL_Z) {
      members.roof.push(point);
      continue;
    }
    const azimuth = ((Math.atan2(nx, ny) * 180) / Math.PI - northDegrees + 360 + 45) % 360;
    members[sectors[Math.floor(azimuth / 90) % 4]].push(point);
  }
  return Object.fromEntries(FACING_GROUPS.map((group) => [group, Uint32Array.from(members[group])])) as Record<FacingGroup, Uint32Array>;
}

/** The values at *indices*. */
export function valuesAt(values: Float32Array, indices: Uint32Array): Float32Array {
  const picked = new Float32Array(indices.length);
  for (let index = 0; index < indices.length; index++) picked[index] = values[indices[index]];
  return picked;
}

// The geometry of a site (design/site-input.md) in the app: its outline in plan, its area and rise, and the reasons it cannot make a
// volume, the same as the engine's check_site (sites.py), so a refused site is caught before it is sent. Points are [x, y, z] in the
// input files' coordinates.
import { messages } from "../messages";

export type SitePoint = [number, number, number];

export interface Site {
  name: string;
  points: SitePoint[];
  height: number;
}

const SAME_POINT = 1e-6;    // m
export const MIN_SITE_AREA = 1;     // m²

/** The outline's vertices without a repeated last point or consecutive repeats. */
export function outlinePoints(points: readonly SitePoint[]): SitePoint[] {
  const same = (a: SitePoint, b: SitePoint) => Math.hypot(a[0] - b[0], a[1] - b[1]) < SAME_POINT;
  const kept: SitePoint[] = [];
  for (const point of points) if (kept.length === 0 || !same(point, kept[kept.length - 1])) kept.push(point);
  if (kept.length > 1 && same(kept[0], kept[kept.length - 1])) kept.pop();
  return kept;
}

/** The plan area of the outline (m²), whichever way round it runs. */
export function planArea(points: readonly SitePoint[]): number {
  let twice = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i], [x2, y2] = points[(i + 1) % points.length];
    twice += x1 * y2 - x2 * y1;
  }
  return Math.abs(twice) / 2;
}

/** The elevations of the lowest and highest vertex. */
export function elevationRange(points: readonly SitePoint[]): [number, number] {
  const z = points.map((point) => point[2]);
  return z.length ? [Math.min(...z), Math.max(...z)] : [0, 0];
}

/** How much higher the highest vertex is than the lowest. */
export function siteRise(points: readonly SitePoint[]): number {
  const [low, high] = elevationRange(points);
  return high - low;
}

function cross(ax: number, ay: number, bx: number, by: number): number {
  return ax * by - ay * bx;
}

/** Whether the segments p1-p2 and q1-q2 meet (in plan), touching included. */
export function segmentsMeet(p1: readonly number[], p2: readonly number[], q1: readonly number[], q2: readonly number[]): boolean {
  const d1 = cross(q2[0] - q1[0], q2[1] - q1[1], p1[0] - q1[0], p1[1] - q1[1]);
  const d2 = cross(q2[0] - q1[0], q2[1] - q1[1], p2[0] - q1[0], p2[1] - q1[1]);
  const d3 = cross(p2[0] - p1[0], p2[1] - p1[1], q1[0] - p1[0], q1[1] - p1[1]);
  const d4 = cross(p2[0] - p1[0], p2[1] - p1[1], q2[0] - p1[0], q2[1] - p1[1]);
  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) return true;
  const onSegment = (a: readonly number[], b: readonly number[], c: readonly number[], d: number) =>
    Math.abs(d) < 1e-12 && Math.min(a[0], b[0]) - 1e-12 <= c[0] && c[0] <= Math.max(a[0], b[0]) + 1e-12
    && Math.min(a[1], b[1]) - 1e-12 <= c[1] && c[1] <= Math.max(a[1], b[1]) + 1e-12;
  return onSegment(q1, q2, p1, d1) || onSegment(q1, q2, p2, d2) || onSegment(p1, p2, q1, d3) || onSegment(p1, p2, q2, d4);
}

/** Whether the closed outline crosses or touches itself (edges that are not neighbours meet). */
export function crossesItself(points: readonly SitePoint[]): boolean {
  const n = points.length;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue;          // neighbours share a vertex
      if (segmentsMeet(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n])) return true;
    }
  }
  return false;
}

/** The plain reasons the site cannot make a volume (as the engine gives them); empty when it can. */
export function siteProblems(site: Site): string[] {
  const points = outlinePoints(site.points);
  if (points.some((point) => point.some((value) => !Number.isFinite(value)))) return [messages.siteNoNumber];
  if (points.length < 3) return [messages.siteTooFewVertices];
  const problems: string[] = [];
  if (points.length > 3 && crossesItself(points)) problems.push(messages.siteCrossesItself);
  else if (planArea(points) < MIN_SITE_AREA) problems.push(messages.siteTooSmall(planArea(points)));
  if (!Number.isFinite(site.height) || site.height <= 0) problems.push(messages.siteHeightNotPositive);
  else if (site.height <= siteRise(points)) problems.push(messages.siteTooLow(siteRise(points)));
  return problems;
}

/** Whether the plan point lies inside the outline (even-odd rule). */
export function containsPoint(points: readonly SitePoint[], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i], [xj, yj] = points[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** The point at *t* (0 to 1) along the edge from *a* to *b*, its elevation interpolated. */
export function pointAlong(a: SitePoint, b: SitePoint, t: number): SitePoint {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/** "Site 3": the first "Site n" not taken. */
export function nextSiteName(sites: readonly Site[]): string {
  const taken = new Set(sites.map((site) => site.name));
  let number = sites.length + 1;
  while (taken.has(messages.siteName(number))) number += 1;
  return messages.siteName(number);
}

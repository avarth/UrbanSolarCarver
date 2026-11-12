// The geometry of a site (design/site-input.md) in the app: its outline in plan, its area and rise, and the reasons it cannot make a
// volume, the same as the engine's check_site (sites.py), so a refused site is caught before it is sent. Points are [x, y, z] in the
// input files' coordinates.
import { messages } from "../messages";

export type SitePoint = [number, number, number];

export interface Site {
  name: string;
  points: SitePoint[];
  /** The site's own max height, used while the max height is Per site. */
  height: number;
  /** The site's own base height (Per site); null or absent: no lower limit. */
  base_height?: number | null;
  /** Closed outlines strictly inside the outline where nothing is built (design/site-holes.md); absent or empty: none. */
  holes?: SitePoint[][];
  /** An imported site's outline (and holes) as imported, and its file (design/site-import.md); absent for a drawn site. */
  original?: { file: string; points: SitePoint[]; holes?: SitePoint[][] } | null;
}

/** The site's holes; none when it has none. */
export function holesOf(site: Pick<Site, "holes">): SitePoint[][] {
  return site.holes ?? [];
}

/** The site's rings: its outline first, then its holes. */
export function ringsOf(site: Pick<Site, "points" | "holes">): SitePoint[][] {
  return [site.points, ...holesOf(site)];
}

/** *site* with *rings* (the outline first, then the holes); without holes it carries no holes field, as a site without holes is stored. */
export function withRings(site: Site, rings: SitePoint[][]): Site {
  const { holes: _holes, ...rest } = site;
  return rings.length > 1 ? { ...rest, points: rings[0], holes: rings.slice(1) } : { ...rest, points: rings[0] };
}

/** Every vertex of the site, the outline's then the holes'. */
export function allPoints(site: Pick<Site, "points" | "holes">): SitePoint[] {
  return ringsOf(site).flat();
}

function samePoints(a: readonly SitePoint[], b: readonly SitePoint[]): boolean {
  return a.length === b.length && a.every((point, index) => point.every((value, axis) => Math.abs(value - b[index][axis]) <= 1e-9));
}

/** Two sites whose areas overlap in plan, by their indices; *inside*: the first lies wholly inside the second (design/site-holes.md). */
export interface SiteOverlap {
  first: number;
  second: number;
  inside: boolean;
}

/** Whether the site's outline or holes differ from those it was imported with (Restore original is then offered). */
export function differsFromOriginal(site: Site): boolean {
  const original = site.original;
  if (!original) return false;
  const originalHoles = original.holes ?? [], holes = holesOf(site);
  return !samePoints(original.points, site.points) || originalHoles.length !== holes.length
    || originalHoles.some((hole, index) => !samePoints(hole, holes[index]));
}

/** One of the two heights (design/base-height.md): the same for all sites (value, m), or each site's own. */
export interface HeightSetting {
  for_all_sites: boolean;
  value?: number | null;
}

/** The max height and the base height of the sites, as the service stores them. */
export interface Heights {
  max: HeightSetting;
  base: HeightSetting;
}

/** The heights of a project that has not set them: each site's own max height, no base height. */
export const NO_HEIGHTS: Heights = { max: { for_all_sites: false, value: null }, base: { for_all_sites: true, value: null } };

/** The heights a reply carries, with the defaults for a part it leaves out. */
export function heightsOf(reply: { max?: HeightSetting; base?: HeightSetting }): Heights {
  return { max: reply.max ?? NO_HEIGHTS.max, base: reply.base ?? NO_HEIGHTS.base };
}

/** The site's max height: the project's while it is one for all sites, else its own. */
export function maxHeightOf(site: Site, heights: Heights): number {
  return heights.max.for_all_sites && typeof heights.max.value === "number" ? heights.max.value : site.height;
}

/** The site's base height: the project's while it is one for all sites, else its own; null for no lower limit. */
export function baseHeightOf(site: Site, heights: Heights): number | null {
  const value = heights.base.for_all_sites ? heights.base.value : site.base_height;
  return typeof value === "number" && value > 0 ? value : null;      // 0 is no lower limit, as none is
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

/** The site's area in plan (m²): its outline's less its holes'. */
export function siteArea(site: Pick<Site, "points" | "holes">): number {
  return planArea(outlinePoints(site.points)) - holesOf(site).reduce((sum, hole) => sum + planArea(outlinePoints(hole)), 0);
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

/** The plain reasons the site cannot make a volume (as the engine gives them, and the service for a base height); empty when it can.
 * With *heights*, the site's max and base heights are the ones they give it. */
export function siteProblems(site: Site, heights?: Heights): string[] {
  if (heights !== undefined) {
    const problems = siteProblems({ ...site, height: maxHeightOf(site, heights) });
    const base = baseHeightOf(site, heights), top = maxHeightOf(site, heights);
    if (base !== null && base >= top) problems.push(messages.siteBaseNotBelowMax(base, top));
    return problems;
  }
  const points = outlinePoints(site.points);
  const holes = holesOf(site).map((hole) => outlinePoints(hole));
  if ([points, ...holes].some((ring) => ring.some((point) => point.some((value) => !Number.isFinite(value))))) return [messages.siteNoNumber];
  if (points.length < 3) return [messages.siteTooFewVertices];
  const problems: string[] = [];
  if (points.length > 3 && crossesItself(points)) problems.push(messages.siteCrossesItself);
  else {
    const holeProblems = holeProblemsOf(points, holes);
    problems.push(...holeProblems);
    const area = holeProblems.length ? planArea(points) : siteArea({ points, holes });
    if (area < MIN_SITE_AREA) problems.push(messages.siteTooSmall(area));
  }
  const rise = siteRise([...points, ...holes.flat()]);
  if (!Number.isFinite(site.height) || site.height <= 0) problems.push(messages.siteHeightNotPositive);
  else if (site.height <= rise) problems.push(messages.siteTooLow(rise));
  return problems;
}

/** Why the holes do not fit the outline, as the engine says it: each needs 3 vertices, must not cross itself, needs 1 m², must lie
 * strictly inside the outline and must not touch or cross another hole. Holes are numbered from 1. */
function holeProblemsOf(outline: SitePoint[], holes: SitePoint[][]): string[] {
  const problems: string[] = [];
  const fitting: { number: number; ring: SitePoint[] }[] = [];
  holes.forEach((hole, index) => {
    const number = index + 1;
    if (hole.length < 3) problems.push(messages.holeTooFewVertices(number));
    else if (hole.length > 3 && crossesItself(hole)) problems.push(messages.holeCrossesItself(number));
    else if (planArea(hole) < MIN_SITE_AREA) problems.push(messages.holeTooSmall(number, planArea(hole)));
    else if (!ringInside(hole, outline)) problems.push(messages.holeNotInside(number));
    else fitting.push({ number, ring: hole });
  });
  fitting.forEach((hole, index) => {
    for (const other of fitting.slice(index + 1)) if (ringsMeet(hole.ring, other.ring)) problems.push(messages.holesTouch(hole.number, other.number));
  });
  return problems;
}

/** Whether an edge of ring *a* meets (crosses or touches) an edge of ring *b*, in plan. */
function edgesMeet(a: readonly SitePoint[], b: readonly SitePoint[]): boolean {
  for (let i = 0; i < a.length; i++) {
    for (let j = 0; j < b.length; j++) {
      if (segmentsMeet(a[i], a[(i + 1) % a.length], b[j], b[(j + 1) % b.length])) return true;
    }
  }
  return false;
}

/** Whether the closed ring *inner* lies strictly inside the closed ring *outer* in plan: no edges meet (touching is not inside) and
 * its vertices are inside. */
export function ringInside(inner: readonly SitePoint[], outer: readonly SitePoint[]): boolean {
  if (inner.length === 0 || outer.length < 3 || edgesMeet(inner, outer)) return false;
  return inner.every((point) => containsPoint(outer, point[0], point[1]));
}

/** Whether two closed rings share any part in plan: their edges meet, or one lies inside the other. */
export function ringsMeet(a: readonly SitePoint[], b: readonly SitePoint[]): boolean {
  if (edgesMeet(a, b)) return true;
  return (a.length > 0 && containsPoint(b, a[0][0], a[0][1])) || (b.length > 0 && containsPoint(a, b[0][0], b[0][1]));
}

/**
 * What a closed outline drawn in the view becomes (design/site-holes.md): a hole of the site whose area holds it wholly (strictly
 * inside its outline, and clear of its holes), the smallest such site when there are several; else, drawn inside a hole, partly over a
 * site or over no site, a new site. Returns the index of the site it is a hole of, or null for a new site.
 */
export function siteHoleIsDrawnIn(sites: readonly Site[], drawn: readonly SitePoint[]): number | null {
  const ring = outlinePoints(drawn);
  let found: { index: number; area: number } | null = null;
  sites.forEach((site, index) => {
    const outline = outlinePoints(site.points);
    if (!ringInside(ring, outline) || holesOf(site).some((hole) => ringsMeet(ring, outlinePoints(hole)))) return;
    const area = planArea(outline);
    if (found === null || area < found.area) found = { index, area };
  });
  return (found as { index: number } | null)?.index ?? null;
}

/** Whether the plan point lies in the site's area: inside its outline and outside its holes. */
export function siteAreaContains(site: Pick<Site, "points" | "holes">, x: number, y: number): boolean {
  return containsPoint(site.points, x, y) && !holesOf(site).some((hole) => containsPoint(hole, x, y));
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

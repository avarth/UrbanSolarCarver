// Drawing a site outline (design/site-input.md), without the view: where the next point goes for a pointer position. The pointer
// snaps to the first point (to close the outline) and to the vertices and edges of the other sites, within SNAP_PIXELS on the
// screen; Shift holds the new segment at a multiple of ANGLE_STEP_DEGREES from the previous one (from the x axis for the second
// point). Points are in plan, in the input files' coordinates; *toScreen* gives a point's place on the screen in pixels.
import type { SitePoint } from "./site_geometry";

export const SNAP_PIXELS = 10;
export const ANGLE_STEP_DEGREES = 15;

export type ScreenPoint = [number, number];
export type ToScreen = (point: SitePoint) => ScreenPoint | null;

export type SnapKind = "first_point" | "vertex" | "edge" | "angle" | null;

export interface PlacedPoint {
  point: SitePoint;
  snap: SnapKind;
}

function screenDistance(a: ScreenPoint, b: ScreenPoint): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** The nearest point of the segment a-b to p, and how far along it (0 to 1), in the plane of a and b's first two coordinates. */
export function nearestOnSegment(a: readonly number[], b: readonly number[], p: readonly number[]): { t: number; point: [number, number] } {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.min(1, Math.max(0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lengthSquared));
  return { t, point: [a[0] + t * dx, a[1] + t * dy] };
}

/** *target* turned about *last* to the nearest multiple of the angle step from the previous segment (*before* to *last*), or from the
 *  x axis without one; its distance from *last* kept. */
export function constrainedToAngle(before: SitePoint | null, last: SitePoint, target: SitePoint): SitePoint {
  const length = Math.hypot(target[0] - last[0], target[1] - last[1]);
  if (length === 0) return target;
  const base = before === null ? 0 : Math.atan2(last[1] - before[1], last[0] - before[0]);
  const step = (ANGLE_STEP_DEGREES * Math.PI) / 180;
  const angle = Math.atan2(target[1] - last[1], target[0] - last[0]);
  const snapped = base + Math.round((angle - base) / step) * step;
  return [last[0] + length * Math.cos(snapped), last[1] + length * Math.sin(snapped), target[2]];
}

/**
 * Where a click at *pointer* (on the screen) puts the next point of the outline *drawn* so far, *ground* being the pointer on the
 * drawing level. In order: the first point (closes the outline, from 3 points), a vertex of another site, an edge of another site,
 * then with *shift* the angle step, else the ground point itself.
 */
export function placePoint(drawn: readonly SitePoint[], ground: SitePoint, pointer: ScreenPoint, otherOutlines: readonly SitePoint[][],
                           toScreen: ToScreen, shift: boolean): PlacedPoint {
  if (drawn.length >= 3) {
    const first = toScreen(drawn[0]);
    if (first && screenDistance(first, pointer) <= SNAP_PIXELS) return { point: drawn[0], snap: "first_point" };
  }
  let nearestVertex: { point: SitePoint; distance: number } | null = null;
  for (const outline of otherOutlines) {
    for (const vertex of outline) {
      const onScreen = toScreen(vertex);
      if (!onScreen) continue;
      const distance = screenDistance(onScreen, pointer);
      if (distance <= SNAP_PIXELS && (!nearestVertex || distance < nearestVertex.distance)) nearestVertex = { point: [vertex[0], vertex[1], ground[2]], distance };
    }
  }
  if (nearestVertex) return { point: nearestVertex.point, snap: "vertex" };
  let nearestEdge: { point: SitePoint; distance: number } | null = null;
  for (const outline of otherOutlines) {
    for (let i = 0; i < outline.length; i++) {
      const a = outline[i], b = outline[(i + 1) % outline.length];
      const aScreen = toScreen(a), bScreen = toScreen(b);
      if (!aScreen || !bScreen) continue;
      const { t, point } = nearestOnSegment(aScreen, bScreen, pointer);
      const distance = screenDistance(point, pointer);
      if (distance <= SNAP_PIXELS && (!nearestEdge || distance < nearestEdge.distance)) {
        nearestEdge = { point: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, ground[2]], distance };
      }
    }
  }
  if (nearestEdge) return { point: nearestEdge.point, snap: "edge" };
  if (shift && drawn.length > 0) {
    const last = drawn[drawn.length - 1];
    return { point: constrainedToAngle(drawn.length > 1 ? drawn[drawn.length - 2] : null, last, ground), snap: "angle" };
  }
  return { point: ground, snap: null };
}

/** How an outline is drawn: point by point, a rectangle along the x and y axes from two opposite corners, or a rectangle at any
 *  angle from a first side (two clicks) and its width (a third click). */
export type DrawShape = "polygon" | "rectangle" | "tilted_rectangle";

/** The clicks that finish a rectangle; a polygon is finished on its first point or with Enter. */
export const CLICKS_TO_FINISH: Record<Exclude<DrawShape, "polygon">, number> = { rectangle: 2, tilted_rectangle: 3 };

/** Corners closer than this (in metres) to a line give no rectangle. */
const MIN_SIDE = 0.001;

function toMillimetre(value: number): number {
  return Math.round(value * 1000) / 1000 + 0;
}

/**
 * The outline a rectangle shape makes from its clicks (in plan, at the first click's level, corners to the millimetre), in the order
 * drawn; null for a polygon, for too few clicks, or for a rectangle with no area. Rectangle: the first corner, then along x to the
 * second's x, the second corner, then back along x. Tilted rectangle: the first side from the first two clicks, then the side square to
 * it as far as the third click lies from the first side's line, on the third click's side.
 */
export function shapeOutline(shape: DrawShape, clicks: readonly SitePoint[]): SitePoint[] | null {
  if (shape === "polygon" || clicks.length < CLICKS_TO_FINISH[shape]) return null;
  const [a, b] = clicks;
  const z = a[2];
  const at = (x: number, y: number): SitePoint => [toMillimetre(x), toMillimetre(y), z];
  if (shape === "rectangle") {
    if (Math.abs(b[0] - a[0]) < MIN_SIDE || Math.abs(b[1] - a[1]) < MIN_SIDE) return null;
    return [at(a[0], a[1]), at(b[0], a[1]), at(b[0], b[1]), at(a[0], b[1])];
  }
  const c = clicks[2];
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (length < MIN_SIDE) return null;
  const normal = [-(b[1] - a[1]) / length, (b[0] - a[0]) / length];
  const width = (c[0] - a[0]) * normal[0] + (c[1] - a[1]) * normal[1];
  if (Math.abs(width) < MIN_SIDE) return null;
  const dx = normal[0] * width, dy = normal[1] * width;
  return [at(a[0], a[1]), at(b[0], b[1]), at(b[0] + dx, b[1] + dy), at(a[0] + dx, a[1] + dy)];
}

/**
 * Where a click at *pointer* puts the next point of a *shape* with *clicks* so far. A polygon's as placePoint says; a rectangle's
 * corners and a tilted rectangle's width point snap to the other outlines only; a tilted rectangle's second point also takes Shift's
 * angle steps from the x axis.
 */
export function placeShapePoint(shape: DrawShape, clicks: readonly SitePoint[], ground: SitePoint, pointer: ScreenPoint,
                                otherOutlines: readonly SitePoint[][], toScreen: ToScreen, shift: boolean): PlacedPoint {
  if (shape === "polygon") return placePoint(clicks, ground, pointer, otherOutlines, toScreen, shift);
  if (shape === "tilted_rectangle" && clicks.length === 1) return placePoint(clicks, ground, pointer, otherOutlines, toScreen, shift);
  return placePoint([], ground, pointer, otherOutlines, toScreen, false);
}

/** The drawing level, in the files' coordinates: the lowest vertex of the sites; for a first site the lowest level of the existing
 *  surroundings and terrain when there are any, else 0. */
export function drawingLevel(outlines: readonly SitePoint[][], surroundingsLowestZ: number | null): number {
  const z = outlines.flat().map((point) => point[2]);
  if (z.length) return Math.min(...z);
  return surroundingsLowestZ ?? 0;
}

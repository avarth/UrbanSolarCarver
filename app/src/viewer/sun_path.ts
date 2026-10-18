// The sun path layer's content (UX 8.2): for each day of GET sun-path, the whole day's path (drawn dashed), the analysis hours on
// it (drawn solid, 3 px) and a sun with an "<hour> h" label at each marker, all placed on the hemisphere around the model.
import type { SunPath } from "../api_client/client";
import { dayAndMonth, listedWithAnd, messages } from "../messages";
import type { Point3 } from "./local_origin";
import type { Hemisphere } from "./sky_dome";

export interface SunPathLine {
  kind: "day_path" | "period_path";
  runs: Point3[][];       // unbroken stretches of the curve
}

export interface SunPathMarker {
  hour: number;
  label: string;
  position: Point3;
}

export interface SunPathObjects {
  lines: SunPathLine[];
  markers: SunPathMarker[];
}

// The engine samples the period path at a fixed time step, and the sun crosses the sky at a constant angular speed over a day,
// so neighbouring samples are one angular step apart. A gap of more than this many steps is a jump between two stretches of the
// period (a period over midnight lists its early hours first, then its evening hours).
const LONGEST_UNBROKEN_GAP_IN_STEPS = 1.5;

function onHemisphere(vector: ArrayLike<number>, sphere: Hemisphere): Point3 {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  return [0, 1, 2].map((axis) => sphere.centre[axis] + (sphere.radius * vector[axis]) / length) as Point3;
}

function angleBetween(first: ArrayLike<number>, second: ArrayLike<number>): number {
  const dot = first[0] * second[0] + first[1] * second[1] + first[2] * second[2];
  return Math.acos(Math.max(-1, Math.min(1, dot / (Math.hypot(first[0], first[1], first[2]) * Math.hypot(second[0], second[1], second[2])))));
}

function median(values: number[]): number {
  const sorted = [...values].sort((first, second) => first - second);
  return sorted[Math.floor(sorted.length / 2)];
}

/** The samples split where neighbours are more than one sampling step apart. */
function unbrokenRuns(vectors: number[][]): number[][][] {
  if (vectors.length < 3) return vectors.length ? [vectors] : [];
  const steps = vectors.slice(1).map((vector, index) => angleBetween(vectors[index], vector));
  const largestStep = LONGEST_UNBROKEN_GAP_IN_STEPS * median(steps);
  const runs: number[][][] = [[vectors[0]]];
  steps.forEach((step, index) => {
    if (step > largestStep) runs.push([]);
    runs[runs.length - 1].push(vectors[index + 1]);
  });
  return runs;
}

export function sunPathObjects(sunPath: SunPath, sphere: Hemisphere): SunPathObjects {
  const lines: SunPathLine[] = [];
  const markers: SunPathMarker[] = [];
  for (const day of sunPath.days) {
    lines.push({ kind: "day_path", runs: day.day_path.length ? [day.day_path.map((vector) => onHemisphere(vector, sphere))] : [] });
    lines.push({ kind: "period_path", runs: unbrokenRuns(day.period_path).map((run) => run.map((vector) => onHemisphere(vector, sphere))) });
    for (const marker of day.markers) markers.push({ hour: marker.hour, label: messages.hourLabel(marker.hour), position: onHemisphere(marker.vector, sphere) });
  }
  return { lines, markers };
}

/** "Sun path, 21 Dec; sun at 10, 12 and 14 h": the days and the hours that have a sun on any of them. */
export function sunPathLegend(sunPath: SunPath): string {
  const days = sunPath.days.map((day) => dayAndMonth(day.date));
  const hours = [...new Set(sunPath.days.flatMap((day) => day.markers.map((marker) => marker.hour)))];
  return messages.sunPathLegend(listedWithAnd(days), listedWithAnd(hours.map(String)));
}

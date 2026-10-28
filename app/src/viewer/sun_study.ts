// Simulate's sun tool on the 3D view: what the sun_study layer draws of the year's sun path (GET sun-chart) and of the sun at the
// chosen time, placed on the hemisphere around the scene, and the numbers the shadows and the hours in shade are worked out from.
import type { SunChart } from "../api_client/client";
import { messages } from "../messages";
import type { Point3 } from "./local_origin";
import type { Hemisphere } from "./sky_dome";

export interface SunHourLineObject {
  hour: number;
  label: string;
  runs: Point3[][];
  /** Where the hour's label goes: the line's highest point. */
  labelAt: Point3;
}

export interface SunStudyObjects {
  keyDays: Point3[][];
  hourLines: SunHourLineObject[];
  day: Point3[][];
  /** The sun at the chosen time; null below the horizon. */
  sun: Point3 | null;
}

/** The sun, *the shadows* it casts at that time, and the hours in shade over a range, as Simulate's sun tool asks for them. */
export interface ShadeHours {
  /** Unit vectors toward the sun at the times of the range (above the horizon). */
  directions: Point3[];
  /** The hours each direction stands for, divided by the number of days sampled: the sum over the shaded ones is hours per day. */
  hoursEach: number;
  /** The length of the daily range in hours, the top of the colour scale. */
  maxHours: number;
}

export function onHemisphere(vector: ArrayLike<number>, sphere: Hemisphere): Point3 {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  return [0, 1, 2].map((axis) => sphere.centre[axis] + (sphere.radius * vector[axis]) / length) as Point3;
}

/** The lines and the sun of *chart* and *sun* (a vector toward the sun, or null) on *sphere*. */
export function sunStudyObjects(chart: SunChart, sun: ArrayLike<number> | null, sphere: Hemisphere): SunStudyObjects {
  const placed = (runs: number[][][]) => runs.map((run) => run.map((vector) => onHemisphere(vector, sphere)));
  return {
    keyDays: chart.key_days.flatMap((day) => placed(day.runs)),
    hourLines: chart.hour_lines.map((line) => {
      const runs = placed(line.runs);
      const labelAt = runs.flat().reduce((highest, point) => (point[2] > highest[2] ? point : highest));
      return { hour: line.hour, label: messages.hourLabel(line.hour), runs, labelAt };
    }),
    day: placed(chart.day.runs),
    sun: sun === null ? null : onHemisphere(sun, sphere),
  };
}

/** The direction toward the sun at the time nearest *minute* among *positions* of one day, within *tolerance* minutes; else null. */
export function sunAt<Position extends { minute: number; vector: number[] }>(positions: readonly Position[], minute: number, tolerance: number): Position | null {
  let nearest: Position | null = null;
  for (const position of positions) {
    if (Math.abs(position.minute - minute) <= tolerance && (nearest === null || Math.abs(position.minute - minute) < Math.abs(nearest.minute - minute))) nearest = position;
  }
  return nearest;
}

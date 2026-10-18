import { expect, test } from "vitest";
import { axisScreenDirections, northNeedleScreenAngle } from "./compass";
import { compassRingMarks } from "./compass_ring";
import type { Point3 } from "./local_origin";

const SPHERE = { centre: [20, 10, -1] as Point3, radius: 60 };

function letterAt(northDegrees: number, letter: string): Point3 {
  return compassRingMarks(SPHERE, northDegrees).letters.find((mark) => mark.letter === letter)!.position;
}

/** The screen angle, clockwise from up, of a point on the ground seen from the centre in a view turned by *yawDegrees*. */
function screenAngleFromCentre(point: Point3, yawDegrees: number): number {
  const directions = axisScreenDirections(yawDegrees, 90);
  const dx = point[0] - SPHERE.centre[0], dy = point[1] - SPHERE.centre[1];
  const right = dx * directions.x[0] + dy * directions.y[0], up = dx * directions.x[1] + dy * directions.y[1];
  return (((Math.atan2(right, up) * 180) / Math.PI) % 360 + 360) % 360;
}

test("the compass ring has a tick every 10 degrees, long ones every 90 degrees, on the ground at the scene's lowest z", () => {
  const { ticks, letters } = compassRingMarks(SPHERE, 0);
  expect(ticks).toHaveLength(36);
  expect(ticks.filter((tick) => tick.long).map((tick) => tick.azimuthDegrees)).toEqual([0, 90, 180, 270]);
  expect(letters.map((mark) => mark.letter)).toEqual(["N", "E", "S", "W"]);
  for (const tick of ticks) {
    expect(Math.hypot(tick.outer[0] - SPHERE.centre[0], tick.outer[1] - SPHERE.centre[1])).toBeCloseTo(SPHERE.radius);
    expect(tick.outer[2]).toBe(-1);
  }
  const longTick = ticks.find((tick) => tick.long)!, shortTick = ticks.find((tick) => !tick.long)!;
  const length = (tick: typeof longTick) => Math.hypot(tick.outer[0] - tick.inner[0], tick.outer[1] - tick.inner[1]);
  expect(length(longTick)).toBeGreaterThan(length(shortTick));
});

test("the compass ring turns with North direction: N toward +Y at 0 degrees, toward +X at 90 degrees", () => {
  const northAtZero = letterAt(0, "N"), northAtNinety = letterAt(90, "N");
  expect(northAtZero[0]).toBeCloseTo(SPHERE.centre[0]); expect(northAtZero[1]).toBeGreaterThan(SPHERE.centre[1] + SPHERE.radius);
  expect(northAtNinety[1]).toBeCloseTo(SPHERE.centre[1]); expect(northAtNinety[0]).toBeGreaterThan(SPHERE.centre[0] + SPHERE.radius);
  const eastAtNinety = letterAt(90, "E");
  expect(eastAtNinety[0]).toBeCloseTo(SPHERE.centre[0]); expect(eastAtNinety[1]).toBeLessThan(SPHERE.centre[1]);   // east turned to -Y
  expect(compassRingMarks(SPHERE, 30).ticks.filter((tick) => tick.long).map((tick) => tick.azimuthDegrees)).toEqual([30, 120, 210, 300]);
});

test("the ring's N and the compass overlay's needle point the same way on screen, for any north and camera turn", () => {
  for (const [northDegrees, yawDegrees] of [[0, 0], [30, 0], [30, 50], [275, 120], [-40, 300]]) {
    expect(screenAngleFromCentre(letterAt(northDegrees, "N"), yawDegrees)).toBeCloseTo(northNeedleScreenAngle(yawDegrees, northDegrees));
  }
});

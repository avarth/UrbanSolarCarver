import { expect, test } from "vitest";
import { hemisphere, skyPatchOutline, skyPatchShares } from "./sky_dome";

function towards(altitudeDegrees: number, azimuthDegrees: number): [number, number, number] {
  const altitude = (altitudeDegrees * Math.PI) / 180, azimuth = (azimuthDegrees * Math.PI) / 180;
  return [Math.cos(altitude) * Math.sin(azimuth), Math.cos(altitude) * Math.cos(azimuth), Math.sin(altitude)];
}

test("hemisphere is 1.5 times the larger horizontal side", () => {
  expect(hemisphere([[0, 0, 2], [40, 30, 35]])).toEqual({centre: [20, 15, 2], radius: 60});
});

test("a sky patch spans its Tregenza band and its share of the band's azimuth", () => {
  const nearHorizon = skyPatchOutline(towards(6, 0));
  expect(nearHorizon.altitudeRange).toEqual([0, 12]);
  expect(nearHorizon.azimuthRange[0]).toBeCloseTo(-6); expect(nearHorizon.azimuthRange[1]).toBeCloseTo(6);   // 30 patches in the band
  const sixthBand = skyPatchOutline(towards(66, 45));
  expect(sixthBand.altitudeRange).toEqual([60, 72]);
  expect(sixthBand.azimuthRange[1] - sixthBand.azimuthRange[0]).toBeCloseTo(30);   // 12 patches
  expect(skyPatchOutline(towards(90, 0)).altitudeRange).toEqual([84, 90]);       // the zenith cap
});

test("sky patch colours run from the smallest weight to the largest", () => {
  expect(skyPatchShares([2, 4, 6])).toEqual([0, 0.5, 1]);
  expect(skyPatchShares([3, 3])).toEqual([0, 0]);
});

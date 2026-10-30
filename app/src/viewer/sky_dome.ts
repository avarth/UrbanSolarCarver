// The hemisphere the sun path, the sky dome and the compass ring are drawn on (UX 8.2, R2 2), and the outline of each of the 145
// Tregenza sky patches.
import type { Bounds3, Point3 } from "./local_origin";

export interface Hemisphere {
  centre: Point3;
  radius: number;
}

const HEMISPHERE_RADIUS_SHARE = 0.75;
const DEGREES = 180 / Math.PI;

/**
 * The hemisphere around the whole scene: *sceneBounds* are the bounds of the maximum volume and the test surfaces together.
 * Centred on their footprint centre at their lowest z, radius 0.75 times their larger horizontal side: just more than half the
 * diagonal of a square footprint, so the rim encloses the footprint without dwarfing it.
 */
export function sceneHemisphere(sceneBounds: Bounds3): Hemisphere {
  const [low, high] = sceneBounds;
  return {
    centre: [(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]],
    radius: HEMISPHERE_RADIUS_SHARE * Math.max(high[0] - low[0], high[1] - low[1]),
  };
}

// The Tregenza sky: seven 12 degree bands from the horizon with these patch counts, and a cap from 84 degrees to the zenith.
const BAND_HEIGHT_DEGREES = 12;
const PATCHES_PER_BAND = [30, 30, 24, 24, 18, 12, 6];
const ZENITH_CAP_ALTITUDE_DEGREES = BAND_HEIGHT_DEGREES * PATCHES_PER_BAND.length;

export interface SkyPatchOutline {
  altitudeRange: [number, number];      // degrees above the horizon
  azimuthRange: [number, number];       // degrees clockwise from +Y; [0, 360] for the zenith cap
}

/** The patch around a patch centre direction: its band, and its share of the band's azimuth centred on the direction. */
export function skyPatchOutline(direction: ArrayLike<number>): SkyPatchOutline {
  const length = Math.hypot(direction[0], direction[1], direction[2]);
  const altitude = Math.asin(Math.min(1, direction[2] / length)) * DEGREES;
  const band = Math.floor(altitude / BAND_HEIGHT_DEGREES);
  if (band >= PATCHES_PER_BAND.length) return { altitudeRange: [ZENITH_CAP_ALTITUDE_DEGREES, 90], azimuthRange: [0, 360] };
  const azimuth = Math.atan2(direction[0], direction[1]) * DEGREES;
  const halfWidth = 180 / PATCHES_PER_BAND[band];
  return { altitudeRange: [band * BAND_HEIGHT_DEGREES, (band + 1) * BAND_HEIGHT_DEGREES], azimuthRange: [azimuth - halfWidth, azimuth + halfWidth] };
}

/** Each patch weight as a share of the way from the smallest weight to the largest (0 for all when they are equal). */
export function skyPatchShares(weights: number[]): number[] {
  const smallest = Math.min(...weights), largest = Math.max(...weights);
  return weights.map((weight) => (largest > smallest ? (weight - smallest) / (largest - smallest) : 0));
}

/** A point on the hemisphere at an altitude and an azimuth (degrees clockwise from +Y). */
export function pointOnHemisphere(sphere: Hemisphere, altitudeDegrees: number, azimuthDegrees: number): Point3 {
  const altitude = altitudeDegrees / DEGREES, azimuth = azimuthDegrees / DEGREES;
  return [
    sphere.centre[0] + sphere.radius * Math.cos(altitude) * Math.sin(azimuth),
    sphere.centre[1] + sphere.radius * Math.cos(altitude) * Math.cos(azimuth),
    sphere.centre[2] + sphere.radius * Math.sin(altitude),
  ];
}

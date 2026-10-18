// The local origin of the 3D view (technical spec 7): every object is shifted by the minimum corner of the maximum volume,
// in float64, before its coordinates are written into a Float32Array. Georeferenced coordinates (500 000, 4 200 000) have a
// float32 step of 0.5 m; after the shift the numbers are small and keep millimetres.

export type Point3 = [number, number, number];
export type Bounds3 = [Point3, Point3];

/** The minimum corner of the bounds. */
export function localOrigin(bounds: Bounds3): Point3 {
  return [bounds[0][0], bounds[0][1], bounds[0][2]];
}

/** A point in coordinates relative to the local origin. */
export function toLocal(point: ArrayLike<number>, origin: Point3): Point3 {
  return [point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]];
}

/** Bounds in coordinates relative to the local origin. */
export function localBounds(bounds: Bounds3, origin: Point3): Bounds3 {
  return [toLocal(bounds[0], origin), toLocal(bounds[1], origin)];
}

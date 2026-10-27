// Reading the geometry of a test surfaces file as the service packs it (local_web_service/inspection, GET
// inspect/test_surfaces/{file}/geometry), all numbers little-endian: uint32 header length n; the header as UTF-8 JSON padded with
// spaces to a multiple of 4; float32 the three corners of each triangle (x, y, z each, relative to the header's frame); uint32 the
// surface number of each triangle.
import { toLocal, type Point3 } from "../viewer/local_origin";

export interface InspectSurface {
  centre: Point3;             // relative to the header's frame
  normal: Point3;
  area: number;
}

export interface InspectGeometryHeader {
  frame: Point3;              // world coordinates the corners and centres are relative to
  triangle_count: number;
  surface_count: number;
  surfaces: InspectSurface[];
}

export interface InspectGeometry {
  header: InspectGeometryHeader;
  corners: Float32Array;               // triangle_count * 3 corners * 3
  surfaceOfTriangle: Uint32Array;      // the surface number of each triangle
}

const LENGTH_FIELD_BYTES = 4;
const FLOAT_BYTES = 4;
const TRIANGLE_FLOATS = 9;

export function decodeInspectGeometry(buffer: ArrayBuffer): InspectGeometry {
  const headerLength = new DataView(buffer).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, LENGTH_FIELD_BYTES, headerLength))) as InspectGeometryHeader;
  const count = header.triangle_count;
  let offset = LENGTH_FIELD_BYTES + headerLength;       // a multiple of 4: the header is padded
  const corners = new Float32Array(buffer, offset, count * TRIANGLE_FLOATS);
  offset += count * TRIANGLE_FLOATS * FLOAT_BYTES;
  const surfaceOfTriangle = new Uint32Array(buffer, offset, count);
  return { header, corners, surfaceOfTriangle };
}

/** The corners of each triangle, relative to the scene's local origin. */
export function localCorners(geometry: InspectGeometry, origin: Point3): Float32Array {
  const shift = toLocal(geometry.header.frame, origin);       // float64 here, so the float32 positions are small numbers
  const { corners } = geometry;
  const local = new Float32Array(corners.length);
  for (let value = 0; value < corners.length; value += 3) {
    local[value] = corners[value] + shift[0];
    local[value + 1] = corners[value + 1] + shift[1];
    local[value + 2] = corners[value + 2] + shift[2];
  }
  return local;
}

/** Each surface with its centre relative to the scene's local origin (the normal and area as they are). */
export function localSurfaces(geometry: InspectGeometry, origin: Point3): InspectSurface[] {
  const shift = toLocal(geometry.header.frame, origin);
  return geometry.header.surfaces.map(({ centre, normal, area }) => ({
    centre: [centre[0] + shift[0], centre[1] + shift[1], centre[2] + shift[2]], normal, area,
  }));
}

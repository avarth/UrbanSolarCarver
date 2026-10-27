import { expect, test } from "vitest";
import { decodeInspectGeometry, localCorners, localSurfaces } from "./inspect_geometry_decoder";

/** The service's packing (local_web_service/inspection): uint32 header length; the header as JSON padded with spaces to a multiple of 4;
 *  float32 the corners of each triangle; uint32 the surface number of each triangle. */
function packedGeometry(header: object, corners: number[], surfaceOfTriangle: number[]): ArrayBuffer {
  let headerText = JSON.stringify(header);
  headerText += " ".repeat((4 - (headerText.length % 4)) % 4);
  const headerBytes = new TextEncoder().encode(headerText);
  const buffer = new ArrayBuffer(4 + headerBytes.length + corners.length * 4 + surfaceOfTriangle.length * 4);
  new DataView(buffer).setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  new Float32Array(buffer, 4 + headerBytes.length, corners.length).set(corners);
  new Uint32Array(buffer, 4 + headerBytes.length + corners.length * 4, surfaceOfTriangle.length).set(surfaceOfTriangle);
  return buffer;
}

const FRAME = [4500000, 0, 0];
const CORNERS = [0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0, 5, 3, 0, 5, 2, 1, 5];
const SURFACES = [
  { centre: [0.25, 0.25, 0], normal: [0, 0, 1], area: 0.5 },
  { centre: [2.25, 0.25, 5], normal: [0, 0, -1], area: 0.5 },
];

const geometryBuffer = () => packedGeometry({ frame: FRAME, triangle_count: 2, surface_count: 2, surfaces: SURFACES }, CORNERS, [0, 1]);

test("decodeInspectGeometry reads the header, corners and surface numbers", () => {
  const decoded = decodeInspectGeometry(geometryBuffer());
  expect(decoded.header).toEqual({ frame: FRAME, triangle_count: 2, surface_count: 2, surfaces: SURFACES });
  expect(Array.from(decoded.corners)).toEqual(CORNERS);
  expect(Array.from(decoded.surfaceOfTriangle)).toEqual([0, 1]);
});

test("localCorners moves the corners from the frame into the local origin", () => {
  const decoded = decodeInspectGeometry(geometryBuffer());
  expect(Array.from(localCorners(decoded, [4500000, 0, 0]))).toEqual(CORNERS);       // the origin at the frame: the raw corners
  const shifted = localCorners(decoded, [4500000, -10, 2]);
  expect(shifted).toHaveLength(18);
  expect(Array.from(shifted.slice(0, 3))).toEqual([0, 10, -2]);
  expect(Array.from(shifted.slice(9, 12))).toEqual([2, 10, 3]);
});

test("localSurfaces moves each surface's centre the same way, leaving the normal and area", () => {
  const decoded = decodeInspectGeometry(geometryBuffer());
  expect(localSurfaces(decoded, [4500000, 0, 0])).toEqual(SURFACES);
  expect(localSurfaces(decoded, [4499990, 1, -2])).toEqual([
    { centre: [10.25, -0.75, 2], normal: [0, 0, 1], area: 0.5 },
    { centre: [12.25, -0.75, 7], normal: [0, 0, -1], area: 0.5 },
  ]);
});

test("a file without triangles decodes to empty arrays", () => {
  const decoded = decodeInspectGeometry(packedGeometry({ frame: [0, 0, 0], triangle_count: 0, surface_count: 0, surfaces: [] }, [], []));
  expect(decoded.corners).toHaveLength(0);
  expect(decoded.surfaceOfTriangle).toHaveLength(0);
  expect(localCorners(decoded, [1, 2, 3])).toHaveLength(0);
  expect(localSurfaces(decoded, [1, 2, 3])).toEqual([]);
});

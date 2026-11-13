// Reading the per-point values of a study's last result as the service packs them (local_web_service/simulation.study_values,
// GET studies/{id}/values), all numbers little-endian: uint32 header length n; the header as UTF-8 JSON padded with spaces to a
// multiple of 4; float32 the four corners of each point's patch (x, y, z each, relative to the header's frame); float32 one value
// per point for each column, in the header's order. The patches are left out (header quads false) when the page asked with the
// points key of patches it holds: they are then taken from those.
import { toLocal, type Point3 } from "./local_origin";

export interface StudyValuesHeader {
  frame: Point3;              // world coordinates the corners are relative to
  point_count: number;
  columns: string[];          // "open", then the study's geometry ("max_volume", "envelope" or "massing") unless it stands nothing
  unit: string;
  geometry?: string;                  // the geometry the result accounts for: "none", "max_volume", "envelope" or "massing"
  geometry_point_count?: number;      // how many of the points, the last ones, are on the faces of that geometry
  sun_day_step?: number;              // a quick sun hours result counted the sun on every that many days; 1 otherwise
  points_key?: string | null;         // what the points were made from; null for a result that does not record it
  quads?: boolean;                    // whether the patches follow the header (absent: they do)
}

/** Patches the page holds, with the points key they came with. */
export interface HeldPatches {
  pointsKey: string;
  quads: Float32Array;
}

/** The reply left the patches out, but the patches held are not those of its points (or none are held): ask again without a key. */
export class MissingPatchesError extends Error {}

export interface StudyValues {
  header: StudyValuesHeader;
  quads: Float32Array;        // point_count * 4 corners * 3
  values: Record<string, Float32Array>;
}

const LENGTH_FIELD_BYTES = 4;
const FLOAT_BYTES = 4;
const QUAD_FLOATS = 12;

export function decodeStudyValues(buffer: ArrayBuffer, held?: HeldPatches): StudyValues {
  const headerLength = new DataView(buffer).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, LENGTH_FIELD_BYTES, headerLength))) as StudyValuesHeader;
  const count = header.point_count;
  let offset = LENGTH_FIELD_BYTES + headerLength;       // a multiple of 4: the header is padded
  let quads: Float32Array;
  if (header.quads === false) {
    if (held === undefined || held.pointsKey !== header.points_key || held.quads.length !== count * QUAD_FLOATS) throw new MissingPatchesError();
    quads = held.quads;
  } else {
    quads = new Float32Array(buffer, offset, count * QUAD_FLOATS);
    offset += count * QUAD_FLOATS * FLOAT_BYTES;
  }
  const values: Record<string, Float32Array> = {};
  for (const column of header.columns) {
    values[column] = new Float32Array(buffer, offset, count);
    offset += count * FLOAT_BYTES;
  }
  return { header, quads, values };
}

/** The four corners of each point's patch (in order around it), relative to the scene's local origin. */
export function patchCorners(studyValues: StudyValues, origin: Point3): Float32Array {
  const shift = toLocal(studyValues.header.frame, origin);       // float64 here, so the float32 positions are small numbers
  const { quads } = studyValues;
  const corners = new Float32Array(quads.length);
  for (let value = 0; value < quads.length; value += 3) {
    corners[value] = quads[value] + shift[0];
    corners[value + 1] = quads[value + 1] + shift[1];
    corners[value + 2] = quads[value + 2] + shift[2];
  }
  return corners;
}

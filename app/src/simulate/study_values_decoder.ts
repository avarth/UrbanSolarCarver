// Reading the per-point values of a study's last result as the service packs them (local_web_service/simulation.study_values,
// GET studies/{id}/values), all numbers little-endian: uint32 header length n; the header as UTF-8 JSON padded with spaces to a
// multiple of 4; float32 the four corners of each point's patch (x, y, z each, relative to the header's frame); float32 one value
// per point for each column, in the header's order.
import { toLocal, type Point3 } from "../viewer/local_origin";

export interface StudyValuesHeader {
  frame: Point3;              // world coordinates the corners are relative to
  point_count: number;
  columns: string[];          // "open", "max_volume", then "envelope" and "massing" when they were built
  unit: string;
}

export interface StudyValues {
  header: StudyValuesHeader;
  quads: Float32Array;        // point_count * 4 corners * 3
  values: Record<string, Float32Array>;
}

const LENGTH_FIELD_BYTES = 4;
const FLOAT_BYTES = 4;
const QUAD_FLOATS = 12;

export function decodeStudyValues(buffer: ArrayBuffer): StudyValues {
  const headerLength = new DataView(buffer).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, LENGTH_FIELD_BYTES, headerLength))) as StudyValuesHeader;
  const count = header.point_count;
  let offset = LENGTH_FIELD_BYTES + headerLength;       // a multiple of 4: the header is padded
  const quads = new Float32Array(buffer, offset, count * QUAD_FLOATS);
  offset += count * QUAD_FLOATS * FLOAT_BYTES;
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

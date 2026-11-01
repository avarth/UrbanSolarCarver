// Packed study values for tests, as local_web_service/simulation.study_values packs them: shared by the decoder's test and the
// workspace's (the fake service answers GET studies/{id}/values with one).

/** uint32 header length; the header as JSON padded with spaces to a multiple of 4; float32 the quads, then each column. */
export function packedStudyValues(header: object, quads: number[], columns: number[][]): ArrayBuffer {
  let headerText = JSON.stringify(header);
  headerText += " ".repeat((4 - (headerText.length % 4)) % 4);
  const headerBytes = new TextEncoder().encode(headerText);
  const floats = [...quads, ...columns.flat()];
  const buffer = new ArrayBuffer(4 + headerBytes.length + floats.length * 4);
  new DataView(buffer).setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  new Float32Array(buffer, 4 + headerBytes.length).set(floats);
  return buffer;
}

/** One unit square patch per point along x, at height 0 in a frame at the origin, with *columns* by name (each one value per point). */
export function studyValuesOf(columns: Record<string, number[]>, unit = "h"): ArrayBuffer {
  const names = Object.keys(columns);
  const count = columns[names[0]].length;
  const quads = Array.from({ length: count }, (_, point) => [point, 0, 0, point + 1, 0, 0, point + 1, 1, 0, point, 1, 0]).flat();
  return packedStudyValues({ frame: [0, 0, 0], point_count: count, columns: names, unit }, quads, names.map((name) => columns[name]));
}

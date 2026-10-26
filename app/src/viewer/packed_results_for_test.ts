// The binary layers of the service, packed in tests the way local_web_service/score_points.py packs them: a uint32 header length,
// the JSON header padded with spaces to a multiple of 4, then the arrays.
import type { ScorePointsHeader } from "./score_points_decoder";

const HEADER_ALIGNMENT_BYTES = 4;

function paddedHeader(header: object): Uint8Array {
  const text = JSON.stringify(header);
  const unpaddedLength = new TextEncoder().encode(text).length;
  return new TextEncoder().encode(text + " ".repeat((HEADER_ALIGNMENT_BYTES - (unpaddedLength % HEADER_ALIGNMENT_BYTES)) % HEADER_ALIGNMENT_BYTES));
}

/** The carved-by-criterion layer: one byte per voxel of the grid in C order, 0 for a kept or empty voxel, k for the k-th id of *criterionIds*. */
export function packCarvedByCriterion(shape: [number, number, number], criterionIds: string[], carvedBy: number[],
                                      origin: [number, number, number] = [0, 0, 0], voxelSize = 1): ArrayBuffer {
  const headerBytes = paddedHeader({ origin, shape, voxel_size: voxelSize, criterion_ids: criterionIds });
  const buffer = new ArrayBuffer(4 + headerBytes.length + carvedBy.length);
  new DataView(buffer).setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  new Uint8Array(buffer, 4 + headerBytes.length).set(carvedBy);
  return buffer;
}

/** Score points of a carving: the flat indices of the occupied voxels, their scores and whether each was kept. */
export function packScorePoints(indices: number[], kept: number[], overrides: Partial<ScorePointsHeader> = {}): ArrayBuffer {
  const header: ScorePointsHeader = {
    origin: [0, 0, 0], shape: [2, 2, 1], voxel_size: 1, mode: "time-based", scores_kind: "violation_count", weight_unit: "none (sun positions, no sky patches)",
    score_unit: "m²·h", score_min: 0, score_max: 3, compared_score_max: 3, occupied_count: indices.length, point_count: indices.length, thinning_step: 1,
    has_mask: true, has_compared_scores: false, ...overrides,
  };
  const headerBytes = paddedHeader(header);
  const count = indices.length;
  const buffer = new ArrayBuffer(4 + headerBytes.length + 8 * count + count);
  const view = new DataView(buffer);
  view.setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  let offset = 4 + headerBytes.length;
  for (const index of indices) { view.setUint32(offset, index, true); offset += 4; }
  for (let point = 0; point < count; point++) { view.setFloat32(offset, point + 0.5, true); offset += 4; }
  for (const flag of kept) { view.setUint8(offset, flag); offset += 1; }
  return buffer;
}

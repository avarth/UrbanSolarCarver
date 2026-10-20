import { expect, test } from "vitest";
import { decodeScorePoints, voxelCentres, type ScorePointsHeader } from "./score_points_decoder";

const HEADER_ALIGNMENT_BYTES = 4;

/** The layout of the service's score_points.py, written the same way: a JSON header padded with spaces to 4 bytes, then the arrays. */
function packScorePoints(header: ScorePointsHeader, indices: number[], scores: number[], kept: number[] | null, compared: number[] | null): ArrayBuffer {
  const unpaddedLength = new TextEncoder().encode(JSON.stringify(header)).length;     // UTF-8 bytes: the unit has two-byte characters
  const headerBytes = new TextEncoder().encode(JSON.stringify(header) + " ".repeat((HEADER_ALIGNMENT_BYTES - (unpaddedLength % HEADER_ALIGNMENT_BYTES)) % HEADER_ALIGNMENT_BYTES));
  const count = indices.length;
  const totalBytes = 4 + headerBytes.length + 8 * count + (kept ? count : 0) + (compared ? 4 * count : 0);
  const buffer = new ArrayBuffer(totalBytes);
  const view = new DataView(buffer);
  view.setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  let offset = 4 + headerBytes.length;
  for (const index of indices) { view.setUint32(offset, index, true); offset += 4; }
  for (const score of scores) { view.setFloat32(offset, score, true); offset += 4; }
  for (const flag of kept ?? []) { view.setUint8(offset, flag); offset += 1; }
  for (const score of compared ?? []) { view.setFloat32(offset, score, true); offset += 4; }
  return buffer;
}

function header(overrides: Partial<ScorePointsHeader> = {}): ScorePointsHeader {
  return {
    origin: [100, 200, 0], shape: [4, 3, 2], voxel_size: 0.5, mode: "time-based", scores_kind: "violation_count", weight_unit: "none (sun positions, no sky patches)", score_unit: "m²·h",
    score_min: 0, score_max: 3, compared_score_max: 3, occupied_count: 3, point_count: 3, thinning_step: 1, has_mask: true, has_compared_scores: true, ...overrides,
  };
}

test("score points decode to the header's counts, compared scores included", () => {
  const decoded = decodeScorePoints(packScorePoints(header(), [0, 7, 23], [0.5, 1.5, 3], [1, 0, 1], [0.25, 0.75, 1.5]));
  expect(decoded.header.point_count).toBe(3);
  for (const values of [decoded.indices, decoded.scores, decoded.kept!, decoded.comparedScores!]) expect(values).toHaveLength(3);
  expect(Array.from(decoded.indices)).toEqual([0, 7, 23]);
  expect(Array.from(decoded.scores)).toEqual([0.5, 1.5, 3]);
  expect(Array.from(decoded.kept!)).toEqual([1, 0, 1]);
  expect(Array.from(decoded.comparedScores!)).toEqual([0.25, 0.75, 1.5]);   // starts 3 bytes after a 4-byte boundary
});

test("without thresholding output the mask and the compared scores are null", () => {
  const decoded = decodeScorePoints(packScorePoints(header({ has_mask: false, has_compared_scores: false }), [1, 2, 3], [1, 2, 3], null, null));
  expect(decoded.kept).toBeNull();
  expect(decoded.comparedScores).toBeNull();
  expect(Array.from(decoded.scores)).toEqual([1, 2, 3]);
});

test("voxel centres come from the flat index in C order, shifted by the local origin", () => {
  // shape (4, 3, 2): index 23 is i = 3, j = 2, k = 1; index 7 is i = 1, j = 0, k = 1
  const centres = voxelCentres(header(), Uint32Array.from([0, 7, 23]), [99, 199, 0]);
  expect(Array.from(centres)).toEqual([1.25, 1.25, 0.25, 1.75, 1.25, 0.75, 2.75, 2.25, 0.75]);
});

// Reading the score layer the service packs (local_web_service/score_points.py), all numbers little-endian:
// uint32 header length n; the header as UTF-8 JSON padded with spaces to a multiple of 4; uint32 flat indices; float32 raw
// scores; uint8 kept flags (when has_mask); float32 compared scores (when has_compared_scores).
import { toLocal, type Point3 } from "./local_origin";

export interface ScorePointsHeader {
  origin: Point3;                 // world coordinates of the grid's minimum corner
  shape: [number, number, number];
  voxel_size: number;
  scores_kind: "weighted_sum" | "violation_count";
  weight_unit: string;
  score_min: number | null;       // of all occupied voxels, not only the points sent
  score_max: number | null;
  occupied_count: number;
  point_count: number;
  thinning_step: number;          // 1 when every occupied voxel is sent
  has_mask: boolean;
  has_compared_scores: boolean;
}

export interface ScorePoints {
  header: ScorePointsHeader;
  indices: Uint32Array;
  scores: Float32Array;
  kept: Uint8Array | null;
  comparedScores: Float32Array | null;
}

const LENGTH_FIELD_BYTES = 4;
const FOUR_BYTE_VALUE = 4;

export function decodeScorePoints(buffer: ArrayBuffer): ScorePoints {
  const headerLength = new DataView(buffer).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, LENGTH_FIELD_BYTES, headerLength))) as ScorePointsHeader;
  const count = header.point_count;
  let offset = LENGTH_FIELD_BYTES + headerLength;      // a multiple of 4: the header is padded
  const indices = new Uint32Array(buffer, offset, count);
  offset += count * FOUR_BYTE_VALUE;
  const scores = new Float32Array(buffer, offset, count);
  offset += count * FOUR_BYTE_VALUE;
  let kept: Uint8Array | null = null;
  if (header.has_mask) {
    kept = new Uint8Array(buffer, offset, count);
    offset += count;
  }
  // After the unpadded kept flags the offset need not be a multiple of 4, which a Float32Array view requires: copy the bytes.
  const comparedScores = header.has_compared_scores ? new Float32Array(buffer.slice(offset, offset + count * FOUR_BYTE_VALUE)) : null;
  return { header, indices, scores, kept, comparedScores };
}

/** The centre of each indexed voxel relative to the local origin, as x, y, z triples: header.origin + (ijk + 0.5) * voxel_size. */
export function voxelCentres(header: ScorePointsHeader, indices: Uint32Array, origin: Point3): Float32Array {
  const [, rowCount, layerCount] = header.shape;
  const size = header.voxel_size;
  const gridCorner = toLocal(header.origin, origin);      // float64 here, so the float32 centres are small numbers
  const centres = new Float32Array(indices.length * 3);
  for (let point = 0; point < indices.length; point++) {
    const flatIndex = indices[point];
    const k = flatIndex % layerCount;
    const j = Math.floor(flatIndex / layerCount) % rowCount;
    const i = Math.floor(flatIndex / (layerCount * rowCount));
    centres[point * 3] = gridCorner[0] + (i + 0.5) * size;
    centres[point * 3 + 1] = gridCorner[1] + (j + 0.5) * size;
    centres[point * 3 + 2] = gridCorner[2] + (k + 0.5) * size;
  }
  return centres;
}

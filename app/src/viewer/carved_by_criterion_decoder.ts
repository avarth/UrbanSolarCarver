// Reading the carved-by-criterion layer the service packs (local_web_service/score_points.py build_carved_by_criterion): uint32 header
// length n; the header as UTF-8 JSON padded with spaces to a multiple of 4 ({origin, shape, voxel_size, criterion_ids}); then one uint8 per
// voxel of the grid in C order: 0 for a voxel the last criterion that is on kept (or that was never occupied), k for a voxel removed by the
// k-th id of criterion_ids.
import type { Point3 } from "./local_origin";
import { voxelCentres } from "./score_points_decoder";

export interface CarvedByCriterion {
  origin: Point3;                   // world coordinates of the grid's minimum corner
  shape: [number, number, number];
  voxelSize: number;
  criterionIds: string[];           // the criteria that are on, in chain order
  carvedBy: Uint8Array;             // per voxel in C order
}

interface CarvedByCriterionHeader {
  origin: Point3;
  shape: [number, number, number];
  voxel_size: number;
  criterion_ids: string[];
}

const LENGTH_FIELD_BYTES = 4;

export function decodeCarvedByCriterion(buffer: ArrayBuffer): CarvedByCriterion {
  const headerLength = new DataView(buffer).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, LENGTH_FIELD_BYTES, headerLength))) as CarvedByCriterionHeader;
  const voxelCount = header.shape[0] * header.shape[1] * header.shape[2];
  return {
    origin: header.origin, shape: header.shape, voxelSize: header.voxel_size, criterionIds: header.criterion_ids,
    carvedBy: new Uint8Array(buffer, LENGTH_FIELD_BYTES + headerLength, voxelCount),
  };
}

export interface CarvedVoxels {
  centres: Float32Array;            // x, y, z per carved voxel, local coordinates
  criterionIndex: Uint8Array;       // per carved voxel: the position of its criterion in criterionIds
}

/** The voxels some criterion removed, with their centres relative to the local origin (as the score points' voxels are placed). */
export function carvedVoxelsByCriterion(data: CarvedByCriterion, origin: Point3): CarvedVoxels {
  const flatIndices: number[] = [];
  const criterionIndex: number[] = [];
  data.carvedBy.forEach((criterion, flatIndex) => {
    if (criterion === 0) return;
    flatIndices.push(flatIndex);
    criterionIndex.push(criterion - 1);
  });
  const centres = voxelCentres({ origin: data.origin, shape: data.shape, voxel_size: data.voxelSize }, Uint32Array.from(flatIndices), origin);
  return { centres, criterionIndex: Uint8Array.from(criterionIndex) };
}

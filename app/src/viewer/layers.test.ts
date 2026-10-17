import { expect, test } from "vitest";
import * as THREE from "three";
import { buildingMassingLayer, carvedOutlineSegments, keptColumnTops, splitScorePoints, storeyOfPart } from "./layers";
import type { ScorePoints } from "./score_points_decoder";

function scorePoints(indices: number[], scores: number[], kept: number[] | null): ScorePoints {
  return {
    header: { origin: [0, 0, 0], shape: [2, 2, 3], voxel_size: 1, scores_kind: "violation_count", weight_unit: "m²·h", score_min: 0, score_max: 9,
              occupied_count: indices.length, point_count: indices.length, thinning_step: 1, has_mask: kept !== null, has_compared_scores: false },
    indices: Uint32Array.from(indices), scores: Float32Array.from(scores), kept: kept && Uint8Array.from(kept), comparedScores: null,
  };
}

test("score points split into kept and carved voxels by the mask", () => {
  const points = scorePoints([0, 1, 2], [1, 5, 9], [1, 1, 0]);
  const centres = Float32Array.from([0.5, 0.5, 0.5, 0.5, 0.5, 1.5, 0.5, 0.5, 2.5]);
  const { kept, carved } = splitScorePoints(points, centres);
  expect(Array.from(kept.scores)).toEqual([1, 5]);
  expect(Array.from(kept.centres)).toEqual([0.5, 0.5, 0.5, 0.5, 0.5, 1.5]);
  expect(Array.from(carved.centres)).toEqual([0.5, 0.5, 2.5]);
});

test("without a mask every voxel is drawn as kept", () => {
  const { kept, carved } = splitScorePoints(scorePoints([0, 1], [1, 2], null), new Float32Array(6));
  expect(kept.scores).toHaveLength(2);
  expect(carved.scores).toHaveLength(0);
});

test("the kept top of a column is the top face of its highest kept voxel, the grid bottom without one", () => {
  // shape (2, 2, 3): column (0, 0) keeps layers 0 and 1; column (1, 1) keeps nothing
  const points = scorePoints([0, 1, 2, 9, 10], [0, 0, 0, 0, 0], [1, 1, 0, 0, 0]);
  const keptTopAt = keptColumnTops(points, [0, 0, 0]);
  expect(keptTopAt(0.5, 0.5)).toBe(2);
  expect(keptTopAt(1, 1)).toBe(2);           // a point within half a voxel of column (0, 0) takes the highest of those columns
  expect(keptTopAt(1.9, 1.9)).toBe(0);
});

test("the carved outline keeps the maximum volume's edges above the kept voxels", () => {
  const keptTopAt = (x: number) => (x < 5 ? 10 : 0);
  const edges = Float32Array.from([
    0, 0, 0, 0, 0, 30,          // vertical edge over kept voxels 10 m high: drawn from 10 m
    8, 0, 0, 8, 0, 30,          // vertical edge where everything was carved: drawn whole
    0, 0, 30, 8, 0, 30,         // top edge: drawn
    0, 0, 0, 4, 0, 0,           // bottom edge under kept voxels: left out
  ]);
  expect(Array.from(carvedOutlineSegments(edges, keptTopAt))).toEqual([0, 0, 10, 0, 0, 30, 8, 0, 0, 8, 0, 30, 0, 0, 30, 8, 0, 30]);
});

test("the storey of a building massing part comes from its name", () => {
  expect(storeyOfPart("floor_3_plate_1")).toBe(3);
  expect(storeyOfPart("something_else")).toBeNull();
});

test("a building massing without storeys has none", () => {
  const empty = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([], 3));
  empty.userData.partNames = [];
  expect(buildingMassingLayer(empty).userData.storeyCount).toBe(0);
});

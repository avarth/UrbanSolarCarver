import { expect, test } from "vitest";
import * as THREE from "three";
import { buildingMassingLayer, carvedOutlineSegments, keptColumnTops, pointSizeForVoxel, splitScorePoints, storeyOfPart, volumeOutline } from "./layers";
import type { ScorePoints } from "./score_points_decoder";

function scorePoints(indices: number[], scores: number[], kept: number[] | null): ScorePoints {
  return {
    header: { origin: [0, 0, 0], shape: [2, 2, 3], voxel_size: 1, mode: "time-based", scores_kind: "violation_count", weight_unit: "m²·h", score_unit: "m²·h", score_min: 0, score_max: 9, compared_score_max: 9,
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

// A box 10 by 10 m and 20 m high on the ground: four vertical edges at its corners, four top and four bottom edges.
function boxOutline() {
  return volumeOutline(new THREE.BoxGeometry(10, 10, 20).translate(5, 5, 10));
}

function segmentsOf(values: Float32Array): number[][] {
  return Array.from({ length: values.length / 6 }, (_, segment) => Array.from(values.subarray(segment * 6, segment * 6 + 6)));
}

test("the outline knows the outward horizontal normal of each vertical edge", () => {
  const outline = boxOutline();
  const verticals = segmentsOf(outline.segments).map((segment, index) => ({ segment, normal: Array.from(outline.outwardNormals.subarray(index * 2, index * 2 + 2)) }))
    .filter(({ segment }) => segment[0] === segment[3] && segment[1] === segment[4]);
  expect(verticals).toHaveLength(4);
  const southWest = verticals.find(({ segment }) => segment[0] === 0 && segment[1] === 0)!;
  expect(southWest.normal[0]).toBeCloseTo(-Math.SQRT1_2); expect(southWest.normal[1]).toBeCloseTo(-Math.SQRT1_2);
});

test("the carved outline keeps the top edges and the vertical edges facing the camera, from the kept top up", () => {
  const keptTopAt = (x: number) => (x < 5 ? 8 : 0);
  const drawn = segmentsOf(carvedOutlineSegments(boxOutline(), keptTopAt, [-50, 5]));      // camera to the west
  const verticals = drawn.filter((segment) => segment[0] === segment[3] && segment[1] === segment[4]);
  expect(verticals.map((segment) => [segment[0], segment[1], Math.min(segment[2], segment[5]), Math.max(segment[2], segment[5])]).sort())
    .toEqual([[0, 0, 8, 20], [0, 10, 8, 20]]);         // the two west corners; the east ones are at the back
  const others = drawn.filter((segment) => !(segment[0] === segment[3] && segment[1] === segment[4]));
  expect(others).toHaveLength(4);
  expect(others.every((segment) => segment[2] === 20 && segment[5] === 20)).toBe(true);
});

test("over a fully carved column the vertical edge is drawn from the ground and the bottom edges are not", () => {
  const drawn = segmentsOf(carvedOutlineSegments(boxOutline(), () => 0, [-50, -50]));     // camera to the south-west
  const verticals = drawn.filter((segment) => segment[0] === segment[3] && segment[1] === segment[4]);
  expect(verticals).toHaveLength(1);
  expect([Math.min(verticals[0][2], verticals[0][5]), Math.max(verticals[0][2], verticals[0][5])]).toEqual([0, 20]);
  expect(drawn.some((segment) => segment[2] === 0 && segment[5] === 0)).toBe(false);
});

test("a voxel drawn as a point is as wide as the voxel on screen", () => {
  const voxelSize = 2, fieldOfViewDegrees = 35, viewHeightPixels = 800, depth = 50;
  const pointPixels = (pointSizeForVoxel(voxelSize, fieldOfViewDegrees) * viewHeightPixels / 2) / depth;       // three.js size attenuation
  const voxelPixels = (voxelSize * viewHeightPixels) / (2 * depth * Math.tan((fieldOfViewDegrees * Math.PI) / 360));
  expect(pointPixels).toBeCloseTo(voxelPixels);
});

test("the building massing edges follow the viewport theme", () => {
  document.documentElement.style.setProperty("--colour-ink", "#1f2a30");
  document.documentElement.style.setProperty("--colour-ink-on-dark", "#e6ecee");
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  geometry.userData.partNames = [];
  const massing = buildingMassingLayer(geometry);
  massing.userData.applyTheme("dark");
  const edges = massing.children.find((child) => child instanceof THREE.LineSegments) as THREE.LineSegments;
  expect(`#${(edges.material as THREE.LineBasicMaterial).color.getHexString()}`).toBe("#e6ecee");
  document.documentElement.removeAttribute("style");
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

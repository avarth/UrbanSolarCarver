import { expect, test } from "vitest";
import * as THREE from "three";
import {
  buildingMassingLayer, carvedByCriterionLayer, carvedOutlineSegments, contextLayer, LAYER_NAMES, maxVolumeLayer, terrainLayer, keptColumnTops, pointSizeForVoxel, splitScorePoints,
  storeyOfPart, studyValuesLayer, testSurfacesLayer, volumeOutline,
} from "./layers";
import { decodeStudyValues, patchCorners } from "../simulate/study_values_decoder";
import { studyValuesOf } from "../simulate/study_values_for_test";
import { changeRamp, cividis } from "./colour_scales";
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

test("the existing surroundings and the terrain are layers of their own, listed after the test surfaces", () => {
  expect(LAYER_NAMES.slice(0, 4)).toEqual(["max_volume", "test_surfaces", "context", "terrain"]);
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  expect(contextLayer(geometry.clone())).toBeInstanceOf(THREE.Object3D);
  expect(terrainLayer(geometry.clone())).toBeInstanceOf(THREE.Object3D);
});

test("the carved-by-criterion layer comes right after the carved voxels", () => {
  expect(LAYER_NAMES[LAYER_NAMES.indexOf("carved_voxels") + 1]).toBe("carved_by_criterion");
});

test("the carved-by-criterion layer draws each voxel in the colour of the criterion that removed it", () => {
  const layer = carvedByCriterionLayer({
    voxels: { centres: Float32Array.from([0.5, 0.5, 0.5, 1.5, 0.5, 0.5, 2.5, 0.5, 0.5]), criterionIndex: Uint8Array.from([0, 1, 0]), carvedCount: 3, thinningStep: 1 },
    colours: ["#4477aa", "#228833"], voxelSize: 1,
  }) as THREE.InstancedMesh;
  const colourOf = (voxel: number) => {
    const colour = new THREE.Color();
    layer.getColorAt(voxel, colour);
    return colour.getHexString();
  };
  expect(layer.count).toBe(3);
  expect([0, 1, 2].map(colourOf)).toEqual([new THREE.Color("#4477aa"), new THREE.Color("#228833"), new THREE.Color("#4477aa")].map((colour) => colour.getHexString()));
});

test("the carved-by-criterion layer of a grid where nothing was carved is empty", () => {
  const layer = carvedByCriterionLayer({ voxels: { centres: new Float32Array(0), criterionIndex: new Uint8Array(0), carvedCount: 0, thinningStep: 1 }, colours: ["#4477aa"], voxelSize: 1 });
  expect(layer.children).toHaveLength(0);
});

test("the test surfaces layer has one mesh per part in the part's colour, all at full strength; a part without a colour takes the accent, which follows the theme", () => {
  const surfaces = () => new THREE.BoxGeometry(1, 1, 0.1);
  document.documentElement.style.setProperty("--colour-accent", "#0000ff");        // jsdom has no theme tokens
  document.documentElement.style.setProperty("--colour-test-surface-on-dark", "#00ffff");
  const layer = testSurfacesLayer([{ name: "1", colour: "#4477aa", geometry: surfaces() }, { name: "2", colour: "#228833", geometry: surfaces() },
                                   { name: "3", colour: null, geometry: surfaces() }]);
  const materialOf = (name: string) => (layer.getObjectByName(name) as THREE.Mesh).material as THREE.MeshLambertMaterial;
  expect(layer.children.map((child) => child.name)).toEqual(["1", "2", "3"]);
  expect(["1", "2", "3"].map((name) => materialOf(name).opacity)).toEqual([1, 1, 1]);
  expect(["1", "2"].map((name) => materialOf(name).color.getHexString())).toEqual(["4477aa", "228833"]);
  expect(materialOf("3").color.getHexString()).toBe("0000ff");
  layer.userData.applyTheme("dark");
  expect(["1", "2"].map((name) => materialOf(name).color.getHexString())).toEqual(["4477aa", "228833"]);      // a criterion's colour stays
  expect(materialOf("3").color.getHexString()).toBe("00ffff");
  expect(testSurfacesLayer([]).children).toHaveLength(0);
});

test("test surfaces are drawn in front of a context or maximum volume face they lie on, instead of flickering through it", () => {
  const geometry = () => new THREE.BoxGeometry(1, 1, 1);
  const surfaces = (testSurfacesLayer([{ name: "1", colour: "#4477aa", geometry: geometry() }]).children[0] as THREE.Mesh).material as THREE.Material;
  const context = (contextLayer(geometry()).children[0] as THREE.Mesh).material as THREE.Material;
  const maxVolume = (maxVolumeLayer(geometry(), "solid").children[0] as THREE.Mesh).material as THREE.Material;
  expect(surfaces.polygonOffset).toBe(true);
  for (const other of [context, maxVolume]) {
    expect(surfaces.polygonOffsetFactor).toBeLessThan(other.polygonOffsetFactor);
    expect(surfaces.polygonOffsetUnits).toBeLessThan(other.polygonOffsetUnits);
  }
  expect(surfaces.polygonOffsetFactor).toBeLessThan(0);      // toward the camera, not only less far back
});

// The study values of Simulate --------------------------------------------------------------------------------------------------

function studyView(change: boolean, target: number | null) {
  const values = decodeStudyValues(studyValuesOf({ open: [4, 4, 4, 4], max_volume: [1, 1, 1, 1], envelope: [0, 2, 4, 1.0005] }));
  return { view: { values, geometry: "envelope" as const, change, target, unit: "h", dimmed: false }, corners: patchCorners(values, [0, 0, 0]) };
}

function setColourTokens() {
  for (const [name, colour] of [["context", "#b9c1c4"], ["carved", "#c8553d"], ["storey-low", "#dfe6ea"], ["accent", "#2f5d7c"]]) {
    document.documentElement.style.setProperty(`--colour-${name}`, colour);       // jsdom has no theme tokens
  }
}

/** The colour of each point's patch, as "rrggbb" (all four corners of a patch have it). */
function patchColours(layer: THREE.Object3D): string[] {
  const colours = (layer as THREE.Mesh).geometry.getAttribute("color");
  return Array.from({ length: colours.count / 4 }, (_, point) => {
    const corners = [0, 1, 2, 3].map((corner) => new THREE.Color().fromBufferAttribute(colours as THREE.BufferAttribute, point * 4 + corner).getHexString());
    expect(new Set(corners).size).toBe(1);
    return corners[0];
  });
}

const hexOf = (colour: string) => new THREE.Color(colour).getHexString();

test("the study values layer colours each point's patch by its value, cividis from 0 to the highest, below the target muted", () => {
  setColourTokens();
  const { view, corners } = studyView(false, 1.5);
  const layer = studyValuesLayer(view, corners);
  expect(LAYER_NAMES).toContain("study_values");
  const geometry = (layer as THREE.Mesh).geometry;
  expect(geometry.getAttribute("position").count).toBe(4 * 4);
  expect(Array.from(geometry.index!.array.slice(0, 6))).toEqual([0, 1, 2, 0, 2, 3]);
  expect(patchColours(layer)).toEqual([hexOf("#b9c1c4"), hexOf(cividis(0.5)), hexOf(cividis(1)), hexOf("#b9c1c4")]);
  expect(patchColours(studyValuesLayer({ ...view, target: null }, corners))[0]).toBe(hexOf(cividis(0)));
  expect(layer.userData.summary).toBe("4 points");
});

test("with Change the layer colours the change from the maximum volume on the change ramp, losses in the carved colour", () => {
  setColourTokens();
  const { view, corners } = studyView(true, 3);
  // Changes -1, 1, 3 and 0.0005: a loss, a third of the largest gain, the largest gain, and less than the tolerance (0.004), none.
  expect(patchColours(studyValuesLayer(view, corners))).toEqual([hexOf("#c8553d"), hexOf(changeRamp(1 / 3)), hexOf("#2f5d7c"), hexOf("#dfe6ea")]);
});

test("study values are drawn in front of the test surfaces they lie on, unlit, and leave the corners they are given as they are", () => {
  setColourTokens();
  const { view, corners } = studyView(false, null);
  const before = Float32Array.from(corners);
  const layer = studyValuesLayer(view, corners) as THREE.Mesh;
  const material = layer.material as THREE.MeshBasicMaterial;
  expect(material).toBeInstanceOf(THREE.MeshBasicMaterial);
  expect([material.polygonOffset, material.polygonOffsetFactor, material.polygonOffsetUnits]).toEqual([true, -2, -8]);
  expect(material.side).toBe(THREE.DoubleSide);
  expect(Array.from(corners)).toEqual(Array.from(before));
});

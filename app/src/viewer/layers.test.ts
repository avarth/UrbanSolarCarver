import { expect, test } from "vitest";
import * as THREE from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import {
  applyLayerAppearance, buildingMassingLayer, carvedByCriterionLayer, carvedOutlineSegments, contextLayer, inspectSurfacesLayer, LAYER_NAMES, maxVolumeLayer, terrainLayer,
  keptColumnTops, pointSizeForVoxel, splitScorePoints, type InspectLayerFile,
  storeyOfPart, studyValuesLayer, testSurfacesLayer, volumeOutline,
} from "./layers";
import { decodeStudyValues, patchCorners } from "../simulate/study_values_decoder";
import { studyValuesOf } from "../simulate/study_values_for_test";
import { changeRamp, colourToken, viridis } from "./colour_scales";
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

function studyView(change: boolean, target: number | null, colourBy: "share" | "value" = "value") {
  const values = decodeStudyValues(studyValuesOf({ open: [4, 4, 4, 4], max_volume: [1, 1, 1, 1], envelope: [0, 2, 4, 1.0005] }));
  return { view: { values, geometry: "envelope" as const, change, colourBy, target, unit: "h", dimmed: false }, corners: patchCorners(values, [0, 0, 0]) };
}

const BELOW_TARGET = "#8e7b88", BELOW_TARGET_ON_DARK = "#6e5f6a", CONTEXT = "#b9c1c4", TERRAIN = "#cfc8b8", PANEL = "#ffffff";

function setColourTokens() {
  for (const [name, colour] of [["context", CONTEXT], ["terrain", TERRAIN], ["panel", PANEL], ["carved", "#c8553d"], ["storey-low", "#dfe6ea"],
                                ["accent", "#2f5d7c"], ["below-target", BELOW_TARGET], ["below-target-on-dark", BELOW_TARGET_ON_DARK]]) {
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

test("the study values layer colours each point's patch by its value, viridis from 0 to the highest, below the target muted", () => {
  setColourTokens();
  const { view, corners } = studyView(false, 1.5);
  const layer = studyValuesLayer(view, corners);
  expect(LAYER_NAMES).toContain("study_values");
  const geometry = (layer as THREE.Mesh).geometry;
  expect(geometry.getAttribute("position").count).toBe(4 * 4);
  expect(Array.from(geometry.index!.array.slice(0, 6))).toEqual([0, 1, 2, 0, 2, 3]);
  expect(patchColours(layer)).toEqual([hexOf(BELOW_TARGET), hexOf(viridis(0.5)), hexOf(viridis(1)), hexOf(BELOW_TARGET)]);
  expect(patchColours(studyValuesLayer({ ...view, target: null }, corners))[0]).toBe(hexOf(viridis(0)));
  expect(layer.userData.summary).toBe("4 points");
});

test("by share each point is coloured by its value over its open-site value, one 0 to 100 % scale; no open-site value is neutral", () => {
  setColourTokens();
  // Open 4, 8, 4, 0 and envelope 0, 4, 4, 0: shares 0, 0.5 and 1 (the second point's value is the highest of the envelope, yet half
  // of its own open-site value), and none for a point the open site gives nothing.
  const values = decodeStudyValues(studyValuesOf({ open: [4, 8, 4, 0], max_volume: [1, 1, 1, 0], envelope: [0, 4, 4, 0] }));
  const view = { values, geometry: "envelope" as const, change: false, colourBy: "share" as const, target: null, unit: "h", dimmed: false };
  const layer = studyValuesLayer(view, patchCorners(values, [0, 0, 0]));
  expect(patchColours(layer)).toEqual([hexOf(viridis(0)), hexOf(viridis(0.5)), hexOf(viridis(1)), hexOf("#dfe6ea")]);
  layer.userData.recolour({ ...view, target: 3 });          // the target is in the unit: points below it stay muted by share too
  expect(patchColours(layer)).toEqual([hexOf(BELOW_TARGET), hexOf(viridis(0.5)), hexOf(viridis(1)), hexOf(BELOW_TARGET)]);
});

test("points below the target are in a muted colour of their own, not the grey of the surroundings, terrain or volumes", () => {
  setColourTokens();
  expect([CONTEXT, TERRAIN, PANEL]).not.toContain(BELOW_TARGET);
  const { view, corners } = studyView(false, 1.5);
  const layer = studyValuesLayer(view, corners);
  layer.userData.applyTheme("dark");           // as the scene does on the dark viewport
  expect(patchColours(layer)[0]).toBe(hexOf(BELOW_TARGET_ON_DARK));
  expect([CONTEXT, TERRAIN, PANEL]).not.toContain(BELOW_TARGET_ON_DARK);
});

test("a new target or Change recolours the same layer in place", () => {
  setColourTokens();
  const { view, corners } = studyView(false, 1.5);
  const layer = studyValuesLayer(view, corners);
  const colours = (layer as THREE.Mesh).geometry.getAttribute("color") as THREE.BufferAttribute;
  const version = colours.version;
  layer.userData.recolour({ ...view, target: 3 });
  expect(patchColours(layer)).toEqual([hexOf(BELOW_TARGET), hexOf(BELOW_TARGET), hexOf(viridis(1)), hexOf(BELOW_TARGET)]);
  expect(colours.version).toBeGreaterThan(version);          // uploaded again
  layer.userData.recolour({ ...view, change: true });
  expect(patchColours(layer)[0]).toBe(hexOf("#c8553d"));
});

test("changeTolerance on 527,633 points takes under 1 s: the Change view of that many points is drawn in under 1 s", () => {
  // The first build scanned the whole open column once per point to find the change tolerance while colouring the change, about
  // 2.8e11 steps on District's 527,633 points, which froze the browser. This times that path: the layer with Change on.
  // The bound is 1 s, not 200 ms: it passes alone in 77 to 90 ms but took 329 ms in a full run under load, and the O(N²) path
  // it guards takes seconds, so 1 s still tells them apart.
  setColourTokens();
  colourToken("accent");       // jsdom's first getComputedStyle takes about 80 ms once (a browser's is warm): not the path timed
  const count = 527_633;
  const open = Array.from({ length: count }, (_, point) => ((point * 7919) % 1000) / 100);
  const values = decodeStudyValues(studyValuesOf({ open, max_volume: open.map((value) => value * 0.8), envelope: open.map((value) => value * 0.9) }));
  const corners = patchCorners(values, [0, 0, 0]);
  const started = performance.now();
  const layer = studyValuesLayer({ values, geometry: "envelope", change: true, colourBy: "share", target: null, unit: "h", dimmed: false }, corners);
  const elapsed = performance.now() - started;
  expect(layer.userData.summary).toBe("527 633 points");
  expect(elapsed).toBeLessThan(1000);
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

// The surface orientation layer of Inspect -----------------------------------------------------------------------------------------

/** Three triangles in two surfaces: triangles 0 and 1 are surface 0 (a unit square in the x-y plane, 1 m^2), triangle 2 is surface 1 (a 4 m^2 wall). */
function inspectFile(overrides: Partial<InspectLayerFile> = {}): InspectLayerFile {
  return {
    fileName: "facades.obj",
    corners: Float32Array.from([0, 0, 0, 1, 0, 0, 1, 1, 0,   0, 0, 0, 1, 1, 0, 0, 1, 0,   5, 0, 0, 7, 0, 0, 5, 0, 2]),
    surfaceOfTriangle: Uint32Array.from([0, 0, 1]),
    surfaces: [{ centre: [0.5, 0.5, 0], normal: [0, 0, 1], area: 1 }, { centre: [5.5, 0, 0.5], normal: [0, -1, 0], area: 4 }],
    turned: new Set<number>(),
    selected: true,
    ...overrides,
  };
}

const SURFACE_BACK = "#c2610a", SURFACE_BACK_ON_DARK = "#f0a050", TEST_SURFACE_ON_DARK = "#6fa0c4";

function setInspectColourTokens() {
  setColourTokens();
  for (const [name, colour] of [["surface-back", SURFACE_BACK], ["surface-back-on-dark", SURFACE_BACK_ON_DARK], ["test-surface-on-dark", TEST_SURFACE_ON_DARK],
                                ["ink", "#1f2a30"], ["ink-on-dark", "#e6ecee"]]) {
    document.documentElement.style.setProperty(`--colour-${name}`, colour);
  }
}

/** The front and back meshes of a file of an inspect layer. */
function meshesOf(layer: THREE.Object3D, fileIndex = 0): { front: THREE.Mesh; back: THREE.Mesh } {
  const meshes = layer.children[fileIndex].children.filter((child): child is THREE.Mesh => child instanceof THREE.Mesh && !(child instanceof LineSegments2));
  const front = meshes.find((mesh) => (mesh.material as THREE.Material).side === THREE.FrontSide)!;
  const back = meshes.find((mesh) => (mesh.material as THREE.Material).side === THREE.BackSide)!;
  return { front, back };
}

const indexOf = (mesh: THREE.Mesh) => Array.from(mesh.geometry.index!.array);
const colourOf = (mesh: THREE.Mesh) => (mesh.material as THREE.MeshLambertMaterial).color.getHexString();

test("the surface orientation layer is the last of the layers and draws each file as a front mesh and a back mesh on one geometry", () => {
  setInspectColourTokens();
  expect(LAYER_NAMES[LAYER_NAMES.length - 1]).toBe("inspect_surfaces");
  const layer = inspectSurfacesLayer([inspectFile()], { arrows: false });
  const { front, back } = meshesOf(layer);
  expect(front.geometry).toBe(back.geometry);
  expect(front.geometry.getAttribute("position").count).toBe(9);
  expect(layer.userData.summary).toBe("2 surfaces");
  expect(colourOf(front)).toBe("2f5d7c");
  expect(colourOf(back)).toBe(hexOf(SURFACE_BACK));
});

test("the colours follow the viewport theme: the front in the test surface colour of the theme, the back in the orange that reads on it", () => {
  setInspectColourTokens();
  const layer = inspectSurfacesLayer([inspectFile()], { arrows: true });
  const { front, back } = meshesOf(layer);
  layer.userData.applyTheme("dark");
  expect(colourOf(front)).toBe(hexOf(TEST_SURFACE_ON_DARK));
  expect(colourOf(back)).toBe(hexOf(SURFACE_BACK_ON_DARK));
  layer.userData.applyTheme("light");
  expect(colourOf(front)).toBe("2f5d7c");
  expect(colourOf(back)).toBe(hexOf(SURFACE_BACK));
});

test("the back colour has a token for the light viewport and one for the dark viewport, each apart from the test surface colour it is seen against", async () => {
  const { readFileSync } = await import("node:fs");
  const tokens = readFileSync("src/theme/tokens.css", "utf8");
  const token = (name: string) => tokens.match(new RegExp(`--colour-${name}:\\s*(#[0-9a-fA-F]{6})`))![1].toLowerCase();
  expect(token("surface-back")).not.toBe(token("accent"));
  expect(token("surface-back-on-dark")).not.toBe(token("test-surface-on-dark"));
  expect(token("surface-back")).not.toBe(token("surface-back-on-dark"));
});

test("a turned surface has the winding of its triangles swapped in the index, and no other surface does", () => {
  setInspectColourTokens();
  const { front } = meshesOf(inspectSurfacesLayer([inspectFile()], { arrows: false }));
  expect(indexOf(front)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
  const turned = meshesOf(inspectSurfacesLayer([inspectFile({ turned: new Set([1]) })], { arrows: false }));
  expect(indexOf(turned.front)).toEqual([0, 1, 2, 3, 4, 5, 6, 8, 7]);
  const bothTurned = meshesOf(inspectSurfacesLayer([inspectFile({ turned: new Set([0, 1]) })], { arrows: false }));
  expect(indexOf(bothTurned.back)).toEqual([0, 2, 1, 3, 5, 4, 6, 8, 7]);
});

test("a file that is not selected is drawn at 35 % strength, a selected one at full strength, and both can be dimmed", () => {
  setInspectColourTokens();
  const layer = inspectSurfacesLayer([inspectFile(), inspectFile({ fileName: "roofs.obj", selected: false })], { arrows: true });
  const opacities = (fileIndex: number) => layer.children[fileIndex].children.map((child) => ((child as THREE.Mesh).material as THREE.Material).opacity);
  expect(opacities(0).every((opacity) => opacity === 1)).toBe(true);
  expect(opacities(1).every((opacity) => opacity === 0.35)).toBe(true);
  expect(layer.children[1].children.length).toBe(layer.children[0].children.length);
  applyLayerAppearance(layer, 0.35, 1);
  expect(opacities(0)[0]).toBeCloseTo(0.35);
  expect(opacities(1)[0]).toBeCloseTo(0.35 * 0.35);
});

test("there is one arrow per surface, and none without arrows", () => {
  setInspectColourTokens();
  const files = [inspectFile(), inspectFile({ fileName: "roofs.obj" })];
  expect(inspectSurfacesLayer(files, { arrows: true }).userData.arrowCount).toBe(4);
  const without = inspectSurfacesLayer(files, { arrows: false });
  expect(without.userData.arrowCount).toBe(0);
  expect(without.children.flatMap((file) => file.children).some((child) => child instanceof LineSegments2)).toBe(false);
});

/** The shaft of each arrow of a file: the first of the five segments the arrow is drawn with. */
function shaftsOf(layer: THREE.Object3D, fileIndex = 0): { from: number[]; to: number[] }[] {
  const lines = layer.children[fileIndex].children.find((child) => child instanceof LineSegments2) as LineSegments2;
  const starts = lines.geometry.getAttribute("instanceStart"), ends = lines.geometry.getAttribute("instanceEnd");
  const segments = Array.from({ length: starts.count }, (_, at) => ({ from: [starts.getX(at), starts.getY(at), starts.getZ(at)], to: [ends.getX(at), ends.getY(at), ends.getZ(at)] }));
  return segments.filter((_, at) => at % 5 === 0);
}

test("an arrow runs from the centre of its surface along the normal, negated when the surface is turned; 0.3 sqrt(area) m long, at least 1 m, at most 10 m", () => {
  setInspectColourTokens();
  const small = { centre: [0, 0, 0] as [number, number, number], normal: [0, 0, 1] as [number, number, number], area: 4 };      // 0.6 m: raised to 1 m
  const middle = { centre: [10, 0, 0] as [number, number, number], normal: [1, 0, 0] as [number, number, number], area: 100 };        // 3 m
  const huge = { centre: [0, 20, 0] as [number, number, number], normal: [0, 1, 0] as [number, number, number], area: 1_000_000 };    // 300 m: capped to 10 m
  const file = inspectFile({ surfaces: [small, middle, huge], surfaceOfTriangle: Uint32Array.from([0, 1, 2]), turned: new Set([1]) });
  const shafts = shaftsOf(inspectSurfacesLayer([file], { arrows: true }));
  expect(shafts).toHaveLength(3);
  const reach = (shaft: { from: number[]; to: number[] }) => shaft.to.map((value, axis) => Math.round((value - shaft.from[axis]) * 1000) / 1000);
  expect(shafts[0].from).toEqual([0, 0, 0]);
  expect(reach(shafts[0])).toEqual([0, 0, 1]);
  expect(shafts[1].from).toEqual([10, 0, 0]);
  expect(reach(shafts[1])).toEqual([-3, 0, 0]);       // turned: against the normal
  expect(reach(shafts[2])).toEqual([0, 10, 0]);
});

test("fileAndSurfaceOf maps the triangle that was hit to its file and surface, and anything else to null", () => {
  setInspectColourTokens();
  const layer = inspectSurfacesLayer([inspectFile(), inspectFile({ fileName: "roofs.obj", surfaceOfTriangle: Uint32Array.from([1, 1, 0]) })], { arrows: true });
  const hit = (object: THREE.Object3D, faceIndex: number | undefined) => ({ object, faceIndex, distance: 1, point: new THREE.Vector3() }) as THREE.Intersection;
  expect(layer.userData.fileAndSurfaceOf(hit(meshesOf(layer, 0).front, 0))).toEqual({ fileName: "facades.obj", surface: 0 });
  expect(layer.userData.fileAndSurfaceOf(hit(meshesOf(layer, 0).back, 2))).toEqual({ fileName: "facades.obj", surface: 1 });
  expect(layer.userData.fileAndSurfaceOf(hit(meshesOf(layer, 1).front, 0))).toEqual({ fileName: "roofs.obj", surface: 1 });
  expect(layer.userData.fileAndSurfaceOf(hit(meshesOf(layer, 1).back, 2))).toEqual({ fileName: "roofs.obj", surface: 0 });
  expect(layer.userData.fileAndSurfaceOf(hit(new THREE.Mesh(), 0))).toBeNull();
  expect(layer.userData.fileAndSurfaceOf(hit(meshesOf(layer, 0).front, undefined))).toBeNull();
});

test("an arrow cannot be hit: the arrow lines take no part in a ray cast", () => {
  setInspectColourTokens();
  const layer = inspectSurfacesLayer([inspectFile()], { arrows: true });
  const lines = layer.children[0].children.find((child) => child instanceof LineSegments2) as LineSegments2;
  const hits: THREE.Intersection[] = [];
  lines.raycast(new THREE.Raycaster(new THREE.Vector3(0.5, 0.5, 5), new THREE.Vector3(0, 0, -1)), hits);
  expect(hits).toEqual([]);
});

test("the surface orientation layer leaves the corners it is given as they are, and is drawn in front of the faces it lies on", () => {
  setInspectColourTokens();
  const file = inspectFile();
  const before = Array.from(file.corners);
  const { front, back } = meshesOf(inspectSurfacesLayer([file], { arrows: false }));
  expect(Array.from(file.corners)).toEqual(before);
  for (const mesh of [front, back]) expect((mesh.material as THREE.Material).polygonOffsetFactor).toBeLessThan(0);
});

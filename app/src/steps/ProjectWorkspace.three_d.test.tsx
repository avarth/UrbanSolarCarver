// The 3D view of a project with several criteria, against a fake service of a chain: the carved-by-criterion layer (asked for only
// when every criterion that is on has run), the state after the selected criterion, and the test surfaces of the selected criterion.
import { act } from "react";
import * as THREE from "three";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { packCarvedByCriterion, packScorePoints } from "../viewer/packed_results_for_test";
import {
  CURRENT, FACADES, ROOFS, WINDOWS, card, deleteCriterion, openChain, select, service, type ChainService, type CriterionStages,
} from "./chain_service_for_test";
import {
  CARVED, TRIANGLE_OBJ, container, endWorkspaceTest, pressRunAnalysis, settle, startWorkspaceTest, thresholdField, typeAndLeave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const TWO_TRIANGLES_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nf 1 2 3\nf 2 4 3\n";
const NOT_RUN: CriterionStages = { preprocessing: "missing", thresholding: "missing" };

/** A (2, 2, 1) grid: criterion 1 carved voxel 1, criterion 2 carved voxel 2; the score points of each criterion are those after it. */
function holdResults(chain: ChainService, ids = ["1", "2"]) {
  chain.carvedByCriterion = packCarvedByCriterion([2, 2, 1], ids, [0, 1, 2, 0]);
  chain.scorePointsOf = { "1": packScorePoints([0, 1, 2, 3], [1, 0, 1, 1]), "2": packScorePoints([0, 1, 2, 3], [1, 0, 0, 1]), "3": packScorePoints([0, 1, 2, 3], [1, 0, 0, 0]) };
}

const carvedByRequests = () => service.requests.filter((request) => request === "GET /run/carved-by-criterion").length;
const layer = (name: Parameters<FakeViewerScene["layers"]["get"]>[0]) => FakeViewerScene.latest!.layers.get(name) ?? null;
const countOf = (name: Parameters<FakeViewerScene["layers"]["get"]>[0]) => (layer(name) as THREE.InstancedMesh).count;
const layersMenuEntries = () => {
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  const entries = [...container().querySelectorAll<HTMLElement>(".viewer-layers-panel li")];
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  return entries.map((entry) => ({ label: entry.querySelector("label")!.textContent, disabled: entry.querySelector("input")!.disabled, note: entry.querySelector(".viewer-layer-note") !== null }));
};
const carvedByEntry = () => layersMenuEntries().find((entry) => entry.label === "Carved voxels, by criterion");

async function bypass(name: string) {
  await act(async () => card(name).querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
}

test("test the layer is missing until every active criterion has run: no request, the Layers menu lists it without a result", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: NOT_RUN }, holdResults);
  expect(carvedByRequests()).toBe(0);                                   // the route would answer 404
  expect(layer("carved_by_criterion")).toBeNull();
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: true, note: true });

  service.runCriterionStages = { 1: ["thresholding"], 2: ["preprocessing", "thresholding"] };
  await pressRunAnalysis();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "preprocessing", criterion: "2", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "1", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "2", done: 0, total: 1 });
  await settle();
  expect(carvedByRequests()).toBe(0);                                   // criterion 2's stage status still says it has not run
  service.criterionStages = { 1: CURRENT, 2: CURRENT };
  service.stages = { ...CARVED };
  run.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();
  expect(carvedByRequests()).toBe(1);
  expect(countOf("carved_by_criterion")).toBe(2);
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: false, note: false });
});

test("with every criterion run the layer is drawn, in the criteria's colours, and hidden until it is turned on", async () => {
  await openChain([FACADES, WINDOWS], undefined, holdResults);
  expect(carvedByRequests()).toBe(1);
  expect(countOf("carved_by_criterion")).toBe(2);
  expect(FakeViewerScene.latest!.visibleLayers.has("carved_by_criterion")).toBe(false);
  expect(FakeViewerScene.latest!.visibleLayers.has("kept_voxels")).toBe(true);
  const mesh = layer("carved_by_criterion") as THREE.InstancedMesh;
  const colourOf = (voxel: number) => {
    const colour = new THREE.Color();
    mesh.getColorAt(voxel, colour);
    return colour.getHexString();
  };
  // the first carved voxel was removed by criterion 1 (blue), the second by criterion 2 (red)
  expect([colourOf(0), colourOf(1)]).toEqual([FACADES.colour, WINDOWS.colour].map((hex) => new THREE.Color(hex).getHexString()));
});

test("a project of one criterion never asks for the layer, and does not list it", async () => {
  await openChain([FACADES], undefined, holdResults);
  expect(carvedByRequests()).toBe(0);
  expect(carvedByEntry()).toBeUndefined();
});

test("two criteria where one is bypassed ask nothing either; turning it back on asks", async () => {
  await openChain([FACADES, WINDOWS, ROOFS], undefined, (chain) => holdResults(chain, ["1", "2", "3"]));
  expect(carvedByRequests()).toBe(1);
  await bypass("Daylight on roofs");
  expect(carvedByRequests()).toBe(2);                                    // the criteria that are on changed
  await bypass("Spring sun on windows");
  expect(carvedByRequests()).toBe(2);                                    // one criterion on: nothing to tell apart
  expect(layer("carved_by_criterion")).toBeNull();
  expect(carvedByEntry()).toBeUndefined();
  await bypass("Spring sun on windows");
  expect(carvedByRequests()).toBe(3);
  expect(countOf("carved_by_criterion")).toBe(2);
});

test("reordering and deleting criteria ask again", async () => {
  await openChain([FACADES, WINDOWS, ROOFS], undefined, (chain) => holdResults(chain, ["1", "2", "3"]));
  expect(carvedByRequests()).toBe(1);
  const handle = card("Spring sun on windows").querySelector<HTMLElement>(".criterion-card-handle")!;
  handle.focus();
  await act(async () => handle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true })));
  await settle();
  expect(carvedByRequests()).toBe(2);
  await deleteCriterion("Daylight on roofs");
  expect(carvedByRequests()).toBe(3);
  expect(countOf("carved_by_criterion")).toBe(2);
});

test("a run that thresholds the criteria again asks for the layer once it has finished", async () => {
  await openChain([FACADES, WINDOWS], undefined, holdResults);
  expect(carvedByRequests()).toBe(1);
  service.runCriterionStages = { 1: ["thresholding"], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "1");
  await settle();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "1", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "2", done: 0, total: 1 });
  await settle();
  expect(carvedByRequests()).toBe(1);
  run.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(carvedByRequests()).toBe(2);
});

test("selecting a card shows the state after that criterion in the kept voxels, and leaves the by-criterion layer as it is", async () => {
  await openChain([FACADES, WINDOWS], undefined, holdResults);
  expect(countOf("kept_voxels")).toBe(3);                                // after criterion 1: voxel 1 is carved
  await select("Spring sun on windows");
  expect(service.requests).toContain("GET /run/score-points?criterion=2");
  expect(countOf("kept_voxels")).toBe(2);                                // after criterion 2: voxel 2 is carved too
  expect(carvedByRequests()).toBe(1);
  expect(countOf("carved_by_criterion")).toBe(2);
  await select("Winter sun on facades");
  expect(countOf("kept_voxels")).toBe(3);
});

const verticesOf = (name: string) => {
  const part = (layer("test_surfaces") as THREE.Group).getObjectByName(name) as THREE.Mesh | undefined;
  return part === undefined ? null : part.geometry.getAttribute("position").count;
};

function twoFiles(chain: ChainService) {
  chain.inputFileContents["/inputs/test_surfaces/facades.obj"] = TRIANGLE_OBJ;
  chain.inputFileContents["/inputs/test_surfaces/windows.obj"] = TWO_TRIANGLES_OBJ;
}

test("test the other criteria's test surfaces are dimmed: the selected criterion's files at full strength, a shared file highlighted", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: ["windows.obj", "facades.obj"] }], undefined, twoFiles);
  expect(verticesOf("highlighted")).toBe(3);                              // facades.obj
  expect(verticesOf("dimmed")).toBe(6);                                   // windows.obj, which only criterion 2 uses
  await select("Spring sun on windows");
  expect(verticesOf("highlighted")).toBe(9);                              // windows.obj and the shared facades.obj
  expect(verticesOf("dimmed")).toBeNull();                                // nothing else is left to dim
  await select("Winter sun on facades");
  expect(verticesOf("highlighted")).toBe(3);
  expect(verticesOf("dimmed")).toBe(6);
});

test("with one criterion nothing is dimmed", async () => {
  await openChain([FACADES], undefined, twoFiles);
  expect(verticesOf("highlighted")).toBe(3);
  expect(verticesOf("dimmed")).toBeNull();
});

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
const carvedByNote = () => {
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  const note = [...container().querySelectorAll<HTMLElement>(".viewer-layers-panel li")].find((entry) => entry.textContent!.includes("by criterion"))?.querySelector(".viewer-layer-note")?.textContent;
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  return note;
};
/** The layer starts hidden and is built only once shown: this turns it on in the Layers menu. */
const turnOnCarvedByCriterion = () => {
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  const entry = [...container().querySelectorAll<HTMLElement>(".viewer-layers-panel li")].find((item) => item.textContent!.includes("by criterion"))!;
  act(() => entry.querySelector<HTMLInputElement>("input")!.click());
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
};

async function bypass(name: string) {
  await act(async () => card(name).querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
}

test("test the layer is missing until every active criterion has run: no request, the Layers menu lists it without a result", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: NOT_RUN }, holdResults);
  expect(carvedByRequests()).toBe(0);                                   // the route would answer 404
  expect(layer("carved_by_criterion")).toBeNull();
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: true, note: true });
  expect(carvedByNote()).toBe("Shows once every criterion that is on has run.");

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
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: false, note: false });
  turnOnCarvedByCriterion();
  expect(countOf("carved_by_criterion")).toBe(2);
});

test("with every criterion run the layer is offered, built only once it is turned on, in the criteria's colours", async () => {
  await openChain([FACADES, WINDOWS], undefined, holdResults);
  expect(carvedByRequests()).toBe(1);
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: false, note: false });
  expect(layer("carved_by_criterion")).toBeNull();                       // hidden: nothing is built yet
  expect(FakeViewerScene.latest!.visibleLayers.has("kept_voxels")).toBe(true);
  turnOnCarvedByCriterion();
  expect(countOf("carved_by_criterion")).toBe(2);
  expect(FakeViewerScene.latest!.visibleLayers.has("carved_by_criterion")).toBe(true);
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
  expect(carvedByEntry()).toBeUndefined();
  await bypass("Spring sun on windows");
  expect(carvedByRequests()).toBe(3);
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: false, note: false });
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
  turnOnCarvedByCriterion();
  expect(countOf("carved_by_criterion")).toBe(2);
});

test("after a reorder the layer on screen stays until the new reply replaces it: no flash to missing", async () => {
  await openChain([FACADES, WINDOWS, ROOFS], undefined, (chain) => holdResults(chain, ["1", "2", "3"]));
  turnOnCarvedByCriterion();
  const before = layer("carved_by_criterion");
  expect(before).not.toBeNull();
  let reply!: () => void;
  service.carvedByCriterionAnswerWhen = new Promise<void>((resolve) => { reply = resolve; });
  service.carvedByCriterion = packCarvedByCriterion([2, 2, 1], ["2", "1", "3"], [0, 2, 1, 0]);
  const handle = card("Spring sun on windows").querySelector<HTMLElement>(".criterion-card-handle")!;
  handle.focus();
  await act(async () => handle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true })));
  await settle();
  expect(carvedByRequests()).toBe(2);
  expect(layer("carved_by_criterion")).toBe(before);                      // the reply is not in
  expect(carvedByEntry()).toEqual({ label: "Carved voxels, by criterion", disabled: false, note: false });
  reply();
  await settle();
  expect(layer("carved_by_criterion")).not.toBe(before);
  expect(countOf("carved_by_criterion")).toBe(2);
});

test("the by-criterion layer is dimmed when any criterion that is on is out of date, not only the selected one", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: { preprocessing: "current", thresholding: "out_of_date" } }, holdResults);
  expect(FakeViewerScene.latest!.dimmed.has("carved_by_criterion")).toBe(true);
  expect(FakeViewerScene.latest!.dimmed.has("kept_voxels")).toBe(false);          // criterion 1, the selected one, is current
  turnOnCarvedByCriterion();
  expect(container().querySelector(".viewer-out-of-date")).not.toBeNull();       // the stamp says so while the layer is shown
});

test("the by-criterion layer of a project that is up to date is not dimmed", async () => {
  await openChain([FACADES, WINDOWS], undefined, holdResults);
  expect(FakeViewerScene.latest!.dimmed.has("carved_by_criterion")).toBe(false);
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
  turnOnCarvedByCriterion();
  // The carved voxels layer holds its cubes first, then the outline.
  const carvedOf = () => (layer("carved_voxels") as THREE.Group).children.find((child) => child instanceof THREE.InstancedMesh) as THREE.InstancedMesh;
  expect([countOf("kept_voxels"), carvedOf().count]).toEqual([3, 1]);   // after criterion 1: voxel 1 is carved
  await select("Spring sun on windows");
  expect(service.requests).toContain("GET /run/score-points?criterion=2");
  expect([countOf("kept_voxels"), carvedOf().count]).toEqual([2, 2]);   // after criterion 2: voxel 2 is carved too
  expect(carvedByRequests()).toBe(1);
  expect(countOf("carved_by_criterion")).toBe(2);
  await select("Winter sun on facades");
  expect([countOf("kept_voxels"), carvedOf().count]).toEqual([3, 1]);
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
  expect(service.count("GET /inputs/test_surfaces/facades.obj")).toBe(1);   // each file is loaded once, however the selection moves
  expect(service.count("GET /inputs/test_surfaces/windows.obj")).toBe(1);
});

test("with one criterion nothing is dimmed, even when a stored file is not one the criterion lists", async () => {
  await openChain([FACADES], undefined, twoFiles, ["windows.obj"]);
  expect(verticesOf("highlighted")).toBe(9);                              // facades.obj and windows.obj, all at full strength
  expect(verticesOf("dimmed")).toBeNull();
});

test("a criterion that lists no files highlights nothing and dims every stored file", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: [] }], undefined, twoFiles);
  await select("Spring sun on windows");
  expect(verticesOf("highlighted")).toBeNull();
  expect(verticesOf("dimmed")).toBe(3);                                   // facades.obj
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
});

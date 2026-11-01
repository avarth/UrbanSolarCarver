// The 3D view of a project with several criteria, against a fake service of a chain: the carved-by-criterion layer (asked for only
// when every criterion that is on has run), the state after the selected criterion, and the test surfaces of each criterion.
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
  CARVED, TRIANGLE_OBJ, buttonIn, container, endWorkspaceTest, openStep, pressRunAnalysis, settle, startWorkspaceTest, stepRow, thresholdField, typeAndLeave,
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

// The mesh of the test surfaces layer that draws criterion *id*'s files (the layer has one per criterion, named by its id).
const partOf = (id: string) => (layer("test_surfaces") as THREE.Group | null)?.children.find((child) => child.name === id) as THREE.Mesh | undefined;
const verticesOf = (id: string) => partOf(id)?.geometry.getAttribute("position").count ?? null;
const colourOf = (id: string) => (partOf(id)!.material as THREE.MeshLambertMaterial).color.getHexString();
const opacityOf = (id: string) => (partOf(id)!.material as THREE.Material).opacity;
const hex = (colour: string) => new THREE.Color(colour).getHexString();

/** The Test surfaces entry of the Layers menu and the entries under it, as the open menu shows them. */
function testSurfaceEntries() {
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  const items = [...container().querySelectorAll<HTMLElement>(".viewer-layers-panel li")];
  const parent = items.find((item) => item.querySelector("label")!.textContent!.startsWith("Test surfaces"))!;
  const parts = items.filter((item) => item !== parent && parent.contains(item));
  const read = (item: HTMLElement) => ({ label: item.querySelector("label")!.textContent, checked: item.querySelector("input")!.checked,
                                         swatch: item.querySelector("label")!.querySelector<HTMLElement>(".viewer-criterion-swatch")?.style.backgroundColor ?? null });
  const entries = { parent: read(parent), parts: parts.map(read), mixed: parent.querySelector("input")!.indeterminate };
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  return entries;
}

/** Clicks the check box of the entry with this label (the Test surfaces entry or one under it) in the Layers menu. */
function clickTestSurfaceEntry(label: string) {
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
  const input = [...container().querySelectorAll<HTMLLabelElement>(".viewer-layers-panel label")].find((candidate) => candidate.textContent === label)!.querySelector("input")!;
  act(() => input.click());
  act(() => container().querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!.click());
}

function twoFiles(chain: ChainService) {
  chain.inputFileContents["/inputs/test_surfaces/facades.obj"] = TRIANGLE_OBJ;
  chain.inputFileContents["/inputs/test_surfaces/windows.obj"] = TWO_TRIANGLES_OBJ;
}

test("each criterion's test surfaces are drawn in its colour, all at full strength, whichever criterion is selected", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, 6]);
  expect([colourOf("1"), colourOf("2")]).toEqual([hex("#4477aa"), hex("#ee6677")]);
  expect([opacityOf("1"), opacityOf("2")]).toEqual([1, 1]);
  expect((layer("test_surfaces") as THREE.Group).children).toHaveLength(2);       // nothing else: no faded copy of the criteria that are not selected
  await select("Spring sun on windows");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, 6]);
  expect([colourOf("1"), colourOf("2")]).toEqual([hex("#4477aa"), hex("#ee6677")]);
  expect(service.count("GET /inputs/test_surfaces/facades.obj")).toBe(1);   // each file is loaded once, however the selection moves
  expect(service.count("GET /inputs/test_surfaces/windows.obj")).toBe(1);
});

test("the Layers menu has a Test surfaces entry with one check box and swatch per criterion, in chain order, all checked", async () => {
  await openChain([FACADES, WINDOWS, ROOFS], undefined, twoFiles);
  const { parent, parts } = testSurfaceEntries();
  expect(parent).toEqual({ label: "Test surfaces", checked: true, swatch: null });
  expect(parts).toEqual([
    { label: "Winter sun on facades", checked: true, swatch: "rgb(68, 119, 170)" },
    { label: "Spring sun on windows", checked: true, swatch: "rgb(238, 102, 119)" },
    { label: "Daylight on roofs", checked: true, swatch: "rgb(34, 136, 51)" },
  ]);
});

test("unchecking a criterion's entry hides only its test surfaces, and selecting another criterion changes nothing about what is shown", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  clickTestSurfaceEntry("Spring sun on windows");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([true, false]);
  expect(testSurfaceEntries().parent.checked).toBe(true);
  await select("Spring sun on windows");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
  await select("Winter sun on facades");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
  clickTestSurfaceEntry("Spring sun on windows");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, 6]);
  clickTestSurfaceEntry("Winter sun on facades");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([null, 6]);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
});

test("the Test surfaces check box hides the layer and shows it again with the criteria the user had not hidden", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  clickTestSurfaceEntry("Spring sun on windows");
  clickTestSurfaceEntry("Test surfaces");
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(false);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([false, false]);
  clickTestSurfaceEntry("Test surfaces");
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([true, false]);       // windows stays hidden by its own entry
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
});

test("the Test surfaces check box is half checked while one of the criteria is hidden", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  expect(testSurfaceEntries().mixed).toBe(false);
  clickTestSurfaceEntry("Spring sun on windows");
  expect([testSurfaceEntries().parent.checked, testSurfaceEntries().mixed]).toEqual([true, true]);
  clickTestSurfaceEntry("Spring sun on windows");
  expect(testSurfaceEntries().mixed).toBe(false);
});

test("hiding the layer is the step's choice, not the criteria's: another step brings back the layer with the criteria not hidden by choice", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  clickTestSurfaceEntry("Spring sun on windows");
  clickTestSurfaceEntry("Test surfaces");
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(false);
  openStep("Inputs");
  await settle();
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([true, false]);
});

test("checking a criterion's entry while the layer is hidden shows it alone when none was hidden by choice, else the layer as the choices stand", async () => {
  await openChain([FACADES, WINDOWS, { ...ROOFS, test_surface_files: [] }], undefined, twoFiles);
  clickTestSurfaceEntry("Test surfaces");
  clickTestSurfaceEntry("Spring sun on windows");
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([false, true, false]);
  expect([verticesOf("1"), verticesOf("2")]).toEqual([null, 6]);
  clickTestSurfaceEntry("Test surfaces");                                  // hides the layer; the entries of the criteria stay as they are
  clickTestSurfaceEntry("Winter sun on facades");
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([true, true, false]);        // windows stays shown and roofs hidden: the layer is shown as the choices stand
});

test("the choice of criteria shown is kept when another step opens", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  clickTestSurfaceEntry("Spring sun on windows");
  openStep("Inputs");
  await settle();
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
  expect(testSurfaceEntries().parts.map((part) => part.checked)).toEqual([true, false]);
});

test("selecting a criterion that moves no file to another criterion does not draw the test surfaces again", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  const setLayer = vi.spyOn(FakeViewerScene.latest!, "setLayer");
  await select("Spring sun on windows");
  await select("Winter sun on facades");
  expect(setLayer.mock.calls.filter(([name]) => name === "test_surfaces")).toHaveLength(0);
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, 6]);
});

test("a file that several criteria list is drawn once: in the selected criterion's colour, else in the first visible owner's", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: ["windows.obj", "facades.obj"] }], undefined, twoFiles);
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, 6]);             // criterion 1 is selected: facades.obj is its
  const setLayer = vi.spyOn(FakeViewerScene.latest!, "setLayer");
  await select("Spring sun on windows");
  expect(setLayer.mock.calls.filter(([name]) => name === "test_surfaces")).toHaveLength(1);       // the shared file moves: drawn again
  expect([verticesOf("1"), verticesOf("2")]).toEqual([null, 9]);          // criterion 2 takes the shared facades.obj
  clickTestSurfaceEntry("Spring sun on windows");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);          // hidden: the file is the first other owner's
  clickTestSurfaceEntry("Winter sun on facades");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([null, null]);       // every owner hidden: not drawn
  expect(testSurfaceEntries().parent.checked).toBe(false);
  expect(FakeViewerScene.latest!.layers.get("test_surfaces") ?? null).toBeNull();
});

test("with one criterion the menu has a single Test surfaces entry, drawn in that criterion's colour; a stored file it does not list is not drawn", async () => {
  await openChain([FACADES], undefined, twoFiles, ["windows.obj"]);
  expect(verticesOf("1")).toBe(3);
  expect((layer("test_surfaces") as THREE.Group).children).toHaveLength(1);
  expect(colourOf("1")).toBe(hex("#4477aa"));
  const { parent, parts } = testSurfaceEntries();
  expect([parent.label, parent.checked, parts]).toEqual(["Test surfaces", true, []]);
});

test("a criterion that is switched off keeps its entry, marked as off, and its test surfaces stay", async () => {
  await openChain([FACADES, WINDOWS], undefined, twoFiles);
  await bypass("Spring sun on windows");
  expect(testSurfaceEntries().parts.map((part) => part.label)).toEqual(["Winter sun on facades", "Spring sun on windows (off)"]);
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, 6]);
});

test("a criterion that lists no files has an entry and draws nothing; the other criterion's files are still shown", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: [] }], undefined, twoFiles);
  await select("Spring sun on windows");
  expect([verticesOf("1"), verticesOf("2")]).toEqual([3, null]);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(testSurfaceEntries().parts.map((part) => part.label)).toEqual(["Winter sun on facades", "Spring sun on windows"]);
});

test("a criterion that was hidden and then deleted leaves nothing behind: one added afterwards (the service numbers it again) is shown", async () => {
  await openChain([FACADES, WINDOWS, { ...ROOFS, test_surface_files: [] }], undefined, twoFiles);
  clickTestSurfaceEntry("Daylight on roofs");
  await deleteCriterion("Daylight on roofs");
  act(() => buttonIn(stepRow("Criteria"), "Add criterion").click());
  await act(async () => [...container().querySelectorAll<HTMLElement>('.add-criterion [role="menuitem"]')]
    .find((item) => item.querySelector(".mode-menu-name")!.textContent === "Daylight")!.click());
  await settle();
  expect(service.entries.map((entry) => entry.id)).toEqual(["1", "2", "3"]);       // the id of the deleted criterion again
  expect(testSurfaceEntries().parts).toEqual([
    { label: "Winter sun on facades", checked: true, swatch: "rgb(68, 119, 170)" },
    { label: "Spring sun on windows", checked: true, swatch: "rgb(238, 102, 119)" },
    { label: "Daylight", checked: true, swatch: "rgb(34, 136, 51)" },
  ]);
});

test("deleting a criterion takes it from the menu and the files only it used out of the 3D view", async () => {
  await openChain([FACADES, WINDOWS, { ...ROOFS, test_surface_files: ["facades.obj"] }], undefined, twoFiles);
  expect([verticesOf("1"), verticesOf("2"), verticesOf("3")]).toEqual([3, 6, null]);
  await deleteCriterion("Spring sun on windows");
  expect(service.storedTestSurfaces.map((file) => file.name)).toEqual(["facades.obj"]);
  expect([verticesOf("1"), verticesOf("2"), verticesOf("3")]).toEqual([3, null, null]);       // facades.obj, which criteria 1 and 3 use, is drawn once
  expect(testSurfaceEntries().parts.map((part) => part.label)).toEqual(["Winter sun on facades", "Daylight on roofs"]);
  await deleteCriterion("Daylight on roofs");
  expect(verticesOf("1")).toBe(3);                                         // one criterion: a single entry
  expect(testSurfaceEntries().parts).toEqual([]);
});

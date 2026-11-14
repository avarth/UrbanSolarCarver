// Test surfaces picked on the context (design/test-surfaces-on-context.md), in the open workspace against a fake service: From
// context in the Site step's Test surfaces box (Carve only), the picker over the view, Use making a surface set (new, added to, or
// edited) that no criterion or study uses until it is switched on there, and Rename.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as THREE from "three";
import type { CriterionEntry, InputFileInfo, ProjectDetail } from "../api_client/client";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { byRole, type } from "../viewer_overlays/render_for_test";
import { FACADES, WINDOWS, criterion, openChain, protectedFiles, service } from "./chain_service_for_test";
import {
  buttonIn, container, endWorkspaceTest, openPanelSection, openStep, settle, startWorkspaceTest, stepIsOpen, surfaceSetSwitches, surfaceSetsBox, switchMode,
} from "./project_workspace_for_test";
import { openSimulate, openStudySettings, simulateService, study, studyPopover } from "./simulate_service_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

// The surroundings: the corner of a box, a floor of two triangles (faces 0 and 1, z = 0) and a wall of two (faces 2 and 3, x = 0).
// The project's local origin is (0, 0, 0), so the input files' coordinates are the view's.
const CITY_OBJ = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 1 1\nv 0 0 1\nf 1 2 3\nf 1 3 4\nf 1 4 5\nf 1 5 6\n";
const CITY: InputFileInfo = { name: "city.obj", triangle_count: 4 };
const ROOFS_SET: InputFileInfo = { name: "picked_1.ply", triangle_count: 2, shown_name: "Roofs", picked: true };
const FLOOR_PICK = { point: [0.5, 0.25, 0], ray: [0, 0, -1] };

/** The unit ray from the fake scene's camera, at (100, 0, 0), to *point*. */
function rayTo(point: number[]): number[] {
  const ray = [point[0] - 100, point[1], point[2]];
  const length = Math.hypot(...ray);
  return ray.map((value) => value / length);
}

/**
 * Opens the project of these criteria at the Site step, with the surroundings (city.obj) unless *withSurroundings* is false, and
 * *sets* stored besides the criteria's files (a set a criterion lists is given here with its name and whether it was picked).
 */
async function openCarve(entries: CriterionEntry[], { sets = [], withSurroundings = true }: { sets?: InputFileInfo[]; withSurroundings?: boolean } = {}) {
  const usersOf = (name: string) => entries.filter((entry) => (entry.test_surface_files ?? []).includes(name)).map((entry) => entry.name);
  const storedOf = (names: string[]) => names.map((name) => ({ ...(sets.find((set) => set.name === name) ?? { name, triangle_count: 1 }), used_by: usersOf(name) }));
  const listed = [...new Set([...entries.flatMap((entry) => entry.test_surface_files ?? []), ...sets.map((set) => set.name)])];
  await openChain(entries, undefined, (chain) => {
    chain.inputFileContents["/inputs/context/city.obj"] = CITY_OBJ;
    chain.surfacePicks["picked_1.ply"] = [FLOOR_PICK];
  }, [], (opened: ProjectDetail) => ({
    ...opened, inputs: { ...opened.inputs, test_surfaces: storedOf(listed), ...(withSurroundings ? { context: [CITY] } : {}) },
  }));
  service.storedTestSurfaces = storedOf(listed);
  openStep("Site");
}

const box = () => surfaceSetsBox()!;
const pickButton = () => [...box().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Pick") ?? null;
const bar = () => container().querySelector<HTMLFormElement>("form.context-picker-bar");
const useButton = () => bar()!.querySelector<HTMLButtonElement>('button[type="submit"]')!;
const surfaceSetRequests = () => service.requests.filter((request) => request.includes("/surface-sets/") || request.includes("/test-surfaces/"));
const setNames = () => [...box().querySelectorAll(".input-file-name")].map((name) => name.textContent);
/** What the box says of the set shown as *name*: the lines of its remove button's title under what the button does. */
const detailsOf = (name: string) => byRole<HTMLButtonElement>(box(), "button", `Remove ${name}`).title.split("\n").slice(1);
/** The sets criterion 1 uses, read in its panel (the Criteria step is opened, which ends picking). */
function setsOfCriterion() {
  openStep("Criteria");
  openPanelSection("Test surfaces");
  return protectedFiles();
}

function clickFace(faceIndex: number, point: number[]) {
  act(() => FakeViewerScene.latest!.clickLayer("context", {
    faceIndex, point: new THREE.Vector3(point[0], point[1], point[2]), distance: 1, object: new THREE.Object3D(),
  } as THREE.Intersection));
}

async function press(button: HTMLButtonElement) {
  await act(async () => button.click());
  await settle();
}

async function chooseFromSetMenu(setName: string, item: string) {
  act(() => byRole<HTMLButtonElement>(box(), "button", `Actions for ${setName}`).click());
  await press([...box().querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((candidate) => candidate.textContent === item)!);
}

test("Pick is in the Site step's Test surfaces box only while the project has context files", async () => {
  await openCarve([FACADES], { withSurroundings: false });
  expect(box().querySelector(".input-box-title-row button")!.textContent).toBe("Import");
  expect(pickButton()).toBeNull();
  endWorkspaceTest();
  startWorkspaceTest();
  await openCarve([FACADES]);
  expect(pickButton()).not.toBeNull();
  expect(bar()).toBeNull();
  // The criterion's panel offers no picking: only its switches
  openStep("Criteria");
  openPanelSection("Test surfaces");
  expect(container().querySelector(".criterion-panel")!.textContent).not.toContain("Pick");
});

test("Carve: pick a face, Use makes a new set from the pick, which no criterion uses; the box lists it by its name", async () => {
  await openCarve([FACADES]);
  await press(pickButton()!);
  expect(bar()!.querySelector<HTMLInputElement>('input[aria-label="Name of the new set"]')!.value).toBe("Picked 1");
  clickFace(3, [0, 0.2, 0.8]);
  expect(useButton().textContent).toBe("Use 1 face");
  await press(useButton());
  expect(service.pickedSetRequests).toHaveLength(1);
  const sent = service.pickedSetRequests[0];
  expect(sent.name).toBe("Picked 1");
  expect(sent.replace).toBeUndefined();
  expect(sent.picks.map((pick) => pick.point)).toEqual([[0, 0.2, 0.8]]);
  sent.picks[0].ray.forEach((value, axis) => expect(value).toBeCloseTo(rayTo([0, 0.2, 0.8])[axis], 12));
  expect(surfaceSetRequests()).toEqual(["POST /surface-sets/picked"]);           // no criterion is made to use it
  expect(service.requests.lastIndexOf("GET /inputs/test_surfaces")).toBeGreaterThan(service.requests.indexOf("POST /surface-sets/picked"));
  expect(bar()).toBeNull();
  expect(setNames()).toEqual(["facades.obj", "Picked 1"]);
  expect(detailsOf("Picked 1")).toEqual(["2 triangles, picked on the context"]);
  expect(detailsOf("facades.obj")).toEqual(["1 triangle"]);       // its users are in the refusal, the first line
  expect(setsOfCriterion()).toEqual(["facades.obj"]);
  expect(surfaceSetSwitches()).toEqual([["facades.obj", true], ["Picked 1", false]]);
});

test("Carve: the name typed for the new set is sent", async () => {
  await openCarve([FACADES]);
  await press(pickButton()!);
  clickFace(0, [0.5, 0.25, 0]);
  type(bar()!.querySelector<HTMLInputElement>('input[aria-label="Name of the new set"]')!, "  Courtyard floor ");
  await press(useButton());
  expect(service.pickedSetRequests[0].name).toBe("Courtyard floor");
  expect(setNames()).toEqual(["facades.obj", "Courtyard floor"]);
});

test("Carve: Add to a picked set another criterion uses joins its picks with the new ones; no other criterion is made to use it", async () => {
  const windows = criterion("2", WINDOWS.name, WINDOWS.settings!, ["picked_1.ply"], WINDOWS.colour);
  await openCarve([FACADES, windows], { sets: [ROOFS_SET] });
  await press(pickButton()!);
  const target = bar()!.querySelector<HTMLSelectElement>('select[aria-label="Where the picked faces go"]')!;
  expect([...target.options].map((option) => option.textContent)).toEqual(["New set", "Add to Roofs"]);
  type(target, "picked_1.ply");
  clickFace(2, [0, 0.5, 0.5]);
  await press(useButton());
  expect(surfaceSetRequests()).toEqual(["GET /surface-sets/picked_1.ply/picks", "POST /surface-sets/picked"]);
  const sent = service.pickedSetRequests[0];
  expect(sent.replace).toBe("picked_1.ply");
  expect(sent.name).toBeUndefined();
  expect(sent.picks.map((pick) => pick.point)).toEqual([[0.5, 0.25, 0], [0, 0.5, 0.5]]);
  expect(sent.picks[0]).toEqual(FLOOR_PICK);
  expect(bar()).toBeNull();
  expect(detailsOf("Roofs")).toEqual(["4 triangles, picked on the context"]);
  expect(setsOfCriterion()).toEqual(["facades.obj"]);
});

test("Carve: Edit picks opens the set's picks and Save picks replaces them, without using the set again", async () => {
  const facades = criterion("1", FACADES.name, FACADES.settings!, ["facades.obj", "picked_1.ply"]);
  await openCarve([facades], { sets: [ROOFS_SET] });
  await chooseFromSetMenu("Roofs", "Edit picks");
  expect(service.requests).toContain("GET /surface-sets/picked_1.ply/picks");
  expect(bar()!.querySelector(".context-picker-target")!.textContent).toBe("Editing Roofs");
  expect(container().querySelectorAll(".context-picker-pieces polygon")).toHaveLength(2);      // the floor, picked before
  expect(useButton().textContent).toBe("Save picks");
  clickFace(3, [0, 0.2, 0.8]);
  await press(useButton());
  expect(service.pickedSetRequests).toEqual([{ picks: [FLOOR_PICK, { point: [0, 0.2, 0.8], ray: expect.any(Array) }], replace: "picked_1.ply" }]);
  expect(service.requests.filter((request) => request.startsWith("PUT /criteria/"))).toEqual([]);
  expect(bar()).toBeNull();
  expect(detailsOf("Roofs")[0]).toBe("4 triangles, picked on the context");
  expect(setsOfCriterion()).toEqual(["facades.obj", "Roofs"]);
});

test("Carve: a refused Use is said in the bar, which stays open with its picks", async () => {
  await openCarve([FACADES]);
  await press(pickButton()!);
  service.pickRefusal = "The pick 1 is on no face of the surroundings.";
  clickFace(0, [0.5, 0.25, 0]);
  await press(useButton());
  expect(bar()!.querySelector('[role="alert"]')!.textContent).toBe("The pick 1 is on no face of the surroundings.");
  expect(useButton().textContent).toBe("Use 1 face");
  expect(useButton().disabled).toBe(false);
  expect(service.requests.filter((request) => request.startsWith("PUT /criteria/"))).toEqual([]);
});

test("Carve: Cancel closes the picker and sends nothing; picking ends when the Site step closes, or the mode leaves Carve", async () => {
  await openCarve([FACADES, WINDOWS]);
  await press(pickButton()!);
  clickFace(0, [0.5, 0.25, 0]);
  await press(buttonIn(bar()!, "Cancel"));
  expect(bar()).toBeNull();
  expect(service.pickedSetRequests).toEqual([]);
  await press(pickButton()!);
  expect(bar()).not.toBeNull();
  openStep("Criteria");
  expect(stepIsOpen("Site")).toBe(false);
  expect(bar()).toBeNull();
  openStep("Site");
  expect(bar()).toBeNull();                       // it does not come back with the step
  await press(pickButton()!);
  expect(bar()).not.toBeNull();
  await switchMode("simulate");
  await settle();
  expect(bar()).toBeNull();
  await switchMode("design");
  await settle();
  expect(bar()).toBeNull();
  expect(service.pickedSetRequests).toEqual([]);
});

test("Carve: Rename shows the set by its new name", async () => {
  const facades = criterion("1", FACADES.name, FACADES.settings!, ["facades.obj", "picked_1.ply"]);
  await openCarve([facades], { sets: [ROOFS_SET] });
  await chooseFromSetMenu("Roofs", "Rename");
  const dialog = container().querySelector<HTMLElement>('[role="dialog"]')!;
  expect(dialog.querySelector("h2")!.textContent).toBe("Rename Roofs");
  type(dialog.querySelector<HTMLInputElement>("input")!, "South roofs");
  await press(byRole<HTMLButtonElement>(dialog, "button", "Rename"));
  expect(service.setRenames).toEqual([{ fileName: "picked_1.ply", name: "South roofs" }]);
  expect(service.requests).toContain("PUT /surface-sets/picked_1.ply/name");
  expect(container().querySelector('[role="dialog"]')).toBeNull();
  expect(setNames()).toEqual(["facades.obj", "South roofs"]);
  expect(setsOfCriterion()).toEqual(["facades.obj", "South roofs"]);
});

test("Simulate: without context a study offers no picking", async () => {
  await openSimulate(undefined, (chain) => { chain.studies = [study("1", "sky_view", ["facades.obj"])]; });
  await openStudySettings("Sky view factor");
  expect(studyPopover()!.querySelector(".study-pick-surfaces")).toBeNull();
});

test("Simulate: a study picks nothing itself; a set picked in the Site step is offered to it by its name, switched off", async () => {
  await openSimulate(undefined, (chain) => {
    chain.surroundingsFiles = [CITY];
    chain.inputFileContents["/inputs/context/city.obj"] = CITY_OBJ;
    chain.studies = [study("1", "sky_view", ["facades.obj"])];
  });
  await openStudySettings("Sky view factor");
  expect(studyPopover()!.querySelector(".study-pick-surfaces")).toBeNull();
  expect(studyPopover()!.textContent).not.toContain("Pick");
  await switchMode("design");
  await settle();
  openStep("Site");
  await press(pickButton()!);
  clickFace(0, [0.5, 0.25, 0]);
  await press(useButton());
  expect(simulateService.pickedSetRequests.map((request) => request.name)).toEqual(["Picked 1"]);
  expect(simulateService.requests.filter((request) => request.startsWith("PUT /studies/") || request.startsWith("PUT /criteria/"))).toEqual([]);
  expect(simulateService.studies[0].entry.test_surface_files).toEqual(["facades.obj"]);
  await switchMode("simulate");
  await settle();
  await openStudySettings("Sky view factor");
  const picked = [...studyPopover()!.querySelectorAll<HTMLElement>(".study-file-switches label")].find((label) => label.textContent!.includes("Picked 1"))!;
  expect(picked.querySelector("input")!.checked).toBe(false);
});

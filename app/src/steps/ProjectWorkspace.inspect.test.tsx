// Inspect (inspect design, sections 3, 5 and 6): the Files panel over the 3D view lists the input files by role; a row selects its
// file, frames it and opens its summary. In flip mode a click on a surface of the selected test surface file turns it, and a second
// click turns it back; the turns are staged until Save, which sends one request for the file, or Discard. Leaving Inspect with turns
// not saved asks to save or discard them (UnsavedTurnsDialog, as the app's switch uses it).
import { act } from "react";
import * as THREE from "three";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { InspectedFile } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import {
  NOTHING_RUN, FakeService, buttonIn, container, endWorkspaceTest, openStep, openWorkspace, packedInspectGeometry, pressRunAnalysis, project, reasonOf,
  settle, startWorkspaceTest, switchMode,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const summary = (role: string, fileName: string, overrides: Partial<InspectedFile> = {}): InspectedFile => ({
  role, file_name: fileName, triangle_count: 1, area_m2: 1, bounds: [[0, 0, 0], [1, 1, 1]], body_count: 1, closed_body_count: 0, surface_count: null,
  flippable: false, original_kept: false, problem: null, ...overrides,
});

const FILES: InspectedFile[] = [
  summary("max_volume", "volume.obj", { triangle_count: 12, area_m2: 600, bounds: [[0, 0, 0], [10, 10, 6]], closed_body_count: 1 }),
  summary("test_surfaces", "facades.obj", { triangle_count: 3, area_m2: 4.5, bounds: [[0, 0, 0], [7, 1, 2]], body_count: 2, surface_count: 2, flippable: true }),
  summary("test_surfaces", "box.obj", { triangle_count: 12, area_m2: 6, closed_body_count: 1, surface_count: 1 }),
  summary("context", "broken.obj", { triangle_count: 0, area_m2: 0, body_count: 0, problem: "The context file 'broken.obj' cannot be read: no faces." }),
  summary("terrain", "ground.obj", { triangle_count: 2, area_m2: 10000, bounds: [[4500000, 0, 0], [4500100, 100, 0]] }),
];

/** facades.obj: triangles 0 and 1 are surface 0 (a square on the ground), triangle 2 is surface 1 (a wall). */
const facadesGeometry = () => packedInspectGeometry([0, 0, 0], [0, 0, 0, 1, 0, 0, 1, 1, 0,   0, 0, 0, 1, 1, 0, 0, 1, 0,   5, 0, 0, 7, 0, 0, 5, 0, 2],
  [0, 0, 1], [{ centre: [0.5, 0.5, 0], normal: [0, 0, 1], area: 1 }, { centre: [5.7, 0, 0.7], normal: [0, -1, 0], area: 2 }]);
const boxGeometry = () => packedInspectGeometry([0, 0, 0], [0, 0, 0, 1, 0, 0, 0, 1, 0], [0], [{ centre: [0.3, 0.3, 0], normal: [0, 0, -1], area: 0.5 }]);

/** Opens the project with FILES as its input files, *beforeInspect* done in Design, then switches to Inspect. */
async function openInspect(beforeInspect: () => Promise<void> = async () => {}): Promise<FakeService> {
  const service = new FakeService(NOTHING_RUN, null);
  service.inspection = FILES;
  service.inspectGeometries = { "facades.obj": facadesGeometry(), "box.obj": boxGeometry() };
  const opened = project(NOTHING_RUN);
  opened.inputs = { ...opened.inputs, test_surfaces: [{ name: "facades.obj", triangle_count: 3 }, { name: "box.obj", triangle_count: 12 }] };
  await openWorkspace(service, opened);
  await beforeInspect();
  await switchMode("inspect");
  await settle();
  return service;
}

/** Text with its no-break spaces (between digit groups, before a unit) read as spaces. */
const plain = (element: Element | null | undefined) => element?.textContent?.replace(/\s/g, " ") ?? null;
const filesPanel = () => container().querySelector<HTMLElement>(".files-panel")!;
const fileRow = (fileName: string) => filesPanel().querySelector<HTMLElement>(`.inspect-file[data-file-name="${fileName}"]`)!;
const roleTitles = () => [...filesPanel().querySelectorAll(".inspect-role-title")].map((title) => title.textContent);
const fileNames = () => [...filesPanel().querySelectorAll(".inspect-file-name")].map((name) => name.textContent);
const fileLine = (fileName: string) => plain(fileRow(fileName).querySelector(".inspect-file-line"));
const turnedLine = (fileName: string) => plain(fileRow(fileName).querySelector(".inspect-file-turned"));
const summaryLines = () => [...filesPanel().querySelectorAll(".inspect-summary p")].map(plain);
const button = (label: string) => buttonIn(filesPanel(), label);
const dialog = () => container().querySelector<HTMLElement>('[role="dialog"]');
const stepsPanel = () => container().querySelector<HTMLElement>(".workspace-panel")!;

async function press(target: HTMLButtonElement) {
  await act(async () => target.click());
  await settle();
}

async function selectFile(fileName: string) {
  await press(fileRow(fileName).querySelector<HTMLButtonElement>(".inspect-file-select")!);
}

/** The mesh of *fileName* in the surface orientation layer. */
const meshOf = (fileName: string) => FakeViewerScene.latest!.layers.get("inspect_surfaces")!.getObjectByName(fileName)!.children[0] as THREE.Mesh;
/** The corner order the layer draws the file's triangles in: a turned triangle has its last two corners swapped. */
const drawnIndex = (fileName: string) => Array.from(meshOf(fileName).geometry.index!.array);

/** A click on the view that lands on triangle *triangle* of *fileName*. */
function clickTriangle(fileName: string, triangle: number) {
  const hit = { object: meshOf(fileName), faceIndex: triangle, distance: 1, point: new THREE.Vector3() } as THREE.Intersection;
  act(() => FakeViewerScene.latest!.clickLayer("inspect_surfaces", hit));
}

test("opening Inspect lists the files by role with triangles and area; a row selects its file, frames its bounds and shows its summary", async () => {
  const service = await openInspect();
  expect(service.count("GET /inspect")).toBe(1);
  expect(service.count("GET /inspect/test_surfaces/facades.obj/geometry")).toBe(1);
  expect(service.count("GET /inspect/test_surfaces/box.obj/geometry")).toBe(1);
  expect(roleTitles()).toEqual(["Maximum volume", "Test surfaces", "Existing surroundings", "Terrain"]);
  expect(fileNames()).toEqual(["volume.obj", "facades.obj", "box.obj", "broken.obj", "ground.obj"]);
  expect(fileLine("volume.obj")).toBe("12 triangles, 600 m²");
  expect(fileLine("facades.obj")).toBe("3 triangles, 4.5 m²");
  expect(plain(filesPanel().querySelector(".inspect-view-origin"))).toBe("The view is drawn around x 0, y 0, z 0.");
  // A file that cannot be read is listed with its problem, and nothing to select.
  expect(plain(fileRow("broken.obj").querySelector(".inspect-file-problem"))).toBe("The context file 'broken.obj' cannot be read: no faces.");
  expect(fileRow("broken.obj").querySelector("button")).toBeNull();
  // The view draws the orientation of the test surface files in place of the test surfaces.
  const scene = FakeViewerScene.latest!;
  expect(scene.layers.get("inspect_surfaces")!.children.map((file) => file.name)).toEqual(["facades.obj", "box.obj"]);
  expect(scene.visibleLayers.has("test_surfaces")).toBe(false);

  await selectFile("facades.obj");
  expect(fileRow("facades.obj").getAttribute("aria-current")).toBe("true");
  expect(summaryLines()).toEqual(["Bounds: x 0 to 7, y 0 to 1, z 0 to 2 m", "Closed bodies: 0 of 2", "Surfaces: 2"]);
  expect(scene.framedBoxes.at(-1)).toEqual({ min: [0, 0, 0], max: [7, 1, 2] });

  await selectFile("ground.obj");
  expect(fileRow("facades.obj").getAttribute("aria-current")).toBeNull();
  expect(summaryLines()).toEqual(["Bounds: x 4 500 000 to 4 500 100, y 0 to 100, z 0 to 0 m", "Georeferenced coordinates, about 4 500 km from 0.",
                                  "Closed bodies: 0 of 1"]);
  expect(scene.framedBoxes.at(-1)).toEqual({ min: [4500000, 0, 0], max: [4500100, 100, 0] });
});

test("in flip mode two clicks on a surface turn it and turn it back; Flip all turns every surface; Discard drops the turns", async () => {
  await openInspect();
  await selectFile("facades.obj");
  const scene = FakeViewerScene.latest!;
  const drawn = scene.layers.get("inspect_surfaces");
  clickTriangle("facades.obj", 2);
  expect(turnedLine("facades.obj")).toBeNull();          // outside flip mode a click turns nothing
  await press(button("Flip mode"));
  expect(button("Flip mode").getAttribute("aria-pressed")).toBe("true");
  expect(scene.layers.get("inspect_surfaces")).toBe(drawn);       // the layer is drawn again for turns, not for every change of the panel

  clickTriangle("facades.obj", 2);
  expect(turnedLine("facades.obj")).toBe("1 surface turned, not saved");
  expect(drawnIndex("facades.obj")).toEqual([0, 1, 2, 3, 4, 5, 6, 8, 7]);
  clickTriangle("facades.obj", 2);
  expect(turnedLine("facades.obj")).toBeNull();
  expect(drawnIndex("facades.obj")).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);

  await press(button("Flip all"));
  expect(turnedLine("facades.obj")).toBe("2 surfaces turned, not saved");
  expect(drawnIndex("facades.obj")).toEqual([0, 2, 1, 3, 5, 4, 6, 8, 7]);
  await press(button("Discard"));
  expect(turnedLine("facades.obj")).toBeNull();
  expect(drawnIndex("facades.obj")).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
});

test("Save sends the turned surfaces once, then asks for the stage status, the stored files and the geometry again; Restore original puts the original back", async () => {
  const service = await openInspect();
  await selectFile("facades.obj");
  await press(button("Flip mode"));
  clickTriangle("facades.obj", 2);
  const counts = () => ({
    stages: service.count("GET /stage-status"), stored: service.count("GET /inputs/test_surfaces"), inspection: service.count("GET /inspect"),
    geometry: service.count("GET /inspect/test_surfaces/facades.obj/geometry"),
  });
  const before = counts();
  await press(button("Save"));
  expect(service.turnRequests).toEqual([{ fileName: "facades.obj", body: { surfaces: [1] } }]);
  expect(counts()).toEqual({ stages: before.stages + 1, stored: before.stored + 1, inspection: before.inspection + 1, geometry: before.geometry + 1 });
  expect(turnedLine("facades.obj")).toBeNull();
  expect(button("Save")).toBeUndefined();
  expect(button("Restore original")).toBeDefined();

  const saved = counts();
  await press(button("Restore original"));
  expect(service.count("POST /inspect/test_surfaces/facades.obj/restore")).toBe(1);
  expect(counts()).toEqual({ stages: saved.stages + 1, stored: saved.stored + 1, inspection: saved.inspection + 1, geometry: saved.geometry + 1 });
  expect(button("Restore original")).toBeUndefined();
  expect(service.turnRequests).toHaveLength(1);
});

test("a file closed as a whole cannot be flipped: Flip mode and Flip all are disabled with the reason", async () => {
  await openInspect();
  await selectFile("box.obj");
  const flipMode = button("Flip mode");
  expect(flipMode.disabled).toBe(true);
  expect(reasonOf(flipMode)).toBe("This file is closed as a whole, so its surfaces cannot be flipped.");
  expect(button("Flip all").disabled).toBe(true);
  expect(summaryLines()).toContain("Surfaces: 1");
});

test("during a run of the project the surfaces can be turned but Save is disabled with the reason, until the run ends", async () => {
  await openInspect(async () => {
    openStep("Site and grid");
    await pressRunAnalysis();
  });
  expect(FakeWebSocket.opened).toHaveLength(1);
  await selectFile("facades.obj");
  await press(button("Flip mode"));
  clickTriangle("facades.obj", 2);
  expect(turnedLine("facades.obj")).toBe("1 surface turned, not saved");
  expect(button("Save").disabled).toBe(true);
  expect(reasonOf(button("Save"))).toBe("A run is in progress");

  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();
  expect(button("Save").disabled).toBe(false);
});

test("leaving Inspect with turns not saved asks first: Stay keeps Inspect, Discard leaves without a request, Save saves then leaves", async () => {
  const service = await openInspect();
  await selectFile("facades.obj");
  await press(button("Flip mode"));
  clickTriangle("facades.obj", 2);

  await switchMode("design");
  expect(dialog()!.querySelector("h2")!.textContent).toBe("Save the turned surfaces before leaving Inspect?");
  expect(stepsPanel().hidden).toBe(true);
  await press(buttonIn(dialog()!, "Stay"));
  expect(dialog()).toBeNull();
  expect(stepsPanel().hidden).toBe(true);
  expect(turnedLine("facades.obj")).toBe("1 surface turned, not saved");

  await switchMode("design");
  await press(buttonIn(dialog()!, "Discard"));
  expect(dialog()).toBeNull();
  expect(stepsPanel().hidden).toBe(false);
  expect(container().querySelector(".files-panel")).toBeNull();
  expect(service.turnRequests).toEqual([]);

  await switchMode("inspect");
  await settle();
  expect(turnedLine("facades.obj")).toBeNull();          // the discarded turns are gone
  await selectFile("facades.obj");
  await press(button("Flip mode"));
  clickTriangle("facades.obj", 0);
  await switchMode("design");
  await press(buttonIn(dialog()!, "Save"));
  expect(service.turnRequests).toEqual([{ fileName: "facades.obj", body: { surfaces: [0] } }]);
  expect(dialog()).toBeNull();
  expect(stepsPanel().hidden).toBe(false);

  await switchMode("inspect");             // nothing left to save: no question
  await settle();
  await switchMode("design");
  expect(dialog()).toBeNull();
  expect(stepsPanel().hidden).toBe(false);
});

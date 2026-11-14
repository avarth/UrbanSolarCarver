// Test surfaces drawn on the ground (design/test-surfaces-on-ground.md): Draw in the Site step's Test surfaces box draws an outline
// with the site editor, saved at once as a surface set; Edit outline in its menu edits it, each change saved, with Undo in the session.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { InputFileInfo } from "../api_client/client";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { byRole } from "../viewer_overlays/render_for_test";
import {
  buttonIn, CARVED, container, endWorkspaceTest, FakeService, NOTHING_RUN, openStep, openWorkspace, pressRunAnalysis, project, settle,
  startWorkspaceTest, surfaceSetsBox,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const GROUND_SET: InputFileInfo = { name: "ground_1.ply", triangle_count: 2, shown_name: "Square", drawn: true };
const SQUARE = { points: [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 10, 0]], holes: [] };

const box = () => surfaceSetsBox()!;
const editor = () => container().querySelector<HTMLElement>(".site-editor");
const titleButtons = () => [...box().querySelectorAll(".input-box-title-row button")].map((button) => button.textContent);
/** Clicks the fake top view at the plan point (x, y) in metres (10 pixels a metre about pixel (400, 300)). */
const clickAt = async (x: number, y: number) => {
  act(() => { FakeViewerScene.latest!.clickView(400 + x * 10, 300 - y * 10); });
  await settle();
};
const key = async (name: string, options: KeyboardEventInit = {}) => {
  act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, ...options })); });
  await settle();
};
async function press(button: HTMLButtonElement) {
  await act(async () => button.click());
  await settle();
}
function menuItems(setName: string) {
  act(() => byRole<HTMLButtonElement>(box(), "button", `Actions for ${setName}`).click());
  return [...box().querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
}
async function chooseFromSetMenu(setName: string, item: string) {
  await press(menuItems(setName).find((candidate) => candidate.textContent === item)!);
}
async function openWith(service: FakeService, sets: InputFileInfo[] = []) {
  service.storedTestSurfaces = [...service.storedTestSurfaces, ...sets];
  const opened = project(NOTHING_RUN);
  await openWorkspace(service, { ...opened, inputs: { ...opened.inputs, test_surfaces: service.storedTestSurfaces } });
}
/** Drags a vertex handle of the editor to the plan point (x, y), without waiting for the service. */
function dragHandleNow(label: string, x: number, y: number) {
  const handle = container().querySelector(`[aria-label="${label}"]`)!;
  vi.spyOn(editor()!, "getBoundingClientRect").mockReturnValue(
    { left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, x: 0, y: 0, toJSON: () => ({}) });
  const at = { clientX: 400 + x * 10, clientY: 300 - y * 10 };
  act(() => { handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: 600, clientY: 300 })); });
  act(() => { handle.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, ...at })); });
  act(() => { handle.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, ...at })); });
}
async function dragHandle(label: string, x: number, y: number) {
  dragHandleNow(label, x, y);
  await settle();
}

test("Draw in the Test surfaces box draws a rectangle on the ground, saved at once as Ground 1, then edited", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWith(service);
  expect(titleButtons()).toEqual(["Draw", "Import"]);
  await press(buttonIn(box(), "Draw"));
  expect(editor()!.textContent).toContain("Drawing Ground 1");
  await press([...editor()!.querySelectorAll<HTMLButtonElement>(".site-editor-shapes button")].find((button) => button.textContent === "Rectangle")!);
  await clickAt(0, 0);
  await clickAt(20, 10);
  expect(service.drawnSetRequests).toEqual([{ outline: { points: SQUARE.points, holes: [] } }]);
  expect(editor()!.textContent).toContain("Editing Ground 1");
  expect([...box().querySelectorAll(".input-file-name")].map((name) => name.textContent)).toContain("Ground 1");
});

test("Edit outline opens a drawn set; a vertex moved is saved over it; Undo sends the outline before", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = SQUARE;
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  expect(editor()!.textContent).toContain("Editing Square");
  await dragHandle("Vertex 2", 30, 0);
  expect(service.drawnSetRequests.at(-1)).toEqual({ outline: { points: [[0, 0, 0], [30, 0, 0], [20, 10, 0], [0, 10, 0]], holes: [] }, replace: "ground_1.ply" });
  await key("z", { ctrlKey: true });
  expect(service.drawnSetRequests.at(-1)).toEqual({ outline: SQUARE, replace: "ground_1.ply" });
  await key("Escape");
  expect(editor()).toBeNull();
});

test("Draw hole in the editor saves the outline with its hole", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = SQUARE;
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  await press(buttonIn(editor()!, "Draw hole"));
  for (const [x, y] of [[5, 2], [10, 2], [10, 6]]) await clickAt(x, y);
  await clickAt(5, 2);
  expect(service.drawnSetRequests.at(-1)).toEqual({ outline: { ...SQUARE, holes: [[[5, 2, 0], [10, 2, 0], [10, 6, 0]]] }, replace: "ground_1.ply" });
});

test("a refused change shows the service's reason in the editor", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = SQUARE;
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  service.drawRefusal = "Not saved: the outline crosses itself.";
  await dragHandle("Vertex 2", 30, 0);
  expect(editor()!.textContent).toContain("Not saved: the outline crosses itself.");
});

test("a picked set's menu has Edit picks, a drawn set's Edit outline, an imported set's neither", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWith(service, [GROUND_SET]);
  expect(menuItems("Square").map((item) => item.textContent)).toEqual(["Rename", "Edit outline"]);
  act(() => byRole<HTMLButtonElement>(box(), "button", "Actions for Square").click());      // closes its menu
  expect(menuItems("surfaces.obj").map((item) => item.textContent)).toEqual(["Rename"]);
});

test("while a run is in progress Draw and Edit outline are disabled with the reason", async () => {
  const analysisOutOfDate = { ...CARVED, preprocessing: "out_of_date" as const };
  const service = new FakeService(analysisOutOfDate, null);
  service.storedTestSurfaces = [...service.storedTestSurfaces, GROUND_SET];
  const opened = project(analysisOutOfDate);
  await openWorkspace(service, { ...opened, inputs: { ...opened.inputs, test_surfaces: service.storedTestSurfaces } });
  openStep("Criteria");
  await pressRunAnalysis();
  openStep("Site");
  expect(buttonIn(box(), "Draw").disabled).toBe(true);
  const editOutline = menuItems("Square").find((item) => item.textContent === "Edit outline")!;
  expect(editOutline.getAttribute("aria-disabled") === "true" || editOutline.disabled).toBe(true);
});


test("a vertex moved stays where it was put while it is saved, and two quick moves are both kept", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = SQUARE;
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  dragHandleNow("Vertex 2", 30, 0);
  expect(container().querySelector('[aria-label="Vertex 2"]')!.getAttribute("cx")).toBe("700");
  dragHandleNow("Vertex 3", 30, 15);
  await settle();
  expect(service.drawnSetRequests.at(-1)!.outline.points).toEqual([[0, 0, 0], [30, 0, 0], [30, 15, 0], [0, 10, 0]]);
  await key("z", { ctrlKey: true });
  expect(service.drawnSetRequests.at(-1)!.outline.points).toEqual([[0, 0, 0], [30, 0, 0], [20, 10, 0], [0, 10, 0]]);
});

test("a refused move puts the vertex back", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = SQUARE;
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  service.drawRefusal = "Not saved: the outline crosses itself.";
  await dragHandle("Vertex 2", 30, 0);
  expect(container().querySelector('[aria-label="Vertex 2"]')!.getAttribute("cx")).toBe("600");
});

test("a hole in a raised surface is drawn on the surface's level", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = { points: SQUARE.points.map(([x, y]) => [x, y, 10]), holes: [] };
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  await press(buttonIn(editor()!, "Draw hole"));
  const levels = vi.spyOn(FakeViewerScene.latest!, "pointOnLevel");
  await clickAt(5, 2);
  expect(levels.mock.calls.at(-1)![2]).toBe(10);
});

test("a refused hole keeps the hole drawing open with the reason", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.groundOutlines["ground_1.ply"] = SQUARE;
  await openWith(service, [GROUND_SET]);
  await chooseFromSetMenu("Square", "Edit outline");
  await press(buttonIn(editor()!, "Draw hole"));
  service.drawRefusal = "Not saved: hole 1 is not strictly inside the outline.";
  for (const [x, y] of [[5, 2], [10, 2], [10, 6]]) await clickAt(x, y);
  await clickAt(5, 2);
  expect(editor()!.textContent).toContain("Drawing a hole in Square");
  expect(editor()!.textContent).toContain("hole 1 is not strictly inside the outline");
});

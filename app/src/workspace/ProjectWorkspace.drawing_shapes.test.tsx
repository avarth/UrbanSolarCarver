// Shapes in the site editor: Polygon, Rectangle and Tilted rectangle in its bar, for sites, holes and drawn context blocks.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { buttonIn, container, endWorkspaceTest, FakeService, NOTHING_RUN, openWorkspace, project, settle, startWorkspaceTest } from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(() => {
  vi.restoreAllMocks();
  endWorkspaceTest();
});

const panel = () => container().querySelector(".workspace-panel")!;
const editor = () => container().querySelector<HTMLElement>(".site-editor");
const boxNamed = (title: string) => [...panel().querySelectorAll<HTMLElement>(".input-box")].find((box) => box.querySelector(".input-box-title-row h3")?.textContent === title)!;
const shapeButtons = () => [...editor()!.querySelectorAll<HTMLButtonElement>(".site-editor-shapes button")];
const shapeButton = (label: string) => shapeButtons().find((button) => button.textContent === label)!;
const key = async (name: string, options: KeyboardEventInit = {}) => {
  act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, ...options })); });
  await settle();
};
/** Clicks the fake top view at the plan point (x, y) in metres (10 pixels a metre about pixel (400, 300)). */
const clickAt = async (x: number, y: number, shift = false) => {
  act(() => { FakeViewerScene.latest!.clickView(400 + x * 10, 300 - y * 10, shift); });
  await settle();
};
async function chooseShape(label: string) {
  act(() => { shapeButton(label).click(); });
  await settle();
}

async function openWithSites(service: FakeService) {
  service.siteSource = "sites";
  const detail = project(NOTHING_RUN);
  await openWorkspace(service, { ...detail, inputs: { ...detail.inputs, max_volume: [] }, joined_bounds: null });
}
async function drawSite() {
  act(() => { buttonIn(boxNamed("Sites"), "Draw").click(); });
  await settle();
}

test("the bar offers the three shapes while drawing, Polygon first and chosen", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSites(service);
  await drawSite();
  expect(shapeButtons().map((button) => button.textContent)).toEqual(["Polygon", "Rectangle", "Tilted rectangle"]);
  expect(shapeButtons().map((button) => button.getAttribute("aria-pressed"))).toEqual(["true", "false", "false"]);
  await chooseShape("Rectangle");
  expect(shapeButtons().map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
  expect(editor()!.textContent).toContain("Click one corner, then the opposite corner");
  await chooseShape("Tilted rectangle");
  expect(editor()!.textContent).toContain("Click two points for the first side, then a third for the width");
});

test("a rectangle is two clicks on opposite corners, saved as a site with its four corners", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSites(service);
  await drawSite();
  await chooseShape("Rectangle");
  await clickAt(0, 0);
  expect(service.savedSites).toHaveLength(0);
  await clickAt(20, 10);
  expect(service.savedSites).toEqual([[{ name: "Site 1", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 10, 0]], height: 30 }]]);
  expect(editor()!.textContent).toContain("Editing Site 1");
});

test("a rectangle's corner snaps to another site's vertex; Backspace takes back a corner; a second click on the first does nothing", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [{ name: "Plot A", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 10, 0]], height: 30 }];
  await openWithSites(service);
  await drawSite();
  await chooseShape("Rectangle");
  await clickAt(50, 50);
  await key("Backspace");
  await clickAt(20.3, 0.2);                     // within 10 pixels of Plot A's corner
  await clickAt(20.3, 0.2);                     // the same corner again: no rectangle
  expect(service.savedSites).toHaveLength(0);
  await clickAt(40, 10);
  expect(service.savedSites[0][1].points).toEqual([[20, 0, 0], [40, 0, 0], [40, 10, 0], [20, 10, 0]]);
});

test("a tilted rectangle is a side from two clicks, Shift holding it to 15 degree steps, then a click for the width", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSites(service);
  await drawSite();
  await chooseShape("Tilted rectangle");
  await clickAt(0, 0);
  await clickAt(8, 6);
  expect(service.savedSites).toHaveLength(0);
  await clickAt(5, 10);
  expect(service.savedSites[0][0].points).toEqual([[0, 0, 0], [8, 6, 0], [5, 10, 0], [-3, 4, 0]]);

  // Shift on the second click: the side along x, its length kept
  act(() => { buttonIn(boxNamed("Sites"), "Draw").click(); });
  await settle();
  expect(shapeButton("Tilted rectangle").getAttribute("aria-pressed")).toBe("true");     // the shape stays chosen
  await clickAt(30, 0);
  await clickAt(40, 1, true);
  await clickAt(35, 5);
  expect(service.savedSites[1][1].points).toEqual([[30, 0, 0], [40.05, 0, 0], [40.05, 5, 0], [30, 5, 0]]);
});

test("another shape starts the drawing again", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSites(service);
  await drawSite();
  await clickAt(0, 0);
  await clickAt(20, 0);
  await chooseShape("Rectangle");
  await clickAt(0, 0);
  await clickAt(10, 10);
  expect(service.savedSites[0][0].points).toEqual([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]);
});

test("the pointer previews the rectangle and its size", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSites(service);
  await drawSite();
  vi.spyOn(editor()!, "getBoundingClientRect").mockReturnValue(
    { left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, x: 0, y: 0, toJSON: () => ({}) });
  await chooseShape("Rectangle");
  await clickAt(0, 0);
  act(() => { window.dispatchEvent(new PointerEvent("pointermove", { clientX: 600, clientY: 200 })); });     // (20, 10)
  await settle();
  expect(editor()!.querySelector(".site-editor-preview")!.getAttribute("points")).toBe("400.0,300.0 600.0,300.0 600.0,200.0 400.0,200.0");
  expect(editor()!.textContent).toContain("20 × 10 m");
});

test("Draw hole draws a rectangle hole", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [{ name: "Block", points: [[0, 0, 0], [60, 0, 0], [60, 50, 0], [0, 50, 0]], height: 20 }];
  await openWithSites(service);
  await clickAt(30, 25);                         // edits the site
  act(() => { buttonIn(editor()!, "Draw hole").click(); });
  await settle();
  await chooseShape("Rectangle");
  await clickAt(20, 15);
  await clickAt(40, 35);
  expect(service.savedSites[0][0].holes).toEqual([[[20, 15, 0], [40, 15, 0], [40, 35, 0], [20, 35, 0]]]);
});

test("a context block is drawn as a tilted rectangle", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  act(() => { buttonIn(boxNamed("Context"), "Draw").click(); });
  await settle();
  expect(editor()!.textContent).toContain("Drawing Block 1");
  await chooseShape("Tilted rectangle");
  await clickAt(100, 100);
  await clickAt(110, 100);
  await clickAt(105, 108);
  expect(service.savedContextBlocks.at(-1)![0].points).toEqual([[100, 100, 0], [110, 100, 0], [110, 108, 0], [100, 108, 0]]);
});

// Sites from DXF and OBJ files (design/site-import.md): Import and a dropped file read the outlines, the window shows what was found,
// Import adds them as one undoable change, and a site's menu places it on the terrain or restores its original outline.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { OutlinesReply, SiteJson } from "../api_client/client";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import {
  buttonIn, container, endWorkspaceTest, FakeService, NOTHING_RUN, openWorkspace, project, reasonOf, settle, startWorkspaceTest,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

/** A project of sites with no maximum volume file; with terrain, one terrain file. */
function sitesProject(withTerrain = false) {
  const detail = project(NOTHING_RUN);
  return { ...detail, inputs: { ...detail.inputs, max_volume: [], ...(withTerrain ? { terrain: [{ name: "terrain.obj", triangle_count: 1 }] } : {}) },
           joined_bounds: null };
}

const EXISTING: SiteJson = { name: "Site 1", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0]], height: 40 };
const FLAT_PLOT = { name: "Plot A", points: [[100, 0, 5], [130, 0, 5], [130, 20, 5], [100, 20, 5]], area: 600, rise: 0 };
const SLOPED_PLOT = { name: "", points: [[200, 0, 0], [240, 0, 45.3], [240, 30, 10]], area: 600, rise: 45.3 };
const FOUND: OutlinesReply = {
  file: "plots.dxf", unit: "metres", outlines: [FLAT_PLOT, SLOPED_PLOT], left_out: ["2 open polylines", "Plot 7: the outline crosses itself"],
  distance_from_inputs: 4200,
};

const panel = () => container().querySelector(".workspace-panel")!;
const sitesBox = () => panel().querySelector<HTMLElement>(".input-box")!;
const importWindow = () => [...document.body.querySelectorAll<HTMLElement>("[role='dialog']")]
  .find((dialog) => dialog.querySelector("h2")?.textContent?.startsWith("Import sites from")) ?? null;

async function openWith(service: FakeService, withTerrain = false) {
  service.siteSource = "sites";
  await openWorkspace(service, sitesProject(withTerrain));
}

/** Chooses *name* with the Sites box's Import button and its hidden file picker. */
async function chooseFile(name: string) {
  const picker = sitesBox().querySelector<HTMLInputElement>('input[type="file"][accept=".dxf,.obj"]')!;
  expect(picker.hidden).toBe(true);
  const click = vi.spyOn(picker, "click").mockImplementation(() => {});
  act(() => { buttonIn(sitesBox(), "Import").click(); });
  expect(click).toHaveBeenCalled();
  Object.defineProperty(picker, "files", { value: [new File(["0\nSECTION"], name)], configurable: true });
  act(() => picker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
}

async function dropFile(name: string) {
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [new File(["v 0 0 0"], name)] } });
  act(() => { sitesBox().dispatchEvent(drop); });
  await settle();
}

async function pressInWindow(text: string) {
  await act(async () => { buttonIn(importWindow()!, text).click(); });
  await settle();
}

/** The items of the menu of the site at *siteIndex*, opened first when it is closed. */
const rowMenuItems = (siteIndex: number) => {
  const row = panel().querySelectorAll(".site-row")[siteIndex];
  const menuButton = row.querySelector<HTMLButtonElement>(".action-menu-button")!;
  if (menuButton.getAttribute("aria-expanded") !== "true") act(() => { menuButton.click(); });
  return [...row.querySelectorAll<HTMLButtonElement>("[role='menuitem']")];
};
const menuItem = (siteIndex: number, label: string) => rowMenuItems(siteIndex).find((item) => item.textContent === label) ?? null;
async function chooseInMenu(siteIndex: number, label: string) {
  const item = menuItem(siteIndex, label)!;
  await act(async () => { item.click(); });
  await settle();
}

test("the Sites box has Draw and Import, and an empty box says a file can be dropped on it", async () => {
  await openWith(new FakeService(NOTHING_RUN, null));
  expect([...sitesBox().querySelectorAll(".site-box-actions button")].map((button) => button.textContent)).toEqual(["Draw", "Import"]);
  expect(sitesBox().textContent).toContain(
    "The plots you may build on: closed outlines in plan, drawn in the 3D view or imported, each with its base and max height.");
  expect(sitesBox().textContent).toContain("You can also drag a DXF or OBJ file of closed polylines onto this box.");
});

test("a chosen file is read and the window shows the outlines found, what was left out and how far they are", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = FOUND;
  await openWith(service);
  await chooseFile("plots.dxf");
  expect(service.count("POST /outlines")).toBe(1);
  expect(service.outlineFilesRead).toEqual(["plots.dxf"]);
  const dialog = importWindow()!;
  expect(dialog.querySelector("h2")!.textContent).toBe("Import sites from plots.dxf");
  expect(dialog.textContent).toContain("2 closed polylines, read in metres.");
  const lines = [...dialog.querySelectorAll(".import-sites-list li")].map((line) => line.textContent);
  expect(lines).toEqual(["Plot A600 m², rise 0 m", "Site 2600 m², rise 45.3 m"]);
  expect(dialog.textContent).toContain("Left out:");
  expect([...dialog.querySelectorAll(".import-sites-left-out li")].map((line) => line.textContent))
    .toEqual(["2 open polylines", "Plot 7: the outline crosses itself"]);
  expect(dialog.textContent).toContain("The outlines are 4.2 km from the other inputs.");
  expect(dialog.querySelector("input[type='checkbox']")).toBeNull();          // no terrain: no Place on terrain
  expect(buttonIn(dialog, "Import 2 sites")).toBeTruthy();
});

test("Cancel closes the window and adds nothing", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = FOUND;
  service.sites = [EXISTING];
  await openWith(service);
  await chooseFile("plots.dxf");
  await pressInWindow("Cancel");
  expect(importWindow()).toBeNull();
  expect(service.savedSites).toHaveLength(0);
  expect(panel().querySelectorAll(".site-row")).toHaveLength(1);
});

test("Import adds the outlines after the sites in one save, with names, heights and originals, frames them, and one undo takes them all back", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = { ...FOUND, left_out: [], distance_from_inputs: null };
  service.sites = [EXISTING];
  await openWith(service);
  await chooseFile("plots.dxf");
  const dialog = importWindow()!;
  expect(dialog.querySelector(".import-sites-left-out")).toBeNull();
  expect(dialog.querySelector(".input-box-problem")).toBeNull();
  const scene = FakeViewerScene.latest!;
  const framedBefore = scene.framedAll + scene.framedBoxes.length;
  await pressInWindow("Import 2 sites");
  expect(importWindow()).toBeNull();
  expect(service.count("PUT /sites")).toBe(1);
  expect(service.terrainRequests).toHaveLength(0);
  expect(service.savedSites[0]).toEqual([
    EXISTING,
    { name: "Plot A", points: FLAT_PLOT.points, height: 40, original: { file: "plots.dxf", points: FLAT_PLOT.points } },
    { name: "Site 3", points: SLOPED_PLOT.points, height: 47, original: { file: "plots.dxf", points: SLOPED_PLOT.points } },
  ]);
  expect(panel().querySelectorAll(".site-row")).toHaveLength(3);
  expect(scene.framedAll + scene.framedBoxes.length).toBeGreaterThan(framedBefore);

  // Undo, in the site editor, takes the import back as one change
  await chooseInMenu(1, "Edit outline");
  act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true })); });
  await settle();
  expect(service.savedSites).toHaveLength(2);
  expect(service.savedSites[1]).toEqual([EXISTING]);
});

test("with terrain, Place on terrain is on: the outlines take the terrain's heights and the vertices without terrain are counted", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = { ...FOUND, left_out: [], distance_from_inputs: null };
  service.terrainHeightsOf = (points) => points.map(([x]) => (x === 130 || x === 240 ? null : 12));
  await openWith(service, true);
  await chooseFile("plots.dxf");
  const box = importWindow()!.querySelector<HTMLInputElement>("input[type='checkbox']")!;
  expect(importWindow()!.textContent).toContain("Place on terrain");
  expect(box.checked).toBe(true);
  await pressInWindow("Import 2 sites");
  expect(service.terrainRequests).toEqual([FLAT_PLOT.points.map(([x, y]) => [x, y]), SLOPED_PLOT.points.map(([x, y]) => [x, y])]);
  expect(service.count("PUT /sites")).toBe(1);
  const [plotA, site2] = service.savedSites[0];
  expect(plotA.points).toEqual([[100, 0, 12], [130, 0, 5], [130, 20, 5], [100, 20, 12]]);
  expect(plotA.original!.points).toEqual(FLAT_PLOT.points);                    // as read, before the terrain
  expect(site2.points).toEqual([[200, 0, 12], [240, 0, 45.3], [240, 30, 10]]);
  expect(site2.height).toBe(Math.max(30, Math.ceil(45.3 - 10 + 1)));
  expect(sitesBox().querySelector("[role='status']")!.textContent).toBe("4 vertices have no terrain under them and kept their elevation.");
});

test("with terrain, Place on terrain switched off keeps the elevations as read", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = { ...FOUND, outlines: [FLAT_PLOT] };
  await openWith(service, true);
  await chooseFile("plots.dxf");
  const box = importWindow()!.querySelector<HTMLInputElement>("input[type='checkbox']")!;
  act(() => { box.click(); });
  expect(box.checked).toBe(false);
  await pressInWindow("Import 1 site");
  expect(service.terrainRequests).toHaveLength(0);
  expect(service.savedSites[0][0].points).toEqual(FLAT_PLOT.points);
});

test("a file the service cannot read shows its reason in the Sites box and opens no window", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = { status: 422, detail: "The file has no closed polylines." };
  await openWith(service);
  await chooseFile("lines.dxf");
  expect(importWindow()).toBeNull();
  expect(sitesBox().querySelector("[role='alert']")!.textContent).toContain("The file has no closed polylines.");
  expect(service.savedSites).toHaveLength(0);
});

test("without terrain a site's Place on terrain waits, with the reason", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [EXISTING];
  await openWith(service);
  const item = menuItem(0, "Place on terrain")!;
  expect(item.getAttribute("aria-disabled")).toBe("true");
  expect(reasonOf(item)).toBe("Add terrain in the Site step to use this");
  await chooseInMenu(0, "Place on terrain");
  expect(service.terrainRequests).toHaveLength(0);
  expect(service.savedSites).toHaveLength(0);
});

test("with terrain a site's Place on terrain saves the terrain's heights", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [EXISTING];
  service.terrainHeightsOf = (points) => points.map(([x]) => x / 2);
  await openWith(service, true);
  expect(menuItem(0, "Place on terrain")!.getAttribute("aria-disabled")).toBeNull();
  await chooseInMenu(0, "Place on terrain");
  expect(service.terrainRequests).toEqual([[[0, 0], [20, 0], [20, 10]]]);
  expect(service.savedSites).toHaveLength(1);
  expect(service.savedSites[0][0].points).toEqual([[0, 0, 0], [20, 0, 10], [20, 10, 10]]);
  expect(sitesBox().querySelector("[role='status']")).toBeNull();
});

test("Restore original is offered only once the outline differs from the imported one, and puts it back", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  const original = { file: "plots.dxf", points: FLAT_PLOT.points };
  service.sites = [{ name: "Plot A", points: FLAT_PLOT.points, height: 40, original }, EXISTING];
  service.terrainHeightsOf = (points) => points.map(() => 20);
  await openWith(service, true);
  expect(menuItem(0, "Restore original")).toBeNull();
  expect(menuItem(1, "Restore original")).toBeNull();                         // a drawn site has no original
  await chooseInMenu(0, "Place on terrain");
  expect(service.savedSites.at(-1)![0].points).toEqual([[100, 0, 20], [130, 0, 20], [130, 20, 20], [100, 20, 20]]);
  expect(menuItem(0, "Restore original")).not.toBeNull();
  await chooseInMenu(0, "Restore original");
  expect(service.savedSites).toHaveLength(2);
  expect(service.savedSites[1][0]).toEqual({ name: "Plot A", points: FLAT_PLOT.points, height: 40, original });
  expect(menuItem(0, "Restore original")).toBeNull();
});

test("a DXF file dropped on the Sites box is read; a PLY file dropped there is not", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = FOUND;
  await openWith(service);
  await dropFile("scan.ply");
  expect(service.count("POST /outlines")).toBe(0);
  expect(importWindow()).toBeNull();
  await dropFile("plots.dxf");
  expect(service.outlineFilesRead).toEqual(["plots.dxf"]);
  expect(importWindow()).not.toBeNull();
});

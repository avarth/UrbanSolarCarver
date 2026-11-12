// Holes in sites (design/site-holes.md): Draw hole in a site's editor draws its hole, a hole's vertices are edited as the outline's,
// the row says how many holes a site has, the menus turn a site inside another into its hole and delete a hole,
// imported holes come with their outlines, and overlapping sites are warned about under the table.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { SiteJson } from "../api_client/client";
import { groupedDigits } from "../format_numbers";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { container, endWorkspaceTest, FakeService, NOTHING_RUN, openWorkspace, project, settle, startWorkspaceTest } from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const BLOCK: number[][] = [[0, 0, 0], [60, 0, 0], [60, 50, 0], [0, 50, 0]];                    // 3 000 m²
const COURTYARD: number[][] = [[20, 15, 0], [40, 15, 0], [40, 35, 0], [20, 35, 0]];            // 400 m²
const SECOND_COURTYARD: number[][] = [[5, 5, 0], [15, 5, 0], [15, 10, 0]];                       // 25 m²
const block = (holes?: number[][][]): SiteJson => ({ name: "Block", points: BLOCK, height: 20, ...(holes ? { holes } : {}) });

const panel = () => container().querySelector(".workspace-panel")!;
const editor = () => container().querySelector(".site-editor");
const sitesBox = () => [...panel().querySelectorAll<HTMLElement>(".input-box")].find((box) => box.querySelector(".input-box-title-row h3")?.textContent === "Sites")!;

async function openWith(service: FakeService) {
  service.siteSource = "sites";
  const detail = project(NOTHING_RUN);
  await openWorkspace(service, { ...detail, inputs: { ...detail.inputs, max_volume: [] }, joined_bounds: null });
}

const key = async (name: string, options: KeyboardEventInit = {}) => {
  act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, ...options })); });
  await settle();
};
/** Clicks the fake top view at the plan point (x, y) in metres (10 pixels a metre about pixel (400, 300)). */
const clickAt = async (x: number, y: number) => {
  act(() => { FakeViewerScene.latest!.clickView(400 + x * 10, 300 - y * 10); });
  await settle();
};
async function drawOutline(points: number[][]) {
  act(() => { [...sitesBox().querySelectorAll("button")].find((button) => button.textContent === "Draw")!.click(); });
  await settle();
  for (const [x, y] of points) await clickAt(x, y);
  await clickAt(points[0][0], points[0][1]);              // the first point closes the outline
}

/** The items of a row's menu (a site's or a hole's), opened first when it is closed. */
function menuOf(row: Element) {
  const button = row.querySelector<HTMLButtonElement>(".action-menu-button")!;
  if (button.getAttribute("aria-expanded") !== "true") act(() => { button.click(); });
  return [...row.querySelectorAll<HTMLButtonElement>("[role='menuitem']")];
}
async function choose(row: Element, label: string) {
  const item = menuOf(row).find((candidate) => candidate.textContent === label)!;
  await act(async () => { item.click(); });
  await settle();
}
const siteRows = () => [...panel().querySelectorAll(".site-row")];
const holeRows = () => [...panel().querySelectorAll(".site-hole-row")];

async function typeElevation(label: string, value: string) {
  const handle = container().querySelector(`[aria-label="${label}"]`)!;
  act(() => {
    handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: 500, clientY: 200 }));
    handle.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, clientX: 500, clientY: 200 }));
  });
  await settle();
  const field = container().querySelector<HTMLInputElement>(`[aria-label="${label}: Elevation"]`)!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => { field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await settle();
}

test("Draw hole in a site's editor draws a hole at the site's lowest level, in one save that one undo takes back", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [{ ...block(), points: [[0, 0, 2], [60, 0, 3], [60, 50, 2], [0, 50, 2]] }];
  await openWith(service);
  await choose(siteRows()[0], "Edit outline");
  const drawHole = [...editor()!.querySelectorAll("button")].find((button) => button.textContent === "Draw hole")!;
  act(() => { drawHole.click(); });
  await settle();
  expect(editor()!.textContent).toContain("Drawing a hole in Block");
  for (const [x, y] of SECOND_COURTYARD) await clickAt(x, y);
  await clickAt(SECOND_COURTYARD[0][0], SECOND_COURTYARD[0][1]);
  expect(service.savedSites).toHaveLength(1);
  expect(service.savedSites[0]).toHaveLength(1);
  expect(service.savedSites[0][0].holes).toEqual([[[5, 5, 2], [15, 5, 2], [15, 10, 2]]]);
  expect(editor()!.textContent).toContain("Editing Block");
  expect(holeRows().map((row) => row.querySelector(".site-hole-name")!.textContent)).toEqual(["Hole 1"]);
  await key("z", { ctrlKey: true });
  expect(service.savedSites).toHaveLength(2);
  expect(service.savedSites[1]).toEqual([{ name: "Block", points: [[0, 0, 2], [60, 0, 3], [60, 50, 2], [0, 50, 2]], height: 20 }]);
  expect("holes" in service.savedSites[1][0]).toBe(false);
});

test("Cancel while drawing a hole goes back to the site's editor; Draw makes a new site, and the service's refusal of a site inside another is shown", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block()];
  await openWith(service);
  await choose(siteRows()[0], "Edit outline");
  act(() => { [...editor()!.querySelectorAll("button")].find((button) => button.textContent === "Draw hole")!.click(); });
  await settle();
  await key("Escape");
  expect(editor()!.textContent).toContain("Editing Block");
  expect(service.savedSites).toHaveLength(0);
  await key("Escape");
  service.sitesRefusal = "Site 2 lies inside Block: draw a hole in Block instead.";
  await drawOutline(SECOND_COURTYARD);
  expect(service.savedSites).toHaveLength(0);
  expect(editor()!.querySelector("[role='alert']")!.textContent).toBe("Site 2 lies inside Block: draw a hole in Block instead.");
});

test("a hole's vertex takes a typed elevation in the same history; a change the service refuses shows its reason", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block([COURTYARD])];
  await openWith(service);
  await clickAt(5, 5);                                     // in the site's area: edits it
  expect(editor()!.textContent).toContain("Editing Block");
  expect(container().querySelector('[aria-label="Hole 1 vertex 4"]')).not.toBeNull();
  expect(editor()!.querySelector(".site-editor-edited path")!.getAttribute("fill-rule")).toBe("evenodd");
  await typeElevation("Hole 1 vertex 2", "1.5");
  expect(service.savedSites.at(-1)![0].holes![0][1]).toEqual([40, 15, 1.5]);
  expect(service.savedSites.at(-1)![0].points).toEqual(BLOCK);
  await key("z", { ctrlKey: true });
  expect(service.savedSites.at(-1)![0].holes![0][1]).toEqual([40, 15, 0]);

  service.sitesRefusal = "Block: hole 1 is not strictly inside the outline";
  await typeElevation("Hole 1 vertex 3", "2");
  expect(editor()!.querySelector(".site-editor-problem")!.textContent).toBe("Block: hole 1 is not strictly inside the outline");
  expect(sitesBox().querySelector("[role='alert']")!.textContent).toContain("Block: hole 1 is not strictly inside the outline");
});

test("a hole pushed out of the outline is refused in the editor and not sent", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block([COURTYARD])];
  await openWith(service);
  await clickAt(5, 5);
  // Pressed on the hole's third vertex and dragged out past the outline's corner
  const handle = container().querySelector('[aria-label="Hole 1 vertex 3"]')!;
  act(() => {
    handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: 800, clientY: -50 }));
    handle.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, button: 0, clientX: 1100, clientY: -300 }));
    handle.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, clientX: 1100, clientY: -300 }));
  });
  await settle();
  expect(editor()!.querySelector(".site-editor-problem")!.textContent).toContain("hole 1 is not strictly inside the outline");
  expect(service.savedSites).toHaveLength(0);
});

test("a site's row says its area less its holes and how many holes it has; each hole has a line under it", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block([COURTYARD]), { ...block([COURTYARD, SECOND_COURTYARD]), name: "Two" }, { ...block(), name: "None" }];
  await openWith(service);
  const names = siteRows().map((row) => row.querySelector<HTMLElement>(".site-row-name")!.title);
  expect(names).toEqual([
    `Block: ${groupedDigits(2600)} m², 1 hole · Flat. Double click to rename`,
    `Two: ${groupedDigits(2575)} m², 2 holes · Flat. Double click to rename`,
    `None: ${groupedDigits(3000)} m² · Flat. Double click to rename`,
  ]);
  expect(holeRows().map((row) => row.querySelector(".site-hole-name")!.textContent)).toEqual(["Hole 1", "Hole 1", "Hole 2"]);
  expect(holeRows()[0].querySelector(".action-menu-button")!.getAttribute("aria-label")).toBe("Actions for hole 1 of Block");
});

test("Make a hole of: a site lying inside another becomes its hole in one save", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  const inner: SiteJson = { name: "Courtyard", points: COURTYARD, height: 20 };
  const other: SiteJson = { name: "Other", points: [[100, 0, 0], [120, 0, 0], [120, 20, 0]], height: 30 };
  service.sites = [block(), inner, other];
  service.siteOverlaps = [{ first: 1, second: 0, inside: true }];
  await openWith(service);
  expect(menuOf(siteRows()[0]).map((item) => item.textContent)).not.toContain("Make a hole of Courtyard");
  expect(menuOf(siteRows()[2]).map((item) => item.textContent).some((label) => label?.startsWith("Make a hole of"))).toBe(false);
  service.siteOverlaps = [];
  await choose(siteRows()[1], "Make a hole of Block");
  expect(service.count("PUT /sites")).toBe(1);
  expect(service.savedSites[0]).toEqual([block([COURTYARD]), other]);
});

test("a hole's menu deletes it in one save; a hole cannot become a site, which would lie inside its site", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block([COURTYARD, SECOND_COURTYARD])];
  await openWith(service);
  expect(menuOf(holeRows()[0]).map((item) => item.textContent)).toEqual(["Delete hole"]);
  await choose(holeRows()[0], "Delete hole");
  expect(service.savedSites).toEqual([[block([SECOND_COURTYARD])]]);
  await choose(holeRows()[0], "Delete hole");
  expect(service.savedSites[1]).toEqual([block()]);
  expect("holes" in service.savedSites[1][0]).toBe(false);
  expect(holeRows()).toHaveLength(0);
});

test("overlapping sites are warned about under the table and their rows carry a warning sign", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  const square = (name: string, x: number): SiteJson => ({ name, points: [[x, 0, 0], [x + 20, 0, 0], [x + 20, 20, 0], [x, 20, 0]], height: 20 });
  service.sites = [square("Site 1", 0), square("Site 2", 100), square("Site 3", 110), square("Site 4", 300)];
  service.siteOverlaps = [{ first: 1, second: 2, inside: false }, { first: 3, second: 0, inside: true }];
  await openWith(service);
  expect([...sitesBox().querySelectorAll(".site-overlap")].map((line) => line.textContent)).toEqual([
    "Site 2 and Site 3 overlap: check their outlines.",
    "Site 4 lies inside Site 1: make it a hole of Site 1, or move it.",
  ]);
  expect(siteRows().map((row) => row.querySelector(".site-row-warning") !== null)).toEqual([true, true, true, true]);
  expect(siteRows()[1].querySelector(".site-row-warning")!.getAttribute("title")).toBe("This site overlaps another site");
});

test("without overlaps there is no warning", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block([COURTYARD])];
  await openWith(service);
  expect(sitesBox().querySelector(".site-overlap")).toBeNull();
  expect(panel().querySelector(".site-row-warning")).toBeNull();
});

test("an imported outline comes with its holes: Place on terrain asks for the holes' vertices too, and the original keeps them", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.outlinesReply = {
    file: "block.dxf", unit: "metres", left_out: [], distance_from_inputs: null,
    outlines: [{ name: "Courtyard block", points: BLOCK, area: 2600, rise: 0, holes: [COURTYARD] }],
  };
  service.terrainHeightsOf = (points) => points.map(([x]) => x / 10);
  service.siteSource = "sites";
  const detail = project(NOTHING_RUN);
  await openWorkspace(service, { ...detail, inputs: { ...detail.inputs, max_volume: [], terrain: [{ name: "terrain.obj", triangle_count: 1 }] }, joined_bounds: null });
  const picker = sitesBox().querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(picker, "files", { value: [new File(["0\nSECTION"], "block.dxf")], configurable: true });
  act(() => picker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  const dialog = [...document.body.querySelectorAll<HTMLElement>("[role='dialog']")].find((candidate) => candidate.textContent?.includes("Import sites from"))!;
  expect(dialog.textContent).toContain(`Courtyard block${groupedDigits(2600)} m², rise 0 m, 1 hole`);
  await act(async () => { [...dialog.querySelectorAll("button")].find((button) => button.textContent === "Import 1 site")!.click(); });
  await settle();
  expect(service.terrainRequests).toEqual([[...BLOCK, ...COURTYARD].map(([x, y]) => [x, y])]);
  const [site] = service.savedSites[0];
  expect(site.points).toEqual(BLOCK.map(([x, y]) => [x, y, x / 10]));
  expect(site.holes).toEqual([COURTYARD.map(([x, y]) => [x, y, x / 10])]);
  expect(site.original).toEqual({ file: "block.dxf", points: BLOCK, holes: [COURTYARD] });
  expect(site.height).toBe(Math.max(30, Math.ceil(6 + 1)));

  // Restore original puts the holes back as imported too
  await choose(siteRows()[0], "Restore original");
  expect(service.savedSites.at(-1)![0].holes).toEqual([COURTYARD]);
  expect(service.savedSites.at(-1)![0].points).toEqual(BLOCK);
});

test("a site's Place on terrain sets its holes' vertices too, in one request", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.sites = [block([COURTYARD])];
  service.terrainHeightsOf = (points) => points.map(([, y]) => y / 10);
  service.siteSource = "sites";
  const detail = project(NOTHING_RUN);
  await openWorkspace(service, { ...detail, inputs: { ...detail.inputs, max_volume: [], terrain: [{ name: "terrain.obj", triangle_count: 1 }] }, joined_bounds: null });
  await choose(siteRows()[0], "Place on terrain");
  expect(service.terrainRequests).toEqual([[...BLOCK, ...COURTYARD].map(([x, y]) => [x, y])]);
  expect(service.savedSites[0][0].holes).toEqual([COURTYARD.map(([x, y]) => [x, y, y / 10])]);
});

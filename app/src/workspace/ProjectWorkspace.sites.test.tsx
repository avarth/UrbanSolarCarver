// A site as the input (design/site-input.md): the tiles of a new project, the Site card, drawing a site in the view and editing it.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import {
  buttonIn, closeProjectSettings, container, endWorkspaceTest, FakeService, NOTHING_RUN, openProjectSettings, openWorkspace, project, projectSettings, settle,
  startWorkspaceTest,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

/** A project with no maximum volume yet: the input is still to be chosen. */
function newProject() {
  const detail = project(NOTHING_RUN);
  return { ...detail, inputs: { ...detail.inputs, max_volume: [] }, joined_bounds: null };
}

const panel = () => container().querySelector(".workspace-panel")!;
const editor = () => container().querySelector(".site-editor");
const key = async (name: string, options: KeyboardEventInit = {}) => {
  act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, ...options })); });
  await settle();
};
/** Clicks the fake top view at the plan point (x, y) in metres (10 pixels a metre about pixel (400, 300)). */
const clickAt = async (x: number, y: number) => {
  act(() => { FakeViewerScene.latest!.clickView(400 + x * 10, 300 - y * 10); });
  await settle();
};

test("a new project offers the two inputs; Site makes the maximum volume from the sites and shows the Site card", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, newProject());
  expect(panel().textContent).toContain("Start from");
  act(() => { buttonIn(panel(), "SiteDraw the site boundaries in the view and give each a height").click(); });
  await settle();
  expect(service.count("PUT /max-volume-source")).toBe(1);
  expect(service.siteSource).toBe("sites");
  expect(panel().textContent).toContain("Draw the site boundary in the 3D view");
  expect(panel().textContent).toContain("Use a maximum volume instead");
});

test("Maximum volume keeps the files' box, with the link to a site instead", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, newProject());
  act(() => { buttonIn(panel(), "Maximum volumeAdd mesh files of the largest volume a building may take").click(); });
  await settle();
  expect(panel().textContent).toContain("Use a site instead");
  expect(service.count("PUT /max-volume-source")).toBe(0);
});

test("a site is drawn with clicks, closed on its first point, saved with the default height, then its vertex elevation is typed", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  await openWorkspace(service, newProject());
  act(() => { buttonIn(panel(), "Draw site").click(); });
  await settle();
  expect(editor()!.textContent).toContain("Drawing Site 1");
  expect(FakeViewerScene.latest!.viewsFromTheTop).toBeGreaterThan(0);
  await clickAt(0, 0);
  await clickAt(20, 0);
  await clickAt(20, 10);
  await clickAt(0, 10);
  await key("Backspace");                     // the last point taken back
  await clickAt(0, 12);
  await clickAt(0.2, 0.1);                    // within 10 pixels of the first point: closes the outline
  expect(service.savedSites).toHaveLength(1);
  expect(service.savedSites[0]).toEqual([{ name: "Site 1", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 12, 0]], height: 30 }]);
  expect(editor()!.textContent).toContain("Editing Site 1");
  expect(panel().textContent).toContain("Site 1");

  // A click on the second vertex's handle selects it; its elevation is typed
  const handle = container().querySelector('[aria-label="Vertex 2"]')!;
  act(() => {
    handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: 600, clientY: 300 }));
    handle.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, clientX: 600, clientY: 300 }));
  });
  await settle();
  const field = container().querySelector<HTMLInputElement>('[aria-label="Vertex 2: Elevation"]')!;
  act(() => {
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setValue.call(field, "4.5");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => { field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await settle();
  expect(service.savedSites).toHaveLength(2);
  expect(service.savedSites[1][0].points[1]).toEqual([20, 0, 4.5]);

  // Ctrl+Z takes it back
  await key("z", { ctrlKey: true });
  expect(service.savedSites[2][0].points[1]).toEqual([20, 0, 0]);
});

test("a height not above the site's rise is refused in its row and not sent", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [{ name: "Site 1", points: [[0, 0, 0], [20, 0, 6], [20, 10, 0]], height: 30 }];
  await openWorkspace(service, newProject());
  const height = container().querySelector<HTMLInputElement>('[aria-label="Max height of Site 1"]')!;
  act(() => {
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setValue.call(height, "5");
    height.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => { height.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await settle();
  expect(panel().textContent).toContain("this site rises 6.00 m, so its height must be more than 6.00 m");
  expect(service.savedSites).toHaveLength(0);
});

test("a click inside a site in the view edits it; Escape ends the editing", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [{ name: "Plot A", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 10, 0]], height: 30 }];
  await openWorkspace(service, newProject());
  expect(editor()).toBeNull();
  await clickAt(5, 5);
  expect(editor()!.textContent).toContain("Editing Plot A");
  await key("Escape");
  expect(editor()).toBeNull();
});

// Heights (design/base-height.md)

const typeIn = async (field: HTMLInputElement, text: string) => {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => { field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await settle();
};
const FLAT_SITE = { name: "Site 1", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0]], height: 30 };

test("a base height for all sites is typed in Settings, shown read-only in each row, and the row opens Settings on it", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [FLAT_SITE];
  await openWorkspace(service, newProject());
  openProjectSettings();
  await settle();
  const heights = projectSettings()!.querySelector(".heights-settings")!;
  expect(heights.textContent).toContain("Base height");
  expect(heights.textContent).toContain("Max height");
  await typeIn(heights.querySelector<HTMLInputElement>('[data-setting="base_height"] input')!, "8");
  expect(service.savedHeights.at(-1)).toEqual({ max: { for_all_sites: false, value: null }, base: { for_all_sites: true, value: 8 } });
  closeProjectSettings();
  await settle();
  const row = buttonIn(panel(), "8 m · set in Settings");
  act(() => { row.click(); });
  await settle();
  expect(projectSettings()).not.toBeNull();
  expect(document.activeElement).toBe(projectSettings()!.querySelector('[data-setting="base_height"] input'));
});

test("with Per site each row takes its own base height, and one not below the max is refused in the row and not sent", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [FLAT_SITE];
  service.heights = { max: { for_all_sites: false, value: null }, base: { for_all_sites: false, value: null } };
  await openWorkspace(service, newProject());
  const base = container().querySelector<HTMLInputElement>('[aria-label="Base height of Site 1"]')!;
  await typeIn(base, "40");
  expect(panel().textContent).toContain("its base height (40 m) must be less than its max height (30 m)");
  expect(service.savedSites).toHaveLength(0);
  await typeIn(base, "12");
  expect(service.savedSites.at(-1)![0].base_height).toBe(12);
});

test("a max height for all sites starts from the first site's height when switched on", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [FLAT_SITE];
  await openWorkspace(service, newProject());
  openProjectSettings();
  await settle();
  const maxRow = projectSettings()!.querySelector('[data-setting="max_height"]')!;
  act(() => { buttonIn(maxRow as HTMLElement, "One for all sites").click(); });
  await settle();
  expect(service.savedHeights.at(-1)!.max).toEqual({ for_all_sites: true, value: 30 });
  closeProjectSettings();
  await settle();
  expect(panel().textContent).toContain("30 m · set in Settings");
});

test("a project with a mesh maximum volume has the base height only", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openProjectSettings();
  await settle();
  const heights = projectSettings()!.querySelector(".heights-settings")!;
  expect(heights.querySelector('[data-setting="max_height"]')).toBeNull();
  expect(heights.querySelector('[data-setting="base_height"] .segmented-switch')).toBeNull();
  expect(heights.textContent).toContain("Measured from the lowest point of the maximum volume");
});

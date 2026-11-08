// A site as the input (design/site-input.md): the tiles of a new project, the Site card, drawing a site in the view and editing it.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { buttonIn, container, endWorkspaceTest, FakeService, NOTHING_RUN, openWorkspace, project, settle, startWorkspaceTest } from "./project_workspace_for_test";

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
  const height = container().querySelector<HTMLInputElement>('[aria-label="Height of Site 1"]')!;
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

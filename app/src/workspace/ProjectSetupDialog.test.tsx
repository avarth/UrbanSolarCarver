// The setup window of a new project (design/new-project-setup.md, section 3), in the open project against a fake service: when it
// opens, its three pages (Location, the way in, the heights), and what Start, Skip setup and Escape leave behind.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { press } from "../viewer_overlays/render_for_test";
import {
  buttonIn, container, endWorkspaceTest, FakeService, NOTHING_RUN, openWorkspace, project, settle, startWorkspaceTest, stepIsOpen,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

/** A project Create project has just made: no maximum volume and no weather file yet. */
function newProject() {
  const detail = project(NOTHING_RUN);
  return { ...detail, inputs: { ...detail.inputs, max_volume: [], weather: [] }, joined_bounds: null, weather_location: null, weather_latitude: null };
}

/** The setup window, drawn into the page's body; null while it is closed. */
const setup = () => [...document.body.querySelectorAll<HTMLElement>("[role='dialog']")]
  .find((dialog) => dialog.querySelector("h2")?.textContent === "Set up the project") ?? null;
const pageCount = () => setup()!.querySelector(".project-setup-count")!.textContent;
const setupButton = (text: string) => buttonIn(setup()!, text);
const editor = () => container().querySelector(".site-editor");

async function openWithSetup(service: FakeService) {
  const onSetupClosed = vi.fn();
  await openWorkspace(service, newProject(), { startsWithSetup: true, onSetupClosed });
  return onSetupClosed;
}

test("the setup window opens over a project Create project has just made, and not over one opened otherwise", async () => {
  await openWithSetup(new FakeService(NOTHING_RUN, null));
  expect(setup()).not.toBeNull();
  expect(pageCount()).toBe("1 of 3");
  endWorkspaceTest();
  startWorkspaceTest();
  await openWorkspace(new FakeService(NOTHING_RUN, null), newProject());
  expect(setup()).toBeNull();
});

test("page 1 has the weather file's box and north; Next and Back go between the pages", async () => {
  await openWithSetup(new FakeService(NOTHING_RUN, null));
  const weather = setup()!.querySelector<HTMLElement>(".input-box")!;
  expect(weather.querySelector("h3")!.textContent).toBe("Weather file");
  expect(weather.querySelector(".input-box-title-row button")!.textContent).toBe("Import");
  expect(setup()!.querySelector('[data-setting="north_deg"]')).not.toBeNull();
  expect(setup()!.querySelector('[data-setting="voxel_size"]')).toBeNull();      // only the Location group's north
  expect(buttonIn(setup()!, "Back")).toBeUndefined();
  act(() => setupButton("Next").click());
  expect(pageCount()).toBe("2 of 3");
  expect(setup()!.querySelector('[data-setting="north_deg"]')).toBeNull();
  act(() => setupButton("Back").click());
  expect(pageCount()).toBe("1 of 3");
  expect(setup()!.querySelector('[data-setting="north_deg"]')).not.toBeNull();
});

test("page 2 offers Sites and Maximum volume; Sites saves the way in and moves to the heights, with the max height", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSetup(service);
  act(() => setupButton("Next").click());
  const tiles = [...setup()!.querySelectorAll(".input-choice-tile strong")].map((tile) => tile.textContent);
  expect(tiles).toEqual(["Sites", "Maximum volume"]);
  act(() => setupButton("SitesDraw the site boundaries in the view and give each a height").click());
  await settle();
  expect(service.count("PUT /max-volume-source")).toBe(1);
  expect(service.siteSource).toBe("sites");
  expect(pageCount()).toBe("3 of 3");
  const heights = setup()!.querySelector(".heights-settings")!;
  expect(heights.querySelector('[data-setting="base_height"]')).not.toBeNull();
  expect(heights.querySelector('[data-setting="max_height"]')).not.toBeNull();
  expect(buttonIn(setup()!, "Next")).toBeUndefined();
  expect(setupButton("Start")).toBeDefined();
});

test("with Maximum volume the heights page has no max height, and nothing is saved for the way in", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWithSetup(service);
  act(() => setupButton("Next").click());
  act(() => setupButton("Maximum volumeAdd mesh files of the largest volume a building may take").click());
  await settle();
  expect(pageCount()).toBe("3 of 3");
  expect(service.count("PUT /max-volume-source")).toBe(0);
  const heights = setup()!.querySelector(".heights-settings")!;
  expect(heights.querySelector('[data-setting="base_height"]')).not.toBeNull();
  expect(heights.querySelector('[data-setting="max_height"]')).toBeNull();
});

test("Start closes the window and tells so; with Sites the Site step is open with drawing on", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  const onSetupClosed = await openWithSetup(service);
  act(() => setupButton("Next").click());
  act(() => setupButton("SitesDraw the site boundaries in the view and give each a height").click());
  await settle();
  act(() => setupButton("Start").click());
  await settle();
  expect(setup()).toBeNull();
  expect(onSetupClosed).toHaveBeenCalledTimes(1);
  expect(stepIsOpen("Site")).toBe(true);
  expect(editor()!.textContent).toContain("Drawing Site 1");
});

test("Skip setup closes the window at any page and tells so", async () => {
  const onSetupClosed = await openWithSetup(new FakeService(NOTHING_RUN, null));
  act(() => setupButton("Next").click());
  act(() => setupButton("Skip setup").click());
  expect(setup()).toBeNull();
  expect(onSetupClosed).toHaveBeenCalledTimes(1);
  expect(editor()).toBeNull();
});

test("Escape closes the window and tells so", async () => {
  const onSetupClosed = await openWithSetup(new FakeService(NOTHING_RUN, null));
  press(setup()!, "Escape");
  expect(setup()).toBeNull();
  expect(onSetupClosed).toHaveBeenCalledTimes(1);
});

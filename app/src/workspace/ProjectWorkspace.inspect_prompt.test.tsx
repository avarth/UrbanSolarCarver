// The prompt to check face directions in Inspect (InspectPrompt): under the Site step's test surfaces box once a test surface file is
// imported in a project that has not answered it. Open Inspect opens Inspect with the file selected; Not now closes it. Either answer
// is sent to the service (POST inspect-prompt-answered), so the prompt is shown once per project.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { InspectedFile } from "../api_client/client";
import { click } from "../viewer_overlays/render_for_test";
import {
  CARVED, CARVING, FakeService, TRIANGLE_OBJ, buttonIn, container, endWorkspaceTest, openWorkspace, packedInspectGeometry, project, settle, startWorkspaceTest,
  surfaceSetsBox,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const prompt = () => container().querySelector<HTMLElement>(".inspect-prompt");
const summary = (role: string, fileName: string): InspectedFile => ({
  role, file_name: fileName, triangle_count: 1, area_m2: 1, bounds: [[0, 0, 0], [1, 1, 1]], body_count: 1, closed_body_count: 0,
  surface_count: role === "test_surfaces" ? 1 : null, flippable: role === "test_surfaces", original_kept: false, problem: null, version: `${fileName}@1`,
});

async function importTestSurfaces(fileName: string) {
  const picker = surfaceSetsBox()!.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(picker, "files", { value: [new File([TRIANGLE_OBJ], fileName)], configurable: true });
  act(() => picker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
}

async function openUnanswered(service: FakeService) {
  await openWorkspace(service, { ...project(CARVED), inspect_prompt_answered: false });
}

test("the first test surface file imported brings the prompt; Not now closes it and is kept in the project", async () => {
  const service = new FakeService(CARVED, CARVING);
  await openUnanswered(service);
  expect(prompt()).toBeNull();                                   // nothing imported yet
  await importTestSurfaces("windows.obj");
  expect(prompt()!.textContent).toContain("Check which way the surfaces of windows.obj face before a run.");
  click(buttonIn(prompt()!, "Not now"));
  await settle();
  expect(prompt()).toBeNull();
  expect(service.requests).toContain("POST /inspect-prompt-answered");
  await importTestSurfaces("roofs.obj");
  expect(prompt()).toBeNull();                                   // once per project
});

test("Open Inspect opens Inspect with the imported file selected", async () => {
  const service = new FakeService(CARVED, CARVING);
  service.inspection = [summary("test_surfaces", "surfaces.obj"), summary("test_surfaces", "windows.obj")];
  const triangle = () => packedInspectGeometry([0, 0, 0], [0, 0, 0, 1, 0, 0, 0, 1, 0], [0], [{ centre: [0.3, 0.3, 0], normal: [0, 0, 1], area: 0.5 }]);
  service.inspectGeometries = { "surfaces.obj": triangle(), "windows.obj": triangle() };
  await openUnanswered(service);
  await importTestSurfaces("windows.obj");
  click(buttonIn(prompt()!, "Open Inspect"));
  await settle();
  expect(service.requests).toContain("POST /inspect-prompt-answered");
  const row = (fileName: string) => container().querySelector<HTMLElement>(`.files-panel .inspect-file[data-file-name="${fileName}"]`)!;
  expect(row("windows.obj").getAttribute("aria-current")).toBe("true");
  expect(row("surfaces.obj").getAttribute("aria-current")).toBeNull();
});

test("a project that answered the prompt does not show it", async () => {
  const answered = new FakeService(CARVED, CARVING);
  await openWorkspace(answered, project(CARVED));                // the fixture's project has answered it
  await importTestSurfaces("windows.obj");
  expect(prompt()).toBeNull();
});

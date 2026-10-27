// Input files changed in the project folder from outside the app, or missing from it: the notice over the steps, the files asked
// for again, and the stage status asked for when the window comes back to the front.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { InputFileChange } from "../api_client/client";
import { CARVED, FakeService, buttonIn, container, endWorkspaceTest, openWorkspace, project, settle, startWorkspaceTest } from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let service: FakeService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const CHANGED_SURFACES: InputFileChange = { role: "test_surfaces", file_name: "surfaces.obj", state: "changed", noticed: "2026-10-27T15:20:00+00:00" };
const notice = () => container().querySelector(".workspace-panel > .input-changes-notice");

const backToTheApp = async () => {
  act(() => { window.dispatchEvent(new Event("focus")); });
  await settle();
};

test("a file changed in the folder, found when the window comes back, is told, its meshes are fetched again, and OK dismisses it", async () => {
  service = new FakeService(CARVED, null);
  await openWorkspace(service, project(CARVED));
  expect(notice()).toBeNull();
  const listsBefore = service.count("GET /inputs/test_surfaces");
  const meshesBefore = service.count("GET /inputs/test_surfaces/surfaces.obj");
  service.inputChanges = [CHANGED_SURFACES];
  await backToTheApp();
  expect(notice()!.textContent).toContain("Changed in the project folder: surfaces.obj (test surface).");
  expect(service.count("GET /inputs/test_surfaces")).toBe(listsBefore + 1);
  expect(service.count("GET /inputs/test_surfaces/surfaces.obj")).toBe(meshesBefore + 1);
  await backToTheApp();       // listed again until dismissed: not fetched again
  expect(service.count("GET /inputs/test_surfaces")).toBe(listsBefore + 1);
  act(() => { buttonIn(notice()!, "OK").click(); });
  await settle();
  expect(service.count("DELETE /input-changes")).toBe(1);
  expect(notice()).toBeNull();
});

test("a second replacement of the same file, found later, fetches its meshes again; a dismissed one does not come back", async () => {
  service = new FakeService(CARVED, null);
  await openWorkspace(service, project(CARVED));
  const lists = () => service.count("GET /inputs/test_surfaces");
  const listsBefore = lists();
  service.inputChanges = [CHANGED_SURFACES];
  await backToTheApp();
  service.inputChanges = [{ ...CHANGED_SURFACES, noticed: "2026-10-27T15:31:00+00:00" }];
  await backToTheApp();
  expect(lists()).toBe(listsBefore + 2);
  const answeredBeforeTheDismissal = service.inputChanges;
  act(() => { buttonIn(notice()!, "OK").click(); });
  await settle();
  service.inputChanges = answeredBeforeTheDismissal;      // a stage status asked for before the dismissal reached the service
  await backToTheApp();
  expect(notice()).toBeNull();
  expect(lists()).toBe(listsBefore + 2);
});

test("a file missing from the folder is told until it is back, with nothing to dismiss", async () => {
  service = new FakeService(CARVED, null);
  service.inputChanges = [{ role: "max_volume", file_name: "volume.obj", state: "missing" }];
  await openWorkspace(service, { ...project(CARVED), stage_status: { stages: CARVED, input_changes: service.inputChanges } });
  expect(notice()!.textContent).toBe("Missing from the project folder: volume.obj (maximum volume). Put it back, or remove it here, before the next run.");
  expect(notice()!.querySelector("button")).toBeNull();
  service.inputChanges = [];
  await backToTheApp();
  expect(notice()).toBeNull();
});

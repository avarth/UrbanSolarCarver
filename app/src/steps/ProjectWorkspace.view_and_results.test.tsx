// The open project as a whole, against a fake service: what the 3D view and Export draw and offer from the stages, the run
// summary and the stored settings, as the unit tests of each cannot show them together.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as THREE from "three";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { PipelineStage, StageState } from "./step_summaries";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, NOTHING_RUN, buildPart, buttonIn, container, endWorkspaceTest, openStep,
  openWorkspace, project, reasonOf, settle, startWorkspaceTest, type, waitForTheSave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let service: FakeService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

test("the sun path, the sky dome and the compass ring are sized to the maximum volume and the test surfaces together", async () => {
  service = new FakeService(NOTHING_RUN, null);
  // The maximum volume is the triangle from 0 to 1 m; the test surface lies apart from it, from 9 to 10 m along x
  service.inputFileContents["/inputs/test_surfaces/surfaces.obj"] = "v 9 0 0\nv 10 0 0\nv 9 1 0\nf 1 2 3\n";
  await openWorkspace(service, project(NOTHING_RUN));
  // The scene runs from 0 to 10 m along x and 0 to 1 m along y: centred at (5, 0.5) on the ground, 1.5 x 10 m wide
  expect(FakeViewerScene.latest!.sceneHemisphere).toEqual({ centre: [5, 0.5, 0], radius: 15 });
});

test("the 3D view and Export use the envelope file that was built, not a format stored since without a build", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "out_of_date", massing: "missing" };
  service = new FakeService(built, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: null };          // export.ply on disk
  await openWorkspace(service, project(built, { final_mesh_format: "obj" }));                  // OBJ stored while Carving was locked
  const envelopeRequests = service.requests.filter((request) => request.includes("/run/files/exporting/"));
  expect(envelopeRequests).toEqual(["GET /run/files/exporting/export.ply"]);
  openStep("Export");
  const envelopeDownload = container().querySelector(".download-list li")!;
  expect(envelopeDownload.textContent).toBe("Carved envelope (PLY)Out of dateBuilt as PLY; the next envelope build writes OBJ.");
});

test("the 3D view draws no envelope while its stage is not recorded: a run that wrote it and then failed", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Envelope and massing");
  await act(async () => buttonIn(buildPart("Envelope"), "Build envelope").click());
  await settle();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "exporting", done: 0, total: 1 });
  await settle();
  service.summary = { carving: CARVING, envelope: { ...ENVELOPE, mesh_file: "export.obj" }, massing: null };      // written, not recorded
  run.send({ type: "run_failed", error_type: "RuntimeError", message: "exporting failed", field_errors: [] });
  await settle();
  expect(service.requests).toContain("GET /run/files/exporting/export.obj");
  expect(FakeViewerScene.latest!.layersWithObjects()).not.toContain("envelope");
});

test("the 3D view draws no building massing while its stage is not recorded: a run that wrote it and then failed", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Envelope and massing");
  await act(async () => buttonIn(buildPart("Building massing"), "Build massing").click());
  await settle();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "massing", done: 0, total: 1 });
  await settle();
  service.massingOnDisk = true;         // written, not recorded
  run.send({ type: "run_failed", error_type: "RuntimeError", message: "massing failed", field_errors: [] });
  await settle();
  expect(service.requests).toContain("GET /run/files/massing/plates.obj");
  expect(FakeViewerScene.latest!.layersWithObjects()).not.toContain("building_massing");
});

test("a North not saved yet turns the drawn sun path with the compass ring, so the two agree until the new path comes", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.sunPath = { days: [{ date: "12-21", day_path: [[0, 1, 0], [0, 0, 1]], period_path: [], markers: [] }] };
  await openWorkspace(service, project(NOTHING_RUN));
  const towardFirstSun = () => {
    let dayPath: THREE.Line | null = null;
    FakeViewerScene.latest!.layers.get("sun_path")!.traverse((object) => { if (object instanceof THREE.Line) dayPath ??= object; });
    const first = new THREE.Vector3().fromBufferAttribute(dayPath!.geometry.getAttribute("position") as THREE.BufferAttribute, 0);
    return first.sub(new THREE.Vector3(...FakeViewerScene.latest!.sceneHemisphere!.centre)).normalize();
  };
  expect(towardFirstSun().y).toBeCloseTo(1);
  openStep("Settings");
  type(container().querySelector<HTMLInputElement>('[data-setting="north_deg"] input[type="number"]')!, "90");
  expect(service.savedValues).toEqual([]);
  expect(towardFirstSun().x).toBeCloseTo(1);
  expect(towardFirstSun().y).toBeCloseTo(0);
});

test("on a first build of both parts the 3D view draws the envelope once its stage is done, before the massing ends", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Carving");
  await act(async () => buttonIn(container().querySelector(".step-pinned-action")!, "Build envelope and massing").click());
  await settle();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "exporting", done: 0, total: 1 });
  await settle();
  service.summary = { carving: CARVING, envelope: { ...ENVELOPE, mesh_file: "export.obj" }, massing: null };
  run.send({ type: "stage_progress", stage: "massing", done: 0, total: 1 });
  await settle();
  expect(FakeViewerScene.latest!.layersWithObjects()).toContain("envelope");
  expect(buildPart("Envelope").querySelector(".envelope-results")).not.toBeNull();
});

test("a finished envelope stage asks for the run summary once: the envelope's file name comes from the same reply", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Envelope and massing");
  await act(async () => buttonIn(buildPart("Envelope"), "Build envelope").click());
  await settle();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "exporting", done: 0, total: 1 });
  await settle();
  const summariesBefore = service.count("GET /run/summary");
  service.summary = { carving: CARVING, envelope: { ...ENVELOPE, mesh_file: "export.obj" }, massing: null };
  service.stages = { ...CARVED, exporting: "current" };
  run.send({ type: "run_finished", stages: ["exporting"], files: [] });
  await settle();
  expect(service.count("GET /run/summary")).toBe(summariesBefore + 1);
  expect(service.requests).toContain("GET /run/files/exporting/export.obj");
});

const chooseMeshFormat = async (format: string) => {
  await act(async () => container().querySelector<HTMLInputElement>(`[data-setting="final_mesh_format"] input[value="${format}"]`)!.click());
  await waitForTheSave();
  await settle();
};
const downloadButton = (label: string) => buttonIn(container().querySelector(".download-list")!, label);

test("a format change rebuilds both parts that exist; while it runs their old files wait: the run removes them, so a download would find none", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: MASSING };
  await openWorkspace(service, project(built, { final_mesh_format: "ply" }));
  openStep("Export");
  expect(downloadButton("Carved envelope (PLY)").disabled).toBe(false);
  await chooseMeshFormat("obj");
  expect(service.runsStarted).toEqual([["exporting", "massing"]]);
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "exporting", done: 0, total: 1 });
  await settle();
  for (const label of ["Carved envelope (PLY)", "Building massing (PLY)"]) {
    expect(downloadButton(label).disabled).toBe(true);
    expect(reasonOf(downloadButton(label))).toBe("A run is in progress");
  }
  service.summary = { carving: CARVING, envelope: { ...ENVELOPE, mesh_file: "export.obj" }, massing: { ...MASSING, export_mesh_file: "plates.obj" } };
  run.send({ type: "run_finished", stages: ["exporting", "massing"], files: [] });
  await settle();
  expect(downloadButton("Carved envelope (OBJ)").disabled).toBe(false);
  expect(downloadButton("Building massing (OBJ)").disabled).toBe(false);
  expect(container().querySelector(".download-list .download-note")).toBeNull();     // every file is in the format chosen
});

test("a format change with only the envelope built rebuilds the envelope", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "missing" };
  service = new FakeService(built, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: null };
  await openWorkspace(service, project(built, { final_mesh_format: "ply" }));
  openStep("Export");
  await chooseMeshFormat("stl");
  expect(service.runsStarted).toEqual([["exporting"]]);
});

test("a format change with only the massing built rebuilds the massing", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "missing", massing: "current" };
  service = new FakeService(built, CARVING);
  service.summary = { carving: CARVING, envelope: null, massing: MASSING };
  await openWorkspace(service, project(built, { final_mesh_format: "ply" }));
  openStep("Export");
  await chooseMeshFormat("glb");
  expect(service.runsStarted).toEqual([["massing"]]);
});

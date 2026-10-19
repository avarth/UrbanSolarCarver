// The open project as a whole, against a fake service: the settings form, the run loop, the stage status, the results and the
// layers of the 3D view together, as the unit tests of each cannot show them.
import { act, type ComponentProps } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ModeInfo, ProjectDetail, SunPath } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { SAVE_DELAY_MILLISECONDS } from "../settings_form/form_state";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import * as THREE from "three";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ProjectWorkspace, type OpenProjectSettingsSaver } from "./ProjectWorkspace";
import { useRunLoop } from "./run_state";
import type { PipelineStage, StageState } from "./step_summaries";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

const SCHEMA = {
  properties: {
    mode: { default: "time-based", type: "string" },
    voxel_size: { default: 1.0, type: "number" },
    north_deg: { default: 0.0, type: "number" },
    start_month: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    start_day: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    start_hour: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_month: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_day: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_hour: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    threshold: { anyOf: [{ $ref: "#/$defs/ThresholdSpec" }, { type: "null" }], default: null },
    carve_above: { default: true, type: "boolean" },
    carve_above_min_consecutive: { default: 1, type: "integer" },
    max_slope_deg: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
  },
};
const MODES: ModeInfo[] = [
  { name: "time-based", description: "", needs_epw: true, needs_period: true, experimental: false, score_kind: "violation_count", weight_unit: "m²·h",
    starting_values: { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14 } },
  { name: "daylight", description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: "weighted_sum", weight_unit: "",
    starting_values: {} },
];
const TRIANGLE_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";
const CARVING = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: null,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 0,
};
const ENVELOPE = { mesh_file: "export.ply", envelope_volume_m3: 4150 };
const MASSING = { export_mesh_file: "plates.ply", floor_area_m2_per_storey: [500, 380], total_floor_area_m2: 880, storeys_built: 2 };
const NOTHING_RUN: Record<PipelineStage, StageState> = { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing" };
const CARVED: Record<PipelineStage, StageState> = { ...NOTHING_RUN, preprocessing: "current", thresholding: "current" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/**
 * The local service as the open project "p" uses it: it stores the settings, answers the stage status, starts runs (whose
 * events the test sends) and serves the run summary and the input meshes; everything else is not there (404).
 */
class FakeService {
  readonly requests: string[] = [];
  readonly savedValues: Record<string, unknown>[] = [];
  readonly runsStarted: string[][] = [];
  stages: Record<PipelineStage, StageState>;
  summary: { carving: typeof CARVING | null; envelope: { mesh_file: string; envelope_volume_m3: number } | null; massing: typeof MASSING | null };
  /** The status every save is refused with (409: a run of the project the page does not know of); null: saves are stored. */
  refuseSavesWith: number | null = null;
  /** While set, a request to start a run gets its reply only once this promise resolves. */
  runStartsWaitFor: Promise<void> | null = null;
  /** Every stage asked for is current already (a run the page did not follow made them so). */
  everythingUpToDate = false;
  /** The field errors a save of these values is refused with (422), or null when it is stored. */
  configErrorsOf: (values: Record<string, unknown>) => { field: string | null; message: string }[] | null = () => null;
  /** The massing's plates.obj is on disk (a run wrote it), whether or not its stage is recorded. */
  massingOnDisk = false;
  /** The contents of input files by path (for example "/inputs/test_surfaces/surfaces.obj"); one triangle for any other. */
  inputFileContents: Record<string, string> = {};
  /** The reply of GET sun-path; null: not there (404). */
  sunPath: SunPath | null = null;
  /** While set, an upload of an input file gets its reply only once this promise resolves. */
  uploadsAnswerWhen: Promise<void> | null = null;
  /** The location and latitude the reply to a weather file upload gives. */
  uploadedWeather = { location: "Golden, CO, USA", latitude: 39.74 };
  /** The reply of GET cold-period. */
  coldPeriodReply: unknown = { status: "none", period: null };

  constructor(stages: Record<PipelineStage, StageState>, carving: typeof CARVING | null) {
    this.stages = stages;
    this.summary = { carving, envelope: null, massing: null };
  }

  answer = async (address: string, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    const path = address.replace("/api/projects/p", "");
    this.requests.push(`${method} ${path}`);
    if (method === "PUT" && path === "/config") {
      if (this.refuseSavesWith !== null) return json({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const { values } = JSON.parse(String(init!.body)) as { values: Record<string, unknown> };
      const fieldErrors = this.configErrorsOf(values);
      if (fieldErrors !== null) return json({ field_errors: fieldErrors, grid_plan: null }, 422);
      this.savedValues.push(values);
      return json({ settings: values, grid_plan: null });
    }
    if (path === "/stage-status") return json({ stages: this.stages });
    if (method === "POST" && path === "/runs") {
      await this.runStartsWaitFor;
      const { produce } = JSON.parse(String(init!.body)) as { produce: string[] };
      if (this.everythingUpToDate) return json({ status: "up_to_date", run_id: null, stages: [] });
      this.runsStarted.push(produce);
      const stages = this.stages.preprocessing === "current" ? produce : ["preprocessing", ...produce];    // the analysis when it is out of date
      return json({ status: "started", run_id: `r${this.runsStarted.length}`, stages });
    }
    if (path === "/sun-path" && this.sunPath !== null) return json(this.sunPath);
    if (path === "/run/summary") return json(this.summary);
    if (method === "POST" && path.startsWith("/inputs/")) {
      await this.uploadsAnswerWhen;
      const role = path.replace("/inputs/", "");
      const files = role === "weather" ? [{ name: "weather.epw", triangle_count: 0 }] : [{ name: "more.obj", triangle_count: 1 }];
      return json({ role, files, joined_bounds: [[0, 0, 0], [1, 1, 0]], weather_location: this.uploadedWeather.location,
                    weather_latitude: this.uploadedWeather.latitude });
    }
    if (path.startsWith("/cold-period")) return json(this.coldPeriodReply);
    if (path.startsWith("/inputs/")) return new Response(this.inputFileContents[path] ?? TRIANGLE_OBJ);
    if (path === "/run/files/exporting/export.obj" && this.summary.envelope?.mesh_file === "export.obj") return new Response(TRIANGLE_OBJ);
    if (path === "/run/files/massing/plates.obj" && this.massingOnDisk) return new Response(TRIANGLE_OBJ);
    return json({ detail: "Not found" }, 404);
  };

  count(request: string): number {
    return this.requests.filter((made) => made === request).length;
  }
}

function project(stages: Record<PipelineStage, StageState>, settings: Record<string, unknown> = {}): ProjectDetail {
  return {
    name: "p", created: "2026-10-17T09:00:00", modified: "2026-10-17T09:00:00", settings: { mode: "time-based", ...settings },
    inputs: { max_volume: [{ name: "volume.obj", triangle_count: 1 }], test_surfaces: [{ name: "surfaces.obj", triangle_count: 1 }],
              weather: [{ name: "weather.epw", triangle_count: 0 }] },
    joined_bounds: [[0, 0, 0], [1, 1, 0]], weather_location: "Golden, CO, USA", weather_latitude: 39.74, stage_status: { stages }, grid_plan: null,
  };
}

let rendered: RenderedOverlay | null = null;
let service: FakeService;

beforeEach(() => {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  pretendTheBrowserHasWebGl();
});

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const settle = () => act(async () => {
  for (let tick = 0; tick < 5; tick++) await new Promise((resolve) => setTimeout(resolve, 0));
});
const waitForTheSave = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, SAVE_DELAY_MILLISECONDS + 50)); });

async function openWorkspace(opened: ProjectDetail,
                             steps: Pick<ComponentProps<typeof ProjectWorkspace>, "startSteps" | "onStepsChange" | "onSettingsSaverReady"> = {},
                             { schema = SCHEMA, modes = MODES }: { schema?: typeof SCHEMA; modes?: ModeInfo[] } = {}) {
  vi.stubGlobal("fetch", vi.fn(service.answer));
  function Page() {
    const runs = useRunLoop("token", () => {});
    return <ProjectWorkspace token="token" project={opened} schema={schema} modes={modes} warmUpState="ready" runs={runs}
                             onServiceProblem={() => {}} onShowProjects={() => {}} {...steps} />;
  }
  rendered = renderForTest(<Page />);
  await settle();
}

const container = () => rendered!.container;
const dimmedLayers = () => [...FakeViewerScene.latest!.dimmed].sort();
/** The dimmed layers among the carving's (the envelope and the massing follow their own stages, never built here). */
const dimmedCarvingLayers = () => dimmedLayers().filter((layer) => ["kept_voxels", "carved_voxels", "sky_dome"].includes(layer));

function stepRow(title: string): HTMLElement {
  return [...container().querySelectorAll<HTMLElement>(".step")].find((row) => row.querySelector(".step-title")!.textContent === title)!;
}

function openStep(title: string) {
  act(() => stepRow(title).querySelector<HTMLButtonElement>(".step-header")!.click());
}

function type(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function typeAndLeave(input: HTMLInputElement, text: string) {
  type(input, text);
  act(() => input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
}

async function pressRunAnalysis() {
  const button = [...container().querySelectorAll<HTMLButtonElement>(".step-pinned-action button")].find((candidate) => candidate.textContent === "Run analysis")!;
  await act(async () => button.click());
  await settle();
}

/** The part of the Envelope and massing step whose heading is *title*. */
function buildPart(title: string): HTMLElement {
  return [...container().querySelectorAll<HTMLElement>(".build-part")].find((part) => part.querySelector(".setting-group-title")!.textContent === title)!;
}

function buttonIn(root: Element, text: string): HTMLButtonElement {
  return [...root.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === text)!;
}

/** Why a disabled button is disabled: the text its aria-describedby names. */
const reasonOf = (button: HTMLButtonElement) => document.getElementById(button.getAttribute("aria-describedby")!)!.textContent;

const voxelSizeField = () => container().querySelector<HTMLInputElement>('[data-setting="voxel_size"] input[type="number"]')!;
const thresholdField = () => container().querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
const thresholdOf = (values: Record<string, unknown>) => (values.threshold as { value: number }).value;

test("a settings change saves; Run analysis starts a run; its events finish it; the stage status and the summary are fetched; the carving undims", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(project(NOTHING_RUN));
  expect(service.count("GET /run/summary")).toBe(0);           // nothing has run: no results to fetch
  openStep("Settings");

  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "time-based", voxel_size: 2 }]);
  expect(service.count("GET /stage-status")).toBe(1);           // the save changed what the stages ran with

  await pressRunAnalysis();
  expect(service.runsStarted).toEqual([["thresholding"]]);
  expect(FakeWebSocket.opened).toHaveLength(1);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels", "sky_dome"]);     // the run brings them

  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "preprocessing", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  await settle();
  service.stages = CARVED;
  service.summary = { carving: CARVING, envelope: null, massing: null };
  run.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();

  expect(service.count("GET /run/summary")).toBe(1);
  expect(service.count("GET /stage-status")).toBe(2);
  expect(stepRow("Carving").classList.contains("step-open")).toBe(true);    // a finished analysis opens Carving
  expect(stepRow("Carving").textContent).toContain("Volume kept61 %");
  expect(dimmedCarvingLayers()).toEqual([]);
  openStep("Settings");
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("61\u00a0% kept");
});

test("a save the service refuses keeps Run analysis from starting a run, and says why", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.refuseSavesWith = 409;
  await openWorkspace(project(NOTHING_RUN));
  openStep("Settings");

  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  const notice = () => container().querySelector(".save-failure");
  expect(notice()!.textContent).toContain("The last change to the settings was not saved.");
  expect(notice()!.textContent).toContain("A run of this project is in progress, perhaps in another tab. Save again once it has ended.");

  await pressRunAnalysis();
  expect(service.count("PUT /config")).toBe(2);                // Run analysis sent the change again first
  expect(service.runsStarted).toEqual([]);
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(notice()).not.toBeNull();
});

test("a page opened during a run it does not follow: Run analysis answered with up to date brings the carving the service holds", async () => {
  service = new FakeService(CARVED, CARVING);                  // the run has ended since
  service.everythingUpToDate = true;
  await openWorkspace(project(NOTHING_RUN));                   // opened while the run had removed the stage records
  openStep("Settings");
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("Not run yet");

  await pressRunAnalysis();
  expect(container().querySelector(".step-pinned-action")!.textContent).toContain("Results are up to date");
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(service.count("GET /run/summary")).toBe(1);
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("61\u00a0% kept");
  openStep("Carving");
  expect(stepRow("Carving").textContent).not.toContain("Run the analysis in Settings to see the carving");
  expect(dimmedCarvingLayers()).toEqual([]);
});

test("threshold values given during a carving run: one more run follows with the last of them, and the carving stays dimmed until it ends", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  expect(service.count("GET /run/summary")).toBe(1);           // the carving the project opened with
  openStep("Carving");
  expect(dimmedCarvingLayers()).toEqual([]);

  typeAndLeave(thresholdField(), "1");
  await settle();
  expect(service.runsStarted).toEqual([["thresholding"]]);     // run A, for 1
  for (const value of ["2", "3"]) typeAndLeave(thresholdField(), value);
  await settle();
  expect(service.runsStarted).toHaveLength(1);                 // 2 and 3 wait; 3 replaces 2

  let answerRunStart: () => void = () => {};
  service.runStartsWaitFor = new Promise((resolve) => { answerRunStart = resolve; });
  const runA = FakeWebSocket.opened[0];
  runA.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  runA.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  // A has ended and B, for 3, is saved and starting: nothing is fetched for 1, which the user left, and the carving stays dimmed.
  expect(service.savedValues.map(thresholdOf)).toEqual([1, 3]);
  expect(service.count("POST /runs")).toBe(2);
  expect(FakeWebSocket.opened).toHaveLength(1);
  expect(service.count("GET /run/summary")).toBe(1);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels"]);

  answerRunStart();
  await settle();
  expect(FakeWebSocket.opened).toHaveLength(2);                // run B under way
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels"]);

  const runB = FakeWebSocket.opened[1];
  runB.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  runB.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(service.count("GET /run/summary")).toBe(2);
  expect(dimmedCarvingLayers()).toEqual([]);
  expect(service.runsStarted).toHaveLength(2);
});

test("a refused mode change locks Carving: the old mode's carving is not shown as current, and fixing the setting starts no analysis", async () => {
  service = new FakeService(CARVED, CARVING);
  // Daylight is refused for a carving setting until the user sets it, as a stored config.yaml or a run could leave it.
  service.configErrorsOf = (values) => (values.mode === "daylight" && values.max_slope_deg === undefined
    ? [{ field: "max_slope_deg", message: "Input should be greater than 0" }] : null);
  await openWorkspace(project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Mode");
  act(() => [...container().querySelectorAll<HTMLElement>('[role="radio"]')][4].click());      // Daylight
  // Locked at once, before the save is sent: the stored settings, which the stage status describes, are still Solar time-based.
  openStep("Carving");
  expect(stepRow("Carving").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  await waitForTheSave();
  await settle();
  expect(service.count("PUT /config")).toBe(1);
  expect(service.savedValues).toEqual([]);                     // refused: config.yaml still says Solar time-based
  expect(stepRow("Carving").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  expect(thresholdField().disabled).toBe(true);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels", "sky_dome"]);
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("1 setting to fix");

  // The setting with the error stays editable in the locked step; fixing it stores Daylight, and must not start a carving run,
  // which would run the whole analysis.
  const slope = container().querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="number"]')!;
  expect(slope.disabled).toBe(false);
  // Once Daylight is stored, the service finds the analysis out of date.
  service.stages = { ...CARVED, preprocessing: "out_of_date", thresholding: "out_of_date" };
  typeAndLeave(slope, "45");
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "daylight", max_slope_deg: 45 }]);
  expect(service.count("POST /runs")).toBe(0);
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(stepRow("Carving").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
});

test("the sun path, the sky dome and the compass ring are sized to the maximum volume and the test surfaces together", async () => {
  service = new FakeService(NOTHING_RUN, null);
  // The maximum volume is the triangle from 0 to 1 m; the test surface lies apart from it, from 9 to 10 m along x
  service.inputFileContents["/inputs/test_surfaces/surfaces.obj"] = "v 9 0 0\nv 10 0 0\nv 9 1 0\nf 1 2 3\n";
  await openWorkspace(project(NOTHING_RUN));
  // The scene runs from 0 to 10 m along x and 0 to 1 m along y: centred at (5, 0.5) on the ground, 1.5 x 10 m wide
  expect(FakeViewerScene.latest!.sceneHemisphere).toEqual({ centre: [5, 0.5, 0], radius: 15 });
});

test("a failed run's link to a setting opens its step and focuses the input its label names: a slider's number field", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(project(NOTHING_RUN));
  openStep("Settings");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid", field_errors: [{ field: "voxel_size", message: "too small" }] });
  await settle();
  const link = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Go to voxel size")!;
  act(() => link.click());
  expect(document.activeElement).toBe(voxelSizeField());
});

test("Build massing sends only massing and Build envelope only exporting; each leaves the other part's out-of-date mark (Review Focus 5)", async () => {
  // A threshold change and Run analysis since the last build: the envelope and the massing are both out of date.
  const stagesAfterAnalysis: Record<PipelineStage, StageState> = { ...CARVED, exporting: "out_of_date", massing: "out_of_date" };
  service = new FakeService(stagesAfterAnalysis, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: MASSING };
  await openWorkspace(project(stagesAfterAnalysis));
  openStep("Envelope and massing");
  const envelopeOutOfDate = () => buildPart("Envelope").querySelector(".envelope-results-out-of-date") !== null;
  const massingOutOfDate = () => buildPart("Building massing").querySelector(".envelope-results-out-of-date") !== null;
  expect([envelopeOutOfDate(), massingOutOfDate()]).toEqual([true, true]);
  expect(container().querySelector(".step-pinned-action")).toBeNull();          // each part has its own button

  await act(async () => buttonIn(buildPart("Building massing"), "Build massing").click());
  await settle();
  expect(service.runsStarted).toEqual([["massing"]]);
  // One run at a time: the envelope's button waits, saying why; the progress is under the button that started the run.
  expect(buttonIn(buildPart("Envelope"), "Build envelope").disabled).toBe(true);
  expect(reasonOf(buttonIn(buildPart("Envelope"), "Build envelope"))).toBe("A run is in progress");
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "massing", done: 0, total: 1 });
  await settle();
  expect(buildPart("Building massing").querySelector(".run-progress-stages")!.textContent).toContain("Building massing");
  expect(buildPart("Envelope").querySelector(".run-progress")).toBeNull();

  service.stages = { ...stagesAfterAnalysis, massing: "current" };
  run.send({ type: "run_finished", stages: ["massing"], files: [] });
  await settle();
  expect([envelopeOutOfDate(), massingOutOfDate()]).toEqual([true, false]);
  openStep("Carving");
  expect(stepRow("Envelope and massing").querySelector(".step-summary")!.textContent).toBe("Envelope out of date, massing built");

  openStep("Envelope and massing");
  await act(async () => buttonIn(buildPart("Envelope"), "Build envelope").click());
  await settle();
  expect(service.runsStarted).toEqual([["massing"], ["exporting"]]);
  expect(FakeWebSocket.opened).toHaveLength(2);
  // Its volume arrives with the run summary once the envelope mesh is done.
  service.stages = { ...service.stages, exporting: "current" };
  service.summary = { ...service.summary, envelope: { mesh_file: "export.ply", envelope_volume_m3: 3900 } };
  FakeWebSocket.opened[1].send({ type: "run_finished", stages: ["exporting"], files: [] });
  await settle();
  expect(buildPart("Envelope").querySelector(".number-tile-value")!.textContent).toBe("3 900 m³");
  expect([envelopeOutOfDate(), massingOutOfDate()]).toEqual([false, false]);
});

test("while Carving is locked, Build envelope, Build massing and Carving's Build envelope and massing are disabled and say why (M10)", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  await openWorkspace(project(built));
  openStep("Envelope and massing");
  expect(buttonIn(buildPart("Envelope"), "Build envelope").disabled).toBe(false);

  // A voxel size typed and not saved yet: the analysis is out of date for the settings shown, and a build would run it.
  openStep("Settings");
  type(voxelSizeField(), "2");
  const lockReason = "Settings changed since the analysis. Run the analysis again before building.";
  openStep("Envelope and massing");
  for (const [part, label] of [["Envelope", "Build envelope"], ["Building massing", "Build massing"]]) {
    const button = buttonIn(buildPart(part), label);
    expect(button.disabled).toBe(true);
    expect(reasonOf(button)).toBe(lockReason);
  }
  openStep("Carving");
  const carvingBuild = buttonIn(container().querySelector(".step-pinned-action")!, "Build envelope and massing");
  expect(carvingBuild.disabled).toBe(true);
  expect(reasonOf(carvingBuild)).toBe(lockReason);

  // Stored, the service finds the analysis out of date: the lock holds until Run analysis.
  service.stages = { preprocessing: "out_of_date", thresholding: "out_of_date", exporting: "out_of_date", massing: "out_of_date" };
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "time-based", voxel_size: 2 }]);
  openStep("Envelope and massing");
  expect(buttonIn(buildPart("Building massing"), "Build massing").disabled).toBe(true);
  expect(service.count("POST /runs")).toBe(0);
});

test("while Carving is locked, a mesh format change is stored but builds nothing, and Export says why (M10)", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  await openWorkspace(project(built, { final_mesh_format: "ply" }));
  const lockReason = "Settings changed since the analysis. Run the analysis again before building.";
  const formatField = () => container().querySelector('[data-setting="final_mesh_format"]')!;
  openStep("Export");
  expect(formatField().textContent).not.toContain(lockReason);

  openStep("Settings");
  service.stages = { preprocessing: "out_of_date", thresholding: "out_of_date", exporting: "out_of_date", massing: "out_of_date" };
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  openStep("Export");
  expect(formatField().textContent).toContain(lockReason);
  await act(async () => formatField().querySelector<HTMLInputElement>('input[value="obj"]')!.click());
  await settle();
  expect(service.savedValues.at(-1)).toEqual({ mode: "time-based", final_mesh_format: "obj", voxel_size: 2 });
  expect(service.count("POST /runs")).toBe(0);                  // a run would start with the analysis
});

test("Carving's Build envelope and massing opens the step, builds both parts, shows its run at the top of the step and blocks both buttons", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(project(CARVED));
  openStep("Carving");
  await act(async () => buttonIn(container().querySelector(".step-pinned-action")!, "Build envelope and massing").click());
  await settle();
  expect(stepRow("Envelope and massing").classList.contains("step-open")).toBe(true);
  expect(service.runsStarted).toEqual([["exporting", "massing"]]);
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "exporting", done: 0, total: 1 });
  await settle();
  const stepContent = container().querySelector(".envelope-step")!;
  const progress = stepContent.querySelector(":scope > .run-progress")!;
  expect(progress.textContent).toContain("Envelope mesh");
  expect(progress.compareDocumentPosition(buildPart("Envelope")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  for (const [part, label] of [["Envelope", "Build envelope"], ["Building massing", "Build massing"]]) {
    expect(reasonOf(buttonIn(buildPart(part), label))).toBe("A run is in progress");
    expect(buildPart(part).querySelector(".run-progress")).toBeNull();
  }

  // The envelope was written, then the massing failed: the run records neither, so the envelope's volume is not shown as built.
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: null };
  run.send({ type: "stage_progress", stage: "massing", done: 0, total: 1 });
  await settle();
  run.send({ type: "run_failed", error_type: "RuntimeError", message: "massing failed", field_errors: [] });
  await settle();
  expect(service.count("GET /run/summary")).toBeGreaterThan(1);
  expect(buildPart("Envelope").querySelector(".envelope-results")).toBeNull();
  openStep("Carving");
  expect(stepRow("Envelope and massing").querySelector(".step-summary")!.textContent).toBe("Not built yet");
});

test("the 3D view and Export use the envelope file that was built, not a format stored since without a build", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "out_of_date", massing: "missing" };
  service = new FakeService(built, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: null };          // export.ply on disk
  await openWorkspace(project(built, { final_mesh_format: "obj" }));                  // OBJ stored while Carving was locked
  const envelopeRequests = service.requests.filter((request) => request.includes("/run/files/exporting/"));
  expect(envelopeRequests).toEqual(["GET /run/files/exporting/export.ply"]);
  openStep("Export");
  const envelopeDownload = container().querySelector(".download-list li")!;
  expect(envelopeDownload.textContent).toBe("Carved envelope (PLY)Out of dateBuilt as PLY; the next envelope build writes OBJ.");
});

test("the 3D view draws no envelope while its stage is not recorded: a run that wrote it and then failed", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(project(CARVED));
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

test("a workspace made again for a renamed project opens with the steps it had open, and says when they change", async () => {
  service = new FakeService(CARVED, CARVING);
  const stepsReported = vi.fn();
  await openWorkspace(project(CARVED), { startSteps: { open: "carving", view: "carving" }, onStepsChange: stepsReported });
  expect(stepRow("Carving").classList.contains("step-open")).toBe(true);
  expect(stepRow("Inputs").classList.contains("step-open")).toBe(false);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("max_volume")).toBe(false);        // the view shows the carving's layers, not the inputs' ones
  openStep("Export");
  expect(stepsReported).toHaveBeenLastCalledWith({ open: "export", view: "export" });
});

test("the 3D view draws no building massing while its stage is not recorded: a run that wrote it and then failed", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(project(CARVED));
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

test("the saver of the open project waits for an upload in flight, so a rename, reset or delete comes after it", async () => {
  service = new FakeService(CARVED, CARVING);
  let answerUpload: () => void = () => {};
  service.uploadsAnswerWhen = new Promise((resolve) => { answerUpload = resolve; });
  let saver: OpenProjectSettingsSaver | null = null;
  await openWorkspace(project(CARVED), { onSettingsSaverReady: (ready) => { saver = ready; } });
  const maximumVolumePicker = container().querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(maximumVolumePicker, "files", { value: [new File([TRIANGLE_OBJ], "more.obj")], configurable: true });
  act(() => maximumVolumePicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  expect(service.requests).toContain("POST /inputs/max_volume");
  let uploadsEnded = false;
  void saver!.waitForInputChanges().then(() => { uploadsEnded = true; });
  await settle();
  expect(uploadsEnded).toBe(false);
  await act(async () => answerUpload());
  await settle();
  expect(uploadsEnded).toBe(true);
});

test("a North not saved yet turns the drawn sun path with the compass ring, so the two agree until the new path comes", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.sunPath = { days: [{ date: "12-21", day_path: [[0, 1, 0], [0, 0, 1]], period_path: [], markers: [] }] };
  await openWorkspace(project(NOTHING_RUN));
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
  await openWorkspace(project(CARVED));
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
  await openWorkspace(project(CARVED));
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
  await openWorkspace(project(built, { final_mesh_format: "ply" }));
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
  await openWorkspace(project(built, { final_mesh_format: "ply" }));
  openStep("Export");
  await chooseMeshFormat("stl");
  expect(service.runsStarted).toEqual([["exporting"]]);
});

test("a format change with only the massing built rebuilds the massing", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "missing", massing: "current" };
  service = new FakeService(built, CARVING);
  service.summary = { carving: CARVING, envelope: null, massing: MASSING };
  await openWorkspace(project(built, { final_mesh_format: "ply" }));
  openStep("Export");
  await chooseMeshFormat("glb");
  expect(service.runsStarted).toEqual([["massing"]]);
});

// The notice of a new weather file (weather_change_notice.ts) in the Settings step.
const BENEFIT_SCHEMA = {
  properties: { ...SCHEMA.properties, balance_temperature: { default: 15, type: "number" }, balance_offset: { default: 2, minimum: 0, type: "number" } },
};
const COLD_SEASON = { start_month: 9, start_day: 30, start_hour: 0, end_month: 5, end_day: 15, end_hour: 23 };
const MODES_WITH_BENEFIT: ModeInfo[] = [...MODES, { name: "benefit", description: "", needs_epw: true, needs_period: true, experimental: false,
                                                     score_kind: "weighted_sum", weight_unit: "", starting_values: COLD_SEASON }];
const BRISBANE = { location: "Brisbane, AUS", latitude: -27.38 };
const GOLDEN = { location: "Golden, CO, USA", latitude: 39.74 };

async function addWeatherFile() {
  if (!stepRow("Inputs").classList.contains("step-open")) openStep("Inputs");
  const weatherPicker = container().querySelector<HTMLInputElement>('input[type="file"][accept=".epw"]')!;
  Object.defineProperty(weatherPicker, "files", { value: [new File(["LOCATION"], "weather.epw")], configurable: true });
  act(() => weatherPicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  openStep("Settings");
}

/** Past the wait before the cold period is asked for, and its reply. */
const waitForTheColdPeriod = async () => {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 450)); });
  await settle();
};

const weatherNotice = () => container().querySelector<HTMLElement>(".weather-change-notice");
const noticeText = () => weatherNotice()!.querySelector("p")!.textContent;

test("a project opened with a weather file in the other hemisphere shows no notice: only a weather file added in this session does", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace({ ...project(NOTHING_RUN), weather_location: BRISBANE.location, weather_latitude: BRISBANE.latitude });
  openStep("Settings");
  expect(weatherNotice()).toBeNull();
});

test("a weather file in the other hemisphere: the notice offers the period six months on, which goes through the saver", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(project(NOTHING_RUN));
  await addWeatherFile();
  expect(weatherNotice()!.getAttribute("role")).toBe("status");
  expect(noticeText()).toBe(
    "Brisbane, AUS is in the southern hemisphere: winter there is June to August. Shift the analysis period by six months, to 21 Jun, 10 to 14 h?");
  expect(buttonIn(weatherNotice()!, "Keep").getAttribute("aria-label")).toBe("Keep the analysis period");
  act(() => buttonIn(weatherNotice()!, "Shift by six months").click());
  expect(weatherNotice()).toBeNull();
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "time-based", start_month: 6, end_month: 6 }]);      // the settings changed, as the period control sends
});

test("a first weather file counts as after a northern one; the heating season preset follows the hemisphere of the file", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace({ ...project(NOTHING_RUN), inputs: { ...project(NOTHING_RUN).inputs, weather: [] }, weather_location: null, weather_latitude: null });
  openStep("Settings");
  expect(buttonIn(container(), "Heating season, October to April")).toBeDefined();
  await addWeatherFile();
  expect(noticeText()).toContain("Brisbane, AUS is in the southern hemisphere");
  expect(buttonIn(container(), "Heating season, October to April")).toBeUndefined();
  expect(buttonIn(container(), "Heating season, April to October")).toBeDefined();
});

test("Keep dismisses the notice and saves nothing; a later weather file brings a notice again", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(project(NOTHING_RUN));
  await addWeatherFile();
  act(() => buttonIn(weatherNotice()!, "Keep").click());
  expect(weatherNotice()).toBeNull();
  await waitForTheSave();
  expect(service.savedValues).toEqual([]);
  service.uploadedWeather = GOLDEN;                 // back north, the period still northern: the notice asks about the change again
  await addWeatherFile();
  expect(noticeText()).toBe(
    "Golden, CO, USA is in the northern hemisphere: winter there is December to February. Shift the analysis period by six months, to 21 Jun, 10 to 14 h?");
});

test("a weather file in the same hemisphere, or in a mode that reads no period, brings no notice", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(project(NOTHING_RUN));
  await addWeatherFile();                           // Golden after Golden
  expect(weatherNotice()).toBeNull();
  rendered!.unmount();
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(project(NOTHING_RUN, { mode: "daylight" }));
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();
});

test("while a run is in progress the notice's buttons are disabled, as the settings are", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(project(NOTHING_RUN));
  await addWeatherFile();
  await pressRunAnalysis();
  for (const name of ["Shift by six months", "Keep"]) expect(buttonIn(weatherNotice()!, name).disabled).toBe(true);
});

test("Solar usefulness: the notice waits for the cold period of the new file and offers it, keeping the hours", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(project(NOTHING_RUN, { mode: "benefit" }), {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await waitForTheColdPeriod();                     // of the file the project opened with: none
  service.coldPeriodReply = { status: "found", period: { start_month: 5, start_day: 3, end_month: 9, end_day: 20 } };
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();               // waiting for the new file's answer
  await waitForTheColdPeriod();
  expect(noticeText()).toBe("The cold period of the new weather file, Brisbane, AUS, is 3 May to 20 Sep; the analysis period reads 30 Sep to 15 May.");
  act(() => buttonIn(weatherNotice()!, "Use the cold period").click());
  expect(weatherNotice()).toBeNull();
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "benefit", start_month: 5, start_day: 3, end_month: 9, end_day: 20 }]);           // the hours kept
});

test("Solar usefulness: no cold period in the new file, or the one the period already has, brings no notice", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(project(NOTHING_RUN, { mode: "benefit" }), {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await addWeatherFile();                           // the service finds no cold period
  await waitForTheColdPeriod();
  expect(weatherNotice()).toBeNull();
  service.coldPeriodReply = { status: "found", period: { start_month: 9, start_day: 30, end_month: 5, end_day: 15 } };
  await addWeatherFile();
  await waitForTheColdPeriod();
  expect(weatherNotice()).toBeNull();
});

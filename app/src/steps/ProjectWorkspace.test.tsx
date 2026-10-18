// The open project as a whole, against a fake service: the settings form, the run loop, the stage status, the results and the
// layers of the 3D view together, as the unit tests of each cannot show them.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ModeInfo, ProjectDetail } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { SAVE_DELAY_MILLISECONDS } from "../settings_form/form_state";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ProjectWorkspace } from "./ProjectWorkspace";
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
  summary: { carving: typeof CARVING | null; massing: null };
  /** The status every save is refused with (409: a run of the project the page does not know of); null: saves are stored. */
  refuseSavesWith: number | null = null;
  /** While set, a request to start a run gets its reply only once this promise resolves. */
  runStartsWaitFor: Promise<void> | null = null;
  /** Every stage asked for is current already (a run the page did not follow made them so). */
  everythingUpToDate = false;
  /** The field errors a save of these values is refused with (422), or null when it is stored. */
  configErrorsOf: (values: Record<string, unknown>) => { field: string | null; message: string }[] | null = () => null;
  /** The contents of input files by path (for example "/inputs/test_surfaces/surfaces.obj"); one triangle for any other. */
  inputFileContents: Record<string, string> = {};

  constructor(stages: Record<PipelineStage, StageState>, carving: typeof CARVING | null) {
    this.stages = stages;
    this.summary = { carving, massing: null };
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
    if (path === "/run/summary") return json(this.summary);
    if (path.startsWith("/inputs/")) return new Response(this.inputFileContents[path] ?? TRIANGLE_OBJ);
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
    joined_bounds: [[0, 0, 0], [1, 1, 0]], weather_location: "Golden, CO, USA", stage_status: { stages }, grid_plan: null,
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

async function openWorkspace(opened: ProjectDetail) {
  vi.stubGlobal("fetch", vi.fn(service.answer));
  function Page() {
    const runs = useRunLoop("token", () => {});
    return <ProjectWorkspace token="token" project={opened} schema={SCHEMA} modes={MODES} warmUpState="ready" runs={runs}
                             onServiceProblem={() => {}} onShowProjects={() => {}} />;
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

const voxelSizeField = () => container().querySelector<HTMLInputElement>('[data-setting="voxel_size"] input')!;
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
  service.summary = { carving: CARVING, massing: null };
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
  const slope = container().querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input')!;
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

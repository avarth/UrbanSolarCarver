// The open project against a fake service, shared by ProjectWorkspace.saves_and_runs.test.tsx and
// ProjectWorkspace.view_and_results.test.tsx: the fake service, the project it serves, opening the workspace and finding its parts.
// Each test file mocks ../viewer/scene with FakeViewerScene itself (vi.mock applies to the file it is written in).
import { act, useState, type ComponentProps } from "react";
import { vi } from "vitest";
import type { CriterionEntry, InputFileChange, InputFileInfo, ModeInfo, ProjectDetail, SunPath } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { SAVE_DELAY_MILLISECONDS } from "../settings_form/form_state";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ProjectWorkspace } from "./ProjectWorkspace";
import { useRunLoop } from "./run_state";
import type { PipelineStage, StageState } from "./step_summaries";
import type { WorkspaceMode } from "./WorkspaceModeSwitch";

export const SCHEMA = {
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
export const MODES: ModeInfo[] = [
  { name: "time-based", description: "", needs_epw: true, needs_period: true, experimental: false, score_kind: "violation_count", weight_unit: "m²·h", score_unit: "m²·h",
    starting_values: { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14 } },
  { name: "daylight", description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: "weighted_sum", weight_unit: "", score_unit: "",
    starting_values: {} },
];
/** The settings that belong to a criterion, as GET criterion-keys names them. */
export const CRITERION_KEYS: ReadonlySet<string> = new Set([
  "balance_offset", "balance_temperature", "bliss_k", "carve_above", "carve_above_min_consecutive", "carve_fraction", "dew_point_celsius", "edge_taper",
  "end_day", "end_hour", "end_month", "id", "include_harm", "max_slope_deg", "min_altitude", "min_sky_elevation_deg", "mode", "name", "rays_per_patch",
  "score_smoothing", "simulated_weights_path", "start_day", "start_hour", "start_month", "sun_steps_per_hour", "test_surface_path", "threshold",
  "tilted_plane_angle_deg", "time_basis",
]);
export const TRIANGLE_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";
export const CARVING = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: null,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 0,
};
export const ENVELOPE = { mesh_file: "export.ply", envelope_volume_m3: 4150 };
export const MASSING = { export_mesh_file: "plates.ply", floor_area_m2_per_storey: [500, 380], total_floor_area_m2: 880, storeys_built: 2 };
export const NOTHING_RUN: Record<PipelineStage, StageState> = { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing" };
export const CARVED: Record<PipelineStage, StageState> = { ...NOTHING_RUN, preprocessing: "current", thresholding: "current" };

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/**
 * The local service as the open project "p" uses it: it stores the shared settings (PUT shared-settings) and those of criterion
 * 1 (PATCH criteria/1), every stored body in savedValues, answers the stage status, starts runs (whose
 * events the test sends) and serves the run summary and the input meshes; everything else is not there (404).
 */
export class FakeService {
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
  /** The criterion a refused shared settings save names (the one whose settings refused the shared values); null: none. */
  sharedRefusalCriterion: string | null = null;
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
  /** The modes whose starting values a criterion's settings are stored on top of (openWorkspace gives the workspace's). */
  modes: ModeInfo[] = MODES;
  /** The shared settings stored by the saves of this test, which a shared settings save is merged into. */
  sharedSettings: Record<string, unknown> = {};
  /** The settings of criterion 1 as stored: those the project opened with (openWorkspace), then those of the last criterion save. */
  criterionSettings: Record<string, unknown> = {};
  /** The test surface files of criterion 1 (openWorkspace gives the opened project's), changed by its test surface routes. */
  criterionTestSurfaceFiles: string[] = ["surfaces.obj"];
  /** Every stored test surface file, as GET inputs/test_surfaces lists them. */
  storedTestSurfaces: InputFileInfo[] = [{ name: "surfaces.obj", triangle_count: 1 }];
  /** The input files changed in the project folder or missing from it, as the stage status lists them; DELETE input-changes drops the changed ones. */
  inputChanges: InputFileChange[] = [];

  constructor(stages: Record<PipelineStage, StageState>, carving: typeof CARVING | null) {
    this.stages = stages;
    this.summary = { carving, envelope: null, massing: null };
  }

  answer = async (address: string, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    // Requests are listed with their query (the criterion of a result); they are answered by their path.
    const fullPath = address.replace("/api/projects/p", "");
    const path = fullPath.split("?")[0];
    this.requests.push(`${method} ${fullPath}`);
    if (method === "PUT" && path === "/shared-settings") {
      if (this.refuseSavesWith !== null) return json({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const { values } = JSON.parse(String(init!.body)) as { values: Record<string, unknown> };
      const criterionSettings = Object.keys(values).filter((name) => CRITERION_KEYS.has(name));
      const fieldErrors = criterionSettings.length > 0
        ? criterionSettings.map((field) => ({ field, message: "A setting of one criterion, not shared by the criteria." })) : this.configErrorsOf(values);
      if (fieldErrors !== null) return json({ field_errors: fieldErrors, grid_plan: null, criterion: this.sharedRefusalCriterion }, 422);
      this.savedValues.push(values);
      this.sharedSettings = { ...this.sharedSettings, ...values };       // merged into the stored shared settings
      return json({ settings: this.sharedSettings, grid_plan: null });
    }
    if (method === "PATCH" && path === "/criteria/1") {
      if (this.refuseSavesWith !== null) return json({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const { values } = JSON.parse(String(init!.body)) as { values: Record<string, unknown> };
      const fieldErrors = this.configErrorsOf(values);
      if (fieldErrors !== null) return json({ field_errors: fieldErrors, grid_plan: null, criterion: "1" }, 422);
      this.savedValues.push(values);
      // The criterion's settings are replaced, on top of the starting values of their mode (shared settings in the values are
      // ignored), and it is named after a new mode.
      const mode = String(values.mode);
      const startingValues = this.modes.find((candidate) => candidate.name === mode)?.starting_values ?? {};
      this.criterionSettings = Object.fromEntries(Object.entries({ ...startingValues, ...values }).filter(([name]) => CRITERION_KEYS.has(name)));
      return json(criterionEntry(this.criterionSettings, this.criterionTestSurfaceFiles));
    }
    if (method === "POST" && path === "/criteria/1/test-surfaces") {
      if (this.refuseSavesWith !== null) return json({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const fileName = ((init!.body as FormData).get("file") as File).name;
      if (!this.criterionTestSurfaceFiles.includes(fileName)) this.criterionTestSurfaceFiles = [...this.criterionTestSurfaceFiles, fileName];
      if (!this.storedTestSurfaces.some((file) => file.name === fileName)) this.storedTestSurfaces = [...this.storedTestSurfaces, { name: fileName, triangle_count: 1 }];
      return json(criterionEntry(this.criterionSettings, this.criterionTestSurfaceFiles));
    }
    if (method === "DELETE" && path.startsWith("/criteria/1/test-surfaces/")) {
      const fileName = decodeURIComponent(path.replace("/criteria/1/test-surfaces/", ""));
      this.criterionTestSurfaceFiles = this.criterionTestSurfaceFiles.filter((name) => name !== fileName);
      this.storedTestSurfaces = this.storedTestSurfaces.filter((file) => file.name !== fileName);       // no other criterion uses it
      return json(criterionEntry(this.criterionSettings, this.criterionTestSurfaceFiles));
    }
    if (method === "GET" && path === "/inputs/test_surfaces") return json(this.storedTestSurfaces);
    if (path === "/stage-status") {
      return json({ stages: this.stages, criteria: { 1: { preprocessing: this.stages.preprocessing, thresholding: this.stages.thresholding } },
                    input_changes: this.inputChanges });
    }
    if (method === "DELETE" && path === "/input-changes") {
      this.inputChanges = this.inputChanges.filter((change) => change.state !== "changed");
      return new Response(null, { status: 204 });
    }
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

/** Criterion 1 of the project "p", with *settings* (the mode and its settings), as the service replies with it. */
export function criterionEntry(settings: Record<string, unknown>, testSurfaceFiles: string[] = ["surfaces.obj"]): CriterionEntry {
  return { id: "1", name: String(settings.mode), named_by_user: false, colour: "#4477aa", bypassed: false, test_surface_files: testSurfaceFiles, settings };
}

/** The project "p" of one criterion; *settings* are flat, the shared ones with those of criterion 1, as GET project gives them. */
export function project(stages: Record<PipelineStage, StageState>, settings: Record<string, unknown> = {}): ProjectDetail {
  const flatSettings = { mode: "time-based", ...settings };
  const criterionSettings = Object.fromEntries(Object.entries(flatSettings).filter(([name]) => CRITERION_KEYS.has(name)));
  return {
    name: "p", created: "2026-10-17T09:00:00", modified: "2026-10-17T09:00:00", settings: flatSettings,
    inputs: { max_volume: [{ name: "volume.obj", triangle_count: 1 }], test_surfaces: [{ name: "surfaces.obj", triangle_count: 1 }],
              weather: [{ name: "weather.epw", triangle_count: 0 }] },
    joined_bounds: [[0, 0, 0], [1, 1, 0]], weather_location: "Golden, CO, USA", weather_latitude: 39.74, stage_status: { stages }, grid_plan: null,
    criteria: [criterionEntry(criterionSettings)], criterion_status: { 1: stages },
  };
}

let rendered: RenderedOverlay | null = null;

/** For each test file's beforeEach. */
export function startWorkspaceTest() {
  // settle and waitForTheSave move the fake clock instead of waiting in real time.
  vi.useFakeTimers();
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  pretendTheBrowserHasWebGl();
}

/** For each test file's afterEach. */
export function endWorkspaceTest() {
  rendered?.unmount();
  rendered = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
}

/** Unmounts the open workspace, so a test can open another (endWorkspaceTest unmounts the last one). */
export function unmountWorkspace() {
  rendered?.unmount();
  rendered = null;
}

export const settle = () => act(async () => {
  for (let tick = 0; tick < 5; tick++) await vi.advanceTimersByTimeAsync(0);
});
export const waitForTheSave = () => act(async () => { await vi.advanceTimersByTimeAsync(SAVE_DELAY_MILLISECONDS + 50); });

export async function openWorkspace(
  service: FakeService, opened: ProjectDetail,
  steps: Pick<ComponentProps<typeof ProjectWorkspace>, "startSteps" | "onStepsChange" | "onSettingsSaverReady"> = {},
  { schema = SCHEMA, modes = MODES }: { schema?: typeof SCHEMA; modes?: ModeInfo[] } = {},
) {
  vi.stubGlobal("fetch", vi.fn(service.answer));
  service.modes = modes;
  service.criterionSettings = opened.criteria?.[0]?.settings ?? {};
  service.criterionTestSurfaceFiles = opened.criteria?.[0]?.test_surface_files ?? [];
  service.storedTestSurfaces = opened.inputs.test_surfaces ?? [];
  function Page() {
    const runs = useRunLoop("token", () => {});
    const [mode, setMode] = useState<WorkspaceMode>("design");
    changeMode = setMode;
    return <ProjectWorkspace token="token" project={opened} schema={schema} modes={modes} criterionKeys={CRITERION_KEYS} warmUpState="ready" runs={runs}
                             mode={mode} onServiceProblem={() => {}} onShowProjects={() => {}} {...steps} />;
  }
  rendered = renderForTest(<Page />);
  await settle();
}

let changeMode: ((mode: WorkspaceMode) => void) | null = null;
/** Switches the open workspace between Design and Simulate, as the top bar's switch does. */
export const switchMode = (mode: WorkspaceMode) => act(() => changeMode!(mode));

export const container = () => rendered!.container;
export const dimmedLayers = () => [...FakeViewerScene.latest!.dimmed].sort();
/** The dimmed layers among the carving's (the envelope and the massing follow their own stages, never built here). */
export const dimmedCarvingLayers = () => dimmedLayers().filter((layer) => ["kept_voxels", "carved_voxels", "sky_dome"].includes(layer));

export function stepRow(title: string): HTMLElement {
  return [...container().querySelectorAll<HTMLElement>(".step")].find((row) => row.querySelector(".step-title")!.textContent === title)!;
}

export function openStep(title: string) {
  act(() => stepRow(title).querySelector<HTMLButtonElement>(".step-header")!.click());
}

/** The header of the criterion panel's section titled *title* ("Test surfaces", "Mode", "Settings", "Carving rule"). */
export function panelSectionHeader(title: string): HTMLButtonElement {
  return [...container().querySelectorAll<HTMLButtonElement>(".panel-section-header")]
    .find((header) => header.querySelector(".panel-section-title")!.textContent === title)!;
}

export const panelSectionOpen = (title: string) => panelSectionHeader(title).getAttribute("aria-expanded") === "true";

/** The titles of the criterion panel's open sections, in order. */
export const openPanelSections = () => [...container().querySelectorAll<HTMLButtonElement>('.panel-section-header[aria-expanded="true"]')]
  .map((header) => header.querySelector(".panel-section-title")!.textContent);

export function togglePanelSection(title: string) {
  act(() => panelSectionHeader(title).click());
}

/** Opens the criterion panel's section titled *title*, when it is closed. */
export function openPanelSection(title: string) {
  if (!panelSectionOpen(title)) togglePanelSection(title);
}

export function type(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

export function typeAndLeave(input: HTMLInputElement, text: string) {
  type(input, text);
  act(() => input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
}

/** The bar pinned under the steps: Run analysis in Site and grid; Run analysis and Build envelope and massing in Criteria. */
export const pinnedBar = () => container().querySelector<HTMLElement>(".step-pinned-action")!;

/** Presses Run analysis, pinned under the steps. */
export async function pressRunAnalysis() {
  const button = [...pinnedBar().querySelectorAll<HTMLButtonElement>("button")].find((candidate) => candidate.textContent === "Run analysis")!;
  await act(async () => button.click());
  await settle();
}

/** The part of the Envelope and massing step whose heading is *title*. */
export function buildPart(title: string): HTMLElement {
  return [...container().querySelectorAll<HTMLElement>(".build-part")].find((part) => part.querySelector(".setting-group-title")!.textContent === title)!;
}

export function buttonIn(root: Element, text: string): HTMLButtonElement {
  return [...root.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === text)!;
}

/** Why a disabled button is disabled: the text its aria-describedby names. */
export const reasonOf = (button: HTMLButtonElement) => document.getElementById(button.getAttribute("aria-describedby")!)!.textContent;

export const voxelSizeField = () => container().querySelector<HTMLInputElement>('[data-setting="voxel_size"] input[type="number"]')!;
export const thresholdField = () => container().querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
export const thresholdOf = (values: Record<string, unknown>) => (values.threshold as { value: number }).value;

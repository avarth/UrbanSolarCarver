// The open project against a fake service, shared by every ProjectWorkspace.*.test.tsx file (saves_and_runs, weather_notice,
// chain_runs, criteria, criterion_cards, input_changes, inspect, picked_surfaces, simulate, three_d, view_and_results) and by chain_service_for_test.tsx,
// which builds on it; a few component tests take its SCHEMA or MODES. It holds the fake service, the project it serves, opening the
// workspace and finding its parts. Each test file mocks ../viewer/scene with FakeViewerScene itself (vi.mock applies to the file it is
// written in). settle, type and typeAndLeave come from render_for_test.tsx and are exported again here, so a workspace test imports
// its helpers from one file.
import { act, useState, type ComponentProps } from "react";
import { flushSync } from "react-dom";
import { vi } from "vitest";
import type {
  ColdPeriodReply, ConfigErrorReply, ConfigReply, CriterionEntry, InputFileChange, InputFileInfo, InputFilesReply, InspectedFile, InspectReply, ModeInfo,
  Heights, OutlinesReply, SiteJson, SitesReply,
  ProjectDetail, RunSummary, StageStatusReply, StartRunReply, SunChart, SunPath, SunPositions,
} from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { SERVICE_CRITERION_KEYS, SERVICE_MODES, SERVICE_SCHEMA } from "../api_client/service_data_for_test";
import type { components } from "../api_client/generated_types";
import { useLeavingInspect } from "../inspect/UnsavedTurnsDialog";
import { SAVE_DELAY_MILLISECONDS } from "../settings_form/form_state";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import { holdReply, renderForTest, settle, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ProjectWorkspace } from "./ProjectWorkspace";
import { useRunLoop } from "../common/run_state";
import type { PipelineStage, StageState } from "../stages";
import type { WorkspaceMode } from "../common/WorkspaceModeSwitch";

type ErrorDetailReply = components["schemas"]["ErrorDetailReply"];
type StoredFileChangedReply = components["schemas"]["StoredFileChangedReply"];
type SurfacePick = components["schemas"]["SurfacePick"];
type PickedSurfacesRequest = components["schemas"]["PickedSurfacesRequest"];
type DrawnSurfaceRequest = components["schemas"]["DrawnSurfaceRequest"];
type GroundOutline = components["schemas"]["GroundOutline"];
type SurfacePicksReply = components["schemas"]["SurfacePicksReply"];

// The service's schema, modes and criterion settings as GET schema, modes and criterion-keys give them (service_data_for_test.json,
// written from the service), so the form has the bounds, defaults and descriptions the user gets.
export const SCHEMA = SERVICE_SCHEMA;
export const MODES: ModeInfo[] = SERVICE_MODES;
/** The settings that belong to a criterion, as GET criterion-keys names them. */
export const CRITERION_KEYS: ReadonlySet<string> = SERVICE_CRITERION_KEYS;
export const TRIANGLE_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";
export const CARVING = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: null,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 0,
};
export const ENVELOPE = { mesh_file: "export.ply", envelope_volume_m3: 4150 };
export const MASSING = { export_mesh_file: "plates.ply", floor_area_m2_per_storey: [500, 380], total_floor_area_m2: 880, storeys_built: 2 };
export const NOTHING_RUN: Record<PipelineStage, StageState> = { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing" };
export const CARVED: Record<PipelineStage, StageState> = { ...NOTHING_RUN, preprocessing: "current", thresholding: "current" };

/** A reply of the fake service. Given the service's type of the reply (json<RunSummary>(...)), the body is checked against it. */
export function json<Reply = unknown>(body: NoInfer<Reply>, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// One triangle as an ASCII PLY file: the joined maximum volume a project that uses its sites is drawn from (GET max-volume)
const TRIANGLE_PLY = ["ply", "format ascii 1.0", "element vertex 3", "property float x", "property float y", "property float z", "element face 1",
  "property list uchar int vertex_indices", "end_header", "0 0 0", "10 0 0", "0 10 30", "3 0 1 2", ""].join("\n");

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
  /** The status GET run/sky-patches fails with; null: it answers that the run has no sky patches (null), as for a time-based run. */
  runSkyPatchesFailWith: number | null = null;
  /** The reply of GET sun-chart (Simulate's sun tool). */
  sunChart: SunChart = { key_days: [], hour_lines: [], day: { date: "12-21", runs: [[[-0.5, -0.5, 0.71], [0, -0.6, 0.8]]] } };
  /** GET sun-positions: the sun is up from 08:00 to 16:00, toward SUN_UP, every step of the range asked for, on one day. */
  static readonly SUN_UP = [0, -0.6, 0.8];
  /** While set, an upload of an input file gets its reply only once this promise resolves. */
  uploadsAnswerWhen: Promise<void> | null = null;
  /** The location and latitude the reply to a weather file upload gives. */
  uploadedWeather = { location: "Golden, CO, USA", latitude: 39.74 };
  /** The reply of GET cold-period. */
  coldPeriodReply: ColdPeriodReply = { status: "none", period: null };
  /** The modes whose starting values a criterion's settings are stored on top of (openWorkspace gives the workspace's). */
  modes: ModeInfo[] = MODES;
  /** The shared settings stored by the saves of this test, which a shared settings save is merged into. */
  sharedSettings: Record<string, unknown> = {};
  /** The settings of criterion 1 as stored: those the project opened with (openWorkspace), then those of the last criterion save. */
  criterionSettings: Record<string, unknown> = {};
  /** The test surface files of criterion 1 (openWorkspace gives the opened project's), changed by its test surface routes. */
  criterionTestSurfaceFiles: string[] = ["surfaces.obj"];
  /**
   * Every stored test surface file (the project's surface sets), as GET inputs/test_surfaces lists them; each is listed with the criteria
   * that use it in used_by (storedSetsWithUsers).
   */
  storedTestSurfaces: InputFileInfo[] = [{ name: "surfaces.obj", triangle_count: 1 }];
  /** The input files changed in the project folder or missing from it, as the stage status lists them; DELETE input-changes drops the changed ones. */
  inputChanges: InputFileChange[] = [];
  /**
   * The input mesh files as GET inspect summarises them (Inspect); POST turn and restore change whether a file's original is kept,
   * and its version (a "*" more). A turn or restore that names another version than the file's here is refused with a 409.
   */
  inspection: InspectedFile[] = [];
  /** The packed geometry of each test surface file (GET inspect/test_surfaces/{file}/geometry; packedInspectGeometry). */
  inspectGeometries: Record<string, ArrayBuffer> = {};
  /** The file and the body of every POST inspect/test_surfaces/{file}/turn. */
  readonly turnRequests: { fileName: string; body: unknown }[] = [];
  /** The file and the body of every POST inspect/test_surfaces/{file}/restore. */
  readonly restoreRequests: { fileName: string; body: unknown }[] = [];
  /** While set, a POST inspect/test_surfaces/{file}/turn gets its reply only once this promise resolves. */
  turnsAnswerWhen: Promise<void> | null = null;
  /** While set, a POST inspect/test_surfaces/{file}/restore gets its reply only once this promise resolves. */
  restoresAnswerWhen: Promise<void> | null = null;

  /** What GET sites answers, and what PUT sites and PUT max-volume-source change. */
  siteSource: "mesh" | "sites" = "mesh";
  sites: SiteJson[] = [];
  /** The overlapping pairs of sites GET and PUT sites report (design/site-holes.md). */
  siteOverlaps: NonNullable<SitesReply["overlaps"]> = [];
  /** What PUT heights stored (design/base-height.md). */
  heights: Heights = { max: { for_all_sites: false, value: null }, base: { for_all_sites: true, value: null } };
  savedHeights: Heights[] = [];
  /** The bodies of every PUT sites. */
  readonly savedSites: SiteJson[][] = [];
  /** While set, PUT sites is refused (422) with this reason, as the service refuses a site that cannot make a volume. */
  sitesRefusal: string | null = null;
  /** What GET context-blocks answers and PUT context-blocks stores (design/context-blocks.md). */
  contextBlocks: SiteJson[] = [];
  /** The bodies of every PUT context-blocks. */
  readonly savedContextBlocks: SiteJson[][] = [];
  /** While set, PUT context-blocks is refused (422) with this reason. */
  contextBlocksRefusal: string | null = null;
  /** What POST outlines answers (design/site-import.md): the outlines read, or a refusal with its status and reason. */
  outlinesReply: OutlinesReply | { status: number; detail: string } = { file: "plots.dxf", unit: "metres", outlines: [], left_out: [], distance_from_inputs: null };
  /** The name of the file of every POST outlines. */
  readonly outlineFilesRead: string[] = [];
  /** The terrain's height at each plan point of a POST terrain-heights; null: the project has no terrain (404). */
  terrainHeightsOf: ((points: number[][]) => (number | null)[]) | null = (points) => points.map(() => 0);
  /** The points of every POST terrain-heights. */
  readonly terrainRequests: number[][][] = [];
  /** Whether the carving reruns as its settings change (project.json carving_updates_itself), as PUT carving-updates stores it. */
  carvingUpdatesItself = true;
  /** The body of every PUT carving-updates. */
  readonly carvingUpdateChoices: { on: boolean }[] = [];
  // Surface sets (design/test-surfaces-on-context.md)
  /** The picks of each picked set by its stored file, as GET surface-sets/{file}/picks gives them and POST surface-sets/picked stores them. */
  surfacePicks: Record<string, SurfacePick[]> = {};
  /** The body of every POST surface-sets/picked. */
  readonly pickedSetRequests: PickedSurfacesRequest[] = [];
  /** The reason POST surface-sets/picked is refused with (422); null: the set is stored. */
  pickRefusal: string | null = null;
  /** The file and the name of every PUT surface-sets/{file}/name. */
  readonly setRenames: { fileName: string; name: string }[] = [];
  // Surface sets drawn on the ground (design/test-surfaces-on-ground.md)
  /** The outline of each drawn set by its stored file, as GET surface-sets/{file}/outline gives it and POST surface-sets/drawn stores it. */
  groundOutlines: Record<string, GroundOutline> = {};
  /** The body of every POST surface-sets/drawn. */
  readonly drawnSetRequests: DrawnSurfaceRequest[] = [];
  /** The reason POST surface-sets/drawn is refused with (422); null: the set is stored. */
  drawRefusal: string | null = null;
  /** Replies held back (holdReply) until their promise resolves: GET surface-sets/{file}/outline by file, and POST surface-sets/drawn ("drawn"). */
  readonly heldReplies: Record<string, Promise<void>> = {};

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
      if (this.refuseSavesWith !== null) return json<ErrorDetailReply>({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const { values } = JSON.parse(String(init!.body)) as { values: Record<string, unknown> };
      const criterionSettings = Object.keys(values).filter((name) => CRITERION_KEYS.has(name));
      const fieldErrors = criterionSettings.length > 0
        ? criterionSettings.map((field) => ({ field, message: "A setting of one criterion, not shared by the criteria." })) : this.configErrorsOf(values);
      if (fieldErrors !== null) return json<ConfigErrorReply>({ field_errors: fieldErrors, grid_plan: null, criterion: this.sharedRefusalCriterion }, 422);
      this.savedValues.push(values);
      this.sharedSettings = { ...this.sharedSettings, ...values };       // merged into the stored shared settings
      return json<ConfigReply>({ settings: this.sharedSettings, grid_plan: null });
    }
    if (method === "PATCH" && path === "/criteria/1") {
      if (this.refuseSavesWith !== null) return json<ErrorDetailReply>({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const { values } = JSON.parse(String(init!.body)) as { values: Record<string, unknown> };
      const fieldErrors = this.configErrorsOf(values);
      if (fieldErrors !== null) return json<ConfigErrorReply>({ field_errors: fieldErrors, grid_plan: null, criterion: "1" }, 422);
      this.savedValues.push(values);
      // The criterion's settings are replaced, on top of the starting values of their mode (shared settings in the values are
      // ignored), and it is named after a new mode.
      const mode = String(values.mode);
      const startingValues = this.modes.find((candidate) => candidate.name === mode)?.starting_values ?? {};
      this.criterionSettings = Object.fromEntries(Object.entries({ ...startingValues, ...values }).filter(([name]) => CRITERION_KEYS.has(name)));
      return json<CriterionEntry>(criterionEntry(this.criterionSettings, this.criterionTestSurfaceFiles));
    }
    if (method === "POST" && path === "/criteria/1/test-surfaces") {
      if (this.refuseSavesWith !== null) return json<ErrorDetailReply>({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const fileName = ((init!.body as FormData).get("file") as File).name;
      if (!this.criterionTestSurfaceFiles.includes(fileName)) this.criterionTestSurfaceFiles = [...this.criterionTestSurfaceFiles, fileName];
      if (!this.storedTestSurfaces.some((file) => file.name === fileName)) this.storedTestSurfaces = [...this.storedTestSurfaces, { name: fileName, triangle_count: 1 }];
      return json<CriterionEntry>(criterionEntry(this.criterionSettings, this.criterionTestSurfaceFiles));
    }
    // A surface set switched on (PUT) or off (DELETE) for criterion 1: the set stays in the project either way
    if ((method === "PUT" || method === "DELETE") && path.startsWith("/criteria/1/test-surfaces/")) {
      if (this.refuseSavesWith !== null) return json<ErrorDetailReply>({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
      const fileName = decodeURIComponent(path.replace("/criteria/1/test-surfaces/", ""));
      if (!this.storedTestSurfaces.some((file) => file.name === fileName)) return json<ErrorDetailReply>({ detail: "Not found" }, 404);
      this.criterionTestSurfaceFiles = method === "PUT"
        ? [...this.criterionTestSurfaceFiles.filter((name) => name !== fileName), fileName] : this.criterionTestSurfaceFiles.filter((name) => name !== fileName);
      return json<CriterionEntry>(criterionEntry(this.criterionSettings, this.criterionTestSurfaceFiles));
    }
    if (method === "GET" && path === "/inputs/test_surfaces") return json<InputFileInfo[]>(this.storedSetsWithUsers());
    // The Site step's Test surfaces box: a set uploaded to the project (used by nothing yet), or removed unless criterion 1 uses it
    if (method === "POST" && path === "/inputs/test_surfaces") {
      await holdReply(this.uploadsAnswerWhen);
      const fileName = ((init!.body as FormData).get("file") as File).name;
      if (!this.storedTestSurfaces.some((file) => file.name === fileName)) this.storedTestSurfaces = [...this.storedTestSurfaces, { name: fileName, triangle_count: 1 }];
      return this.testSurfacesReply();
    }
    if (method === "DELETE" && path.startsWith("/inputs/test_surfaces/")) {
      const fileName = decodeURIComponent(path.replace("/inputs/test_surfaces/", ""));
      if (!this.storedTestSurfaces.some((file) => file.name === fileName)) return json<ErrorDetailReply>({ detail: "Not found" }, 404);
      const users = this.storedSetsWithUsers().find((file) => file.name === fileName)?.used_by ?? [];
      if (users.length > 0) return json<ErrorDetailReply>({ detail: `${fileName} is used by ${users.join(" and ")}. Switch it off there first.` }, 422);
      this.storedTestSurfaces = this.storedTestSurfaces.filter((file) => file.name !== fileName);
      return this.testSurfacesReply();
    }
    if (path.startsWith("/surface-sets/")) return this.answerSurfaceSets(method, path, init);
    if (path === "/sites" || path === "/max-volume-source" || path === "/heights") {
      if (method === "PUT" && path === "/heights") {
        this.heights = JSON.parse(String(init!.body)) as Heights;
        this.savedHeights.push(this.heights);
      }
      if (method === "PUT" && path === "/sites" && this.sitesRefusal !== null) return json<ErrorDetailReply>({ detail: this.sitesRefusal }, 422);
      if (method === "PUT" && path === "/sites") {
        this.sites = (JSON.parse(String(init!.body)) as { sites: SiteJson[] }).sites;
        this.savedSites.push(this.sites);
      }
      if (method === "PUT" && path === "/max-volume-source") this.siteSource = (JSON.parse(String(init!.body)) as { source: "mesh" | "sites" }).source;
      const bounds = this.siteSource === "sites" && this.sites.length ? [[0, 0, 0], [10, 10, 30]] : null;
      return json<SitesReply>({ source: this.siteSource, sites: this.sites, joined_bounds: bounds, grid_plan: null, heights: this.heights, overlaps: this.siteOverlaps });
    }
    if (method === "POST" && path === "/outlines") {
      this.outlineFilesRead.push(((init!.body as FormData).get("file") as File).name);
      const reply = this.outlinesReply;
      return "status" in reply ? json<ErrorDetailReply>({ detail: reply.detail }, reply.status) : json<OutlinesReply>(reply);
    }
    if (method === "POST" && path === "/terrain-heights") {
      const { points } = JSON.parse(String(init!.body)) as { points: number[][] };
      this.terrainRequests.push(points);
      if (this.terrainHeightsOf === null) return json<ErrorDetailReply>({ detail: "The project has no terrain." }, 404);
      return json<{ heights: (number | null)[] }>({ heights: this.terrainHeightsOf(points) });
    }
    if (path === "/context-blocks") {
      if (method === "PUT" && this.contextBlocksRefusal !== null) return json<ErrorDetailReply>({ detail: this.contextBlocksRefusal }, 422);
      if (method === "PUT") {
        this.contextBlocks = (JSON.parse(String(init!.body)) as { blocks: SiteJson[] }).blocks;
        this.savedContextBlocks.push(this.contextBlocks);
      }
      return json({ blocks: this.contextBlocks, has_mesh: this.contextBlocks.length > 0 });
    }
    if (path === "/context-blocks/mesh") return this.contextBlocks.length ? new Response(TRIANGLE_PLY) : json<ErrorDetailReply>({ detail: "No blocks." }, 404);
    if (path === "/max-volume") return new Response(TRIANGLE_PLY);
    if (path === "/base-volume") return new Response(TRIANGLE_PLY);
    if (path === "/stage-status") {
      return json<StageStatusReply>({ stages: this.stages, criteria: { 1: { preprocessing: this.stages.preprocessing, thresholding: this.stages.thresholding } },
                    input_changes: this.inputChanges });
    }
    if (method === "DELETE" && path === "/input-changes") {
      this.inputChanges = this.inputChanges.filter((change) => change.state !== "changed");
      return new Response(null, { status: 204 });
    }
    if (method === "POST" && path === "/mode-chosen") return new Response(null, { status: 204 });
    if (method === "PUT" && path === "/carving-updates") {
      const choice = JSON.parse(String(init!.body)) as { on: boolean };
      this.carvingUpdateChoices.push(choice);
      this.carvingUpdatesItself = choice.on;
      return new Response(null, { status: 204 });
    }
    if (method === "POST" && path === "/runs") {
      await holdReply(this.runStartsWaitFor);
      const { produce } = JSON.parse(String(init!.body)) as { produce: string[] };
      if (this.everythingUpToDate) return json<StartRunReply>({ status: "up_to_date", run_id: null, stages: [] });
      this.runsStarted.push(produce);
      const stages = this.stages.preprocessing === "current" ? produce : ["preprocessing", ...produce];    // the analysis when it is out of date
      return json<StartRunReply>({ status: "started", run_id: `r${this.runsStarted.length}`, stages });
    }
    if (path === "/sun-path" && this.sunPath !== null) return json<SunPath>(this.sunPath);
    if (path === "/sun-chart") return json<SunChart>(this.sunChart);
    if (path === "/sun-positions") {
      const query = new URLSearchParams(fullPath.split("?")[1]);
      const [start, end, step] = ["start", "end", "step"].map((key) => Number(query.get(key)));
      const minutes = Array.from({ length: Math.floor((end - start) / step) + 1 }, (_, index) => start + index * step).filter((minute) => minute >= 480 && minute <= 960);
      return json<SunPositions>({ positions: minutes.map((minute) => ({ date: query.get("from")!, minute, vector: FakeService.SUN_UP, altitude: 53.1, azimuth: 180 })),
                    days_sampled: 1, day_step: 1, step_minutes: step });
    }
    if (path === "/run/summary") return json<RunSummary>(this.summary);
    if (path === "/run/sky-patches") {
      return this.runSkyPatchesFailWith === null ? json<null>(null) : json<ErrorDetailReply>({ detail: "Failed" }, this.runSkyPatchesFailWith);
    }
    if (method === "POST" && path.startsWith("/inputs/")) {
      await holdReply(this.uploadsAnswerWhen);
      const role = path.replace("/inputs/", "");
      const files = role === "weather" ? [{ name: "weather.epw", triangle_count: 0 }] : [{ name: "more.obj", triangle_count: 1 }];
      return json<InputFilesReply>({ role, files, joined_bounds: [[0, 0, 0], [1, 1, 0]], weather_location: this.uploadedWeather.location,
                    weather_latitude: this.uploadedWeather.latitude });
    }
    if (path.startsWith("/cold-period")) return json<ColdPeriodReply>(this.coldPeriodReply);
    if (method === "GET" && path === "/inspect") return json<InspectReply>({ files: this.inspection });
    const inspected = /^\/inspect\/test_surfaces\/([^/]+)\/(geometry|turn|restore)$/.exec(path);
    if (inspected !== null) return this.answerInspect(method, decodeURIComponent(inspected[1]), inspected[2], init);
    if (path.startsWith("/inputs/")) return new Response(this.inputFileContents[path] ?? TRIANGLE_OBJ);
    if (path === "/run/files/exporting/export.obj" && this.summary.envelope?.mesh_file === "export.obj") return new Response(TRIANGLE_OBJ);
    if (path === "/run/files/massing/plates.obj" && this.massingOnDisk) return new Response(TRIANGLE_OBJ);
    return json<ErrorDetailReply>({ detail: "Not found" }, 404);
  };

  /**
   * The routes of one test surface file in Inspect: its geometry, a turn of its surfaces (refused while saves are), its restore. A
   * turn or restore of a version that is not the file's is refused (409), as the service refuses a file changed in the folder.
   */
  private async answerInspect(method: string, fileName: string, route: string, init?: RequestInit): Promise<Response> {
    const fileNow = () => this.inspection.find((candidate) => candidate.role === "test_surfaces" && candidate.file_name === fileName);
    const file = fileNow();
    if (file === undefined) return json<ErrorDetailReply>({ detail: "Not found" }, 404);
    if (method === "GET" && route === "geometry") return new Response(this.inspectGeometries[fileName].slice(0));
    if (method !== "POST") return json<ErrorDetailReply>({ detail: "Not found" }, 404);
    if (this.refuseSavesWith !== null) return json<ErrorDetailReply>({ detail: "A run of this project is in progress." }, this.refuseSavesWith);
    const body = JSON.parse(String(init?.body ?? "{}")) as { version?: string };
    if (route === "turn") {
      if (!file.flippable) return json<ErrorDetailReply>({ detail: `The test surfaces file '${fileName}' is closed as a whole.` }, 422);
      this.turnRequests.push({ fileName, body });
      await holdReply(this.turnsAnswerWhen);
    } else {
      this.restoreRequests.push({ fileName, body });
      await holdReply(this.restoresAnswerWhen);
    }
    // The file as it is now: a test may change it while the reply is held.
    if (body.version !== fileNow()!.version) {
      return json<StoredFileChangedReply>({ detail: route === "turn" ? FILE_CHANGED_SINCE_TURNED : FILE_CHANGED_SINCE_READ, stored_file_changed: true }, 409);
    }
    if (route === "restore" && !file.original_kept) return json<ErrorDetailReply>({ detail: "No original is kept." }, 404);
    const changed = { ...fileNow()!, original_kept: route === "turn", version: `${fileNow()!.version}*` };
    this.inspection = this.inspection.map((candidate) => (candidate.role === "test_surfaces" && candidate.file_name === fileName ? changed : candidate));
    return json<InspectedFile>(changed);
  }

  /**
   * The surface set routes: POST picked stores a new picked set ("picked_<n>.ply", named as asked or "Picked <n>") or replaces the
   * picks of the set *replace*, two triangles a pick; GET {file}/picks gives a set's picks; PUT {file}/name shows a set by another name.
   */
  private answerSurfaceSets(method: string, path: string, init?: RequestInit): Response | Promise<Response> {
    if (method === "POST" && path === "/surface-sets/picked") {
      const body = JSON.parse(String(init!.body)) as PickedSurfacesRequest;
      this.pickedSetRequests.push(body);
      if (this.pickRefusal !== null) return json<ErrorDetailReply>({ detail: this.pickRefusal }, 422);
      if (typeof body.replace === "string") {
        const kept = this.storedTestSurfaces.find((file) => file.name === body.replace);
        if (kept === undefined) return json<ErrorDetailReply>({ detail: "Not found" }, 404);
        const changed = { ...kept, triangle_count: body.picks.length * 2, picks_lost: 0 };
        this.storedTestSurfaces = this.storedTestSurfaces.map((file) => (file.name === kept.name ? changed : file));
        this.surfacePicks[kept.name] = body.picks;
        return json<InputFileInfo>(changed);
      }
      let number = 1;
      while (this.storedTestSurfaces.some((file) => file.name === `picked_${number}.ply`)) number += 1;
      const stored: InputFileInfo = { name: `picked_${number}.ply`, triangle_count: body.picks.length * 2, shown_name: body.name ?? `Picked ${number}`, picked: true };
      this.storedTestSurfaces = [...this.storedTestSurfaces, stored];
      this.surfacePicks[stored.name] = body.picks;
      return json<InputFileInfo>(stored);
    }
    if (method === "POST" && path === "/surface-sets/drawn") {
      const body = JSON.parse(String(init!.body)) as DrawnSurfaceRequest;
      this.drawnSetRequests.push(body);
      if (this.drawRefusal !== null) return json<ErrorDetailReply>({ detail: this.drawRefusal }, 422);
      const outline = { points: body.outline.points, holes: body.outline.holes ?? [] };
      if (typeof body.replace === "string") {
        const kept = this.storedTestSurfaces.find((file) => file.name === body.replace);
        if (kept === undefined) return json<ErrorDetailReply>({ detail: "Not found" }, 404);
        this.groundOutlines[kept.name] = outline;
        return json<InputFileInfo>(kept);
      }
      let number = 1;
      while (this.storedTestSurfaces.some((file) => file.name === `ground_${number}.ply`)) number += 1;
      const stored: InputFileInfo = { name: `ground_${number}.ply`, triangle_count: 2, shown_name: body.name ?? `Ground ${number}`, drawn: true };
      this.storedTestSurfaces = [...this.storedTestSurfaces, stored];
      this.groundOutlines[stored.name] = outline;
      const held = this.heldReplies.drawn;
      return held === undefined ? json<InputFileInfo>(stored) : holdReply(held).then(() => json<InputFileInfo>(stored));
    }
    const [, , encoded, part] = path.split("/");
    const fileName = decodeURIComponent(encoded);
    const file = this.storedTestSurfaces.find((candidate) => candidate.name === fileName);
    if (file === undefined) return json<ErrorDetailReply>({ detail: "Not found" }, 404);
    if (method === "GET" && part === "picks") return json<SurfacePicksReply>({ picks: this.surfacePicks[fileName] ?? [] });
    if (method === "GET" && part === "outline") {
      const outline = this.groundOutlines[fileName];
      const reply = () => (outline === undefined ? json<ErrorDetailReply>({ detail: "Not drawn" }, 422) : json<GroundOutline>(outline));
      const held = this.heldReplies[fileName];
      return held === undefined ? reply() : holdReply(held).then(reply);
    }
    if (method === "PUT" && part === "name") {
      const { name } = JSON.parse(String(init!.body)) as { name: string };
      this.setRenames.push({ fileName, name });
      const renamed = { ...file, shown_name: name };
      this.storedTestSurfaces = this.storedTestSurfaces.map((candidate) => (candidate.name === fileName ? renamed : candidate));
      return json<InputFileInfo>(renamed);
    }
    return json<ErrorDetailReply>({ detail: "Not found" }, 404);
  }

  /** The stored test surface files, each with criterion 1 in used_by while it uses the file. */
  storedSetsWithUsers(): InputFileInfo[] {
    const criterionName = criterionEntry(this.criterionSettings).name;
    return this.storedTestSurfaces.map((file) => ({ ...file, used_by: this.criterionTestSurfaceFiles.includes(file.name) ? [criterionName] : [] }));
  }

  private testSurfacesReply(): Response {
    return json<InputFilesReply>({ role: "test_surfaces", files: this.storedSetsWithUsers(), joined_bounds: [[0, 0, 0], [1, 1, 0]],
                                   weather_location: this.uploadedWeather.location, weather_latitude: this.uploadedWeather.latitude });
  }

  count(request: string): number {
    return this.requests.filter((made) => made === request).length;
  }
}

/** The service's reasons for a turn and a restore refused because the file changed in the project folder. */
export const FILE_CHANGED_SINCE_TURNED = "The file changed in the project folder since its surfaces were turned, so nothing was saved.";
export const FILE_CHANGED_SINCE_READ = "The file changed in the project folder since Inspect read it, so nothing was restored.";

/** Criterion 1 of the project "p", with *settings* (the mode and its settings), as the service replies with it. */
export function criterionEntry(settings: Record<string, unknown>, testSurfaceFiles: string[] = ["surfaces.obj"]): CriterionEntry {
  return { id: "1", name: String(settings.mode), named_by_user: false, colour: "#4477aa", bypassed: false, energy_weighted: false, test_surface_files: testSurfaceFiles, settings };
}

/**
 * The geometry of a test surface file as the service packs it (inspect_geometry_decoder.ts): uint32 header length; the header as
 * JSON padded with spaces to a multiple of 4; float32 the corners of each triangle; uint32 the surface number of each triangle.
 */
export function packedInspectGeometry(frame: [number, number, number], corners: number[], surfaceOfTriangle: number[],
                                      surfaces: { centre: number[]; normal: number[]; area: number }[]): ArrayBuffer {
  let headerText = JSON.stringify({ frame, triangle_count: surfaceOfTriangle.length, surface_count: surfaces.length, surfaces });
  headerText += " ".repeat((4 - (headerText.length % 4)) % 4);
  const headerBytes = new TextEncoder().encode(headerText);
  const buffer = new ArrayBuffer(4 + headerBytes.length + corners.length * 4 + surfaceOfTriangle.length * 4);
  new DataView(buffer).setUint32(0, headerBytes.length, true);
  new Uint8Array(buffer, 4, headerBytes.length).set(headerBytes);
  new Float32Array(buffer, 4 + headerBytes.length, corners.length).set(corners);
  new Uint32Array(buffer, 4 + headerBytes.length + corners.length * 4, surfaceOfTriangle.length).set(surfaceOfTriangle);
  return buffer;
}

/** The project "p" of one criterion; *settings* are flat, the shared ones with those of criterion 1, as GET project gives them. */
export function project(stages: Record<PipelineStage, StageState>, settings: Record<string, unknown> = {}): ProjectDetail {
  const flatSettings = { mode: "time-based", ...settings };
  const criterionSettings = Object.fromEntries(Object.entries(flatSettings).filter(([name]) => CRITERION_KEYS.has(name)));
  return {
    name: "p", created: "2026-10-17T09:00:00", modified: "2026-10-17T09:00:00", settings: flatSettings,
    inputs: { max_volume: [{ name: "volume.obj", triangle_count: 1 }], test_surfaces: [{ name: "surfaces.obj", triangle_count: 1, used_by: ["time-based"] }],
              weather: [{ name: "weather.epw", triangle_count: 0 }] },
    joined_bounds: [[0, 0, 0], [1, 1, 0]], weather_location: "Golden, CO, USA", weather_latitude: 39.74, stage_status: { stages }, grid_plan: null,
    criteria: [criterionEntry(criterionSettings)], criterion_status: { 1: stages }, mode_to_choose: false, carving_updates_itself: true,
  };
}

let rendered: RenderedOverlay | null = null;

/** For each test file's beforeEach. */
export function startWorkspaceTest() {
  reportedServiceProblems.length = 0;
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

export { settle, type, typeAndLeave } from "../viewer_overlays/render_for_test";
export const waitForTheSave = () => act(async () => { await vi.advanceTimersByTimeAsync(SAVE_DELAY_MILLISECONDS + 50); });

/** What the open workspace handed to onServiceProblem since the test started. */
export const reportedServiceProblems: unknown[] = [];

export async function openWorkspace(
  service: FakeService, opened: ProjectDetail,
  steps: Pick<ComponentProps<typeof ProjectWorkspace>, "startSteps" | "onStepsChange" | "onSettingsSaverReady" | "startsWithSetup" | "onSetupClosed"> = {},
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
    // As the app's switch: leaving Inspect with turns not saved asks first (UnsavedTurnsDialog).
    const leaving = useLeavingInspect(mode, runs.activeRun?.project === opened.name ? "A run is in progress" : null);
    changeMode = (next) => leaving.leave(() => setMode(next));
    // The top bar's place for the Settings button, as the app keeps it.
    const [settingsSlot, setSettingsSlot] = useState<HTMLSpanElement | null>(null);
    return (
      <>
        <span ref={setSettingsSlot} className="top-bar-settings-slot" />
        <ProjectWorkspace token="token" project={opened} schema={schema} modes={modes} criterionKeys={CRITERION_KEYS} warmUpState="ready" runs={runs}
                          mode={mode} onServiceProblem={(error) => reportedServiceProblems.push(error)} onShowProjects={() => {}} onInspectUnsavedChange={leaving.onUnsavedChange}
                          onInspectTurnsReady={leaving.onTurnsReady} onGoToCarve={() => leaving.leave(() => setMode("design"))} settingsButtonSlot={settingsSlot} {...steps} />
        {leaving.dialog}
      </>
    );
  }
  rendered = renderForTest(<Page />);
  await settle();
}

let changeMode: ((mode: WorkspaceMode) => void) | null = null;
/** Switches the open workspace between Design, Simulate and Inspect, as the top bar's switch does (leaving Inspect may ask first). */
export const switchMode = (mode: WorkspaceMode) => act(() => changeMode!(mode));

export const container = () => rendered!.container;
export const dimmedLayers = () => [...FakeViewerScene.latest!.dimmed].sort();
/** The dimmed layers among the carving's (the envelope and the massing follow their own stages, never built here). */
export const dimmedCarvingLayers = () => dimmedLayers().filter((layer) => ["kept_voxels", "carved_voxels", "sky_dome"].includes(layer));

export function stepRow(title: string): HTMLElement {
  return [...container().querySelectorAll<HTMLElement>(".step")].find((row) => row.querySelector(".step-title")!.textContent === title)!;
}

/** Whether the step titled *title* is open, as its header button tells a screen reader (aria-expanded). */
export const stepIsOpen = (title: string) => stepRow(title).querySelector(".step-header")!.getAttribute("aria-expanded") === "true";

export function openStep(title: string) {
  act(() => stepRow(title).querySelector<HTMLButtonElement>(".step-header")!.click());
}

/** The Test surfaces box of the Site step: the project's surface sets (SurfaceSetsBox); undefined while the step is closed. */
export const surfaceSetsBox = () => [...stepRow("Site").querySelectorAll<HTMLElement>(".input-box")]
  .find((box) => box.querySelector(".input-box-title")?.textContent === "Test surfaces");

/** The switches of the shown criterion's surface sets, by set name, each with whether the criterion uses it. */
export const surfaceSetSwitches = () => [...container().querySelectorAll<HTMLInputElement>('.criterion-panel .surface-set-switches [role="switch"]')]
  .map((input) => [input.getAttribute("aria-label")!.replace(/^Use /, ""), input.checked] as const);

/** The Settings button of the top bar, which the open project draws into the place kept for it. */
export const settingsButton = () => container().querySelector<HTMLButtonElement>(".top-bar-settings-button")!;
/** The project settings window, drawn into the page's body; null while it is closed. */
export const projectSettings = () => [...document.body.querySelectorAll<HTMLElement>("[role='dialog']")]
  .find((dialog) => dialog.querySelector("h2")?.textContent === "Project settings") ?? null;

/** Opens the project settings window with the Settings button (nothing when it is open). */
export function openProjectSettings() {
  if (projectSettings() === null) act(() => settingsButton().click());
}

/** Closes the project settings window with Done (nothing when it is closed). */
export function closeProjectSettings() {
  const dialog = projectSettings();
  if (dialog !== null) act(() => [...dialog.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Done")!.click());
}

/** The weather file's box in the project settings window, first in Location; null while the window is closed. */
export const settingsWeatherBox = () => projectSettings()?.querySelector<HTMLElement>('[data-setting="weather_file"] .input-box') ?? null;

/** Adds a weather file with the box in the project settings window, as a user does, and closes the window again. */
export async function addWeatherFileInSettings() {
  openProjectSettings();
  const weatherPicker = settingsWeatherBox()!.querySelector<HTMLInputElement>('input[type="file"][accept=".epw"]')!;
  Object.defineProperty(weatherPicker, "files", { value: [new File(["LOCATION"], "weather.epw")], configurable: true });
  act(() => weatherPicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  closeProjectSettings();
}

/**
 * The Criteria step shows the cards of the criteria or the editor of the selected one, never both. A test that needs the cards asks for them
 * (the editor's All criteria), a test that needs the panel asks for the editor (a press on the selected card); each does nothing when the
 * step already shows what is asked for or is not open. The press is flushed at once (flushSync), so they also work inside another act.
 */
export function showCriterionCards() {
  const back = container().querySelector<HTMLButtonElement>(".criterion-editor-back");
  if (back !== null) act(() => { flushSync(() => back.click()); });
}

export function showCriterionEditor() {
  const selected = container().querySelector<HTMLButtonElement>('.criterion-card[aria-current="true"] .criterion-card-select');
  if (selected !== null) act(() => { flushSync(() => selected.click()); });
}

/** The header of the criterion panel's section titled *title* ("Test surfaces", "Mode", "Settings", "Carving rule"). */
export function panelSectionHeader(title: string): HTMLButtonElement {
  showCriterionEditor();
  return [...container().querySelectorAll<HTMLButtonElement>(".panel-section-header")]
    .find((header) => header.querySelector(".panel-section-title")!.textContent === title)!;
}

export const panelSectionOpen = (title: string) => panelSectionHeader(title).getAttribute("aria-expanded") === "true";

/** The titles of the criterion panel's open sections, in order. */
export const openPanelSections = () => (showCriterionEditor(), [...container().querySelectorAll<HTMLButtonElement>('.panel-section-header[aria-expanded="true"]')]
  .map((header) => header.querySelector(".panel-section-title")!.textContent));

export function togglePanelSection(title: string) {
  act(() => panelSectionHeader(title).click());
}

/** Opens the criterion panel's section titled *title*, when it is closed. */
export function openPanelSection(title: string) {
  if (!panelSectionOpen(title)) togglePanelSection(title);
}

/** The bar pinned under the steps: Run analysis and Build envelope and massing in Criteria. */
export const pinnedBar = () => container().querySelector<HTMLElement>(".step-pinned-action")!;

/** Presses Run analysis, pinned under the Criteria step (the window is closed and the step opened first when they are not). */
export async function pressRunAnalysis() {
  closeProjectSettings();
  if (!stepIsOpen("Criteria")) openStep("Criteria");
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

/** The voxel size's number field, in the project settings window (opened first when it is closed). */
export const voxelSizeField = () => (openProjectSettings(), projectSettings()!.querySelector<HTMLInputElement>('[data-setting="voxel_size"] input[type="number"]')!);
export const thresholdField = () => (showCriterionEditor(), container().querySelector<HTMLInputElement>(".threshold-control input[type=number]")!);
export const thresholdOf = (values: Record<string, unknown>) => (values.threshold as { value: number }).value;

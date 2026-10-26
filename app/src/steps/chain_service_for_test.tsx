// A fake service of a project whose criteria are a chain, and the project opened against it at the Criteria step, with the
// queries of its cards and panel: shared by ProjectWorkspace.criterion_cards.test.tsx and ProjectWorkspace.saves_and_runs.test.tsx.
// Each test file mocks ../viewer/scene with FakeViewerScene itself and calls startWorkspaceTest and endWorkspaceTest.
import { act } from "react";
import { expect } from "vitest";
import type { ChainSummary, CriterionCarvingSummary, CriterionEntry, ProjectDetail } from "../api_client/client";
import { plainModeName, type PipelineStage, type StageState } from "./step_summaries";
import {
  CARVED, CARVING, CRITERION_KEYS, FakeService, buttonIn, container, json, openStep, openWorkspace, project, settle, stepRow,
} from "./project_workspace_for_test";

export type CriterionStages = Record<"preprocessing" | "thresholding", StageState>;
const PIPELINE_STAGES: readonly PipelineStage[] = ["preprocessing", "thresholding", "exporting", "massing"];
export const CURRENT: CriterionStages = { preprocessing: "current", thresholding: "current" };
export const OUT_OF_DATE: CriterionStages = { preprocessing: "out_of_date", thresholding: "out_of_date" };

/**
 * The service of a project whose criteria are a chain: it keeps each criterion's entry and stages, answers the criteria routes
 * (settings, saves, add, duplicate, delete, order, test surfaces stored once and shared) and the run summary with its criteria;
 * every other request goes to FakeService.
 */
export class ChainService extends FakeService {
  entries: CriterionEntry[];
  criterionStages: Record<string, CriterionStages>;
  summaryCriteria: CriterionCarvingSummary[] = [];
  /** The chain the run summary reports (RunSummary.chain); null: the summary has none. */
  summaryChain: ChainSummary | null = null;
  /** The body of every PATCH criteria/{id}, with the id. */
  readonly patches: { id: string; body: Record<string, unknown> }[] = [];
  /** While set for a criterion, GET criteria/{id}/settings answers once the promise resolves. */
  readonly settingsAnswerWhen: Record<string, Promise<void>> = {};
  /** The status GET criteria/{id}/settings is refused with, by criterion. */
  readonly settingsRefusedWith: Record<string, number> = {};
  /** While set, a PATCH criteria/{id} answers once the promise resolves. */
  patchesAnswerWhen: Promise<void> | null = null;
  /** The stages a run executes for each criterion (POST runs replies them as criterion_stages); null: FakeService answers. */
  runCriterionStages: Record<string, string[]> | null = null;
  /** The status and body a request to run is refused with; null: it starts. */
  runRefusal: { status: number; body: unknown } | null = null;
  /** GET run/score-points?criterion={id}: the packed score points of each criterion; a criterion without them is not there (404). */
  scorePointsOf: Record<string, ArrayBuffer> = {};
  /** GET run/carved-by-criterion: the packed layer; null: not there (404, as the service answers until every criterion has run). */
  carvedByCriterion: ArrayBuffer | null = null;
  /** While set, GET run/carved-by-criterion answers once the promise resolves. */
  carvedByCriterionAnswerWhen: Promise<void> | null = null;

  constructor(entries: CriterionEntry[], criterionStages: Record<string, CriterionStages>) {
    super(CARVED, CARVING);
    this.entries = entries;
    this.criterionStages = criterionStages;
    const answerOfFakeService = this.answer;
    this.answer = (address, init) => this.answerOfChain(address, init, answerOfFakeService);
  }

  private async answerOfChain(address: string, init: RequestInit | undefined, answerOfFakeService: FakeService["answer"]): Promise<Response> {
    const method = init?.method ?? "GET";
    const fullPath = address.replace("/api/projects/p", "");
    const path = fullPath.split("?")[0];
    if (path === "/stage-status") {
      this.requests.push(`${method} ${fullPath}`);
      const active = this.entries.filter((entry) => !entry.bypassed).map((entry) => [entry.id, this.criterionStages[entry.id]]);
      return json({ stages: this.stages, criteria: Object.fromEntries(active) });
    }
    if (path === "/run/summary") {
      this.requests.push(`${method} ${fullPath}`);
      return json({ ...this.summary, criteria: this.summaryCriteria, chain: this.summaryChain });
    }
    if (path === "/run/score-points" || path === "/run/carved-by-criterion") {
      this.requests.push(`${method} ${fullPath}`);
      if (path === "/run/carved-by-criterion") await this.carvedByCriterionAnswerWhen;
      const packed = path === "/run/carved-by-criterion" ? this.carvedByCriterion : this.scorePointsOf[new URLSearchParams(fullPath.split("?")[1]).get("criterion") ?? ""];
      return packed === undefined || packed === null ? json({ detail: "Not found" }, 404) : new Response(packed);
    }
    if (method === "POST" && path === "/runs" && (this.runRefusal !== null || this.runCriterionStages !== null)) {
      this.requests.push(`${method} ${fullPath}`);
      if (this.runRefusal !== null) return json(this.runRefusal.body, this.runRefusal.status);
      const { produce } = JSON.parse(String(init!.body)) as { produce: string[] };
      this.runsStarted.push(produce);
      const ofCriteria = Object.values(this.runCriterionStages!).flat();
      const stages = PIPELINE_STAGES.filter((stage) => ofCriteria.includes(stage) || (produce.includes(stage) && (stage === "exporting" || stage === "massing")));
      return json({ status: "started", run_id: `r${this.runsStarted.length}`, stages, criterion_stages: this.runCriterionStages });
    }
    if (!path.startsWith("/criteria")) return answerOfFakeService(address, init);
    this.requests.push(`${method} ${fullPath}`);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : {};
    if (method === "PUT" && path === "/criteria/order") {
      const ids = body.ids as string[];
      this.entries = ids.map((id) => this.entries.find((entry) => entry.id === id)!);
      return json(this.entries);
    }
    if (method === "POST" && path === "/criteria") {
      const id = String(Math.max(...this.entries.map((entry) => Number(entry.id))) + 1);
      const mode = String(body.mode);
      const entry: CriterionEntry = { id, name: plainModeName(mode), named_by_user: false, colour: "#228833", bypassed: false, test_surface_files: [],
                                      settings: { mode, ...this.modes.find((candidate) => candidate.name === mode)?.starting_values } };
      this.entries = [...this.entries, entry];
      this.criterionStages[id] = { preprocessing: "missing", thresholding: "missing" };
      return json(entry);
    }
    const [, , id, part, fileName] = path.split("/");
    const entry = this.entries.find((candidate) => candidate.id === id);
    if (entry === undefined) return json({ detail: `The project has no criterion ${id}.` }, 404);
    const replace = (changed: CriterionEntry) => {
      this.entries = this.entries.map((candidate) => (candidate.id === changed.id ? changed : candidate));
      return json(changed);
    };
    if (method === "GET" && part === "settings") {
      await this.settingsAnswerWhen[id];
      if (this.settingsRefusedWith[id] !== undefined) return json({ detail: `The settings of criterion ${id} could not be read.` }, this.settingsRefusedWith[id]);
      return json({ criterion_id: id, settings: { ...this.sharedSettings, ...entry.settings } });
    }
    if (method === "PATCH" && part === undefined) {
      this.patches.push({ id, body });
      await this.patchesAnswerWhen;
      if (body.name === "") return json({ detail: "A criterion needs a name." }, 422);
      const values = body.values as Record<string, unknown> | undefined;
      const startingValues = this.modes.find((candidate) => candidate.name === values?.mode)?.starting_values ?? {};
      const settings = values === undefined ? entry.settings
        : Object.fromEntries(Object.entries({ ...startingValues, ...values }).filter(([name]) => CRITERION_KEYS.has(name)));
      return replace({ ...entry, settings, name: typeof body.name === "string" ? body.name : entry.name,
                       bypassed: typeof body.bypassed === "boolean" ? body.bypassed : entry.bypassed });
    }
    if (method === "DELETE" && part === undefined) {
      if (this.entries.length === 1) return json({ detail: "A project needs at least one criterion." }, 422);
      this.entries = this.entries.filter((candidate) => candidate.id !== id);
      return new Response(null, { status: 204 });
    }
    if (method === "POST" && part === "duplicate") {
      const copy = { ...entry, id: String(Math.max(...this.entries.map((candidate) => Number(candidate.id))) + 1), name: `${entry.name} copy` };
      this.entries = [...this.entries, copy];
      this.criterionStages[copy.id] = { preprocessing: "missing", thresholding: "missing" };
      return json(copy);
    }
    const files = entry.test_surface_files ?? [];
    if (method === "POST" && part === "test-surfaces") {
      const name = ((init!.body as FormData).get("file") as File).name;
      if (this.storedTestSurfaces.some((file) => file.name === name)) {
        // The same name with other content replaces the stored file, in every criterion that uses it.
        for (const user of this.entries.filter((candidate) => candidate.test_surface_files?.includes(name))) this.criterionStages[user.id] = OUT_OF_DATE;
      } else {
        this.storedTestSurfaces = [...this.storedTestSurfaces, { name, triangle_count: 1 }];
      }
      if (!files.includes(name)) this.criterionStages[id] = OUT_OF_DATE;
      return replace({ ...entry, test_surface_files: files.includes(name) ? files : [...files, name] });
    }
    if (method === "PUT" && part === "test-surfaces") {
      this.criterionStages[id] = OUT_OF_DATE;
      return replace({ ...entry, test_surface_files: [...files, decodeURIComponent(fileName)] });
    }
    return json({ detail: "Not found" }, 404);
  }

  storedFileCount(name: string): number {
    return this.storedTestSurfaces.filter((file) => file.name === name).length;
  }
}

export function criterion(id: string, name: string, settings: Record<string, unknown>, files: string[], colour = "#4477aa"): CriterionEntry {
  return { id, name, named_by_user: true, colour, bypassed: false, test_surface_files: files, settings };
}

// Criterion 1 protects the facades on 21 December; criterion 2 the windows on 21 March, with its own cutoff; criterion 3, daylight, the roofs.
// The periods are whole, as a save stores them (on top of the mode's starting values), so a threshold save leaves the analysis as it was.
const HOURS = { start_day: 21, start_hour: 10, end_day: 21, end_hour: 14 };
export const FACADES = criterion("1", "Winter sun on facades",
                                 { mode: "time-based", start_month: 12, end_month: 12, ...HOURS, threshold: { method: "cutoff", value: 1.5 } }, ["facades.obj"]);
export const WINDOWS = criterion("2", "Spring sun on windows",
                                 { mode: "time-based", start_month: 3, end_month: 3, ...HOURS, threshold: { method: "cutoff", value: 3 } }, ["windows.obj"], "#ee6677");
export const ROOFS = criterion("3", "Daylight on roofs", { mode: "daylight" }, ["roofs.obj"], "#228833");

export function carvingSummaryOf(entry: CriterionEntry, retentionPercent: number): CriterionCarvingSummary {
  return { id: entry.id, name: entry.name, colour: entry.colour, mode: String(entry.settings!.mode),
           carving: { ...CARVING, retention_pct: retentionPercent, voxels_kept: retentionPercent * 10 }, voxels_at_start: 1000, volume_kept_m3: retentionPercent * 10,
           volume_removed_m3: 1000 - retentionPercent * 10 };
}

/** One state for each analysis stage of the criteria, as the service sums them: missing when one is, else out of date when one is. */
function summedStages(stages: Record<string, CriterionStages>): CriterionStages {
  const sum = (stage: keyof CriterionStages): StageState => {
    const states = Object.values(stages).map((ofCriterion) => ofCriterion[stage]);
    return states.length === 0 || states.includes("missing") ? "missing" : states.includes("out_of_date") ? "out_of_date" : "current";
  };
  return { preprocessing: sum("preprocessing"), thresholding: sum("thresholding") };
}

/** The service of the project opened last (openChain). */
export let service: ChainService;

/** Opens the project "p" of these criteria, every one carved, at the Criteria step; *prepare* sets what the service holds before the page asks. */
export async function openChain(entries: CriterionEntry[], stages: Record<string, CriterionStages> = Object.fromEntries(entries.map((entry) => [entry.id, CURRENT])),
                                prepare: (service: ChainService) => void = () => {}, unlistedTestSurfaceFiles: string[] = []) {
  service = new ChainService(entries, { ...stages });
  prepare(service);
  service.stages = { ...CARVED, ...summedStages(stages) };
  service.summaryCriteria = entries.filter((entry) => !entry.bypassed).map((entry, index) => carvingSummaryOf(entry, [61, 80, 90][index]));
  const files = [...new Set([...entries.flatMap((entry) => entry.test_surface_files ?? []), ...unlistedTestSurfaceFiles])].map((name) => ({ name, triangle_count: 1 }));
  const opened: ProjectDetail = {
    ...project(service.stages), settings: { voxel_size: 1, ...entries[0].settings }, criteria: entries, criterion_status: stages,
    inputs: { max_volume: [{ name: "volume.obj", triangle_count: 1 }], test_surfaces: files, weather: [{ name: "weather.epw", triangle_count: 0 }] },
  };
  await openWorkspace(service, opened);
  service.storedTestSurfaces = files;
  openStep("Criteria");
  await settle();
}

export const cards = () => [...container().querySelectorAll<HTMLElement>(".criterion-card")];
export const cardNames = () => cards().map((card) => card.querySelector(".criterion-card-name")!.textContent);
export const card = (name: string) => cards().find((candidate) => candidate.querySelector(".criterion-card-name")!.textContent === name)!;
export const cardLine = (name: string) => card(name).querySelector(".criterion-card-line")!.textContent;
export const selectedCardName = () => container().querySelector('.criterion-card[aria-current="true"] .criterion-card-name')!.textContent;
export const panel = () => container().querySelector<HTMLElement>(".criterion-panel")!;
export const protectedFiles = () => [...panel().querySelectorAll(".input-box .input-file-name")].map((name) => name.textContent);
export const periodFieldText = () => container().querySelector('[data-setting="start_month"]')!.textContent;
export const keptTile = () => panel().querySelector(".number-tile-value")!.textContent;
export const criteriaSummary = () => stepRow("Criteria").querySelector(".step-summary")!.textContent;
export const settingsSaves = () => service.requests.filter((request) => request.startsWith("PATCH") || request.startsWith("PUT /shared"));
export const selectButtonOf = (name: string) => card(name).querySelector(".criterion-card-select");
export const panelFrame = () => container().querySelector<HTMLElement>(".criterion-panel-frame")!;

/** The results of criterion *id* were asked for: its score points, sky dome and sun path. */
export function expectResultsOfCriterion(id: string) {
  expect(service.requests).toEqual(expect.arrayContaining([
    `GET /run/score-points?criterion=${id}`, `GET /run/sky-patches?criterion=${id}`, `GET /sun-path?criterion=${id}`,
  ]));
}

/** No refusal, failure or save-failure notice is on the page. */
export function expectNoProblemShown() {
  expect(container().querySelector('[role="alert"]')).toBeNull();
  expect(container().querySelector(".save-failure")).toBeNull();
}

export async function select(name: string) {
  act(() => card(name).querySelector<HTMLButtonElement>(".criterion-card-select")!.click());
  await settle();
}

export async function chooseFromMenu(name: string, label: string) {
  act(() => card(name).querySelector<HTMLButtonElement>(".action-menu-button")!.click());
  await act(async () => [...card(name).querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((item) => item.textContent === label)!.click());
}

export async function deleteCriterion(name: string) {
  await chooseFromMenu(name, "Delete");
  await act(async () => buttonIn(container().querySelector('[role="dialog"]')!, "Delete").click());
  await settle();
}


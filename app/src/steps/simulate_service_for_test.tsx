// A fake service of a project with studies (the Simulate workspace), and the project opened against it in Simulate, with the
// queries of the studies panel: shared by ProjectWorkspace.simulate.test.tsx. Each test file mocks ../viewer/scene with
// FakeViewerScene itself and calls startWorkspaceTest and endWorkspaceTest.
import { act } from "react";
import type { CriterionEntry, MetricInfo, StudyEntry, StudyWithState } from "../api_client/client";
import { ChainService, CURRENT, FACADES, openChainWith, type CriterionStages } from "./chain_service_for_test";
import { buttonIn, container, json, settle, switchMode } from "./project_workspace_for_test";
import type { PipelineStage, StageState } from "./step_summaries";

const PERIOD = { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14, time_basis: "standard" };

/** The metrics as the service lists them, every one available; SimulateService marks those that need a weather file unavailable without one. */
export const METRICS: MetricInfo[] = [
  { name: "sun_hours", label: "Sun hours", unit: "h", needs_epw: true, available: true, default_settings: PERIOD },
  { name: "solar_energy", label: "Solar energy", unit: "kWh/m²", needs_epw: true, available: true, default_settings: PERIOD },
  { name: "useful_solar_energy", label: "Useful solar energy", unit: "kWh/m²", needs_epw: true, available: true,
    default_settings: { ...PERIOD, balance_temperature: 15, balance_offset: 2, include_harm: false } },
  { name: "sky_component", label: "Overcast sky component", unit: "%", needs_epw: false, available: true, default_settings: {} },
  { name: "cooling_sky", label: "Cooling sky", unit: "%", needs_epw: false, available: true, default_settings: { dew_point_celsius: 10, bliss_k: 1.8 } },
  { name: "sky_view", label: "Sky view factor", unit: "%", needs_epw: false, available: true, default_settings: {} },
];
const METRIC_OF_MODE: Record<string, string> = { "time-based": "sun_hours", daylight: "sky_component" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The name the service gives a study until the user names it: the metric's label, then the period when the metric has one. */
export function defaultStudyName(metric: string, settings: Record<string, unknown>): string {
  const label = METRICS.find((info) => info.name === metric)!.label;
  if (settings.start_month === undefined) return label;
  const start = `${String(settings.start_day)} ${MONTHS[Number(settings.start_month) - 1]}`;
  const end = `${String(settings.end_day)} ${MONTHS[Number(settings.end_month) - 1]}`;
  return `${label}, ${start === end ? end : `${start} to ${end}`}`;
}

export function study(id: string, metric: string, files: string[], state: StudyWithState["state"] = "not_run", reason: string | null = null,
                      settings: Record<string, unknown> = METRICS.find((info) => info.name === metric)!.default_settings): StudyWithState {
  return { entry: { id, name: defaultStudyName(metric, settings), named_by_user: false, colour: "#4477aa", metric, settings, target: null, test_surface_files: files },
           state, reason, geometries: [] };
}

/**
 * The service of a project with studies: it keeps each study with its state, answers the studies routes (list, add from a metric or
 * like a criterion, change, delete, order, the use and removal of stored test surface files) and starts a simulation (POST simulate,
 * whose events the test sends); every other request goes to ChainService.
 */
export class SimulateService extends ChainService {
  studies: StudyWithState[] = [];
  /** The project has a weather file: the metrics that need one are available. */
  hasWeatherFile = true;
  /** The status and body a request to simulate is refused with; null: it starts. */
  simulateRefusal: { status: number; body: unknown } | null = null;
  /** Counts the simulations started. */
  simulationsStarted = 0;
  /** The body of every PATCH studies/{id}, with the id. */
  readonly studyPatches: { id: string; body: Record<string, unknown> }[] = [];
  /** GET studies/{id}/values: the packed values of each study's last result; a study without them has none (404). */
  valuesOf: Record<string, ArrayBuffer> = {};

  constructor(entries: CriterionEntry[], criterionStages: Record<string, CriterionStages>) {
    super(entries, criterionStages);
    const answerOfChain = this.answer;
    this.answer = (address, init) => this.answerOfStudies(address, init, answerOfChain);
  }

  private async answerOfStudies(address: string, init: RequestInit | undefined, answerOfChain: ChainService["answer"]): Promise<Response> {
    const method = init?.method ?? "GET";
    const path = address.replace("/api/projects/p", "").split("?")[0];
    if (path === "/simulate" && method === "POST") {
      this.requests.push(`${method} ${path}`);
      if (this.simulateRefusal !== null) return json(this.simulateRefusal.body, this.simulateRefusal.status);
      this.simulationsStarted += 1;
      return json({ status: "started", run_id: `s${this.simulationsStarted}`, stages: ["simulate"], criterion_stages: {} });
    }
    if (!path.startsWith("/studies")) return answerOfChain(address, init);
    this.requests.push(`${method} ${path}`);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : {};
    if (method === "GET" && path === "/studies") {
      return json({ studies: this.studies, metrics: METRICS.map((info) => ({ ...info, available: this.hasWeatherFile || !info.needs_epw })) });
    }
    if (method === "POST" && path === "/studies") {
      const id = String(Math.max(0, ...this.studies.map((each) => Number(each.entry.id))) + 1);
      const criterion = this.entries.find((entry) => entry.id === body.from_criterion);
      const metric = criterion === undefined ? String(body.metric) : METRIC_OF_MODE[String(criterion.settings!.mode)];
      const defaults = METRICS.find((info) => info.name === metric)!.default_settings;
      const settings = criterion === undefined ? defaults
        : Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, criterion.settings![key] ?? value]));
      const files = [...(criterion?.test_surface_files ?? [])];
      const added = files.length === 0 ? study(id, metric, files, "refused", "Add test surfaces", settings) : study(id, metric, files, "not_run", null, settings);
      this.studies = [...this.studies, added];
      return json(added.entry);
    }
    const [, , id, part, fileName] = path.split("/");
    const found = this.studies.find((each) => each.entry.id === id);
    if (found === undefined) return json({ detail: `There is no study '${id}'.` }, 404);
    const replace = (entry: StudyEntry, state: StudyWithState["state"] = found.state === "current" ? "out_of_date" : found.state) => {
      this.studies = this.studies.map((each) => (each.entry.id === id ? { ...each, entry, state } : each));
      return json(entry);
    };
    if (method === "GET" && part === "values") {
      const values = this.valuesOf[id];
      return values === undefined ? json({ detail: `The study '${id}' has no result yet.` }, 404) : new Response(values);
    }
    if (method === "PATCH" && part === undefined && Object.keys(body).length === 1 && "target" in body) {
      this.studyPatches.push({ id, body });
      return replace({ ...found.entry, target: body.target as number | null }, found.state);       // the target changes no result
    }
    if (method === "PATCH" && part === undefined) {
      this.studyPatches.push({ id, body });
      if (body.name === "") return json({ detail: "A study needs a name." }, 422);
      const metric = typeof body.metric === "string" ? body.metric : found.entry.metric;
      const start = metric === found.entry.metric ? found.entry.settings! : METRICS.find((info) => info.name === metric)!.default_settings;
      const settings = { ...start, ...(body.values as Record<string, unknown> | undefined) };
      const named = typeof body.name === "string";
      return replace({ ...found.entry, metric, settings, name: named ? String(body.name) : found.entry.named_by_user ? found.entry.name : defaultStudyName(metric, settings),
                       named_by_user: named || found.entry.named_by_user });
    }
    if (method === "DELETE" && part === undefined) {
      this.studies = this.studies.filter((each) => each.entry.id !== id);
      return new Response(null, { status: 204 });
    }
    const files = found.entry.test_surface_files ?? [];
    const name = decodeURIComponent(fileName ?? "");
    if (method === "PUT" && part === "test-surfaces") return replace({ ...found.entry, test_surface_files: [...files, name] }, "not_run");
    if (method === "DELETE" && part === "test-surfaces") return replace({ ...found.entry, test_surface_files: files.filter((each) => each !== name) });
    return json({ detail: "Not found" }, 404);
  }
}

/** The service of the project opened last (openSimulate). */
export let simulateService: SimulateService;

/**
 * Opens the project "p" of these criteria (each carved) in Simulate; *prepare* sets what the service holds before the page asks
 * (its studies, whether it has a weather file, the run summary); *designStages* are the states of Design's stages besides the
 * carving's (the envelope's "exporting" and the massing's).
 */
export async function openSimulate(entries: CriterionEntry[] = [FACADES], prepare: (service: SimulateService) => void = () => {},
                                   designStages: Partial<Record<PipelineStage, StageState>> = {}) {
  const stages = Object.fromEntries(entries.map((entry) => [entry.id, CURRENT]));
  simulateService = new SimulateService(entries, { ...stages });
  await openChainWith(simulateService, entries, stages, prepare, [], (opened) => {
    simulateService.stages = { ...simulateService.stages, ...designStages };
    const withStages = { ...opened, stage_status: { stages: simulateService.stages } };
    return simulateService.hasWeatherFile ? withStages : { ...withStages, inputs: { ...withStages.inputs, weather: [] } };
  });
  await switchMode("simulate");
  await settle();
}

export const studiesPanel = () => container().querySelector<HTMLElement>(".studies-panel")!;
export const studyRows = () => [...container().querySelectorAll<HTMLElement>(".study-row")];
export const studyNames = () => studyRows().map((row) => row.querySelector(".study-row-name")!.textContent);
export const studyRow = (name: string) => studyRows().find((row) => row.querySelector(".study-row-name")!.textContent === name)!;
export const studyLine = (name: string) => studyRow(name).querySelector(".study-row-line")!.textContent;
export const selectedStudyName = () => container().querySelector('.study-row[aria-current="true"] .study-row-name')?.textContent ?? null;
export const studyPopover = () => container().querySelector<HTMLElement>(".study-popover");
export const addStudyButton = () => buttonIn(studiesPanel(), "Add study");
export const runButton = () => buttonIn(studiesPanel(), "Run");

/** The items of the open Add study menu, with whether each can be chosen. */
export const addStudyMenuItems = () => [...container().querySelectorAll<HTMLButtonElement>('.add-study-menu [role="menuitem"]')]
  .map((item) => ({ label: item.querySelector(".add-study-menu-label")!.textContent, disabled: item.getAttribute("aria-disabled") === "true" }));

export async function chooseAddStudy(label: string) {
  act(() => addStudyButton().click());
  await act(async () => [...container().querySelectorAll<HTMLButtonElement>('.add-study-menu [role="menuitem"]')]
    .find((item) => item.querySelector(".add-study-menu-label")!.textContent === label)!.click());
  await settle();
}

/** Opens the settings popover of the study named *name*. */
export async function openStudySettings(name: string) {
  act(() => studyRow(name).querySelector<HTMLButtonElement>(".study-row-settings")!.click());
  await settle();
}

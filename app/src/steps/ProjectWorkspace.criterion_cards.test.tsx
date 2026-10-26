// The open project with several criteria, against a fake service of a chain: the cards in order, selecting, bypassing, deleting,
// adding and reordering criteria, where a pending save goes, test surface files shared by criteria, and the step summary.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { CriterionCarvingSummary, CriterionEntry, ProjectDetail } from "../api_client/client";
import { plainModeName, type StageState } from "./step_summaries";
import {
  CARVED, CARVING, CRITERION_KEYS, FakeService, buttonIn, container, endWorkspaceTest, json, openStep, openWorkspace, project, settle, startWorkspaceTest,
  stepRow, thresholdField, waitForTheSave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

type CriterionStages = Record<"preprocessing" | "thresholding", StageState>;
const CURRENT: CriterionStages = { preprocessing: "current", thresholding: "current" };
const OUT_OF_DATE: CriterionStages = { preprocessing: "out_of_date", thresholding: "out_of_date" };

/**
 * The service of a project whose criteria are a chain: it keeps each criterion's entry and stages, answers the criteria routes
 * (settings, saves, add, duplicate, delete, order, test surfaces stored once and shared) and the run summary with its criteria;
 * every other request goes to FakeService.
 */
class ChainService extends FakeService {
  entries: CriterionEntry[];
  criterionStages: Record<string, CriterionStages>;
  summaryCriteria: CriterionCarvingSummary[] = [];
  /** The body of every PATCH criteria/{id}, with the id. */
  readonly patches: { id: string; body: Record<string, unknown> }[] = [];

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
      return json({ ...this.summary, criteria: this.summaryCriteria });
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
    if (method === "GET" && part === "settings") return json({ criterion_id: id, settings: { ...this.sharedSettings, ...entry.settings } });
    if (method === "PATCH" && part === undefined) {
      this.patches.push({ id, body });
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

function criterion(id: string, name: string, settings: Record<string, unknown>, files: string[], colour = "#4477aa"): CriterionEntry {
  return { id, name, named_by_user: true, colour, bypassed: false, test_surface_files: files, settings };
}

// Criterion 1 protects the facades on 21 December; criterion 2 the windows on 21 March, with its own cutoff; criterion 3, daylight, the roofs.
const FACADES = criterion("1", "Winter sun on facades", { mode: "time-based", start_month: 12, end_month: 12, threshold: { method: "cutoff", value: 1.5 } },
                          ["facades.obj"]);
const WINDOWS = criterion("2", "Spring sun on windows", { mode: "time-based", start_month: 3, end_month: 3, threshold: { method: "cutoff", value: 3 } },
                          ["windows.obj"], "#ee6677");
const ROOFS = criterion("3", "Daylight on roofs", { mode: "daylight" }, ["roofs.obj"], "#228833");

function carvingSummaryOf(entry: CriterionEntry, retentionPercent: number): CriterionCarvingSummary {
  return { id: entry.id, name: entry.name, colour: entry.colour, mode: String(entry.settings!.mode),
           carving: { ...CARVING, retention_pct: retentionPercent, voxels_kept: retentionPercent * 10 }, voxels_at_start: 1000, volume_kept_m3: retentionPercent * 10,
           volume_removed_m3: 1000 - retentionPercent * 10 };
}

let service: ChainService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

/** Opens the project "p" of these criteria, every one carved, at the Criteria step. */
async function openChain(entries: CriterionEntry[], stages: Record<string, CriterionStages> = Object.fromEntries(entries.map((entry) => [entry.id, CURRENT]))) {
  service = new ChainService(entries, { ...stages });
  service.summaryCriteria = entries.filter((entry) => !entry.bypassed).map((entry, index) => carvingSummaryOf(entry, [61, 80, 90][index]));
  const files = [...new Set(entries.flatMap((entry) => entry.test_surface_files ?? []))].map((name) => ({ name, triangle_count: 1 }));
  const opened: ProjectDetail = {
    ...project(CARVED), settings: { voxel_size: 1, ...entries[0].settings }, criteria: entries, criterion_status: stages,
    inputs: { max_volume: [{ name: "volume.obj", triangle_count: 1 }], test_surfaces: files, weather: [{ name: "weather.epw", triangle_count: 0 }] },
  };
  await openWorkspace(service, opened);
  service.storedTestSurfaces = files;
  openStep("Criteria");
  await settle();
}

const cards = () => [...container().querySelectorAll<HTMLElement>(".criterion-card")];
const cardNames = () => cards().map((card) => card.querySelector(".criterion-card-name")!.textContent);
const card = (name: string) => cards().find((candidate) => candidate.querySelector(".criterion-card-name")!.textContent === name)!;
const cardLine = (name: string) => card(name).querySelector(".criterion-card-line")!.textContent;
const selectedCardName = () => container().querySelector('.criterion-card[aria-current="true"] .criterion-card-name')!.textContent;
const panel = () => container().querySelector<HTMLElement>(".criterion-panel")!;
const protectedFiles = () => [...panel().querySelectorAll(".input-box .input-file-name")].map((name) => name.textContent);
const periodFieldText = () => container().querySelector('[data-setting="start_month"]')!.textContent;
const keptTile = () => panel().querySelector(".number-tile-value")!.textContent;
const criteriaSummary = () => stepRow("Criteria").querySelector(".step-summary")!.textContent;
const settingsSaves = () => service.requests.filter((request) => request.startsWith("PATCH") || request.startsWith("PUT /shared"));

async function select(name: string) {
  act(() => card(name).querySelector<HTMLButtonElement>(".criterion-card-select")!.click());
  await settle();
}

async function chooseFromMenu(name: string, label: string) {
  act(() => card(name).querySelector<HTMLButtonElement>(".action-menu-button")!.click());
  await act(async () => [...card(name).querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((item) => item.textContent === label)!.click());
}

async function deleteCriterion(name: string) {
  await chooseFromMenu(name, "Delete");
  await act(async () => buttonIn(container().querySelector('[role="dialog"]')!, "Delete").click());
  await settle();
}

test("two criteria show cards in order, each with its result, and the first is selected with its panel below", async () => {
  await openChain([FACADES, WINDOWS]);
  expect(cardNames()).toEqual(["Winter sun on facades", "Spring sun on windows"]);
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(cardLine("Winter sun on facades")).toBe("39 % of the volume carved, 390 m³ removed");
  expect(cardLine("Spring sun on windows")).toBe("20 % of the volume carved, 200 m³ removed");
  expect(protectedFiles()).toEqual(["facades.obj"]);
  expect(buttonIn(stepRow("Criteria"), "Add criterion")).toBeDefined();
  expect(container().textContent).not.toContain("Add another criterion");
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Winter sun on facades 61 %, then Spring sun on windows 80 %");
});

test("selecting a card shows its settings, its test surfaces and its results", async () => {
  await openChain([FACADES, WINDOWS]);
  expect(periodFieldText()).toContain("21 Dec");
  expect(thresholdField().value).toBe("1.5");
  expect(keptTile()).toContain("61");
  await select("Spring sun on windows");
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(service.requests).toContain("GET /criteria/2/settings");
  expect(periodFieldText()).toContain("21 Mar");
  expect(thresholdField().value).toBe("3");
  expect(keptTile()).toContain("80");
  expect(protectedFiles()).toEqual(["windows.obj"]);
  expect(service.requests).toContain("GET /run/score-points?criterion=2");
  // A change now saves criterion 2's settings, not criterion 1's.
  act(() => buttonIn(container(), "21 June").click());
  await waitForTheSave();
  await settle();
  expect(service.patches.map((patch) => patch.id)).toEqual(["2"]);
  expect(service.entries[1].settings).toEqual({ mode: "time-based", start_month: 6, end_month: 6, start_day: 21, start_hour: 10, end_day: 21, end_hour: 14,
                                                threshold: { method: "cutoff", value: 3 } });
});

test("a pending save goes to the criterion it was typed in", async () => {
  await openChain([FACADES, WINDOWS]);
  act(() => buttonIn(container(), "21 June").click());           // a period for criterion 1, its save still waiting
  await select("Spring sun on windows");                           // before the save delay
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect((service.patches[0].body.values as Record<string, unknown>).start_month).toBe(6);
  expect(service.entries[1].settings!.start_month).toBe(3);       // criterion 2 kept its own period
  expect(periodFieldText()).toContain("21 Mar");
});

test("bypassing a card greys it and reads Bypassed", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Spring sun on windows").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(service.patches).toEqual([{ id: "2", body: { bypassed: true } }]);
  expect(card("Spring sun on windows").classList.contains("criterion-card-bypassed")).toBe(true);
  expect(cardLine("Spring sun on windows")).toBe("Bypassed");
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(service.count("GET /stage-status")).toBeGreaterThan(0);
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Winter sun on facades 61 %");       // the bypassed criterion is left out
});

test("bypassing the selected card selects the next one", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(periodFieldText()).toContain("21 Mar");
});

test("deleting the selected criterion selects the next one, and the last one the previous; settings and results follow", async () => {
  await openChain([FACADES, WINDOWS, ROOFS]);
  await deleteCriterion("Winter sun on facades");
  expect(service.requests).toContain("DELETE /criteria/1");
  expect(cardNames()).toEqual(["Spring sun on windows", "Daylight on roofs"]);
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(periodFieldText()).toContain("21 Mar");
  expect(thresholdField().value).toBe("3");
  expect(keptTile()).toContain("80");
  await select("Daylight on roofs");
  await deleteCriterion("Daylight on roofs");
  expect(service.requests).toContain("DELETE /criteria/3");
  // One criterion left: no cards, its panel at once, and Add another criterion.
  expect(cards()).toEqual([]);
  expect(periodFieldText()).toContain("21 Mar");
  expect(protectedFiles()).toEqual(["windows.obj"]);
  expect(buttonIn(stepRow("Criteria"), "Add another criterion")).toBeDefined();
});

test("Add another criterion adds one of the chosen mode and selects it", async () => {
  await openChain([FACADES]);
  expect(cards()).toEqual([]);
  act(() => buttonIn(stepRow("Criteria"), "Add another criterion").click());
  await act(async () => [...container().querySelectorAll<HTMLElement>(".add-criterion [role='radio']")].find((tile) => tile.textContent === "Daylight")!.click());
  await settle();
  expect(service.requests).toContain("POST /criteria");
  expect(cardNames()).toEqual(["Winter sun on facades", "Daylight"]);
  expect(selectedCardName()).toBe("Daylight");
  expect(service.requests).toContain("GET /criteria/2/settings");
  expect(cardLine("Daylight")).toBe("Add test surfaces");
  expect(protectedFiles()).toEqual([]);
  expect(panel().querySelector('[role="radio"][aria-checked="true"]')!.textContent).toBe("Daylight");
});

test("reordering with the keyboard sends the new order and the cards follow it", async () => {
  await openChain([FACADES, WINDOWS]);
  const handle = card("Spring sun on windows").querySelector<HTMLElement>(".criterion-card-handle")!;
  handle.focus();
  await act(async () => handle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true })));
  await settle();
  expect(service.requests).toContain("PUT /criteria/order");
  expect(cardNames()).toEqual(["Spring sun on windows", "Winter sun on facades"]);
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(document.activeElement).toBe(card("Spring sun on windows").querySelector(".criterion-card-handle"));     // the focus stays on the handle moved
});

test("a file added to two criteria is stored once and replacing it dates both", async () => {
  await openChain([FACADES, WINDOWS]);
  // Criterion 1 takes criterion 2's file too, from the list of the other criteria's files.
  await act(async () => panel().querySelector<HTMLButtonElement>('[aria-label="Use windows.obj"]')!.click());
  await settle();
  expect(service.requests).toContain("PUT /criteria/1/test-surfaces/windows.obj");
  expect(protectedFiles()).toEqual(["facades.obj", "windows.obj"]);
  expect(service.storedFileCount("windows.obj")).toBe(1);
  service.criterionStages = { 1: CURRENT, 2: CURRENT };
  // A new windows.obj, uploaded to criterion 1, replaces the stored file both use.
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [new File(["v 0 0 1"], "windows.obj")] } });
  await act(async () => panel().querySelector(".input-box")!.dispatchEvent(drop));
  await settle();
  expect(service.storedFileCount("windows.obj")).toBe(1);
  expect(cardLine("Winter sun on facades")).toBe("Out of date");
  expect(cardLine("Spring sun on windows")).toBe("Out of date");
});

test("use a file from another criterion", async () => {
  await openChain([FACADES, WINDOWS]);
  const reuse = panel().querySelector<HTMLElement>(".protects-reuse")!;
  expect([...reuse.querySelectorAll(".protects-reuse-name")].map((name) => name.textContent)).toEqual(["windows.obj"]);
  await act(async () => reuse.querySelector<HTMLButtonElement>('[aria-label="Use windows.obj"]')!.click());
  await settle();
  expect(protectedFiles()).toEqual(["facades.obj", "windows.obj"]);
  expect(panel().querySelector(".protects-reuse")).toBeNull();            // nothing more to use
  expect(cardLine("Winter sun on facades")).toBe("Out of date");
});

test("renaming a card sends the new name and the card shows it", async () => {
  await openChain([FACADES, WINDOWS]);
  await chooseFromMenu("Spring sun on windows", "Rename");
  const field = container().querySelector<HTMLInputElement>('[role="dialog"] input')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, "Courtyard windows");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => field.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(service.patches).toEqual([{ id: "2", body: { name: "Courtyard windows" } }]);
  expect(cardNames()).toEqual(["Winter sun on facades", "Courtyard windows"]);
  expect(container().querySelector('[role="dialog"]')).toBeNull();
});

test("duplicating a card adds the copy after the last card and selects it", async () => {
  await openChain([FACADES, WINDOWS]);
  await chooseFromMenu("Winter sun on facades", "Duplicate");
  await settle();
  expect(service.requests).toContain("POST /criteria/1/duplicate");
  expect(cardNames()).toEqual(["Winter sun on facades", "Spring sun on windows", "Winter sun on facades copy"]);
  expect(selectedCardName()).toBe("Winter sun on facades copy");
  expect(service.requests).toContain("GET /criteria/3/settings");
});

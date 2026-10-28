import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { TypicalBuildingReply } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { buildingGroupSummary, TypicalBuildingSheet, typeOfValues } from "./TypicalBuildingSheet";
import { useTypicalBuilding, type TypicalBuildingValues } from "./use_typical_building";

const NBSP = " ";

function typeValues(width: number, length: number, height: number, wwr: Record<string, number>, mass: string): TypicalBuildingValues {
  return { width, length, height, orientation: 0, wwr: { north: 0, east: 0, south: 0, west: 0, ...wwr }, g_value: 0.6, u_opaque: 0.5, u_window: 1.8,
           mass_class: mass, ach_vent: 1.2, ach_infiltration: 0.3, heat_recovery: 0, t_set_heating: 20, t_set_cooling: 26, gains_day_w_m2: 7.1,
           gains_night_w_m2: 1.7, shading_permanent: null, shading_hot: null, hot_months: [6, 7, 8] };
}

const OFFICE = typeValues(5, 7, 3, { south: 0.27, east: 0.1, west: 0.1 }, "medium");
const LIGHT_HOME = typeValues(5, 6, 3, { south: 0.4, west: 0.22 }, "light");
const PRESETS = { office: { label: "Office, medium mass", values: OFFICE }, light_home: { label: "Light, well-insulated home", values: LIGHT_HOME } };

/** The weights of the fake calculation: benefit 0.5 in the first 1000 hours, harm 0.25 after hour 8000. */
const WEIGHTS = {
  benefit: Array.from({ length: 8760 }, (_, hour) => (hour < 1000 ? 0.5 : 0)),
  harm: Array.from({ length: 8760 }, (_, hour) => (hour > 8000 ? 0.25 : 0)),
};

/** The service's routes of the typical building: it stores what is saved, refuses a window share above 0.9, and calculates. */
class FakeBuildingService {
  values: TypicalBuildingValues = OFFICE;
  startFrom: string | null = "office";
  calculated: TypicalBuildingValues | null = null;
  readonly requests: string[] = [];
  readonly saved: { values: TypicalBuildingValues; start_from: string | null }[] = [];

  reply(): TypicalBuildingReply {
    const state = this.calculated === null ? "missing" : JSON.stringify(this.calculated) === JSON.stringify(this.values) ? "current" : "out_of_date";
    return { values: this.values, start_from: this.startFrom, state, ...(this.calculated === null ? {}
      : { heating_kwh_m2: 189.54, cooling_kwh_m2: 26.9, counted_hours: 7082 }) };
  }

  handle(method: string, address: string, body: unknown): Response {
    this.requests.push(`${method} ${address}`);
    if (address === "/api/typical-building-presets") return json(PRESETS);
    if (address === "/api/projects/p/typical-building/weights") return this.calculated === null ? json({ detail: "not yet" }, 404) : json(WEIGHTS);
    if (address === "/api/projects/p/typical-building/calculate") {
      this.calculated = this.values;
      return json(this.reply());
    }
    if (method === "PUT") {
      const request = body as { values: TypicalBuildingValues; start_from: string | null };
      const south = (request.values.wwr as Record<string, number>).south;
      if (south > 0.9) return json({ field_errors: [{ field: "wwr.south", message: "Give a number from 0 to 0.9." }], grid_plan: null }, 422);
      this.saved.push(request);
      this.values = request.values;
      this.startFrom = request.start_from;
    }
    return json(this.reply());
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

let service = new FakeBuildingService();
let rendered: RenderedOverlay | null = null;
let closed = 0;
// The 2D context of the charts: jsdom draws nothing, so the image data each chart puts is kept.
let drawn: ImageData[] = [];

beforeEach(() => {
  service = new FakeBuildingService();
  closed = 0;
  drawn = [];
  vi.stubGlobal("fetch", vi.fn(async (address: string, options?: RequestInit) =>
    service.handle(options?.method ?? "GET", address, typeof options?.body === "string" ? JSON.parse(options.body) : undefined)));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ({
    createImageData: (width: number, height: number) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
    putImageData: (image: ImageData) => drawn.push(image),
  })) as never);
});

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Sheet({ includesHarm = false, hasWeatherFile = true }: { includesHarm?: boolean; hasWeatherFile?: boolean }) {
  const building = useTypicalBuilding({ token: "t", project: "p", active: true, runActive: false, weatherRevision: 0, onServiceProblem: () => {} });
  return <TypicalBuildingSheet id="sheet" building={building} includesHarm={includesHarm} hasWeatherFile={hasWeatherFile} disabledReason={null}
                               onClose={() => { closed += 1; }} />;
}

/** Lets the fake service's replies arrive. */
async function settle() {
  for (let round = 0; round < 5; round++) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

async function openSheet(props: { includesHarm?: boolean; hasWeatherFile?: boolean } = {}) {
  rendered = renderForTest(<Sheet {...props} />);
  await settle();
}

const find = <Element extends HTMLElement = HTMLElement>(selector: string) => rendered!.container.querySelector<Element>(selector);
const group = (id: string) => find(`.panel-section[data-section="${id}"]`)!;
const summaryOf = (id: string) => group(id).querySelector(".panel-section-summary")?.textContent;
const calculateButton = () => find<HTMLButtonElement>(".typical-building-calculate button")!;

function typeInto(field: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
}

function choose(select: HTMLSelectElement, value: string) {
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

test("the sheet starts from the type of the stored building, says each group in one line, and has Calculate", async () => {
  await openSheet();
  expect(find<HTMLSelectElement>("select")!.value).toBe("office");
  expect(document.activeElement).toBe(find("select"));
  expect([...rendered!.container.querySelectorAll(".panel-section-title")].map((title) => title.textContent))
    .toEqual(["Shape", "Windows", "Walls and glass", "Air", "Use", "Summer shading"]);
  expect(summaryOf("shape")).toBe(`5 × 7 × 3${NBSP}m, 0° from north`);
  expect(summaryOf("windows")).toBe("E 0.1, S 0.27, W 0.1; g 0.6");
  expect(summaryOf("walls")).toBe(`U 0.5 and 1.8${NBSP}W/m²K, medium mass`);
  expect(summaryOf("air")).toBe("1.2 + 0.3 air changes per hour");
  expect(summaryOf("use")).toBe(`20 to 26${NBSP}°C, gains 7.1 and 1.7${NBSP}W/m²`);
  expect(summaryOf("shading")).toBe("None");
  expect(calculateButton().textContent).toBe("Calculate");
  expect(find(".weights-chart")).toBeNull();      // nothing calculated yet
  expect(rendered!.container.textContent).not.toMatch(/5R1C/);
});

test("Start from fills the values of the type and saves them with the type", async () => {
  await openSheet();
  choose(find<HTMLSelectElement>("select")!, "light_home");
  await settle();
  expect(service.saved.at(-1)).toEqual({ values: LIGHT_HOME, start_from: "light_home" });
  expect(summaryOf("shape")).toBe(`5 × 6 × 3${NBSP}m, 0° from north`);
  expect(find<HTMLSelectElement>("select")!.value).toBe("light_home");
});

test("a changed value is saved when its field is left, and the type reads Custom", async () => {
  await openSheet();
  click(group("shape").querySelector(".panel-section-header")!);
  typeInto(group("shape").querySelector<HTMLInputElement>('[data-building-field="width"] input')!, "6");
  await settle();
  expect(service.saved.at(-1)!.values.width).toBe(6);
  expect(service.saved.at(-1)!.start_from).toBe("office");
  expect(find<HTMLSelectElement>("select")!.value).toBe("custom");
  expect(find<HTMLSelectElement>("select")!.selectedOptions[0].textContent).toBe("Custom");
});

test("a refused value shows its error at its field, its group's line warns once closed, and Calculate waits", async () => {
  await openSheet();
  click(group("windows").querySelector(".panel-section-header")!);
  const south = group("windows").querySelector<HTMLInputElement>('input[aria-label="South"]')!;
  typeInto(south, "0.95");
  await settle();
  expect(group("windows").querySelector('[data-building-field="wwr"] .setting-error')!.textContent).toBe("South: Give a number from 0 to 0.9.");
  expect(group("windows").querySelector<HTMLInputElement>('input[aria-label="South"]')!.getAttribute("aria-invalid")).toBe("true");
  expect(group("windows").querySelector<HTMLInputElement>('input[aria-label="South"]')!.value).toBe("0.95");
  expect(service.saved).toEqual([]);
  expect(calculateButton().disabled).toBe(true);
  expect(find(".typical-building-calculate .run-button-reason")!.textContent).toBe("Fix the values marked above to calculate");
  click(group("windows").querySelector(".panel-section-header")!);
  expect(group("windows").querySelector(".panel-section-summary-problem")).not.toBeNull();
});

test("Calculate shows the chart of each hour and the numbers; a change after it dims them and asks to calculate again", async () => {
  await openSheet();
  click(calculateButton());
  await settle();
  expect(service.requests).toContain("POST /api/projects/p/typical-building/calculate");
  expect(rendered!.container.querySelectorAll(".weights-chart")).toHaveLength(1);
  expect(find(".weights-chart canvas")!.getAttribute("aria-label")).toBe("What each hour's sun saves in heating, 0 to 1: day of the year across, hour of the day down");
  // The first day's hours are 0.5, the middle of viridis; day 50 is 0, its dark end.
  const image = drawn.at(-1)!;
  expect([image.width, image.height]).toEqual([365, 24]);
  expect([...image.data.slice(0, 3)]).toEqual([33, 145, 140]);
  expect([...image.data.slice(50 * 4, 50 * 4 + 3)]).toEqual([68, 1, 84]);
  expect([...rendered!.container.querySelectorAll(".typical-building-numbers dd")].map((value) => value.textContent))
    .toEqual([`189.5${NBSP}kWh/m² a year`, `26.9${NBSP}kWh/m² a year`, "7 082 of 8 760"]);
  expect(find(".typical-building-results-out-of-date")).toBeNull();

  click(group("use").querySelector(".panel-section-header")!);
  typeInto(group("use").querySelector<HTMLInputElement>('[data-building-field="t_set_heating"] input')!, "19");
  await settle();
  expect(find(".typical-building-results-out-of-date")).not.toBeNull();
  expect(find(".typical-building-out-of-date")!.textContent).toBe("The building or the weather file changed since this was calculated.");
  expect(calculateButton().textContent).toBe("Calculate again");
  click(calculateButton());
  await settle();
  expect(find(".typical-building-results-out-of-date")).toBeNull();
  expect(calculateButton().textContent).toBe("Calculate");
});

test("a criterion that counts harm has the chart of harm too", async () => {
  service.calculated = OFFICE;
  await openSheet({ includesHarm: true });
  expect([...rendered!.container.querySelectorAll(".weights-chart-title")].map((title) => title.textContent))
    .toEqual(["What each hour's sun saves in heating", "What each hour's sun adds to cooling"]);
});

test("Calculate waits for a weather file; Escape closes the sheet", async () => {
  await openSheet({ hasWeatherFile: false });
  expect(calculateButton().disabled).toBe(true);
  expect(find(".typical-building-calculate .run-button-reason")!.textContent).toBe("Add a weather file in Design (Inputs) to calculate the typical building");
  act(() => find("select")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(closed).toBe(1);
});

test("the shading line names the factors set and the months of the summer one; a type is matched by its values", () => {
  expect(buildingGroupSummary("shading", { ...OFFICE, shading_permanent: 0.8, shading_hot: 0.5 })).toBe("Permanent 0.8; summer 0.5 in Jun, Jul and Aug");
  expect(buildingGroupSummary("air", { ...OFFICE, heat_recovery: 0.6 })).toBe("1.2 + 0.3 air changes per hour, recovery 0.6");
  expect(typeOfValues({ ...LIGHT_HOME }, null, PRESETS)).toBe("light_home");
  expect(typeOfValues({ ...LIGHT_HOME, width: 9 }, "light_home", PRESETS)).toBeNull();
});

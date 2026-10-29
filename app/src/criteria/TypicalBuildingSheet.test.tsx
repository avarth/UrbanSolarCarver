import { readFileSync } from "node:fs";
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { TypicalBuildingLibraryEntry, TypicalBuildingReply } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { buildingGroupSummary, effectColour, libraryGroupsOf, libraryLineOf, SUN_DOWN_COLOUR, SUN_DOWN_COLOUR_DARK, TypicalBuildingSheet, withRoom } from "./TypicalBuildingSheet";
import { useTypicalBuilding, type TypicalBuildingValues } from "./use_typical_building";

const NBSP = " ";
const DIGIT_GROUP = " ";

/** The values of the KENAK reference building of a zone, as the service gives them (typical_building._kenak_values). */
function kenak(uWall: number, uRoof: number, uWindow: number, shading: [string, string]): TypicalBuildingValues {
  return { schedule: "residential", t_set_heating: 20, t_set_cooling: 26, gains_w_m2: 6, fresh_air_m3h_m2: 0.75, heat_recovery: 0, u_wall: uWall,
           u_window: uWindow, g_value: 0.55, mass_capacity_kj_m2k: 250, shading_factor: 0.77, shading_start: shading[0], shading_end: shading[1],
           room: "average", height: 3, depth: 6, wwr: { ne: 0.4, se: 0.4, sw: 0.4, nw: 0.4 }, roof_exposed: false, u_roof: uRoof, floor_exposed: false,
           u_floor: uRoof, ach_infiltration: 0.37 };
}

const ZONE_A = kenak(0.6, 0.5, 3.2, ["05-15", "09-15"]);
const ZONE_B = kenak(0.5, 0.45, 3, ["05-15", "09-15"]);
const CASE_600: TypicalBuildingValues = {
  schedule: "always", t_set_heating: 20, t_set_cooling: 27, gains_w_m2: 4.1667, fresh_air_m3h_m2: 0, heat_recovery: 0, u_wall: 0.514, u_window: 3,
  g_value: 0.71, mass_capacity_kj_m2k: 80, shading_factor: null, shading_start: "06-01", shading_end: "08-31",
  room: "box", height: 2.7, width: 8, length: 6, orientation: 0, wwr: { north: 0, east: 0, south: 0.5556, west: 0 }, roof_exposed: true, u_roof: 0.318,
  floor_exposed: true, u_floor: 0.039, ach_infiltration: 0.5,
};
const SOURCE_B = "ΤΟΤΕΕ 20701-1/2017 (ΦΕΚ Β' 4003/17.11.2017), reference building, zone Β";
const KENAK_GROUP = "Greece, KENAK reference building";
const ASHRAE_GROUP = "ASHRAE 140 test cases";
const EXAMPLES: TypicalBuildingLibraryEntry[] = [
  { id: "kenak-apartment-a", name: "Apartment, zone Α", group: KENAK_GROUP, read_only: true, source: "zone Α source", values: ZONE_A },
  { id: "kenak-apartment-b", name: "Apartment, zone Β", group: KENAK_GROUP, read_only: true, source: SOURCE_B, values: ZONE_B },
  { id: "kenak-office-b", name: "Office, zone Β", group: KENAK_GROUP, read_only: true, source: "office source", values: { ...ZONE_B, schedule: "office" } },
  { id: "ashrae140-600", name: "ASHRAE 140 case 600 (light)", group: ASHRAE_GROUP, read_only: true, source: "ASHRAE source", values: CASE_600 },
];

/** The value with its object keys sorted, so two values compare by their JSON. */
function sortedKeys(value: unknown): unknown {
  if (Array.isArray(value) || typeof value !== "object" || value === null) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortedKeys((value as Record<string, unknown>)[key])]));
}
const same = (first: unknown, second: unknown) => JSON.stringify(sortedKeys(first)) === JSON.stringify(sortedKeys(second));

/** The weights of the fake calculation: benefit 0.5 in the first 1000 hours, harm 0.25 after hour 8000; the sun up from 8 to 16 h. */
const WEIGHTS = {
  benefit: Array.from({ length: 8760 }, (_, hour) => (hour < 1000 ? 0.5 : 0)),
  harm: Array.from({ length: 8760 }, (_, hour) => (hour > 8000 ? 0.25 : 0)),
  sun_up: Array.from({ length: 8760 }, (_, hour) => (hour % 24 >= 8 && hour % 24 < 16 ? 1 : 0)),
};

/**
 * The service's routes of the typical building and its library: it stores what is saved, refuses a window share above 0.9 and a key
 * of the other room, keeps the examples read-only and names unique, and calculates.
 */
class FakeBuildingService {
  /** Null: no building chosen yet, as in a new project. */
  values: TypicalBuildingValues | null = ZONE_B;
  libraryId: string | null = "kenak-apartment-b";
  libraryName: string | null = "Apartment, zone Β";
  calculated: TypicalBuildingValues | null = null;
  own: TypicalBuildingLibraryEntry[] = [];
  readonly requests: string[] = [];
  readonly saved: { values: TypicalBuildingValues; library_id?: string }[] = [];

  library(): TypicalBuildingLibraryEntry[] {
    return [...EXAMPLES, ...[...this.own].sort((first, second) => first.name.localeCompare(second.name))];
  }

  reply(): TypicalBuildingReply {
    const state = this.values === null ? "not_chosen" : this.calculated === null ? "missing" : same(this.calculated, this.values) ? "current" : "out_of_date";
    const entry = this.library().find((each) => each.id === this.libraryId);
    return { values: this.values, library_id: this.libraryId, library_name: entry?.name ?? this.libraryName,
             changed: entry !== undefined && !same(entry.values, this.values), state,
             ...(this.calculated === null ? {} : { heating_kwh_m2: 43.71, cooling_kwh_m2: 24.06, counted_hours: 2386 }) };
  }

  handle(method: string, address: string, body: unknown): Response {
    this.requests.push(`${method} ${address}`);
    const libraryPath = "/api/typical-building-library";
    if (address === libraryPath && method === "GET") return json(this.library());
    if (address === libraryPath && method === "POST") {
      const request = body as { name: string; values: TypicalBuildingValues };
      if (this.library().some((entry) => entry.name.toLowerCase() === request.name.toLowerCase()))
        return json({ detail: `A building named '${request.name}' is already in the library: choose another name.` }, 409);
      const entry = { id: `own-${this.own.length + 1}`, name: request.name, group: null, read_only: false, source: null, values: request.values };
      this.own.push(entry);
      return json(entry);
    }
    if (address.startsWith(`${libraryPath}/`)) {
      const entryId = decodeURIComponent(address.slice(libraryPath.length + 1));
      if (EXAMPLES.some((entry) => entry.id === entryId)) return json({ detail: "An example cannot be changed." }, 409);
      const entry = this.own.find((each) => each.id === entryId)!;
      if (method === "DELETE") {
        this.own = this.own.filter((each) => each !== entry);
        return new Response(null, { status: 204 });
      }
      const change = body as { name?: string; values?: TypicalBuildingValues };
      Object.assign(entry, change);
      return json(entry);
    }
    if (address === "/api/projects/p/typical-building/weights") return this.calculated === null ? json({ detail: "not yet" }, 404) : json(WEIGHTS);
    if (address === "/api/projects/p/typical-building/calculate") {
      this.calculated = this.values;
      return json(this.reply());
    }
    if (method === "PUT") {
      const request = body as { values: TypicalBuildingValues; library_id?: string };
      const shares = request.values.wwr as Record<string, number>;
      const tooLarge = Object.keys(shares).find((side) => shares[side] > 0.9);
      if (tooLarge !== undefined) return json({ field_errors: [{ field: `wwr.${tooLarge}`, message: "Give a number from 0 to 0.9." }], grid_plan: null }, 422);
      const otherRoomKey = request.values.room === "average" ? ["width", "length", "orientation"].find((key) => key in request.values)
        : "depth" in request.values ? "depth" : undefined;
      if (otherRoomKey !== undefined) return json({ field_errors: [{ field: otherRoomKey, message: "Not a value of this room." }], grid_plan: null }, 422);
      this.saved.push(request);
      this.values = request.values;
      if (request.library_id !== undefined) {
        this.libraryId = request.library_id;
        this.libraryName = this.library().find((entry) => entry.id === request.library_id)!.name;
      }
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
// The 2D context of the chart: jsdom draws nothing, so the image data each chart puts is kept.
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
  for (let round = 0; round < 8; round++) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

async function openSheet(props: { includesHarm?: boolean; hasWeatherFile?: boolean } = {}) {
  rendered = renderForTest(<Sheet {...props} />);
  await settle();
}

// The window is rendered into document.body (over the whole app), not into the container of the render.
const find = <Element extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<Element>(selector);
const group = (id: string) => find(`.panel-section[data-section="${id}"]`)!;
const summaryOf = (id: string) => group(id).querySelector(".panel-section-summary")?.textContent;
const openGroup = (id: string) => click(group(id).querySelector(".panel-section-header")!);
const calculateButton = () => find<HTMLButtonElement>(".typical-building-calculate button")!;
const buttonNamed = (name: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === name)!;
const entryButton = (id: string) => find<HTMLButtonElement>(`[data-library-entry="${id}"] .typical-building-library-entry`)!;
const advancedToggle = () => find<HTMLButtonElement>(".typical-building-advanced-toggle")!;
const lastSaved = () => service.saved.at(-1)!;

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

/** The library's dialog (Save as new, Rename, Delete) over the window, or null. */
const libraryDialog = () => document.querySelector<HTMLElement>(".project-dialog:not(.project-dialog-wide)");

async function submitDialog(name?: string) {
  const dialog = libraryDialog()!;
  if (name !== undefined) {
    const field = dialog.querySelector<HTMLInputElement>("input")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, name);
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await act(async () => { dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await settle();
}

test("the sheet names the library entry and its source, says each basic group in one line, keeps Room, Roof and floor and Air under Advanced", async () => {
  await openSheet();
  expect(document.activeElement).toBe(find("h2"));
  expect(summaryOf("library")).toBe("Apartment, zone Β");
  expect(find(".typical-building-source")!.textContent).toBe(SOURCE_B);
  expect([...find(".typical-building-groups + .typical-building-library-actions + .typical-building-groups")!.querySelectorAll(".panel-section-title")]
    .map((title) => title.textContent)).toEqual(["Use", "Fabric", "Summer shading"]);
  expect(summaryOf("use")).toBe(`Residential hours, 20 to 26${NBSP}°C, gains 6${NBSP}W/m²`);
  expect(summaryOf("fabric")).toBe(`U 0.5 and 3${NBSP}W/m²K, g 0.55, mass 250${NBSP}kJ/m²K`);
  expect(summaryOf("shading")).toBe("0.77 from 15 May to 15 Sep");
  expect(advancedToggle().getAttribute("aria-expanded")).toBe("false");
  expect(find('[data-section="room"]')).toBeNull();
  click(advancedToggle());
  expect(summaryOf("room")).toBe(`Average, 6${NBSP}m deep, 3${NBSP}m storey; windows 0.4 on each side`);
  expect(summaryOf("roof_and_floor")).toBe("Both adiabatic");
  expect(summaryOf("air")).toBe(`Infiltration 0.37${NBSP}air changes per hour`);
  expect(calculateButton().textContent).toBe("Calculate");
  expect(find(".weights-chart")).toBeNull();      // nothing calculated yet
  expect(find(".typical-building-sheet")!.textContent).not.toMatch(/5R1C/);
});

test("the library lists the examples in the groups the service names; choosing one replaces the project's copy with its values and id", async () => {
  await openSheet();
  openGroup("library");
  expect([...group("library").querySelectorAll(".typical-building-library-group-name")].map((name) => name.textContent))
    .toEqual([KENAK_GROUP, ASHRAE_GROUP]);
  expect(entryButton("kenak-apartment-b").getAttribute("aria-pressed")).toBe("true");
  expect(group("library").querySelector('[data-library-entry="kenak-apartment-b"] .link-button')).toBeNull();     // an example is read-only
  click(entryButton("ashrae140-600"));
  await settle();
  expect(lastSaved()).toEqual({ values: CASE_600, library_id: "ashrae140-600" });
  expect(entryButton("ashrae140-600").getAttribute("aria-pressed")).toBe("true");
  expect(find(".typical-building-source")!.textContent).toBe("ASHRAE source");
  expect(summaryOf("shading")).toBe("None");
});

test("a changed value is saved without the entry; the library says Changed from it, and an example can only be saved as new", async () => {
  await openSheet();
  openGroup("use");
  typeInto(group("use").querySelector<HTMLInputElement>('[data-building-field="t_set_heating"] input')!, "19");
  await settle();
  expect(lastSaved()).toEqual({ values: { ...ZONE_B, t_set_heating: 19 } });
  expect(summaryOf("library")).toBe("Changed from Apartment, zone Β");
  expect(buttonNamed("Save to library").disabled).toBe(true);
  expect(find(".typical-building-library-actions .setting-note")!.textContent)
    .toBe("Apartment, zone Β is an example: Save as new keeps these values in the library.");

  click(buttonNamed("Save as new"));
  expect(libraryDialog()!.querySelector("h2")!.textContent).toBe("Save as new");
  await submitDialog("Apartment, zone β");     // the name of an example, another letter case
  expect(libraryDialog()!.querySelector("[role=alert]")!.textContent)
    .toBe("A building named 'Apartment, zone β' is already in the library: choose another name.");
  await submitDialog("My flat");
  expect(libraryDialog()).toBeNull();
  expect(service.own.map((entry) => [entry.name, entry.values])).toEqual([["My flat", { ...ZONE_B, t_set_heating: 19 }]]);
  expect(lastSaved().library_id).toBe("own-1");
  expect(summaryOf("library")).toBe("My flat");
  openGroup("library");
  expect([...group("library").querySelectorAll(".typical-building-library-group-name")].at(-1)!.textContent).toBe("Your buildings");
  expect(entryButton("own-1").getAttribute("aria-pressed")).toBe("true");
});

test("an own entry takes the changed values with Save to library, and is renamed and deleted in the list", async () => {
  service.own = [{ id: "own-1", name: "My flat", group: null, read_only: false, source: null, values: ZONE_B }];
  service.libraryId = "own-1";
  service.libraryName = "My flat";
  await openSheet();
  openGroup("fabric");
  typeInto(group("fabric").querySelector<HTMLInputElement>('[data-building-field="u_wall"] input')!, "0.3");
  await settle();
  expect(summaryOf("library")).toBe("Changed from My flat");
  click(buttonNamed("Save to library"));
  await settle();
  expect(service.requests).toContain("PUT /api/typical-building-library/own-1");
  expect(service.own[0].values.u_wall).toBe(0.3);
  expect(summaryOf("library")).toBe("My flat");
  expect(buttonNamed("Save to library").disabled).toBe(true);

  openGroup("library");
  click(group("library").querySelector<HTMLButtonElement>('[aria-label="Rename My flat"]')!);
  expect(libraryDialog()!.querySelector("h2")!.textContent).toBe("Rename My flat");
  await submitDialog("   ");
  expect(libraryDialog()!.querySelector("[role=alert]")!.textContent).toBe("Give the building a name.");
  await submitDialog("Top floor");
  expect(service.own[0].name).toBe("Top floor");
  expect(entryButton("own-1").textContent).toBe("Top floor");

  click(group("library").querySelector<HTMLButtonElement>('[aria-label="Delete Top floor"]')!);
  expect(libraryDialog()!.querySelector("p")!.textContent).toBe("Top floor leaves the library. Projects that use it keep their own copy.");
  await submitDialog();
  expect(service.own).toEqual([]);
  expect(group("library").querySelector('[data-library-entry="own-1"]')).toBeNull();
  openGroup("library");
  // The project keeps the name it took the entry by (the service's library_name once the entry is gone).
  expect(summaryOf("library")).toBe("My flat, no longer in the library");
});

test("thermal mass is one number, the thermal capacity; the schedule is one of three cases; no standard is cited in the form", async () => {
  await openSheet();
  openGroup("fabric");
  expect(group("fabric").querySelector("select")).toBeNull();
  const capacity = group("fabric").querySelector('[data-building-field="mass_capacity_kj_m2k"]')!;
  expect(capacity.querySelector(".setting-label")!.textContent).toBe("Thermal capacity");
  expect(capacity.querySelector(".setting-unit")!.textContent).toBe("kJ/m²K");
  typeInto(capacity.querySelector<HTMLInputElement>("input")!, "300");
  await settle();
  expect(lastSaved().values).toEqual({ ...ZONE_B, mass_capacity_kj_m2k: 300 });
  click(group("fabric").querySelector(".panel-section-header")!);
  expect(summaryOf("fabric")).toBe(`U 0.5 and 3${NBSP}W/m²K, g 0.55, mass 300${NBSP}kJ/m²K`);

  openGroup("use");
  expect([...group("use").querySelectorAll<HTMLOptionElement>('[data-building-field="schedule"] option')].map((option) => option.textContent))
    .toEqual(["Residential: 6:00 to 24:00 every day", "Office: 8:00 to 18:00, Monday to Friday", "Always"]);
  openGroup("shading");
  click(advancedToggle());
  for (const id of ["room", "roof_and_floor", "air"]) openGroup(id);
  expect(group("air").querySelector('[data-building-field="ach_infiltration"] .setting-unit')!.textContent).toBe("1/h");
  // The form's labels, options and notes name no standard or table; the sources are in the examples' source text only.
  const formText = [...document.querySelectorAll(".typical-building-groups .setting-field, .typical-building-groups .setting-note")]
    .map((element) => element.textContent).join(" ");
  expect(formText).not.toMatch(/ΤΟΤΕΕ|TOTEE|KENAK|ΚΕΝΑΚ|ISO|table/);
});

test("a project without a building shows only the library, open, and choosing an example fills the form", async () => {
  service.values = null;
  service.libraryId = null;
  service.libraryName = null;
  await openSheet();
  expect(group("library").querySelector(".panel-section-header")!.getAttribute("aria-expanded")).toBe("true");
  expect(group("library").querySelector(".setting-note")!.textContent)
    .toBe("The project has no typical building yet: choose one to start from, then change its values.");
  expect(find('[data-section="use"]')).toBeNull();
  expect(find(".typical-building-calculate")).toBeNull();
  expect(buttonNamed("Save as new")).toBeUndefined();
  expect(document.activeElement).toBe(find("h2"));
  openGroup("library");
  expect(summaryOf("library")).toBe("None chosen");
  openGroup("library");
  click(entryButton("kenak-apartment-b"));
  await settle();
  expect(lastSaved()).toEqual({ values: ZONE_B, library_id: "kenak-apartment-b" });
  openGroup("library");
  expect(summaryOf("library")).toBe("Apartment, zone Β");
  expect(summaryOf("use")).toMatch(/^Residential hours/);
  expect(calculateButton().textContent).toBe("Calculate");
});

test("summer shading takes a factor and the dates of its period; empty is no shading", async () => {
  await openSheet();
  openGroup("shading");
  const start = group("shading").querySelector('[data-building-field="shading_start"]')!;
  choose(start.querySelector<HTMLSelectElement>("select")!, "6");
  await settle();
  expect(lastSaved().values.shading_start).toBe("06-15");
  typeInto(start.querySelector<HTMLInputElement>("input")!, "1");
  await settle();
  expect(lastSaved().values.shading_start).toBe("06-01");
  typeInto(group("shading").querySelector<HTMLInputElement>('[data-building-field="shading_factor"] input')!, "");
  await settle();
  expect(lastSaved().values.shading_factor).toBeNull();
  expect(group("shading").querySelector('[data-building-field="shading_start"]')).toBeNull();
});

test("under Advanced, the room switches between the average room and the box with the other kind's keys, and the roof and floor are exposed with their U", async () => {
  await openSheet();
  click(advancedToggle());
  openGroup("room");
  expect([...group("room").querySelectorAll('[data-building-field="wwr"] .setting-angle-direction > span')].map((side) => side.textContent))
    .toEqual(["NE", "SE", "SW", "NW"]);
  click([...group("room").querySelectorAll<HTMLButtonElement>('[data-building-field="room"] button')].find((button) => button.textContent === "Box")!);
  await settle();
  const { depth: _depth, ...shared } = ZONE_B;
  expect(lastSaved().values).toEqual({ ...shared, room: "box", width: 24, length: 24, orientation: 45, wwr: { north: 0.4, east: 0.4, south: 0.4, west: 0.4 } });
  expect(group("room").querySelector('[data-building-field="orientation"]')).not.toBeNull();
  expect(group("room").querySelector('[data-building-field="depth"]')).toBeNull();

  openGroup("roof_and_floor");
  expect(group("roof_and_floor").querySelector('[data-building-field="u_roof"]')).toBeNull();
  act(() => group("roof_and_floor").querySelector<HTMLInputElement>('[data-building-field="roof_exposed"] input')!.click());
  await settle();
  expect(lastSaved().values.roof_exposed).toBe(true);
  expect(group("roof_and_floor").querySelector<HTMLInputElement>('[data-building-field="u_roof"] input')!.value).toBe("0.45");
  click(group("roof_and_floor").querySelector(".panel-section-header")!);
  expect(summaryOf("roof_and_floor")).toBe(`Roof U 0.45${NBSP}W/m²K, floor adiabatic`);
});

test("a refused value shows its error at its field, opens Advanced and its group, keeps the typed text, and Calculate waits", async () => {
  await openSheet();
  click(advancedToggle());
  openGroup("room");
  typeInto(group("room").querySelector<HTMLInputElement>('input[aria-label="South-west"]')!, "0.95");
  await settle();
  expect(group("room").querySelector('[data-building-field="wwr"] .setting-error')!.textContent).toBe("South-west: Give a number from 0 to 0.9.");
  expect(group("room").querySelector<HTMLInputElement>('input[aria-label="South-west"]')!.value).toBe("0.95");
  expect(service.saved).toEqual([]);
  expect(calculateButton().disabled).toBe(true);
  expect(find(".typical-building-calculate .run-button-reason")!.textContent).toBe("Fix the values marked above to calculate");
  click(group("room").querySelector(".panel-section-header")!);
  expect(group("room").querySelector(".panel-section-summary-problem")).not.toBeNull();
  click(advancedToggle());
  expect(advancedToggle().querySelector(".panel-section-summary-problem")).not.toBeNull();
});

test("Calculate draws the effect of each hour's sun, grey with the sun down, and the numbers; a change after it dims them", async () => {
  await openSheet();
  click(calculateButton());
  await settle();
  expect(service.requests).toContain("POST /api/projects/p/typical-building/calculate");
  expect(document.querySelectorAll(".weights-chart")).toHaveLength(1);
  expect(find(".weights-chart-title")!.textContent).toBe("Effect of sunlight, by hour");
  expect(find(".weights-chart canvas")!.getAttribute("aria-label")).toBe("Effect of sunlight, by hour: day of the year across, hour of the day down; " +
    "red where the sun offsets heating, grey with the sun down");
  expect([...find(".weights-chart-legend")!.children].map((part) => part.textContent)).toEqual(["no effect", "", "offsets heating", "sun down"]);
  const image = drawn.at(-1)!;
  expect([image.width, image.height]).toEqual([365, 24]);
  const pixel = (day: number, hour: number) => [...image.data.slice((hour * 365 + day) * 4, (hour * 365 + day) * 4 + 3)];
  expect(pixel(0, 2)).toEqual([196, 196, 196]);          // 1 January, 2:00: the sun is down
  expect(pixel(0, 10)).toEqual([244, 165, 130]);         // 0.5 of offsets heating
  expect(pixel(340, 10)).toEqual([255, 255, 255]);       // no effect: harm is not counted
  expect([...document.querySelectorAll(".typical-building-numbers dd")].map((value) => value.textContent))
    .toEqual([`43.7${NBSP}kWh/m² a year`, `24.1${NBSP}kWh/m² a year`, `2${DIGIT_GROUP}386 of 2${DIGIT_GROUP}920 daytime hours`]);
  expect(find(".typical-building-results-out-of-date")).toBeNull();

  openGroup("use");
  typeInto(group("use").querySelector<HTMLInputElement>('[data-building-field="t_set_heating"] input')!, "19");
  await settle();
  expect(find(".typical-building-results-out-of-date")).not.toBeNull();
  expect(find(".typical-building-out-of-date")!.textContent).toBe("The building or the weather file changed since this was calculated.");
  expect(calculateButton().textContent).toBe("Calculate again");
  click(calculateButton());
  await settle();
  expect(find(".typical-building-results-out-of-date")).toBeNull();
});

test("a criterion that counts harm shows benefit minus harm: blue where the sun adds to cooling", async () => {
  service.calculated = ZONE_B;
  await openSheet({ includesHarm: true });
  await settle();
  expect([...find(".weights-chart-legend")!.children].map((part) => part.textContent)).toEqual(["adds to cooling", "", "offsets heating", "sun down"]);
  const image = drawn.at(-1)!;
  const offset = (10 * 365 + 340) * 4;      // 7 December, 10:00: harm 0.25
  expect([...image.data.slice(offset, offset + 3)]).toEqual(effectColour(-0.25));
  expect(effectColour(-0.25)).toEqual([209, 229, 240]);
});

test("Calculate waits for a weather file; Escape closes the sheet", async () => {
  await openSheet({ hasWeatherFile: false });
  expect(calculateButton().disabled).toBe(true);
  expect(find(".typical-building-calculate .run-button-reason")!.textContent).toBe("Add a weather file in Design (Inputs) to calculate the typical building");
  act(() => find(".typical-building-sheet")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(closed).toBe(1);
});

test("the average room is the box 4 times its depth turned 45°, and a box the average room with its facade per m² of floor", () => {
  const box = withRoom(ZONE_B, "box");
  expect(withRoom(box, "average")).toEqual(ZONE_B);
  const average = withRoom(CASE_600, "average");
  expect(average).toMatchObject({ room: "average", depth: 1.71, wwr: { ne: 0, se: 0, sw: 0.5556, nw: 0 } });
  expect(Object.keys(average)).not.toContain("width");
  expect(buildingGroupSummary("room", CASE_600)).toBe(`Box 8 × 6 × 2.7${NBSP}m, 0° from north; S 0.556`);
  expect(buildingGroupSummary("roof_and_floor", CASE_600)).toBe(`Roof U 0.318, floor U 0.039${NBSP}W/m²K`);
  expect(buildingGroupSummary("use", CASE_600)).toBe(`Every hour, 20 to 27${NBSP}°C, gains 4.17${NBSP}W/m²`);
});

test("the colours run from white to red and to blue; a project from no entry, or from one gone, says so", () => {
  expect(effectColour(0)).toEqual([255, 255, 255]);
  expect(effectColour(1)).toEqual([178, 24, 43]);
  expect(effectColour(-1)).toEqual([33, 102, 172]);
  expect(SUN_DOWN_COLOUR).toBe("#c4c4c4");
  // The dark theme: no effect is the dark panel, and a stronger effect is brighter, red or blue
  expect(effectColour(0, "dark")).toEqual([30, 39, 46]);
  expect(effectColour(1, "dark")).toEqual([244, 165, 130]);
  expect(effectColour(-1, "dark")).toEqual([146, 197, 222]);
  expect(SUN_DOWN_COLOUR_DARK).toBe("#3e474e");
  const reply = { values: ZONE_B, library_id: "own-9", library_name: "Old flat", changed: false, state: "missing" as const };
  expect(libraryLineOf({ ...reply, library_id: null, library_name: null }, EXAMPLES)).toBe("Not from the library");
  expect(libraryLineOf(reply, EXAMPLES)).toBe("Old flat, no longer in the library");
  expect(libraryLineOf({ values: null, library_id: null, library_name: null, changed: false, state: "not_chosen" }, EXAMPLES)).toBe("None chosen");
  const own = { id: "own-1", name: "Mine", group: null, read_only: false, source: null, values: ZONE_B };
  expect(libraryGroupsOf([own, ...EXAMPLES]).map(({ name, entries }) => [name, entries.length])).toEqual([[KENAK_GROUP, 3], [ASHRAE_GROUP, 1], ["Your buildings", 1]]);
});

test("the typical building opens as a modal window: aria-modal, its title takes the focus, × and Done close it", async () => {
  await openSheet();
  const window = find('[role="dialog"][aria-modal="true"]')!;
  expect(window.classList.contains("project-dialog-wide")).toBe(true);
  expect(window.contains(find("#sheet"))).toBe(true);
  const title = find("h2")!;
  expect(title.textContent).toBe("Typical building");
  expect(window.getAttribute("aria-labelledby")).toBe(title.id);
  expect(document.activeElement).toBe(title);
  click(find<HTMLButtonElement>('button[aria-label="Close"]')!);
  expect(closed).toBe(1);
  click(buttonNamed("Done"));
  expect(closed).toBe(2);
});

test("the short windows (reading, no building chosen) are the same modal window, closed by ×, without Done", async () => {
  service.values = null;
  service.libraryId = null;
  service.libraryName = null;
  await openSheet();
  expect(find('[role="dialog"][aria-modal="true"].project-dialog-wide')).not.toBeNull();
  expect(document.activeElement).toBe(find("h2"));
  expect(find(".typical-building-window-columns")).toBeNull();
  expect(buttonNamed("Done")).toBeUndefined();
  click(find<HTMLButtonElement>('button[aria-label="Close"]')!);
  expect(closed).toBe(1);
});

test("Escape closes the window; in a library dialog over it, Escape closes only that dialog", async () => {
  await openSheet();
  click(buttonNamed("Save as new"));
  const inner = libraryDialog()!;
  act(() => inner.querySelector("input")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(closed).toBe(0);
  expect([...document.querySelectorAll(".project-dialog h2")].map((title) => title.textContent)).toEqual(["Typical building"]);
  act(() => find("h2")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(closed).toBe(1);
});

test("Tab stays inside the window, and inside a library dialog over it", async () => {
  await openSheet();
  const window = find<HTMLElement>('[role="dialog"]')!;
  const controls = () => [...window.querySelectorAll<HTMLElement>("button, input, select")].filter((control) => !(control as HTMLButtonElement).disabled);
  const tab = (shiftKey = false) => act(() => document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey, bubbles: true, cancelable: true })));
  // Shift+Tab from the title (which has the focus) goes to the last control; Tab from the last goes to the first.
  tab(true);
  expect(document.activeElement).toBe(buttonNamed("Done"));
  tab();
  expect(document.activeElement).toBe(controls()[0]);
  tab(true);
  expect(document.activeElement).toBe(buttonNamed("Done"));
  // Over a library dialog the innermost one keeps it.
  click(buttonNamed("Save as new"));
  const inner = libraryDialog()!;
  const innerControls = [...inner.querySelectorAll<HTMLElement>("button, input")];
  innerControls[innerControls.length - 1].focus();
  tab();
  expect(document.activeElement).toBe(innerControls[0]);
  tab(true);
  expect(document.activeElement).toBe(innerControls[innerControls.length - 1]);
});

test("the values are in the left column and Calculate, the chart and the numbers in the right one", async () => {
  await openSheet();
  await act(async () => { calculateButton().click(); });
  await settle();
  const values = find(".typical-building-window-columns > .typical-building-window-values")!;
  const results = find(".typical-building-window-columns > .typical-building-window-results")!;
  expect(values.querySelector(".typical-building-groups")).not.toBeNull();
  expect(values.querySelector(".typical-building-library-actions")).not.toBeNull();
  expect(values.querySelector(".typical-building-advanced")).not.toBeNull();
  expect(values.querySelector(".typical-building-calculate")).toBeNull();
  expect(results.querySelector(".typical-building-calculate")).not.toBeNull();
  expect(results.querySelector(".weights-chart")).not.toBeNull();
  expect(results.querySelector(".typical-building-numbers")).not.toBeNull();
  expect(results.querySelector(".typical-building-groups")).toBeNull();
  // Done ends the window, under both columns.
  expect(find(".project-dialog-buttons")!.previousElementSibling).toBe(find(".typical-building-window-columns"));
});

test("the window is drawn into document.body, over the whole app, not inside the render's container", async () => {
  await openSheet();
  const backdrop = find(".project-dialog-backdrop")!;
  expect(backdrop.parentElement).toBe(document.body);
  expect(rendered!.container.contains(backdrop)).toBe(false);
  expect(document.getElementById("sheet")).not.toBeNull();
});

test("choosing the first building changes the window's shape without losing the focus: it stays inside, and Escape closes the window", async () => {
  service.values = null;
  service.libraryId = null;
  service.libraryName = null;
  await openSheet();
  const entry = entryButton("kenak-apartment-b");
  entry.focus();
  expect(document.activeElement).toBe(entry);
  click(entry);
  await settle();
  expect(find(".typical-building-window-columns")).not.toBeNull();
  const window = find('[role="dialog"]')!;
  expect(window.contains(document.activeElement)).toBe(true);
  expect(document.activeElement).not.toBe(document.body);
  act(() => document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(closed).toBe(1);
});

test("the window is a modal frame in two columns from 900 px: no fixed sheet beside the panel, no stamp moved aside for it", () => {
  const css = readFileSync("src/steps/steps.css", "utf8").replace(/\r\n/g, "\n");
  const wide = css.match(/@media \(min-width: 900px\) \{[\s\S]*?\n\}/)![0];
  // At every width the window is as wide as 880 px allows; under 900 px it is one column, not a narrow dialog.
  expect(css.replace(wide, "")).toMatch(/\.project-dialog-wide \{[^}]*width: min\(880px, 100%\)/);
  expect(wide).toMatch(/\.typical-building-window-columns \{[^}]*display: grid;[^}]*grid-template-columns: minmax\(0, 440px\) minmax\(0, 1fr\)/);
  // From 900 px only the values column scrolls beside the results; the short windows and the results column scroll when they do not fit.
  expect(wide).toMatch(/\.project-dialog-wide > \.typical-building-sheet \{[^}]*overflow-y: auto/);
  expect(wide).toMatch(/\.typical-building-window-results \{[^}]*min-height: 0;[^}]*overflow-y: auto/);
  expect(wide).toMatch(/\.typical-building-window-values \{[^}]*overflow-y: auto/);
  expect(css).toMatch(/\.project-dialog-wide \{[^}]*max-height: calc\(100vh - 64px\)/);
  expect(css).not.toMatch(/\.typical-building-sheet \{[^}]*position: fixed/);
  expect(css).not.toContain("viewer-out-of-date");
});

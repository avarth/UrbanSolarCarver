import { act, useReducer } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../../viewer_overlays/render_for_test";
import { formReducer, initialFormState, shownValue, type FormState } from "../form_state";
import { settingsForStep } from "../presentation";
import { SettingField } from "../SettingField";

// The engine's period settings, as GET schema gives them (pydantic_schemas.py): whole numbers, unset by default.
const PERIOD_SETTING = { anyOf: [{ type: "integer" }, { type: "null" }], default: null };
const SCHEMA = {
  properties: {
    mode: { default: "time-based", type: "string" },
    start_month: PERIOD_SETTING, start_day: PERIOD_SETTING, start_hour: PERIOD_SETTING,
    end_month: PERIOD_SETTING, end_day: PERIOD_SETTING, end_hour: PERIOD_SETTING,
  },
};
const WINTER_DAY = { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14 };
const MODES: ModeInfo[] = [{ name: "time-based", description: "", needs_epw: true, needs_period: true, experimental: false,
                             score_kind: "violation_count", weight_unit: "", starting_values: WINTER_DAY }];
const NBSP = " ";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function form(settings: Record<string, unknown> = WINTER_DAY, modes: ModeInfo[] = MODES): FormState {
  return initialFormState({ schema: SCHEMA, modes, settings: { mode: "time-based", ...settings }, gridPlan: null });
}

const periodView = () => settingsForStep("settings", "time-based").flatMap((group) => group.essential).find((view) => view.name === "start_month")!;

// The form behind the control, as the app holds it: every change goes through the form's reducer; the user values are what the
// saver sends to the engine (shownValue: the starting values of the mode, with the changes made).
let latest: FormState | null = null;
let changes: Record<string, unknown>[] = [];
function Period({ start, disabled = false }: { start: FormState; disabled?: boolean }) {
  const [state, dispatch] = useReducer(formReducer, start);
  latest = state;
  return <SettingField view={periodView()} form={state} disabled={disabled}
                       onChange={(values) => { changes.push(values); dispatch({ type: "values_changed", values }); }} />;
}

function renderPeriod(start: FormState = form(), disabled = false) {
  changes = [];
  rendered = renderForTest(<Period start={start} disabled={disabled} />);
  // jsdom lays nothing out: the year strip is 365 px wide (1 px a day), the hour strip 240 px (10 px an hour).
  const [yearStrip, hourStrip] = strips();
  for (const [strip, width] of [[yearStrip, 365], [hourStrip, 240]] as const) {
    strip.getBoundingClientRect = () => ({ left: 0, width, top: 0, height: 26, right: width, bottom: 26, x: 0, y: 0, toJSON: () => ({}) });
  }
}

const strips = () => [...rendered!.container.querySelectorAll<HTMLElement>(".period-strip")];
const handle = (name: string) => rendered!.container.querySelector<HTMLElement>(`[role='slider'][aria-label='${name}']`)!;
const words = () => rendered!.container.querySelector<HTMLButtonElement>(".period-words")!;
const periodValues = () => Object.fromEntries(Object.keys(WINTER_DAY).map((name) => [name, shownValue(latest!, name)]));
const rangePiecesIn = (strip: HTMLElement) => strip.querySelectorAll(".period-range").length;

function pointer(strip: HTMLElement, type: "pointerdown" | "pointermove" | "pointerup", clientX: number) {
  act(() => { strip.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX, pointerId: 1, button: 0 })); });
}

/** A drag on *strip* from *fromX* through *throughX* to the last of them, released there. */
function drag(strip: HTMLElement, fromX: number, ...throughX: number[]) {
  pointer(strip, "pointerdown", fromX);
  for (const x of throughX) pointer(strip, "pointermove", x);
  pointer(strip, "pointerup", throughX.at(-1) ?? fromX);
}

const keyDown = (element: HTMLElement, key: string) => act(() => { element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });

/** Sets *text* as the value the way the browser does when the user types, so React's change handler runs. */
function typeInto(field: HTMLInputElement | HTMLSelectElement, text: string) {
  act(() => {
    const prototype = field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}
const leave = (field: HTMLElement) => act(() => { field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
const typedField = (name: string) => rendered!.container.querySelector<HTMLInputElement>(`input[type='number'][aria-label='${name}']`)!;
const typedMonth = (name: string) => rendered!.container.querySelector<HTMLSelectElement>(`select[aria-label='${name}']`)!;
const presetButton = (text: string) => [...rendered!.container.querySelectorAll<HTMLButtonElement>(".period-preset")].find((button) => button.textContent === text)!;

test("a year strip and an hour strip with two handles each, named apart, saying their values in words; the period in words under them", () => {
  renderPeriod();
  expect(strips()).toHaveLength(2);
  expect(strips()[0].textContent).toBe("JFMAMJJASOND");
  const spoken = ["Start date", "End date", "Start hour", "End hour"].map((name) => handle(name).getAttribute("aria-valuetext"));
  expect(spoken).toEqual(["21 December", "21 December", `10${NBSP}h`, `14${NBSP}h`]);
  for (const name of ["Start date", "End date", "Start hour", "End hour"]) expect(handle(name).tabIndex).toBe(0);
  expect(words().textContent).toBe(`21 Dec, 10 to 14${NBSP}h`);
  // A link to the setting focuses the start date: the field names it as the input its label targets.
  const field = rendered!.container.querySelector<HTMLElement>("[data-setting='start_month']")!;
  expect(field.dataset.inputId).toBe(handle("Start date").id);
  // The control is one group, named by the setting's label.
  expect(rendered!.container.querySelector(".period-control")!.getAttribute("aria-labelledby")).toBe(rendered!.container.querySelector(".setting-label")!.id);
});

test("dragged across the new year: the engine receives the start after the end, the strip is drawn wrapped, one change per drag (Review Focus 4)", () => {
  renderPeriod();
  const [yearStrip] = strips();
  // The two date handles of 21 December lie on one spot: the drag to the left moves the start.
  drag(yearStrip, 354.5, 340, 300, 273.5);
  expect(changes).toEqual([{ start_month: 10, start_day: 1 }]);
  drag(yearStrip, 355, 200, 119.5);
  expect(changes).toHaveLength(2);
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_month: 10, start_day: 1, end_month: 4, end_day: 30 });
  expect(words().textContent).toBe(`1 Oct to 30 Apr, 10 to 14${NBSP}h`);
  expect(rangePiecesIn(yearStrip)).toBe(2);
});

test("dragged across midnight on one date: the end date becomes the next day in the same change, and the words say so (Review Focus 4)", () => {
  renderPeriod();
  const [, hourStrip] = strips();
  pointer(hourStrip, "pointerdown", 100);           // the start hour, 10 h
  pointer(hourStrip, "pointermove", 225);           // 22 h
  expect(words().textContent).toBe(`21 to 22 Dec, 22 to 14${NBSP}h`);
  expect(changes).toEqual([]);                      // nothing is sent until the release
  pointer(hourStrip, "pointerup", 225);
  expect(changes).toEqual([{ start_hour: 22, end_day: 22 }]);
  drag(hourStrip, 150, 60, 25);                     // the end hour, drawn at the end of 14 h, to 2 h
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 22, end_day: 22, end_hour: 2 });
  expect(words().textContent).toBe(`21 to 22 Dec, 22 to 2${NBSP}h`);
  expect(rangePiecesIn(hourStrip)).toBe(2);
  // Hours that stop crossing midnight leave the dates as they are.
  drag(hourStrip, 225, 125);
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 12, end_day: 22, end_hour: 2 });
  drag(hourStrip, 30, 145);
  expect(words().textContent).toBe(`21 to 22 Dec, 12 to 14${NBSP}h`);
});

test("a drag that crosses the end hour and comes back before the release does not move the end date", () => {
  renderPeriod();
  const [, hourStrip] = strips();
  drag(hourStrip, 100, 225, 125);
  expect(changes).toEqual([{ start_hour: 12 }]);
});

test("arrows move a date handle a day, Page Up and Page Down a month, Home and End to the ends of the year", () => {
  renderPeriod();
  keyDown(handle("Start date"), "ArrowLeft");
  expect(periodValues()).toMatchObject({ start_month: 12, start_day: 20 });
  keyDown(handle("Start date"), "PageDown");
  expect(periodValues()).toMatchObject({ start_month: 11, start_day: 20 });
  keyDown(handle("End date"), "PageUp");
  expect(periodValues()).toMatchObject({ end_month: 12, end_day: 31 });
  keyDown(handle("Start date"), "Home");
  expect(periodValues()).toMatchObject({ start_month: 1, start_day: 1 });
  keyDown(handle("End date"), "ArrowLeft");
  keyDown(handle("End date"), "End");
  expect(periodValues()).toMatchObject({ end_month: 12, end_day: 31 });
  expect(handle("Start date").getAttribute("aria-valuetext")).toBe("1 January");
});

test("a date handle moved past the other by key gives a period across the new year", () => {
  renderPeriod();
  keyDown(handle("Start date"), "ArrowRight");
  expect(periodValues()).toMatchObject({ start_month: 12, start_day: 22, end_month: 12, end_day: 21 });
  expect(rangePiecesIn(strips()[0])).toBe(2);
  expect(words().textContent).toBe(`22 Dec to 21 Dec, 10 to 14${NBSP}h`);
});

test("arrows move an hour handle an hour, Page Up and Page Down six hours; past the end hour on one date the end date moves to the next day", () => {
  renderPeriod();
  keyDown(handle("End hour"), "ArrowRight");
  expect(periodValues()).toMatchObject({ end_hour: 15 });
  keyDown(handle("Start hour"), "PageDown");
  expect(periodValues()).toMatchObject({ start_hour: 4 });
  keyDown(handle("Start hour"), "End");
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 23, end_day: 22, end_hour: 15 });
  expect(words().textContent).toBe(`21 to 22 Dec, 23 to 15${NBSP}h`);
  keyDown(handle("End hour"), "Home");
  expect(periodValues()).toMatchObject({ end_hour: 0, end_day: 22 });
});

test("on 31 December, hours across midnight end on 1 January", () => {
  renderPeriod(form({ ...WINTER_DAY, start_day: 31, end_day: 31 }));
  keyDown(handle("Start hour"), "End");
  expect(periodValues()).toEqual({ start_month: 12, start_day: 31, start_hour: 23, end_month: 1, end_day: 1, end_hour: 14 });
  expect(words().textContent).toBe(`31 Dec to 1 Jan, 23 to 14${NBSP}h`);
});

test("one hour on one date stays as it is", () => {
  renderPeriod();
  for (let step = 0; step < 4; step++) keyDown(handle("End hour"), "ArrowLeft");
  expect(periodValues()).toEqual({ ...WINTER_DAY, end_hour: 10 });
  expect(words().textContent).toBe(`21 Dec, 10 to 10${NBSP}h`);
});

test("the presets set the dates and keep the hours; the one the dates match shows as chosen", () => {
  renderPeriod(form({ ...WINTER_DAY, start_hour: 7, end_hour: 19 }));
  expect(presetButton("21 December").getAttribute("aria-pressed")).toBe("true");
  click(presetButton("Heating season, October to April"));
  expect(periodValues()).toEqual({ start_month: 10, start_day: 1, start_hour: 7, end_month: 4, end_day: 30, end_hour: 19 });
  expect(presetButton("Heating season, October to April").getAttribute("aria-pressed")).toBe("true");
  expect(presetButton("21 December").getAttribute("aria-pressed")).toBe("false");
  click(presetButton("Whole year"));
  expect(periodValues()).toEqual({ start_month: 1, start_day: 1, start_hour: 7, end_month: 12, end_day: 31, end_hour: 19 });
  click(presetButton("21 June"));
  expect(words().textContent).toBe(`21 Jun, 7 to 19${NBSP}h`);
});

test("a preset of one date while the hours cross midnight gives one night", () => {
  renderPeriod(form({ start_month: 10, start_day: 1, start_hour: 22, end_month: 4, end_day: 30, end_hour: 2 }));
  click(presetButton("21 December"));
  expect(periodValues()).toEqual({ start_month: 12, start_day: 21, start_hour: 22, end_month: 12, end_day: 22, end_hour: 2 });
  expect(presetButton("21 December").getAttribute("aria-pressed")).toBe("true");
});

test("typed across the new year and across midnight: the words open the exact fields; a typed number is sent when its field is left (Review Focus 4)", () => {
  renderPeriod();
  expect(words().getAttribute("aria-expanded")).toBe("false");
  click(words());
  expect(words().getAttribute("aria-expanded")).toBe("true");
  typeInto(typedMonth("Start month"), "10");
  typeInto(typedField("Start day"), "1");
  leave(typedField("Start day"));
  typeInto(typedMonth("End month"), "4");
  typeInto(typedField("End day"), "30");
  leave(typedField("End day"));
  // The end hour on its way to 2 passes nothing on until the field is left.
  typeInto(typedField("Start hour, typed"), "2");
  typeInto(typedField("Start hour, typed"), "22");
  leave(typedField("Start hour, typed"));
  typeInto(typedField("End hour, typed"), "2");
  leave(typedField("End hour, typed"));
  expect(periodValues()).toEqual({ start_month: 10, start_day: 1, start_hour: 22, end_month: 4, end_day: 30, end_hour: 2 });
  expect(words().textContent).toBe(`1 Oct to 30 Apr, 22 to 2${NBSP}h`);
});

test("typed hours across midnight on one date: the end date moves to the next day; a value on the way does not move it", () => {
  renderPeriod();
  click(words());
  // On the way from 14 to 18, the end hour reads 1 (before 10): nothing is sent until the field is left.
  typeInto(typedField("End hour, typed"), "1");
  typeInto(typedField("End hour, typed"), "18");
  leave(typedField("End hour, typed"));
  expect(changes).toEqual([{ end_hour: 18 }]);
  typeInto(typedField("Start hour, typed"), "22");
  act(() => { typedField("Start hour, typed").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 22, end_day: 22, end_hour: 18 });
  expect(typedField("End day").value).toBe("22");
});

test("31 February cannot be produced: a month change holds the day to its length, and a typed day past it is refused", () => {
  renderPeriod(form({ ...WINTER_DAY, start_month: 1, start_day: 31 }));
  click(words());
  typeInto(typedMonth("Start month"), "2");
  expect(periodValues()).toMatchObject({ start_month: 2, start_day: 28 });
  typeInto(typedField("Start day"), "31");
  leave(typedField("Start day"));
  expect(rendered!.container.querySelector(".setting-error")!.textContent).toBe("Use 1 to 28.");
  expect(periodValues()).toMatchObject({ start_month: 2, start_day: 28 });
  // Page Up from 31 January lands on 28 February.
  rendered!.unmount();
  renderPeriod(form({ ...WINTER_DAY, start_month: 1, start_day: 31 }));
  keyDown(handle("Start date"), "PageUp");
  expect(periodValues()).toMatchObject({ start_month: 2, start_day: 28 });
});

test("an error of the period marks its handles and strips, and is said under the control", () => {
  const refused = formReducer(form(), { type: "save_rejected", reply: { field_errors: [{ field: "start_day", message: "Input should be less than or equal to 31" }], grid_plan: null } });
  renderPeriod(refused);
  const error = rendered!.container.querySelector(".setting-error")!;
  expect(error.textContent).toContain("Input should be less than or equal to 31");
  expect(handle("Start date").getAttribute("aria-invalid")).toBe("true");
  expect(handle("End hour").getAttribute("aria-describedby")).toBe(error.id);
  expect(strips().map((strip) => strip.dataset.invalid)).toEqual(["true", "true"]);
});

test("disabled (the carving lock): no key, drag or preset changes the period", () => {
  renderPeriod(form(), true);
  expect(handle("Start date").getAttribute("aria-disabled")).toBe("true");
  expect(handle("Start date").tabIndex).toBe(-1);
  keyDown(handle("Start date"), "ArrowLeft");
  drag(strips()[1], 100, 225);
  expect(presetButton("Whole year").disabled).toBe(true);
  expect(words().disabled).toBe(true);
  expect(changes).toEqual([]);
});

test("a period not set yet says so; a first change sends all six settings", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={periodView()} form={form({}, [{ ...MODES[0], starting_values: {} }])} onChange={onChange} />);
  expect(words().textContent).toBe("Not set yet");
  expect([...rendered.container.querySelectorAll(".period-preset")].map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
  click(presetButton("21 December"));
  expect(onChange).toHaveBeenLastCalledWith({ start_month: 12, start_day: 21, start_hour: 0, end_month: 12, end_day: 21, end_hour: 23 });
});

test("a period stored as one date with hours across midnight is shown as the engine runs it, every night, and not written until changed", () => {
  renderPeriod(form({ start_month: 12, start_day: 21, start_hour: 22, end_month: 12, end_day: 21, end_hour: 2 }));
  expect(words().textContent).toBe(`Every night, 22 to 2${NBSP}h`);
  const yearRange = strips()[0].querySelector<HTMLElement>(".period-range")!;
  expect(rangePiecesIn(strips()[0])).toBe(1);
  expect([yearRange.style.getPropertyValue("--range-start"), yearRange.style.getPropertyValue("--range-end")]).toEqual(["0", "1"]);
  expect([...rendered!.container.querySelectorAll(".period-preset")].map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
  expect(changes).toEqual([]);
  // The next change applies the rule: one night.
  keyDown(handle("End hour"), "ArrowRight");
  expect(changes).toEqual([{ end_day: 22, end_hour: 3 }]);
  expect(words().textContent).toBe(`21 to 22 Dec, 22 to 3${NBSP}h`);
});

test("the typed hour fields are named apart from the hour handles", () => {
  renderPeriod();
  click(words());
  const names = [...rendered!.container.querySelectorAll("[aria-label]")].map((element) => element.getAttribute("aria-label"));
  expect(names.filter((name) => name!.startsWith("Start hour"))).toEqual(["Start hour", "Start hour, typed"]);
  expect(names.filter((name) => name!.startsWith("End hour"))).toEqual(["End hour", "End hour, typed"]);
});

test("a typed value is sent when the typed fields close without the field being left", () => {
  renderPeriod();
  click(words());
  typeInto(typedField("End hour, typed"), "18");
  expect(changes).toEqual([]);
  click(words());
  expect(rendered!.container.querySelector(".setting-period")).toBeNull();
  expect(changes).toEqual([{ end_hour: 18 }]);
  expect(words().textContent).toBe(`21 Dec, 10 to 18${NBSP}h`);
});

test("the tooltip writes the default period in the same words as the control", () => {
  renderPeriod();
  click(rendered!.container.querySelector<HTMLButtonElement>("button.setting-info")!);
  expect(rendered!.container.querySelector("[role='tooltip']")!.textContent).toContain(`default 21 Dec, 10 to 14${NBSP}h`);
});

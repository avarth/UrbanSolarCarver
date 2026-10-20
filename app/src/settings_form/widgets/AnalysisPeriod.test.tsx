import { act, useReducer } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../../api_client/client";
import { addStyleSheetForTest, click, renderForTest, type RenderedOverlay } from "../../viewer_overlays/render_for_test";
import type { ColdPeriodState, Hemisphere } from "../analysis_period";
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
                             score_kind: "violation_count", weight_unit: "", score_unit: "", starting_values: WINTER_DAY }];
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
function Period({ start, disabled = false, coldPeriod = null, hemisphere }: { start: FormState; disabled?: boolean; coldPeriod?: ColdPeriodState | null;
                                                                                hemisphere?: Hemisphere }) {
  const [state, dispatch] = useReducer(formReducer, start);
  latest = state;
  return <SettingField view={periodView()} form={state} disabled={disabled} extras={{ coldPeriod, hemisphere }}
                       onChange={(values) => { changes.push(values); dispatch({ type: "values_changed", values }); }} />;
}

function renderPeriod(start: FormState = form(), disabled = false, coldPeriod: ColdPeriodState | null = null, hemisphere?: Hemisphere) {
  changes = [];
  rendered = renderForTest(<Period start={start} disabled={disabled} coldPeriod={coldPeriod} hemisphere={hemisphere} />);
  // jsdom lays nothing out: the year strip is 365 px wide (1 px a day), the hour strip 240 px (10 px an hour).
  const [yearStrip, hourStrip] = strips();
  for (const [strip, width] of [[yearStrip, 365], [hourStrip, 240]] as const) {
    strip.getBoundingClientRect = () => ({ left: 0, width, top: 0, height: 26, right: width, bottom: 26, x: 0, y: 0, toJSON: () => ({}) });
  }
}

const strips = () => [...rendered!.container.querySelectorAll<HTMLElement>(".scale-strip")];
const handle = (name: string) => rendered!.container.querySelector<HTMLElement>(`[role='slider'][aria-label='${name}']`)!;
/** The values over the handles: the start and end date, then the start and end hour. */
const bubbles = () => [...rendered!.container.querySelectorAll(".scale-strip-bubble")].map((bubble) => bubble.textContent);
const note = () => rendered!.container.querySelector(".period-control > .setting-note")?.textContent ?? null;
const periodValues = () => Object.fromEntries(Object.keys(WINTER_DAY).map((name) => [name, shownValue(latest!, name)]));
const rangePiecesIn = (strip: HTMLElement) => strip.querySelectorAll(".scale-strip-range").length;

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
const presetButton = (text: string) => [...rendered!.container.querySelectorAll<HTMLButtonElement>(".period-preset")].find((button) => button.textContent === text)!;

test("a year strip and an hour strip with two handles each, named apart, saying their values, which the bubbles over them show", () => {
  renderPeriod();
  expect(strips()).toHaveLength(2);
  expect(strips().map((strip) => strip.querySelector(".scale-strip-cells")!.textContent)).toEqual(["JFMAMJJASOND", "061218"]);
  const spoken = ["Start date", "End date", "Start hour", "End hour"].map((name) => handle(name).getAttribute("aria-valuetext"));
  expect(spoken).toEqual(["21 December", "21 December", `10${NBSP}h`, `14${NBSP}h`]);
  for (const name of ["Start date", "End date", "Start hour", "End hour"]) expect(handle(name).tabIndex).toBe(0);
  expect(bubbles()).toEqual(["21 Dec", "21 Dec", `10${NBSP}h`, `14${NBSP}h`]);
  // No period in words to open typed fields, and no note under a period that is set.
  expect(rendered!.container.querySelector(".period-words")).toBeNull();
  expect(rendered!.container.querySelectorAll("input, select")).toHaveLength(0);
  expect(note()).toBeNull();
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
  expect(bubbles().slice(0, 2)).toEqual(["1 Oct", "30 Apr"]);
  expect(rangePiecesIn(yearStrip)).toBe(2);
});

test("dragged across midnight on one date: the end date becomes the next day in the same change, and its bubble says so (Review Focus 4)", () => {
  renderPeriod();
  const [, hourStrip] = strips();
  pointer(hourStrip, "pointerdown", 100);           // the start hour, 10 h
  pointer(hourStrip, "pointermove", 225);           // 22 h
  expect(bubbles()).toEqual(["21 Dec", "22 Dec", `22${NBSP}h`, `14${NBSP}h`]);
  expect(changes).toEqual([]);                      // nothing is sent until the release
  pointer(hourStrip, "pointerup", 225);
  expect(changes).toEqual([{ start_hour: 22, end_day: 22 }]);
  drag(hourStrip, 150, 60, 25);                     // the end hour, drawn at the end of 14 h, to 2 h
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 22, end_day: 22, end_hour: 2 });
  expect(bubbles()).toEqual(["21 Dec", "22 Dec", `22${NBSP}h`, `2${NBSP}h`]);
  expect(rangePiecesIn(hourStrip)).toBe(2);
  // Hours that stop crossing midnight leave the dates as they are.
  drag(hourStrip, 225, 125);
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 12, end_day: 22, end_hour: 2 });
  drag(hourStrip, 30, 145);
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 12, end_day: 22, end_hour: 14 });
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
  expect(bubbles().slice(0, 2)).toEqual(["22 Dec", "21 Dec"]);
});

test("arrows move an hour handle an hour, Page Up and Page Down six hours; past the end hour on one date the end date moves to the next day", () => {
  renderPeriod();
  keyDown(handle("End hour"), "ArrowRight");
  expect(periodValues()).toMatchObject({ end_hour: 15 });
  keyDown(handle("Start hour"), "PageDown");
  expect(periodValues()).toMatchObject({ start_hour: 4 });
  keyDown(handle("Start hour"), "End");
  expect(periodValues()).toEqual({ ...WINTER_DAY, start_hour: 23, end_day: 22, end_hour: 15 });
  expect(bubbles()).toEqual(["21 Dec", "22 Dec", `23${NBSP}h`, `15${NBSP}h`]);
  keyDown(handle("End hour"), "Home");
  expect(periodValues()).toMatchObject({ end_hour: 0, end_day: 22 });
});

test("on 31 December, hours across midnight end on 1 January", () => {
  renderPeriod(form({ ...WINTER_DAY, start_day: 31, end_day: 31 }));
  keyDown(handle("Start hour"), "End");
  expect(periodValues()).toEqual({ start_month: 12, start_day: 31, start_hour: 23, end_month: 1, end_day: 1, end_hour: 14 });
  expect(bubbles().slice(0, 2)).toEqual(["31 Dec", "1 Jan"]);
});

test("one hour on one date stays as it is", () => {
  renderPeriod();
  for (let step = 0; step < 4; step++) keyDown(handle("End hour"), "ArrowLeft");
  expect(periodValues()).toEqual({ ...WINTER_DAY, end_hour: 10 });
  expect(bubbles()).toEqual(["21 Dec", "21 Dec", `10${NBSP}h`, `10${NBSP}h`]);
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
  expect(bubbles()).toEqual(["21 Jun", "21 Jun", `7${NBSP}h`, `19${NBSP}h`]);
});

test("with a weather file in the southern hemisphere the heating season preset is April to October", () => {
  renderPeriod(form({ ...WINTER_DAY, start_hour: 7, end_hour: 19 }), false, null, "southern");
  expect(presetButton("Heating season, October to April")).toBeUndefined();
  click(presetButton("Heating season, April to October"));
  expect(periodValues()).toEqual({ start_month: 4, start_day: 1, start_hour: 7, end_month: 10, end_day: 31, end_hour: 19 });
  expect(presetButton("Heating season, April to October").getAttribute("aria-pressed")).toBe("true");
  rendered!.unmount();
  renderPeriod(form(), false, null, "northern");
  expect(presetButton("Heating season, October to April")).toBeDefined();
});

test("a preset of one date while the hours cross midnight gives one night", () => {
  renderPeriod(form({ start_month: 10, start_day: 1, start_hour: 22, end_month: 4, end_day: 30, end_hour: 2 }));
  click(presetButton("21 December"));
  expect(periodValues()).toEqual({ start_month: 12, start_day: 21, start_hour: 22, end_month: 12, end_day: 22, end_hour: 2 });
  expect(presetButton("21 December").getAttribute("aria-pressed")).toBe("true");
});

test("Page Up from 31 January lands on 28 February: no key gives 31 February", () => {
  renderPeriod(form({ ...WINTER_DAY, start_month: 1, start_day: 31 }));
  keyDown(handle("Start date"), "PageUp");
  expect(periodValues()).toMatchObject({ start_month: 2, start_day: 28 });
  expect(bubbles()[0]).toBe("28 Feb");
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
  expect(changes).toEqual([]);
});

test("a period not set yet says so under the strips; a first change sends all six settings", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={periodView()} form={form({}, [{ ...MODES[0], starting_values: {} }])} onChange={onChange} />);
  expect(note()).toBe("Not set yet");
  expect([...rendered.container.querySelectorAll(".period-preset")].map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
  click(presetButton("21 December"));
  expect(onChange).toHaveBeenLastCalledWith({ start_month: 12, start_day: 21, start_hour: 0, end_month: 12, end_day: 21, end_hour: 23 });
});

test("a period stored as one date with hours across midnight is shown as the engine runs it, every night, and not written until changed", () => {
  renderPeriod(form({ start_month: 12, start_day: 21, start_hour: 22, end_month: 12, end_day: 21, end_hour: 2 }));
  expect(note()).toBe(`Every day, 22 to 2${NBSP}h: the hours cross midnight on one date, which the engine runs on every day of the year. ` +
                      "The next change makes it one night.");
  const yearRange = strips()[0].querySelector<HTMLElement>(".scale-strip-range")!;
  expect(rangePiecesIn(strips()[0])).toBe(1);
  expect([yearRange.style.getPropertyValue("--range-start"), yearRange.style.getPropertyValue("--range-end")]).toEqual(["0", "1"]);
  expect([...rendered!.container.querySelectorAll(".period-preset")].map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
  expect(changes).toEqual([]);
  // The next change applies the rule: one night.
  keyDown(handle("End hour"), "ArrowRight");
  expect(changes).toEqual([{ end_day: 22, end_hour: 3 }]);
  expect(bubbles()).toEqual(["21 Dec", "22 Dec", `22${NBSP}h`, `3${NBSP}h`]);
  expect(note()).toBeNull();
});

test("the tooltip writes the default period in the same words as the step summary", () => {
  renderPeriod();
  click(rendered!.container.querySelector<HTMLButtonElement>("button.setting-info")!);
  expect(rendered!.container.querySelector("[role='tooltip']")!.textContent).toContain(`default 21 Dec, 10 to 14${NBSP}h`);
});


const COLD_PERIOD = "Cold period from the weather file";
const coldLine = () => document.getElementById(presetButton(COLD_PERIOD).getAttribute("aria-describedby")!)!.textContent;

test("the cold period preset sets the dates the weather file gives, keeps the hours and shows as chosen", () => {
  renderPeriod(form(), false, { kind: "found", dates: { startMonth: 9, startDay: 30, endMonth: 5, endDay: 15 }, baseTemperature: 13 });
  expect(coldLine()).toBe(`Cold period of the weather file, where the mean of the month around each day is below 13${NBSP}°C: 30 Sep to 15 May.`);
  expect(presetButton(COLD_PERIOD).getAttribute("aria-pressed")).toBe("false");
  click(presetButton(COLD_PERIOD));
  expect(periodValues()).toEqual({ start_month: 9, start_day: 30, start_hour: 10, end_month: 5, end_day: 15, end_hour: 14 });
  expect(presetButton(COLD_PERIOD).getAttribute("aria-pressed")).toBe("true");
  expect(bubbles().slice(0, 2)).toEqual(["30 Sep", "15 May"]);
});

test("the cold period preset waits for the weather file, or says no day is cold enough, and sets nothing", () => {
  renderPeriod(form(), false, { kind: "needs_weather_file" });
  expect(presetButton(COLD_PERIOD).getAttribute("aria-disabled")).toBe("true");      // still in the tab order, with its line
  expect(coldLine()).toBe("Add a weather file to find its cold period.");
  click(presetButton(COLD_PERIOD));
  rendered!.unmount();
  renderPeriod(form(), false, { kind: "none", baseTemperature: 9.5 });
  expect(presetButton(COLD_PERIOD).getAttribute("aria-disabled")).toBe("true");
  expect(coldLine()).toBe(`No month-long stretch of the weather file has a mean below 9.5${NBSP}°C (balance temperature minus dead band).`);
  click(presetButton(COLD_PERIOD));
  expect(changes).toEqual([]);
});

const FOUND: ColdPeriodState = { kind: "found", dates: { startMonth: 9, startDay: 21, endMonth: 5, endDay: 25 }, baseTemperature: 14.5 };
const FOUND_TEXT = `Cold period of the weather file, where the mean of the month around each day is below 14.5${NBSP}°C: 21 Sep to 25 May.`;
const coldTooltip = () => rendered!.container.querySelector<HTMLElement>(".period-preset-tooltip");

// The pointer moves onto *target* from *from* (React's mouse enter and leave are read from mouseover and mouseout).
function movePointer(from: Element, target: Element) {
  act(() => {
    from.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: target }));
    target.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, relatedTarget: from }));
  });
}

test("the cold period line is no longer always shown: it is the preset's tooltip on hover, and its description for a screen reader", () => {
  const outside = document.createElement("button");
  document.body.appendChild(outside);
  renderPeriod(form(), false, FOUND);
  expect(coldTooltip()).toBeNull();
  expect(rendered!.container.querySelector("p.setting-note")).toBeNull();
  expect(coldLine()).toBe(FOUND_TEXT);
  movePointer(outside, presetButton(COLD_PERIOD));
  expect(coldTooltip()!.textContent).toBe(FOUND_TEXT);
  expect(coldTooltip()!.getAttribute("role")).toBe("tooltip");
  expect(coldTooltip()!.getAttribute("aria-hidden")).toBe("true");          // seen, not read: the description reads it
  movePointer(presetButton(COLD_PERIOD), outside);
  expect(coldTooltip()).toBeNull();
  outside.remove();
});

test("the keyboard focus on the cold period preset shows its tooltip, Escape closes it; the focus of a pointer press does not", () => {
  renderPeriod(form(), false, FOUND);
  act(() => {
    presetButton(COLD_PERIOD).dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    presetButton(COLD_PERIOD).focus();
  });
  expect(coldTooltip()).toBeNull();
  click(presetButton(COLD_PERIOD));
  expect(periodValues()).toMatchObject({ start_month: 9, start_day: 21, end_month: 5, end_day: 25 });
  act(() => presetButton(COLD_PERIOD).blur());
  act(() => presetButton(COLD_PERIOD).focus());
  expect(coldTooltip()!.textContent).toBe(FOUND_TEXT);
  keyDown(presetButton(COLD_PERIOD), "Escape");
  expect(coldTooltip()).toBeNull();
});

test("the reasons the cold period preset cannot be used yet are in its tooltip too", () => {
  for (const [state, text] of [
    [{ kind: "needs_weather_file" }, "Add a weather file to find its cold period."],
    [{ kind: "finding" }, "Finding the cold period of the weather file."],
    [{ kind: "failed", reason: "The weather file cannot be read." }, "The cold period cannot be found. The weather file cannot be read."],
  ] as const) {
    renderPeriod(form(), false, state);
    act(() => presetButton(COLD_PERIOD).focus());
    expect(coldTooltip()!.textContent).toBe(text);
    expect(coldLine()).toBe(text);
    rendered!.unmount();
  }
  rendered = null;
});

test("the cold period tooltip lets the pointer through, so it never takes a click meant for what lies under it", () => {
  const removeStyles = [addStyleSheetForTest("src/settings_form/settings_form.css")];
  renderPeriod(form(), false, FOUND);
  act(() => presetButton(COLD_PERIOD).focus());
  expect(getComputedStyle(coldTooltip()!).pointerEvents).toBe("none");
  removeStyles.forEach((remove) => remove());
});

test("a mode without a cold period has no such preset", () => {
  renderPeriod();
  expect(presetButton(COLD_PERIOD)).toBeUndefined();
});

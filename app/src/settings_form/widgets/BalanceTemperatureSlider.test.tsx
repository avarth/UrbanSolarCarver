import { readFileSync } from "node:fs";
import { act, useReducer } from "react";
import { afterEach, expect, test } from "vitest";
import type { ModeInfo } from "../../api_client/client";
import { renderForTest, type RenderedOverlay } from "../../viewer_overlays/render_for_test";
import { formReducer, initialFormState, type FormState } from "../form_state";
import { settingsForStep } from "../presentation";
import { SettingField } from "../SettingField";

// The engine's balance settings, as GET schema gives them (pydantic_schemas.py): any temperature, a dead band of 0 or more.
const SCHEMA = {
  properties: {
    mode: { default: "benefit", type: "string" },
    balance_temperature: { default: 15.0, type: "number" },
    balance_offset: { default: 2.0, type: "number", minimum: 0 },
    include_harm: { default: false, type: "boolean" },
  },
};
const MODES: ModeInfo[] = [{ name: "benefit", description: "", needs_epw: true, needs_period: true, experimental: false,
                             score_kind: "weighted_sum", weight_unit: "", starting_values: {} }];

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function form(settings: Record<string, unknown> = {}): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "benefit", ...settings }, gridPlan: null });
}

const balanceView = () => settingsForStep("settings", "benefit").flatMap((group) => group.essential).find((view) => view.name === "balance_temperature")!;

function renderBalance(state: FormState, onChange: (values: Record<string, unknown>) => void = () => {}) {
  rendered = renderForTest(<SettingField view={balanceView()} form={state} onChange={onChange} />);
}

/** Sets *text* as the value the way the browser does when the user types or drags, so React's change handler runs. */
function setValue(field: HTMLInputElement, text: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const handle = (name: string) => rendered!.container.querySelector<HTMLInputElement>(`input[type='range'][aria-label='${name}']`)!;
const number = (name: string) => rendered!.container.querySelector<HTMLInputElement>(`input[type='number'][aria-label='${name}']`)!;
const lowerHandle = () => handle("Counts below"), upperHandle = () => handle("Too warm above");
const lowerNumber = () => number("Counts below"), upperNumber = () => number("Too warm above");

// The form behind the widget, as the app holds it: every change goes through the form's reducer.
let latest: FormState | null = null;
function Balance({ start }: { start: FormState }) {
  const [state, dispatch] = useReducer(formReducer, start);
  latest = state;
  return <SettingField view={balanceView()} form={state} onChange={(values) => dispatch({ type: "values_changed", values })} />;
}

const press = (element: HTMLInputElement, type: "pointerdown" | "pointerup") => act(() => { element.dispatchEvent(new Event(type, { bubbles: true })); });
/** Presses *key* on *element* with the focus on it; returns whether the widget kept the browser from stepping *element*. */
function keyDown(element: HTMLInputElement, key: string): boolean {
  act(() => element.focus());
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  act(() => { element.dispatchEvent(event); });
  return event.defaultPrevented;
}

test("one track from 10 to 30 °C whose two handles are the ends of the dead band: balance temperature minus and plus the dead band", () => {
  renderBalance(form());
  for (const end of [lowerHandle(), upperHandle()]) expect([end.min, end.max]).toEqual(["10", "30"]);
  expect([lowerHandle().value, upperHandle().value]).toEqual(["13", "17"]);
  expect(lowerHandle().getAttribute("aria-valuetext")).toBe("13 °C");
  expect(upperHandle().getAttribute("aria-valuetext")).toBe("17 °C");
  expect(rendered!.container.querySelector(".balance-dead-band-label")!.textContent).toBe("Dead band");
  expect([lowerNumber().value, upperNumber().value]).toEqual(["13", "17"]);
  const group = rendered!.container.querySelector("[role='group']")!;
  expect(group.getAttribute("aria-labelledby")).toBe(rendered!.container.querySelector(".setting-label")!.id);
});

test("each handle moves its own end; the engine gets the middle and half the width, and an end cannot pass the other", () => {
  rendered = renderForTest(<Balance start={form()} />);
  setValue(lowerHandle(), "11");
  expect(latest!.userValues).toEqual({ balance_temperature: 14, balance_offset: 3 });
  setValue(upperHandle(), "22");
  expect(latest!.userValues).toEqual({ balance_temperature: 16.5, balance_offset: 5.5 });
  setValue(lowerHandle(), "25");                          // past the upper end: the band closes there
  expect(latest!.userValues).toEqual({ balance_temperature: 22, balance_offset: 0 });
});

test("both ends can be typed; one outside 10 to 30 °C is taken and its handle stays at the end of the track", () => {
  rendered = renderForTest(<Balance start={form()} />);
  setValue(upperNumber(), "35");
  expect(latest!.userValues).toEqual({ balance_temperature: 24, balance_offset: 11 });
  expect(upperHandle().value).toBe("30");
  expect(upperHandle().getAttribute("aria-valuetext")).toBe("35 °C");
  setValue(lowerNumber(), "40");                          // above the upper end: the band closes at 40
  expect(latest!.userValues).toEqual({ balance_temperature: 40, balance_offset: 0 });
});

test("an error of either setting marks both ends, which are both made of the two settings", () => {
  const refused = formReducer(form(), { type: "save_rejected", reply: { field_errors: [{ field: "balance_offset", message: "Input should be greater than or equal to 0" }], grid_plan: null } });
  renderBalance(refused);
  const error = rendered!.container.querySelector(".setting-error")!;
  expect(error.textContent).toContain("Input should be greater than or equal to 0");
  expect([lowerHandle(), upperHandle(), lowerNumber(), upperNumber()].map((input) => input.getAttribute("aria-invalid"))).toEqual(["true", "true", "true", "true"]);
  expect(lowerHandle().getAttribute("aria-describedby")).toBe(error.id);
});

test("both handles and both number fields are disabled while the field is", () => {
  rendered = renderForTest(<SettingField view={balanceView()} form={form()} onChange={() => {}} disabled />);
  expect([...rendered.container.querySelectorAll<HTMLInputElement>("input")].map((input) => input.disabled)).toEqual([true, true, true, true]);
});

test("on one spot (a dead band of 0) the direction of the move picks the end, for a whole drag", () => {
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  expect(lowerHandle().classList).toContain("balance-handle-on-top");
  expect(rendered.container.querySelector(".balance-dead-band-label")).toBeNull();      // no band to name
  press(lowerHandle(), "pointerdown");
  setValue(lowerHandle(), "16");
  setValue(lowerHandle(), "15.5");                        // back toward the spot: still the upper end of this drag
  press(lowerHandle(), "pointerup");
  expect(latest!.userValues).toEqual({ balance_temperature: 15.25, balance_offset: 0.25 });
  rendered.unmount();
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  press(lowerHandle(), "pointerdown");
  setValue(lowerHandle(), "13");
  press(lowerHandle(), "pointerup");
  expect(latest!.userValues).toEqual({ balance_temperature: 14, balance_offset: 1 });
});

test("on one spot, a key toward the other end moves the focus to that end's handle, which steps; a key toward its own end steps it", () => {
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  expect(keyDown(lowerHandle(), "ArrowRight")).toBe(true);           // the lower handle, on top, does not step
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 15.25, balance_offset: 0.25 });
  expect(keyDown(upperHandle(), "ArrowRight")).toBe(false);          // off the spot: the browser steps the focused handle
  rendered.unmount();
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  expect(keyDown(lowerHandle(), "ArrowLeft")).toBe(false);           // its own end: the browser steps it
  expect(document.activeElement).toBe(lowerHandle());
  setValue(lowerHandle(), "14.5");
  expect(latest!.userValues).toEqual({ balance_temperature: 14.75, balance_offset: 0.25 });
});

test("on one spot, Home and End pick the end by their direction too: Home the lower end, End the upper one", () => {
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);           // both ends at 15
  expect(keyDown(upperHandle(), "Home")).toBe(true);
  expect(document.activeElement).toBe(lowerHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 12.5, balance_offset: 2.5 });             // 10 to 15
  rendered.unmount();
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  expect(keyDown(lowerHandle(), "End")).toBe(true);
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 22.5, balance_offset: 7.5 });             // 15 to 30
  expect(keyDown(upperHandle(), "Home")).toBe(false);                                                  // off the spot: the browser's
});

test("both ends pinned at an end of the track step back from it", () => {
  rendered = renderForTest(<Balance start={form({ balance_temperature: 35, balance_offset: 0 })} />);    // both at 35, drawn at 30
  expect(keyDown(upperHandle(), "ArrowLeft")).toBe(true);
  expect(document.activeElement).toBe(lowerHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 32.25, balance_offset: 2.75 });             // 29.5 to 35
  rendered.unmount();
  rendered = renderForTest(<Balance start={form({ balance_temperature: 5, balance_offset: 0 })} />);     // both at 5, drawn at 10
  expect(keyDown(lowerHandle(), "ArrowRight")).toBe(true);
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 7.75, balance_offset: 2.75 });              // 5 to 10.5
});

test("the lower handle comes first, as on the track and in the number fields, so Tab reaches the ends in their order", () => {
  renderBalance(form());
  const handles = [...rendered!.container.querySelectorAll<HTMLInputElement>("input[type='range']")];
  expect(handles.map((input) => input.getAttribute("aria-label"))).toEqual(["Counts below", "Too warm above"]);
});

test("without harm counted the upper end does nothing: it is muted, with a note its handle and number field name", () => {
  renderBalance(form());
  const note = rendered!.container.querySelector<HTMLElement>(".balance-end-note")!;
  expect(note.textContent).toBe("(only with harm counted)");
  for (const input of [upperHandle(), upperNumber()]) expect(input.getAttribute("aria-describedby")).toContain(note.id);
  expect(upperNumber().closest(".setting-control")!.classList).toContain("balance-end-muted");
  expect(upperHandle().classList).toContain("balance-handle-muted");
  rendered!.unmount();
  renderBalance(form({ include_harm: true }));
  expect(rendered!.container.querySelector(".balance-end-note")).toBeNull();
  expect(upperHandle().classList).not.toContain("balance-handle-muted");
});

test("an invalid balance handle is marked on its own handle, not on the track the two share, and keeps its focus ring", () => {
  const formCss = readFileSync("src/settings_form/settings_form.css", "utf8");
  expect(formCss).toMatch(/\.balance-handle\[aria-invalid="true"\]::-webkit-slider-thumb\s*{[^}]*box-shadow: 0 0 0 2px var\(--colour-error\)/);
  expect(formCss).toMatch(/\.balance-handle\[aria-invalid="true"\]::-moz-range-thumb\s*{[^}]*box-shadow: 0 0 0 2px var\(--colour-error\)/);
  expect(formCss).not.toMatch(/\.balance-handle\[aria-invalid="true"\][^{]*track/);
});

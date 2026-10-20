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
                             score_kind: "weighted_sum", weight_unit: "", score_unit: "", starting_values: {} }];
const NBSP = " ";
const degrees = (value: number) => `${value}${NBSP}°C`;

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function form(settings: Record<string, unknown> = {}): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "benefit", ...settings }, gridPlan: null });
}

const balanceView = () => settingsForStep("settings", "benefit").flatMap((group) => group.essential).find((view) => view.name === "balance_temperature")!;

// The form behind the widget, as the app holds it: every change goes through the form's reducer.
let latest: FormState | null = null;
function Balance({ start, disabled = false }: { start: FormState; disabled?: boolean }) {
  const [state, dispatch] = useReducer(formReducer, start);
  latest = state;
  return <SettingField view={balanceView()} form={state} disabled={disabled} onChange={(values) => dispatch({ type: "values_changed", values })} />;
}

function renderBalance(start: FormState = form(), disabled = false) {
  rendered = renderForTest(<Balance start={start} disabled={disabled} />);
  // jsdom lays nothing out: the strip is 200 px wide, 10 px a degree from 10 °C at its left end.
  strip().getBoundingClientRect = () => ({ left: 0, width: 200, top: 0, height: 26, right: 200, bottom: 26, x: 0, y: 0, toJSON: () => ({}) });
}

const strip = () => rendered!.container.querySelector<HTMLElement>(".scale-strip")!;
const handle = (name: string) => rendered!.container.querySelector<HTMLElement>(`[role='slider'][aria-label='${name}']`)!;
const lowerHandle = () => handle("Counts below"), upperHandle = () => handle("Too warm above");
const bubbles = () => [...rendered!.container.querySelectorAll(".scale-strip-bubble")].map((bubble) => bubble.textContent);

function pointer(type: "pointerdown" | "pointermove" | "pointerup", clientX: number) {
  act(() => { strip().dispatchEvent(new PointerEvent(type, { bubbles: true, clientX, pointerId: 1, button: 0 })); });
}

/** A drag on the strip from *fromX* through *throughX* to the last of them, released there. */
function drag(fromX: number, ...throughX: number[]) {
  pointer("pointerdown", fromX);
  for (const x of throughX) pointer("pointermove", x);
  pointer("pointerup", throughX.at(-1) ?? fromX);
}

/** Presses *key* on *element* with the focus on it; returns whether the widget took the key. */
function keyDown(element: HTMLElement, key: string): boolean {
  act(() => element.focus());
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  act(() => { element.dispatchEvent(event); });
  return event.defaultPrevented;
}

test("one strip from 10 to 30 °C whose two handles are the ends of the dead band, each with its value in a bubble above it", () => {
  renderBalance();
  for (const end of [lowerHandle(), upperHandle()]) expect([end.getAttribute("aria-valuemin"), end.getAttribute("aria-valuemax")]).toEqual(["10", "30"]);
  expect([lowerHandle().getAttribute("aria-valuenow"), upperHandle().getAttribute("aria-valuenow")]).toEqual(["13", "17"]);
  expect(lowerHandle().getAttribute("aria-valuetext")).toBe(degrees(13));
  expect(upperHandle().getAttribute("aria-valuetext")).toBe(degrees(17));
  expect(bubbles()).toEqual([degrees(13), degrees(17)]);
  // The scale: a tick a degree, labelled every 5 °C, as the hour strip of the analysis period is every 6 h.
  expect(strip().querySelector(".scale-strip-cells")!.textContent).toBe("10152025");
  expect(strip().querySelectorAll(".scale-strip-cell")).toHaveLength(20);
  // The band between the two ends is filled: 13 to 17 °C of 10 to 30 °C.
  const band = strip().querySelector<HTMLElement>(".scale-strip-range")!;
  expect([band.style.getPropertyValue("--range-start"), band.style.getPropertyValue("--range-end")]).toEqual(["0.15", "0.35"]);
  // No label on the band and no number fields.
  expect(rendered!.container.textContent).not.toContain("Dead band");
  expect(rendered!.container.querySelectorAll("input")).toHaveLength(0);
  const group = rendered!.container.querySelector("[role='group']")!;
  expect(group.getAttribute("aria-labelledby")).toBe(rendered!.container.querySelector(".setting-label")!.id);
  // A link to the setting focuses the lower end: the field names it as the input its label targets.
  expect(rendered!.container.querySelector<HTMLElement>("[data-setting='balance_temperature']")!.dataset.inputId).toBe(lowerHandle().id);
});

test("each handle moves its own end; the engine gets the middle and half the width, and an end cannot pass the other", () => {
  renderBalance();
  drag(30, 20, 10);                                       // the lower end, 13 °C, to 11 °C
  expect(latest!.userValues).toEqual({ balance_temperature: 14, balance_offset: 3 });
  drag(70, 120);                                          // the upper end, 17 °C, to 22 °C
  expect(latest!.userValues).toEqual({ balance_temperature: 16.5, balance_offset: 5.5 });
  drag(10, 150);                                          // the lower end past the upper one: the band closes there
  expect(latest!.userValues).toEqual({ balance_temperature: 22, balance_offset: 0 });
  expect(bubbles()).toEqual([degrees(22), degrees(22)]);
});

test("a press on the strip moves the nearer end there, to the step of the track", () => {
  renderBalance();
  drag(162);                                              // 26.2 °C, nearer the upper end: 26 °C
  expect(latest!.userValues).toEqual({ balance_temperature: 19.5, balance_offset: 6.5 });
});

test("an end outside 10 to 30 °C says its value in its bubble, with its handle pinned at the end of the strip", () => {
  renderBalance(form({ balance_temperature: 24, balance_offset: 11 }));       // 13 to 35 °C
  expect(upperHandle().style.getPropertyValue("--handle-position")).toBe("1");
  expect(upperHandle().getAttribute("aria-valuenow")).toBe("30");
  expect(upperHandle().getAttribute("aria-valuetext")).toBe(degrees(35));
  expect(bubbles()).toEqual([degrees(13), degrees(35)]);
  rendered!.unmount();
  renderBalance(form({ balance_temperature: 5, balance_offset: 0.5 }));       // 4.5 to 5.5 °C
  expect(bubbles()).toEqual([degrees(4.5), degrees(5.5)]);
  expect(lowerHandle().style.getPropertyValue("--handle-position")).toBe("0");
});

test("an error of either setting marks both ends, which are both made of the two settings, and the strip", () => {
  const refused = formReducer(form(), { type: "save_rejected", reply: { field_errors: [{ field: "balance_offset", message: "Input should be greater than or equal to 0" }], grid_plan: null } });
  renderBalance(refused);
  const error = rendered!.container.querySelector(".setting-error")!;
  expect(error.textContent).toContain("Input should be greater than or equal to 0");
  expect([lowerHandle(), upperHandle()].map((end) => end.getAttribute("aria-invalid"))).toEqual(["true", "true"]);
  expect(lowerHandle().getAttribute("aria-describedby")).toBe(error.id);
  expect(strip().dataset.invalid).toBe("true");
});

test("disabled (the carving lock): both handles say so and leave the tab order; no key or drag changes the band", () => {
  renderBalance(form(), true);
  for (const end of [lowerHandle(), upperHandle()]) {
    expect(end.getAttribute("aria-disabled")).toBe("true");
    expect(end.tabIndex).toBe(-1);
  }
  keyDown(lowerHandle(), "ArrowLeft");
  drag(30, 10);
  expect(latest!.userValues).toEqual({});
});

test("arrows move an end by the step of the track, Page Up and Page Down by 2 °C, Home and End to the ends of the track", () => {
  renderBalance();
  expect(keyDown(upperHandle(), "ArrowRight")).toBe(true);
  expect(latest!.userValues).toEqual({ balance_temperature: 15.25, balance_offset: 2.25 });            // 13 to 17.5
  keyDown(upperHandle(), "PageUp");
  expect(latest!.userValues).toEqual({ balance_temperature: 16.25, balance_offset: 3.25 });            // 13 to 19.5
  keyDown(lowerHandle(), "PageDown");
  keyDown(lowerHandle(), "ArrowDown");
  expect(latest!.userValues).toEqual({ balance_temperature: 15, balance_offset: 4.5 });                // 10.5 to 19.5
  keyDown(lowerHandle(), "Home");
  keyDown(upperHandle(), "End");
  expect(latest!.userValues).toEqual({ balance_temperature: 20, balance_offset: 10 });                 // 10 to 30
  keyDown(upperHandle(), "Enter");
  expect(latest!.userValues).toEqual({ balance_temperature: 20, balance_offset: 10 });
});

test("on one spot (a dead band of 0) the direction of the move picks the end, for a whole drag", () => {
  renderBalance(form({ balance_offset: 0 }));             // both ends at 15 °C, 50 px
  pointer("pointerdown", 50);
  pointer("pointermove", 60);                              // to the right: the upper end
  pointer("pointermove", 55);                              // back toward the spot: still the upper end of this drag
  pointer("pointerup", 55);
  expect(latest!.userValues).toEqual({ balance_temperature: 15.25, balance_offset: 0.25 });
  rendered!.unmount();
  renderBalance(form({ balance_offset: 0 }));
  drag(50, 30);                                            // to the left: the lower end
  expect(latest!.userValues).toEqual({ balance_temperature: 14, balance_offset: 1 });
});

test("on one spot, a key toward the other end moves the focus to that end's handle, which steps; a key toward its own end steps it", () => {
  renderBalance(form({ balance_offset: 0 }));
  expect(keyDown(lowerHandle(), "ArrowRight")).toBe(true);
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 15.25, balance_offset: 0.25 });
  keyDown(upperHandle(), "ArrowRight");                    // off the spot: the focused handle steps
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 15.5, balance_offset: 0.5 });
  rendered!.unmount();
  renderBalance(form({ balance_offset: 0 }));
  keyDown(lowerHandle(), "ArrowLeft");                     // its own end
  expect(document.activeElement).toBe(lowerHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 14.75, balance_offset: 0.25 });
});

test("on one spot, Home and End pick the end by their direction too: Home the lower end, End the upper one", () => {
  renderBalance(form({ balance_offset: 0 }));             // both ends at 15
  keyDown(upperHandle(), "Home");
  expect(document.activeElement).toBe(lowerHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 12.5, balance_offset: 2.5 });             // 10 to 15
  rendered!.unmount();
  renderBalance(form({ balance_offset: 0 }));
  keyDown(lowerHandle(), "End");
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 22.5, balance_offset: 7.5 });             // 15 to 30
  keyDown(upperHandle(), "Home");                                                                      // off the spot: to the lower end
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 15, balance_offset: 0 });
});

test("both ends pinned at an end of the track step back from it", () => {
  renderBalance(form({ balance_temperature: 35, balance_offset: 0 }));       // both at 35, drawn at 30
  keyDown(upperHandle(), "ArrowLeft");
  expect(document.activeElement).toBe(lowerHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 32.25, balance_offset: 2.75 });             // 29.5 to 35
  rendered!.unmount();
  renderBalance(form({ balance_temperature: 5, balance_offset: 0 }));        // both at 5, drawn at 10
  keyDown(lowerHandle(), "ArrowRight");
  expect(document.activeElement).toBe(upperHandle());
  expect(latest!.userValues).toEqual({ balance_temperature: 7.75, balance_offset: 2.75 });              // 5 to 10.5
});

test("the lower handle comes first, as on the strip, so Tab reaches the ends in their order", () => {
  renderBalance();
  const handles = [...rendered!.container.querySelectorAll("[role='slider']")];
  expect(handles.map((end) => end.getAttribute("aria-label"))).toEqual(["Counts below", "Too warm above"]);
});

test("the upper end looks and reads like the lower one whether or not harm is counted: no note, nothing muted", () => {
  for (const settings of [{}, { include_harm: true }]) {
    renderBalance(form(settings));
    expect(rendered!.container.textContent).not.toContain("harm");
    expect(upperHandle().getAttribute("aria-describedby")).toBe(lowerHandle().getAttribute("aria-describedby"));
    rendered!.unmount();
  }
  rendered = null;
});

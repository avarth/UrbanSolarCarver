import { readFileSync } from "node:fs";
import { act, useReducer } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../../viewer_overlays/render_for_test";
import { formReducer, initialFormState, type FormState } from "../form_state";
import { settingsForStep } from "../presentation";
import { SettingField } from "../SettingField";

// The engine's balance settings, as GET schema gives them (pydantic_schemas.py): any temperature, a dead band of 0 or more.
const SCHEMA = {
  properties: {
    mode: { default: "benefit", type: "string" },
    balance_temperature: { default: 15.0, type: "number" },
    balance_offset: { default: 2.0, type: "number", minimum: 0 },
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

const byName = (name: string) => rendered!.container.querySelector<HTMLInputElement>(`input[aria-label='${name}']`)!;
const balanceHandle = () => rendered!.container.querySelector<HTMLInputElement>("input[type='range'][aria-label='Balance temperature']")!;
const lowerEndHandle = () => byName("Lower end of the dead band");
const balanceNumber = () => rendered!.container.querySelector<HTMLInputElement>("input[type='number'][aria-label='Balance temperature']")!;
const deadBandNumber = () => rendered!.container.querySelector<HTMLInputElement>("input[type='number'][aria-label='Dead band']")!;

test("one track from 10 to 30 °C: the right handle is the balance temperature, the left one the balance temperature minus the dead band", () => {
  renderBalance(form());
  for (const handle of [balanceHandle(), lowerEndHandle()]) expect([handle.min, handle.max]).toEqual(["10", "30"]);
  expect(balanceHandle().value).toBe("15");
  expect(lowerEndHandle().value).toBe("13");
  expect(balanceHandle().getAttribute("aria-valuetext")).toBe("15 °C");
  expect(lowerEndHandle().getAttribute("aria-valuetext")).toBe("13 °C");
  expect(rendered!.container.querySelector(".balance-dead-band-label")!.textContent).toBe("Dead band");
  expect(balanceNumber().value).toBe("15");
  expect(deadBandNumber().value).toBe("2");
  // The handles and the number fields are one group, named by the setting's label.
  const group = rendered!.container.querySelector("[role='group']")!;
  expect(group.getAttribute("aria-labelledby")).toBe(rendered!.container.querySelector(".setting-label")!.id);
});

test("dragging the left handle changes only the dead band, and it cannot pass the right handle", () => {
  const onChange = vi.fn();
  renderBalance(form(), onChange);
  setValue(lowerEndHandle(), "11");
  expect(onChange).toHaveBeenLastCalledWith({ balance_offset: 4 });
  setValue(lowerEndHandle(), "18");
  expect(onChange).toHaveBeenLastCalledWith({ balance_offset: 0 });
  expect(onChange.mock.calls.every(([values]) => !("balance_temperature" in values))).toBe(true);
});

// The form behind the widget, as the app holds it: every change goes through the form's reducer.
let latest: FormState | null = null;
function Balance({ start }: { start: FormState }) {
  const [state, dispatch] = useReducer(formReducer, start);
  latest = state;
  return <SettingField view={balanceView()} form={state} onChange={(values) => dispatch({ type: "values_changed", values })} />;
}

const press = (handle: HTMLInputElement, type: "pointerdown" | "pointerup") => act(() => { handle.dispatchEvent(new Event(type, { bubbles: true })); });

test("dragging the right handle moves the band with it: only the balance temperature changes", () => {
  rendered = renderForTest(<Balance start={form()} />);
  setValue(balanceHandle(), "20");
  expect(latest!.userValues).toEqual({ balance_temperature: 20 });
  expect(lowerEndHandle().value).toBe("18");
  setValue(balanceHandle(), "10.5");
  expect(lowerEndHandle().value).toBe("10");          // 8.5 °C lies off the track: the handle stays at its end
  expect(lowerEndHandle().getAttribute("aria-valuetext")).toBe("8.5 °C");
});

test("both values can be typed; one outside 10 to 30 °C is taken and its handle stays at the end of the track", () => {
  const onChange = vi.fn();
  renderBalance(form(), onChange);
  setValue(balanceNumber(), "35");
  expect(onChange).toHaveBeenLastCalledWith({ balance_temperature: 35 });
  setValue(deadBandNumber(), "3.5");
  expect(onChange).toHaveBeenLastCalledWith({ balance_offset: 3.5 });
  setValue(deadBandNumber(), "-1");
  expect(onChange).toHaveBeenCalledTimes(2);           // the engine needs a dead band of 0 or more
  expect(rendered!.container.querySelector(".setting-error")!.textContent).toBe("Use 0 or more.");
  rendered!.rerender(<SettingField view={balanceView()} form={form({ balance_temperature: 35 })} onChange={onChange} />);
  expect(balanceHandle().value).toBe("30");
  expect(lowerEndHandle().value).toBe("30");
});

test("the dead band has its own tooltip, and its error is shown under the widget", () => {
  const refused = formReducer(form(), { type: "save_rejected", reply: { field_errors: [{ field: "balance_offset", message: "Input should be greater than or equal to 0" }], grid_plan: null } });
  renderBalance(refused);
  const error = rendered!.container.querySelector(".setting-error")!;
  expect(error.textContent).toContain("Input should be greater than or equal to 0");
  expect(deadBandNumber().getAttribute("aria-invalid")).toBe("true");
  expect(lowerEndHandle().getAttribute("aria-describedby")).toBe(error.id);
  const infoButtons = rendered!.container.querySelectorAll<HTMLButtonElement>("button.setting-info");
  expect(infoButtons).toHaveLength(2);
  click(infoButtons[1]);
  expect(rendered!.container.querySelector("[role='tooltip']")!.textContent).toContain("Config name: balance_offset, default 2.0 °C");
});

test("both handles and both number fields are disabled while the field is", () => {
  rendered = renderForTest(<SettingField view={balanceView()} form={form()} onChange={() => {}} disabled />);
  expect([...rendered.container.querySelectorAll<HTMLInputElement>("input")].map((input) => input.disabled)).toEqual([true, true, true, true]);
});

test("on one spot (a dead band of 0) the left handle is on top, and the drag's direction picks the handle", () => {
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  expect(lowerEndHandle().classList).toContain("balance-handle-on-top");
  expect(rendered.container.querySelector(".balance-dead-band-label")).toBeNull();      // no band to name
  // To the right: the balance temperature moves, the band stays 0 wide, for the whole drag.
  press(lowerEndHandle(), "pointerdown");
  setValue(lowerEndHandle(), "17");
  setValue(lowerEndHandle(), "18");
  press(lowerEndHandle(), "pointerup");
  expect(latest!.userValues).toEqual({ balance_temperature: 18, balance_offset: 0 });
  // To the left: the band opens.
  press(lowerEndHandle(), "pointerdown");
  setValue(lowerEndHandle(), "15");
  press(lowerEndHandle(), "pointerup");
  expect(latest!.userValues).toEqual({ balance_temperature: 18, balance_offset: 3 });
  expect(lowerEndHandle().classList).not.toContain("balance-handle-on-top");
});

test("both pinned at the low end (5 °C typed, dead band 2): a drag to the right moves the balance temperature and keeps the band", () => {
  rendered = renderForTest(<Balance start={form({ balance_temperature: 5 })} />);
  expect([lowerEndHandle().value, balanceHandle().value]).toEqual(["10", "10"]);
  press(lowerEndHandle(), "pointerdown");
  setValue(lowerEndHandle(), "12");
  expect(latest!.userValues).toEqual({ balance_temperature: 12 });
  // The handles are apart now, but the drag keeps moving the balance temperature: the band is never closed on the way.
  setValue(lowerEndHandle(), "12.5");
  press(lowerEndHandle(), "pointerup");
  expect(latest!.userValues).toEqual({ balance_temperature: 12.5 });
  expect(lowerEndHandle().value).toBe("10.5");
});

const keyDown = (handle: HTMLInputElement, key: string) => act(() => { handle.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true })); });

test("on one spot, a key to the right on the left handle moves the balance temperature, not the dead band", () => {
  rendered = renderForTest(<Balance start={form({ balance_offset: 0 })} />);
  keyDown(lowerEndHandle(), "ArrowRight");
  setValue(lowerEndHandle(), "15.5");
  expect(latest!.userValues).toEqual({ balance_temperature: 15.5, balance_offset: 0 });
});

test("pinned at the low end (5 °C typed, dead band 2), a run of Right keys stays a balance move until the handle loses the focus", () => {
  rendered = renderForTest(<Balance start={form({ balance_temperature: 5 })} />);
  // The browser steps the handle from where it is drawn: 10, then 10.5 once the band shows from 8.5 (pinned at 10).
  keyDown(lowerEndHandle(), "ArrowRight");
  setValue(lowerEndHandle(), "10.5");
  expect(latest!.userValues).toEqual({ balance_temperature: 10.5 });
  keyDown(lowerEndHandle(), "ArrowRight");
  setValue(lowerEndHandle(), "10.5");      // the lower end, 8.5, is still drawn at 10: one step right is 10.5
  keyDown(lowerEndHandle(), "ArrowRight");
  setValue(lowerEndHandle(), "11");
  expect(latest!.userValues).toEqual({ balance_temperature: 11 });          // the band is never closed on the way
  // After the focus leaves, the left handle is the lower end again: Right narrows the band.
  act(() => { lowerEndHandle().dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
  keyDown(lowerEndHandle(), "ArrowRight");
  setValue(lowerEndHandle(), "10.5");
  expect(latest!.userValues).toEqual({ balance_temperature: 11, balance_offset: 0.5 });
});

test("an error of one of the two marks only its own handle and number field", () => {
  const refused = formReducer(form(), { type: "save_rejected", reply: { field_errors: [{ field: "balance_offset", message: "Input should be greater than or equal to 0" }], grid_plan: null } });
  renderBalance(refused);
  expect([lowerEndHandle(), deadBandNumber()].map((input) => input.getAttribute("aria-invalid"))).toEqual(["true", "true"]);
  expect([balanceHandle(), balanceNumber()].map((input) => input.getAttribute("aria-invalid"))).toEqual(["false", "false"]);
});

test("an invalid balance handle is marked on its own handle, not on the track the two share, and keeps its focus ring", () => {
  const formCss = readFileSync("src/settings_form/settings_form.css", "utf8");
  expect(formCss).toMatch(/\.balance-handle\[aria-invalid="true"\]::-webkit-slider-thumb\s*{[^}]*box-shadow: 0 0 0 2px var\(--colour-error\)/);
  expect(formCss).toMatch(/\.balance-handle\[aria-invalid="true"\]::-moz-range-thumb\s*{[^}]*box-shadow: 0 0 0 2px var\(--colour-error\)/);
  expect(formCss).toMatch(/\.balance-handle\[aria-invalid="true"\]:focus-visible::-webkit-slider-thumb\s*{[^}]*var\(--colour-error\)[^}]*0 0 0 5px var\(--colour-accent\)/);
  expect(formCss).toMatch(/\.balance-handle\[aria-invalid="true"\]:focus-visible::-moz-range-thumb\s*{[^}]*var\(--colour-error\)[^}]*0 0 0 5px var\(--colour-accent\)/);
  expect(formCss).not.toMatch(/\.balance-handle\[aria-invalid="true"\][^{]*track/);
});

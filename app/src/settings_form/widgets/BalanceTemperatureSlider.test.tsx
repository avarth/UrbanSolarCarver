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

test("dragging the right handle moves the band with it: only the balance temperature changes", () => {
  // The form behind the widget, as the app holds it.
  let latest: FormState | null = null;
  function Balance() {
    const [state, dispatch] = useReducer(formReducer, form());
    latest = state;
    return <SettingField view={balanceView()} form={state} onChange={(values) => dispatch({ type: "values_changed", values })} />;
  }
  rendered = renderForTest(<Balance />);
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

import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../api_client/client";
import { initialFormState, type FormState } from "../settings_form/form_state";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { useColdPeriod, type ColdPeriodState } from "./cold_period_request";

const NUMBER = { type: "number" };
const SCHEMA = { properties: { mode: { default: "benefit", type: "string" }, balance_temperature: { ...NUMBER, default: 15 },
                               balance_offset: { ...NUMBER, default: 2, minimum: 0 } } };
const MODES: ModeInfo[] = ["benefit", "irradiance"].map((name) => ({ name, description: "", needs_epw: true, needs_period: true, experimental: false,
                                                                    score_kind: "weighted_sum", weight_unit: "", starting_values: {} }));

const formOf = (settings: Record<string, unknown>): FormState =>
  initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "benefit", ...settings }, gridPlan: null });

let rendered: RenderedOverlay | null = null;
let state: ColdPeriodState | null = null;
let requests: string[] = [];
const FOUND = { status: "found", period: { start_month: 9, start_day: 30, end_month: 5, end_day: 15 } };
let reply: unknown = FOUND;

function ColdPeriodOf({ form, hasWeatherFile = true }: { form: FormState; hasWeatherFile?: boolean }) {
  state = useColdPeriod({ token: "t", project: "p", form, hasWeatherFile, weatherFileKey: "Golden, CO, USA", onServiceProblem: () => {} });
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  requests = [];
  reply = FOUND;
  vi.stubGlobal("fetch", vi.fn(async (address: string) => {
    requests.push(address);
    return new Response(JSON.stringify(reply), { status: 200, headers: { "content-type": "application/json" } });
  }));
});

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function waitForTheRequest() {
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
}

test("the cold period is asked for with the balance temperature minus the dead band the form shows", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({ balance_temperature: 16, balance_offset: 1.5 })} />);
  expect(state).toEqual({ kind: "finding" });
  await waitForTheRequest();
  expect(requests).toEqual(["/api/projects/p/cold-period?base_temperature=14.5"]);
  expect(state).toEqual({ kind: "found", dates: { startMonth: 9, startDay: 30, endMonth: 5, endDay: 15 }, baseTemperature: 14.5 });
});

test("the defaults give 13 °C, and a change of the balance asks again once it rests", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({})} />);
  await waitForTheRequest();
  rendered.rerender(<ColdPeriodOf form={formOf({ balance_temperature: 17 })} />);
  rendered.rerender(<ColdPeriodOf form={formOf({ balance_temperature: 18 })} />);
  await waitForTheRequest();
  expect(requests).toEqual(["/api/projects/p/cold-period?base_temperature=13", "/api/projects/p/cold-period?base_temperature=16"]);
});

test("no weather file asks nothing and says it is needed; no cold day says so with the base", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({})} hasWeatherFile={false} />);
  await waitForTheRequest();
  expect(requests).toEqual([]);
  expect(state).toEqual({ kind: "needs_weather_file" });
  reply = { status: "none", period: null };
  rendered.rerender(<ColdPeriodOf form={formOf({})} />);
  await waitForTheRequest();
  expect(state).toEqual({ kind: "none", baseTemperature: 13 });
});

test("a mode without a balance temperature has no cold period", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({ mode: "irradiance" })} />);
  await waitForTheRequest();
  expect(state).toBeNull();
  expect(requests).toEqual([]);
});

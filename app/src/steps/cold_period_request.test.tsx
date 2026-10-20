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
                                                                    score_kind: "weighted_sum", weight_unit: "", score_unit: "", starting_values: {} }));

const formOf = (settings: Record<string, unknown>): FormState =>
  initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "benefit", ...settings }, gridPlan: null });

let rendered: RenderedOverlay | null = null;
let state: ColdPeriodState | null = null;
let answeredRevision: number | null = null;
let requests: string[] = [];
const FOUND = { status: "found", period: { start_month: 9, start_day: 30, end_month: 5, end_day: 15 } };
let reply: unknown = FOUND;

function ColdPeriodOf({ form, hasWeatherFile = true, weatherFileRevision = 0 }: { form: FormState; hasWeatherFile?: boolean; weatherFileRevision?: number }) {
  ({ coldPeriod: state, answeredWeatherFileRevision: answeredRevision } =
    useColdPeriod({ token: "t", project: "p", form, hasWeatherFile, weatherFileRevision, onServiceProblem: () => {} }));
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

test("the base is rounded as the slider rounds its values: 16.1 - 2.9 asks for 13.2, not 13.200000000000001", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({ balance_temperature: 16.1, balance_offset: 2.9 })} />);
  await waitForTheRequest();
  expect(requests).toEqual(["/api/projects/p/cold-period?base_temperature=13.2"]);
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

test("a base that comes back to one already answered shows that answer at once and asks nothing", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({})} />);
  await waitForTheRequest();
  rendered.rerender(<ColdPeriodOf form={formOf({ balance_temperature: 18 })} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(100); });
  rendered.rerender(<ColdPeriodOf form={formOf({})} />);
  expect(state?.kind).toBe("found");
  await waitForTheRequest();
  expect(requests).toEqual(["/api/projects/p/cold-period?base_temperature=13"]);
});

test("a reply for a base the form no longer shows is not shown", async () => {
  let answerFirst: () => void = () => {};
  vi.stubGlobal("fetch", vi.fn(async (address: string) => {
    requests.push(address);
    if (requests.length === 1) await new Promise<void>((resolve) => { answerFirst = resolve; });
    const period = requests.length === 1 ? FOUND.period : { start_month: 10, start_day: 1, end_month: 4, end_day: 30 };
    return new Response(JSON.stringify({ status: "found", period }), { status: 200, headers: { "content-type": "application/json" } });
  }));
  rendered = renderForTest(<ColdPeriodOf form={formOf({})} />);
  await waitForTheRequest();                                     // asked for 13 °C; its reply waits
  rendered.rerender(<ColdPeriodOf form={formOf({ balance_temperature: 12 })} />);
  await waitForTheRequest();                                     // asked for 10 °C, answered
  await act(async () => { answerFirst(); await vi.advanceTimersByTimeAsync(0); });
  expect(state).toEqual({ kind: "found", dates: { startMonth: 10, startDay: 1, endMonth: 4, endDay: 30 }, baseTemperature: 10 });
});

test("a replaced weather file is asked about again at the same base", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({})} />);
  await waitForTheRequest();
  rendered.rerender(<ColdPeriodOf form={formOf({})} weatherFileRevision={1} />);
  await waitForTheRequest();
  expect(requests).toHaveLength(2);
});

test("the answer says which weather file it is of; while the replaced file is asked about, none is", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({})} />);
  expect(answeredRevision).toBeNull();
  await waitForTheRequest();
  expect(answeredRevision).toBe(0);
  reply = { status: "none", period: null };
  rendered.rerender(<ColdPeriodOf form={formOf({})} weatherFileRevision={1} />);
  expect(answeredRevision).toBeNull();                           // the first file's answer is no answer for the second
  expect(state).toEqual({ kind: "finding" });
  await waitForTheRequest();
  expect(answeredRevision).toBe(1);
  expect(state).toEqual({ kind: "none", baseTemperature: 13 });
});

test("a mode without a balance temperature has no cold period", async () => {
  rendered = renderForTest(<ColdPeriodOf form={formOf({ mode: "irradiance" })} />);
  await waitForTheRequest();
  expect(state).toBeNull();
  expect(requests).toEqual([]);
});

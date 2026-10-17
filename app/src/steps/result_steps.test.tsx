import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import * as THREE from "three";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { initialFormState, type SaveOutcome } from "../settings_form/form_state";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { dimmedLayersOf, isStageDimmed, missingLayersOf, useResultSteps, type ResultSteps } from "./result_steps";
import { resultsOfStages, useResultsFollowingRun, type RunResults } from "./run_results";
import { initialRunState, runReducer, useRunLoop, type RunRecord, type RunState } from "./run_state";
import type { PipelineStage, StageState } from "./step_summaries";

const ALL_CURRENT: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
const NO_RESULTS: RunResults = { summary: null, scorePoints: null, skyDome: null, envelope: null, massing: null, platesFile: null };

function record(state: RunState, serial = 1): RunRecord {
  return { serial, project: "p", origin: "build", runId: `r${serial}`, state, refusal: null };
}

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

test("a stage of the run under way is dimmed until the run has done it; other stages follow their status", () => {
  let state = initialRunState(["exporting", "massing"]);
  state = runReducer(state, { type: "stage_progress", stage: "massing", done: 0, total: 1 });
  const stages: Record<PipelineStage, StageState> = { ...ALL_CURRENT, thresholding: "out_of_date", exporting: "missing", massing: "missing" };
  expect(isStageDimmed("exporting", record(state), stages)).toBe(false);       // done in this run, though its status still says missing
  expect(isStageDimmed("massing", record(state), stages)).toBe(true);
  expect(isStageDimmed("thresholding", record(state), stages)).toBe(true);     // not in the run: its status
  expect(dimmedLayersOf(record(state), stages)).toEqual(["kept_voxels", "carved_voxels", "building_massing"]);
  expect(dimmedLayersOf(null, ALL_CURRENT)).toEqual([]);
  const ended = runReducer(state, { type: "run_finished", stages: ["exporting", "massing"], files: [] });
  expect(isStageDimmed("massing", record(ended), { ...stages, massing: "current" })).toBe(false);
});

test("a run that stopped early lists the layers its stages left without data; a finished run lists none", () => {
  const cancelled = runReducer(initialRunState(["preprocessing", "thresholding"]), { type: "run_cancelled" });
  const scorePointsWithoutMask = { kept: null } as unknown as ScorePoints;
  const withoutCarving: RunResults = { ...NO_RESULTS, scorePoints: scorePointsWithoutMask };
  expect(missingLayersOf(record(cancelled), withoutCarving, false)).toEqual(["kept_voxels", "carved_voxels"]);
  expect(missingLayersOf(record(cancelled), withoutCarving, true)).toEqual(["sky_dome", "kept_voxels", "carved_voxels"]);
  const failedBuild = runReducer(initialRunState(["exporting", "massing"]), { type: "run_failed", error_type: "E", message: "m", field_errors: [] });
  expect(missingLayersOf(record(failedBuild), { ...NO_RESULTS, envelope: new THREE.BufferGeometry() }, false)).toEqual(["building_massing"]);
  const finished = runReducer(initialRunState(["exporting"]), { type: "run_finished", stages: ["exporting"], files: [] });
  expect(missingLayersOf(record(finished), NO_RESULTS, false)).toEqual([]);
  expect(missingLayersOf(null, NO_RESULTS, false)).toEqual([]);
});

test("each stage names the results it writes; the score points follow the carving, not the analysis", () => {
  expect(resultsOfStages(["preprocessing"])).toEqual(["skyDome"]);
  expect(resultsOfStages(["thresholding", "exporting", "massing"])).toEqual(["summary", "scorePoints", "envelope", "massing", "platesFile"]);
});

function followedRun(initial: RunRecord | null) {
  const reload = vi.fn(), onRunEnded = vi.fn();
  function Follower({ current }: { current: RunRecord | null }) {
    useResultsFollowingRun(current, reload, onRunEnded);
    return null;
  }
  rendered = renderForTest(<Follower current={initial} />);
  return { reload, onRunEnded, show: (next: RunRecord | null) => rendered!.rerender(<Follower current={next} />) };
}

test("results are fetched again stage by stage as a run does them, the rest at its end, and the end is reported once", () => {
  const { reload, onRunEnded, show } = followedRun(null);
  let state = initialRunState(["preprocessing", "thresholding"]);
  show(record(state));
  expect(reload).not.toHaveBeenCalled();
  state = runReducer(state, { type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  show(record(state));
  expect(reload.mock.calls).toEqual([[["preprocessing"]]]);
  state = runReducer(state, { type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  show(record(state));
  expect(reload.mock.calls).toEqual([[["preprocessing"]], [["thresholding"]]]);
  expect(onRunEnded).toHaveBeenCalledOnce();
  show(record(state));
  expect(onRunEnded).toHaveBeenCalledOnce();
});

test("a cancelled run fetches again what its unfinished stages removed", () => {
  const { reload, onRunEnded, show } = followedRun(null);
  show(record(runReducer(initialRunState(["preprocessing", "thresholding"]), { type: "run_cancelled" })));
  expect(reload.mock.calls).toEqual([[["preprocessing", "thresholding"]]]);
  expect(onRunEnded).toHaveBeenCalledOnce();
});

test("a run that had ended before the project opened is not followed again; the next run is", () => {
  const ended = record(runReducer(initialRunState(["thresholding"]), { type: "run_finished", stages: ["thresholding"], files: [] }));
  const { reload, onRunEnded, show } = followedRun(ended);
  expect(reload).not.toHaveBeenCalled();
  expect(onRunEnded).not.toHaveBeenCalled();
  show(record(runReducer(initialRunState(["exporting"]), { type: "run_finished", stages: ["exporting"], files: [] }), 2));
  expect(reload.mock.calls).toEqual([[["exporting"]]]);
  expect(onRunEnded).toHaveBeenCalledOnce();
});

// ---- Review Focus 5: threshold moves during a carving run, through the queue, the run loop and the results ----

const settle = () => act(async () => {
  for (let tick = 0; tick < 5; tick++) await new Promise((resolve) => setTimeout(resolve, 0));
});

function typeAndLeave(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
}

const STARTED = (runId: string) => ({ status: "started", run_id: runId, stages: ["thresholding"] });

test("threshold moves during a carving run: one more run with the last value, and the left value's results are never fetched or shown as current", async () => {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  let answerSecondStart: () => void = () => {};
  const startReplies = [Promise.resolve(STARTED("r1")), new Promise((resolve) => { answerSecondStart = () => resolve(STARTED("r2")); })];
  const requests: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (address: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    requests.push(`${method} ${address}`);
    if (method === "POST" && address.endsWith("/runs")) return new Response(JSON.stringify(await startReplies.shift()));
    if (address.endsWith("/run/summary")) return new Response(JSON.stringify({ carving: null, massing: null }));
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  }));
  const resultFetches = () => requests.filter((request) => request.endsWith("/run/summary") || request.endsWith("/run/score-points")).length;
  const changeAndSave = vi.fn(async (): Promise<SaveOutcome> => "saved");
  const refreshStageStatus = vi.fn();
  const stages: Record<PipelineStage, StageState> = { ...ALL_CURRENT, exporting: "missing", massing: "missing" };
  const form = initialFormState({ schema: { properties: { mode: { default: "time-based" }, threshold: { default: null } } }, modes: [],
                                  settings: { mode: "time-based", threshold: { method: "cutoff", value: 1.5 } }, gridPlan: null });
  let latest: ResultSteps | null = null;
  function Workspace() {
    const runs = useRunLoop("token", vi.fn());
    latest = useResultSteps({
      token: "token", project: "p", form, dispatch: vi.fn(), flushSave: async () => "none", changeAndSave, isWeightedMode: false, stages,
      refreshStageStatus, runs, runBlocker: null, projectRunActive: runs.activeRun?.project === "p", origin: [0, 0, 0], openStep: vi.fn(),
      goToSetting: vi.fn(), onServiceProblem: vi.fn(),
    });
    return <>{latest.content.carving}</>;
  }
  rendered = renderForTest(<Workspace />);
  await settle();
  const fetchesAtOpen = resultFetches();
  const field = () => rendered!.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  const carvingDimmed = () => latest!.viewer.dimmedLayers!.includes("kept_voxels");

  typeAndLeave(field(), "1");
  await settle();
  expect(FakeWebSocket.opened).toHaveLength(1);           // run A, for 1
  for (const value of ["2", "3", "4"]) typeAndLeave(field(), value);
  await settle();
  FakeWebSocket.opened[0].send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  // A has ended and B (for 4) is saved and starting: 1's results are not fetched, and the carving on screen stays dimmed.
  expect(changeAndSave.mock.calls).toEqual([[{ threshold: { method: "cutoff", value: 1 } }], [{ threshold: { method: "cutoff", value: 4 } }]]);
  expect(resultFetches()).toBe(fetchesAtOpen);
  expect(carvingDimmed()).toBe(true);
  expect(refreshStageStatus).toHaveBeenLastCalledWith([]);

  answerSecondStart();
  await settle();
  expect(carvingDimmed()).toBe(true);                     // B under way
  FakeWebSocket.opened[1].send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  FakeWebSocket.opened[1].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(requests.filter((request) => request.startsWith("POST") && request.endsWith("/runs"))).toHaveLength(2);
  expect(resultFetches()).toBe(fetchesAtOpen + 2);         // the summary and the score points of 4, once
  expect(carvingDimmed()).toBe(false);
  expect(refreshStageStatus).toHaveBeenLastCalledWith(["thresholding"]);
});

test("a threshold run whose follow-up brings no run (a failed save, results up to date) does not leave the carving dimmed with old results", async () => {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const startReplies = [STARTED("r1"), { status: "up_to_date", run_id: null, stages: [] }];
  const requests: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (address: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    requests.push(`${method} ${address}`);
    if (method === "POST" && address.endsWith("/runs")) return new Response(JSON.stringify(startReplies.shift()));
    if (address.endsWith("/run/summary")) return new Response(JSON.stringify({ carving: null, massing: null }));
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  }));
  const resultFetches = () => requests.filter((request) => request.endsWith("/run/summary") || request.endsWith("/run/score-points")).length;
  // The save of 4 fails (a run in another tab answers 409); the others are stored.
  const changeAndSave = vi.fn(async (values: Record<string, unknown>): Promise<SaveOutcome> =>
    (values.threshold as { value: number }).value === 4 ? "failed" : "saved");
  const refreshStageStatus = vi.fn();
  const stages: Record<PipelineStage, StageState> = { ...ALL_CURRENT, exporting: "missing", massing: "missing" };
  const form = initialFormState({ schema: { properties: { mode: { default: "time-based" }, threshold: { default: null } } }, modes: [],
                                  settings: { mode: "time-based", threshold: { method: "cutoff", value: 1.5 } }, gridPlan: null });
  let latest: ResultSteps | null = null;
  function Workspace() {
    const runs = useRunLoop("token", vi.fn());
    latest = useResultSteps({
      token: "token", project: "p", form, dispatch: vi.fn(), flushSave: async () => "none", changeAndSave, isWeightedMode: false, stages,
      refreshStageStatus, runs, runBlocker: null, projectRunActive: runs.activeRun?.project === "p", origin: [0, 0, 0], openStep: vi.fn(),
      goToSetting: vi.fn(), onServiceProblem: vi.fn(),
    });
    return <>{latest.content.carving}</>;
  }
  rendered = renderForTest(<Workspace />);
  await settle();
  const fetchesAtOpen = resultFetches();
  const field = () => rendered!.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  const carvingDimmed = () => latest!.viewer.dimmedLayers!.includes("kept_voxels");

  typeAndLeave(field(), "1");
  await settle();
  typeAndLeave(field(), "4");                             // waits behind run A, for 1
  FakeWebSocket.opened[0].send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  // The save of 4 failed, so no run follows A: A's carving, the one the service holds, is fetched and shown undimmed.
  expect(changeAndSave).toHaveBeenCalledTimes(2);
  expect(FakeWebSocket.opened).toHaveLength(1);
  expect(resultFetches()).toBe(fetchesAtOpen + 2);
  expect(carvingDimmed()).toBe(false);
  expect(refreshStageStatus).toHaveBeenLastCalledWith();

  typeAndLeave(field(), "1");                             // stored; the service has nothing to run
  await settle();
  expect(requests.filter((request) => request.startsWith("POST") && request.endsWith("/runs"))).toHaveLength(2);
  expect(FakeWebSocket.opened).toHaveLength(1);
  expect(rendered.container.textContent).toContain("Results are up to date");
  expect(resultFetches()).toBe(fetchesAtOpen + 4);
  expect(carvingDimmed()).toBe(false);
  expect(refreshStageStatus).toHaveBeenCalledTimes(3);    // at A's end, after the failed save, after "up to date"
  expect(refreshStageStatus).toHaveBeenLastCalledWith();
});

const CARVING_SUMMARY = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: null,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 0,
};

test("after a follow-up with nothing to run, the carving stays dimmed until the results the service holds have arrived", async () => {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const startReplies = [STARTED("r1"), { status: "up_to_date", run_id: null, stages: [] }];
  let resultsHeld: Promise<void> | null = null;
  let releaseResults: () => void = () => {};
  vi.stubGlobal("fetch", vi.fn(async (address: string, init?: RequestInit) => {
    if ((init?.method ?? "GET") === "POST" && address.endsWith("/runs")) return new Response(JSON.stringify(startReplies.shift()));
    if (address.endsWith("/run/summary") || address.endsWith("/run/score-points")) await resultsHeld;
    if (address.endsWith("/run/summary")) return new Response(JSON.stringify({ carving: CARVING_SUMMARY, massing: null }));
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  }));
  const stages: Record<PipelineStage, StageState> = { ...ALL_CURRENT, exporting: "missing", massing: "missing" };
  const form = initialFormState({ schema: { properties: { mode: { default: "time-based" }, threshold: { default: null } } }, modes: [],
                                  settings: { mode: "time-based", threshold: { method: "cutoff", value: 1.5 } }, gridPlan: null });
  let latest: ResultSteps | null = null;
  function Workspace() {
    const runs = useRunLoop("token", vi.fn());
    latest = useResultSteps({
      token: "token", project: "p", form, dispatch: vi.fn(), flushSave: async () => "none", changeAndSave: async () => "saved", isWeightedMode: false,
      stages, refreshStageStatus: vi.fn(), runs, runBlocker: null, projectRunActive: runs.activeRun?.project === "p", origin: [0, 0, 0],
      openStep: vi.fn(), goToSetting: vi.fn(), onServiceProblem: vi.fn(),
    });
    return <>{latest.content.carving}</>;
  }
  rendered = renderForTest(<Workspace />);
  await settle();
  const field = () => rendered!.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  const carvingDimmed = () => latest!.viewer.dimmedLayers!.includes("kept_voxels");
  const carvingStepDimmed = () => rendered!.container.querySelector(".carving-content-dimmed") !== null;
  expect(carvingStepDimmed()).toBe(false);               // the carving numbers of the last run are shown

  resultsHeld = new Promise((resolve) => { releaseResults = resolve; });
  typeAndLeave(field(), "1");
  await settle();
  typeAndLeave(field(), "2");
  typeAndLeave(field(), "1");                             // back to 1: waits behind run A, for 1
  FakeWebSocket.opened[0].send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  // The service had nothing to run for 1, and A's results are on their way: what is on screen is still from before A.
  expect(rendered.container.textContent).toContain("Results are up to date");
  expect(carvingDimmed()).toBe(true);
  expect(carvingStepDimmed()).toBe(true);
  releaseResults();
  await settle();
  expect(carvingDimmed()).toBe(false);
  expect(carvingStepDimmed()).toBe(false);
});

test("Run analysis answered with up to date asks for the stage status again and fetches the results the service holds (a run the page did not follow)", async () => {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const requests: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (address: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    requests.push(`${method} ${address}`);
    if (method === "POST" && address.endsWith("/runs")) return new Response(JSON.stringify({ status: "up_to_date", run_id: null, stages: [] }));
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  }));
  // The page was reloaded while a run went on: the stage status it opened with said "missing" for the stages that run rewrote.
  const stages: Record<PipelineStage, StageState> = { preprocessing: "missing", thresholding: "missing", exporting: "current", massing: "current" };
  const refreshStageStatus = vi.fn();
  const form = initialFormState({ schema: { properties: { mode: { default: "daylight" } } }, modes: [], settings: { mode: "daylight" }, gridPlan: null });
  function Workspace() {
    const runs = useRunLoop("token", vi.fn());
    const steps = useResultSteps({
      token: "token", project: "p", form, dispatch: vi.fn(), flushSave: async () => "none", changeAndSave: async () => "saved", isWeightedMode: true,
      stages, refreshStageStatus, runs, runBlocker: null, projectRunActive: runs.activeRun?.project === "p", origin: [0, 0, 0], openStep: vi.fn(),
      goToSetting: vi.fn(), onServiceProblem: vi.fn(),
    });
    return <>{steps.content.carving}</>;
  }
  rendered = renderForTest(<Workspace />);
  await settle();
  const requestsAtOpen = requests.length;
  const runAnalysis = [...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Run analysis")!;
  await act(async () => runAnalysis.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await settle();
  expect(rendered.container.textContent).toContain("Results are up to date");
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(refreshStageStatus).toHaveBeenCalledOnce();
  // The carving asked for, and the analysis before it that the page did not hold as current; not the envelope or the massing.
  expect(requests.slice(requestsAtOpen).filter((request) => request.startsWith("GET")).map((request) => request.split("/api/projects/p/")[1]).sort())
    .toEqual(["run/score-points", "run/sky-patches", "run/summary"]);
});

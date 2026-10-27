import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, serviceProblemOf } from "../api_client/client";
import { renderForTest } from "../viewer_overlays/render_for_test";
import { NOTICE_MILLISECONDS, runningCriterion, useRunLoop, type RunLoop, type RunOutcome } from "./run_state";

class FakeWebSocket {
  static opened: FakeWebSocket[] = [];
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  constructor(readonly address: string) {
    FakeWebSocket.opened.push(this);
  }
  close() {}
  send(event: object) {
    act(() => this.onmessage?.({ data: JSON.stringify(event) }));
  }
}

function replyWith(body: unknown, status = 200) {
  return vi.fn().mockImplementation(async () => new Response(JSON.stringify(body), { status }));
}

function renderedLoop(onServiceProblem = vi.fn()) {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  let latest: RunLoop | null = null;
  function LoopProbe() {
    latest = useRunLoop("token", onServiceProblem);
    return null;
  }
  const rendered = renderForTest(createElement(LoopProbe));
  return { loop: () => latest!, onServiceProblem, unmount: rendered.unmount };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("a run is followed to its last event: the active run, then the record of how it ended", async () => {
  vi.stubGlobal("fetch", replyWith({ status: "started", run_id: "r1", stages: ["thresholding"] }));
  const { loop, unmount } = renderedLoop();
  let outcome: Promise<RunOutcome> | null = null;
  await act(async () => { outcome = loop().start("p", ["thresholding"], "carving_update"); });
  expect(loop().activeRun).toEqual({ project: "p", origin: "carving_update" });
  expect(loop().current).toMatchObject({ project: "p", origin: "carving_update", runId: "r1" });
  FakeWebSocket.opened[0].send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  expect(await outcome).toBe("finished");
  expect(loop().activeRun).toBeNull();
  expect(loop().current!.state.final).toBe("finished");
  unmount();
});

test("a start while a run is active starts nothing and says A run is in progress at its button", async () => {
  vi.stubGlobal("fetch", replyWith({ status: "started", run_id: "r1", stages: ["thresholding"] }));
  const { loop, unmount } = renderedLoop();
  await act(async () => { void loop().start("p", ["thresholding"], "carving_update"); });
  let second: RunOutcome | null = null;
  await act(async () => { second = await loop().start("p", ["exporting"], "build"); });
  expect(second).toBe("not_started");
  expect(loop().notice).toEqual({ project: "p", origin: "build", message: "A run is in progress" });
  unmount();
});

test("a stage-status reply holds only when no run of its project started or ran since it was asked for", async () => {
  vi.stubGlobal("fetch", replyWith({ status: "started", run_id: "r1", stages: ["thresholding"] }));
  const { loop, unmount } = renderedLoop();
  const askedBeforeTheRun = loop().replyStillHolds("p");
  const askedForAnotherProject = loop().replyStillHolds("q");
  expect(askedBeforeTheRun()).toBe(true);
  let outcome: Promise<RunOutcome> | null = null;
  await act(async () => { outcome = loop().start("p", ["thresholding"], "carving_update"); });
  const askedDuringTheRun = loop().replyStillHolds("p");
  expect(askedBeforeTheRun()).toBe(false);
  expect(askedDuringTheRun()).toBe(false);
  expect(askedForAnotherProject()).toBe(true);
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await outcome;
  expect(askedBeforeTheRun()).toBe(false);          // a run started after it was asked for
  expect(askedDuringTheRun()).toBe(false);          // read while the run had removed its stage records
  expect(loop().replyStillHolds("p")()).toBe(true);
  unmount();
});

test("nothing to run shows Results are up to date at the button for three seconds", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", replyWith({ status: "up_to_date", run_id: null, stages: [] }));
  const { loop, unmount } = renderedLoop();
  let outcome: RunOutcome | null = null;
  await act(async () => { outcome = await loop().start("p", ["exporting", "massing"], "build"); });
  expect(outcome).toBe("up_to_date");
  expect(loop().notice).toEqual({ project: "p", origin: "build", message: "Results are up to date" });
  await act(() => vi.advanceTimersByTimeAsync(NOTICE_MILLISECONDS));
  expect(loop().notice).toBeNull();
  unmount();
});

test("a start refused for invalid settings is a failed run naming its fields; another refusal keeps the service's words", async () => {
  vi.stubGlobal("fetch", replyWith({ field_errors: [{ field: "voxel_size", message: "too small" }], grid_plan: null }, 422));
  const { loop, unmount } = renderedLoop();
  await act(async () => { await loop().start("p", ["thresholding"], "settings_run_analysis"); });
  expect(loop().current!.state.final).toBe("failed");
  expect(loop().current!.state.failure!.field_errors).toEqual([{ field: "voxel_size", message: "too small" }]);
  vi.stubGlobal("fetch", replyWith({ detail: "A run of project 'q' is active." }, 409));
  await act(async () => { await loop().start("p", ["thresholding"], "settings_run_analysis"); });
  expect(loop().current!.refusal).toBe("A run of project 'q' is active.");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("Internal Server Error", { status: 500 })));
  await act(async () => { await loop().start("p", ["thresholding"], "settings_run_analysis"); });
  expect(loop().current!.refusal).toBe("The USC engine refused the request and gave no reason (status 500). Try again.");
  unmount();
});

test("a connection lost during a run is passed on as a stopped engine, or a lost token for 4401", async () => {
  for (const [code, isAccessLost] of [[1006, false], [4401, true]] as const) {
    vi.stubGlobal("fetch", replyWith({ status: "started", run_id: "r1", stages: ["preprocessing"] }));
    const { loop, onServiceProblem, unmount } = renderedLoop();
    let outcome: Promise<RunOutcome> | null = null;
    await act(async () => { outcome = loop().start("p", ["thresholding"], "settings_run_analysis"); });
    act(() => FakeWebSocket.opened[0].onclose?.({ code, reason: "" }));
    expect(await outcome).toBe("connection_lost");
    const problem = onServiceProblem.mock.calls[0][0];
    expect(serviceProblemOf(problem)).toBe(isAccessLost ? "access_lost" : "engine_stopped");
    expect(problem instanceof ApiError).toBe(isAccessLost);
    unmount();
  }
});

test("forget drops the record of a project renamed, reset or deleted, and only that project's, and never during a run", async () => {
  vi.stubGlobal("fetch", replyWith({ detail: "Add a maximum volume first." }, 409));
  const { loop, unmount } = renderedLoop();
  await act(async () => { await loop().start("Plot 7", ["thresholding"], "settings_run_analysis"); });
  expect(loop().current!.refusal).toBe("Add a maximum volume first.");
  act(() => loop().forget("Other"));
  expect(loop().current).not.toBeNull();
  act(() => loop().forget("plot 7"));       // names ignore letter case
  expect(loop().current).toBeNull();

  vi.stubGlobal("fetch", replyWith({ status: "started", run_id: "r1", stages: ["thresholding"] }));
  await act(async () => { void loop().start("Plot 7", ["thresholding"], "carving_update"); });
  act(() => loop().forget("Plot 7"));
  expect(loop().current).toMatchObject({ project: "Plot 7", runId: "r1" });
  unmount();
});

test("progress of two criteria is kept apart, in the order of the chain, then the stages of the whole chain", async () => {
  // The reply's criteria come as an object, whose number-like keys read in ascending order: the chain order is the app's.
  vi.stubGlobal("fetch", replyWith({ status: "started", run_id: "r1", stages: ["preprocessing", "thresholding", "exporting"],
                                     criterion_stages: { 1: ["thresholding"], 2: ["preprocessing", "thresholding"], 3: [] } }));
  const { loop, unmount } = renderedLoop();
  await act(async () => { void loop().start("p", ["exporting"], "build", { chainOrder: ["2", "3", "1"] }); });
  const progress = () => loop().current!.state;
  expect(progress().order).toEqual(["2:preprocessing", "2:thresholding", "1:thresholding", "exporting"]);
  expect(runningCriterion(progress())).toBe("2");
  const socket = FakeWebSocket.opened[0];
  socket.send({ type: "stage_progress", stage: "preprocessing", criterion: "2", done: 3, total: 10 });
  socket.send({ type: "stage_progress", stage: "thresholding", criterion: "2", done: 0, total: 1 });
  socket.send({ type: "stage_progress", stage: "thresholding", criterion: "1", done: 0, total: 1 });
  expect(progress().stages["2:preprocessing"]).toEqual({ state: "done", done: 3, total: 10 });
  expect(progress().stages["2:thresholding"].state).toBe("done");
  expect(progress().stages["1:thresholding"]).toEqual({ state: "running", done: 0, total: 1 });
  expect(runningCriterion(progress())).toBe("1");
  socket.send({ type: "stage_progress", stage: "exporting", criterion: null, done: 0, total: 1 });
  expect(runningCriterion(progress())).toBeNull();          // exporting reads the whole chain
  unmount();
});

test("a start refused for a criterion's settings names the criterion; one refused for missing inputs keeps their roles", async () => {
  vi.stubGlobal("fetch", replyWith({ field_errors: [{ field: "max_slope_deg", message: "too steep" }], grid_plan: null, criterion: "2" }, 422));
  const { loop, unmount } = renderedLoop();
  await act(async () => { await loop().start("p", ["thresholding"], "carving_run_analysis"); });
  expect(loop().current!.state.failure).toMatchObject({ criterion: "2", field_errors: [{ field: "max_slope_deg", message: "too steep" }] });
  vi.stubGlobal("fetch", replyWith({ detail: "Add test surfaces to Daylight.", missing_inputs: ["test_surfaces:3"] }, 422));
  await act(async () => { await loop().start("p", ["thresholding"], "carving_run_analysis"); });
  expect(loop().current!.refusal).toBe("Add test surfaces to Daylight.");
  expect(loop().current!.missingInputs).toEqual(["test_surfaces:3"]);
  unmount();
});

test("a simulation holds the loop as a run does, names the study it runs, and leaves the project's stage status standing", async () => {
  const fetchSpy = replyWith({ status: "started", run_id: "s1", stages: ["simulate"], criterion_stages: {} });
  vi.stubGlobal("fetch", fetchSpy);
  const { loop, unmount } = renderedLoop();
  const askedBefore = loop().replyStillHolds("p");
  let outcome: Promise<RunOutcome> | null = null;
  await act(async () => { outcome = loop().startSimulation("p"); });
  expect(fetchSpy).toHaveBeenCalledWith("/api/projects/p/simulate", expect.objectContaining({ method: "POST" }));
  expect(loop().activeRun).toEqual({ project: "p", origin: "simulate" });
  let second: RunOutcome | null = null;
  await act(async () => { second = await loop().start("p", ["thresholding"], "carving_update"); });
  expect(second).toBe("not_started");
  FakeWebSocket.opened[0].send({ type: "stage_progress", stage: "simulate", criterion: null, study: "2", done: 1, total: 4 });
  expect(loop().current!.state.study).toBe("2");
  act(() => loop().forget("p"));
  expect(loop().current).not.toBeNull();       // not during the simulation
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["simulate"], files: [] });
  expect(await outcome).toBe("finished");
  expect(askedBefore()).toBe(true);
  unmount();
});

test("a simulation the service refuses keeps its words at Run", async () => {
  vi.stubGlobal("fetch", replyWith({ detail: "No study can run: Sun hours, 21 Dec: Add test surfaces." }, 422));
  const { loop, unmount } = renderedLoop();
  let outcome: RunOutcome | null = null;
  await act(async () => { outcome = await loop().startSimulation("p"); });
  expect(outcome).toBe("not_started");
  expect(loop().activeRun).toBeNull();
  expect(loop().current).toMatchObject({ origin: "simulate", refusal: "No study can run: Sun hours, 21 Dec: Add test surfaces." });
  unmount();
});

import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, serviceProblemOf } from "../api_client/client";
import { renderForTest } from "../viewer_overlays/render_for_test";
import { NOTICE_MILLISECONDS, useRunLoop, type RunLoop, type RunOutcome } from "./run_state";

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

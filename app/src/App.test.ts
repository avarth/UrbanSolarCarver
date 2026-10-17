import { afterEach, expect, test, vi } from "vitest";
import { ApiError, type HealthReply } from "./api_client/client";
import { freeProjectName, pollHealth } from "./App";

afterEach(() => {
  vi.useRealTimers();
});

const RUNNING: HealthReply = { version: "1", warm_up: { state: "running" } };
const READY: HealthReply = { version: "1", warm_up: { state: "ready", device_name: "GPU" } };
const NO_REPLY = new TypeError("Failed to fetch");

function polling(replies: (HealthReply | Error)[]) {
  const ask = vi.fn(async () => {
    const next = replies.shift()!;
    if (next instanceof Error) throw next;
    return next;
  });
  const onReply = vi.fn();
  const onProblem = vi.fn();
  const stop = pollHealth({ ask, onReply, onProblem, askAgainAfter: (reply) => reply.warm_up.state === "running", intervalMilliseconds: 1000,
                            failuresBeforeStopped: 3 });
  return { ask, onReply, onProblem, stop };
}

test("one failed health poll does not end polling: the warm-up is still followed", async () => {
  vi.useFakeTimers();
  const { ask, onReply, onProblem } = polling([RUNNING, NO_REPLY, RUNNING, READY]);
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(4);
  expect(onReply).toHaveBeenLastCalledWith(READY);
  expect(onProblem).not.toHaveBeenCalled();
});

test("the engine is said to be stopped only after three failed polls in a row", async () => {
  vi.useFakeTimers();
  const { ask, onProblem } = polling([NO_REPLY, NO_REPLY, NO_REPLY, READY]);
  await vi.advanceTimersByTimeAsync(1500);
  expect(onProblem).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(3);
  expect(onProblem).toHaveBeenCalledExactlyOnceWith("engine_stopped");
});

test("a lost token is said at once", async () => {
  vi.useFakeTimers();
  const { ask, onProblem } = polling([new ApiError(401, { detail: "token" })]);
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(1);
  expect(onProblem).toHaveBeenCalledExactlyOnceWith("access_lost");
});

test("stopping ends the polling", async () => {
  vi.useFakeTimers();
  const { ask, stop } = polling([RUNNING, RUNNING, RUNNING]);
  await vi.advanceTimersByTimeAsync(0);
  stop();
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(1);
});

test("an example's project is named after its title, numbered when that name is taken", () => {
  expect(freeProjectName("Perimeter block", ["Other"])).toBe("Perimeter block");
  expect(freeProjectName("Perimeter block", ["perimeter block", "Perimeter block 2"])).toBe("Perimeter block 3");
  expect(freeProjectName("x".repeat(70), ["x".repeat(64)])).toBe(`${"x".repeat(62)} 2`);
});

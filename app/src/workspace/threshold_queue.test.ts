import { expect, test, vi } from "vitest";
import { createThresholdUpdateQueue } from "./threshold_queue";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

test("threshold moves during a run give exactly one more run, with the last value", async () => {
  const calls: number[] = [];
  let finish!: () => void;
  const queue = createThresholdUpdateQueue((v) => { calls.push(v); return new Promise((r) => { finish = () => r(true); }); }, vi.fn());
  queue.submit(1); queue.submit(2); queue.submit(3); queue.submit(4);
  expect(queue.busy()).toBe(true);
  finish(); await flush(); finish(); await flush();
  expect(calls).toEqual([1, 4]);
  expect(queue.busy()).toBe(false);
});

test("values of different keys (criteria) wait side by side: one never replaces another's, and a run is superseded only by its own key's", async () => {
  const calls: string[] = [];
  const supersededChecks: (() => boolean)[] = [];
  let finish!: () => void;
  const queue = createThresholdUpdateQueue<number>((v, isSuperseded, key) => {
    calls.push(`${key}=${v}`);
    supersededChecks.push(isSuperseded);
    return new Promise((r) => { finish = () => r(true); });
  }, vi.fn());
  queue.submit(1, "1");
  queue.submit(2, "1");
  queue.submit(4, "2");
  expect(supersededChecks[0]()).toBe(true);           // criterion 1's newer value waits
  queue.submit(5, "2");                               // replaces criterion 2's waiting value only
  finish(); await flush();
  expect(supersededChecks[1]()).toBe(false);          // criterion 2's waiting value does not supersede criterion 1's run
  finish(); await flush(); finish(); await flush();
  expect(calls).toEqual(["1=1", "1=2", "2=5"]);
  expect(queue.busy()).toBe(false);
});

test("a value submitted while idle runs at once, and a failed run does not stop the next value", async () => {
  const calls: number[] = [];
  const queue = createThresholdUpdateQueue(async (v) => {
    calls.push(v);
    if (v === 1) throw new Error("the run could not start");
    return true;
  }, vi.fn());
  queue.submit(1);
  await flush();
  queue.submit(2);
  await flush();
  expect(calls).toEqual([1, 2]);
  expect(queue.busy()).toBe(false);
});

test("a run's value counts as left once a newer value is submitted; the last value's run is never superseded", async () => {
  const runs: { value: number; isSuperseded: () => boolean }[] = [];
  let finish!: () => void;
  const queue = createThresholdUpdateQueue((value, isSuperseded) => {
    runs.push({ value, isSuperseded });
    return new Promise((resolve) => { finish = () => resolve(true); });
  }, vi.fn());
  queue.submit(1);
  expect(runs[0].isSuperseded()).toBe(false);
  queue.submit(2); queue.submit(4);
  expect(runs[0].isSuperseded()).toBe(true);
  finish(); await flush();
  expect(runs.map((run) => run.value)).toEqual([1, 4]);
  expect(runs[0].isSuperseded()).toBe(true);
  expect(runs[1].isSuperseded()).toBe(false);
  finish(); await flush();
  expect(runs[1].isSuperseded()).toBe(false);
});

test("when the last value ends without a run, the run before it is no longer superseded and the queue says so once", async () => {
  const runs: { value: number; isSuperseded: () => boolean }[] = [];
  const answers: ((runStarted: boolean) => void)[] = [];
  const onLastValueEndedWithoutRun = vi.fn();
  const queue = createThresholdUpdateQueue((value, isSuperseded) => {
    runs.push({ value, isSuperseded });
    return new Promise((resolve) => { answers.push(resolve); });
  }, onLastValueEndedWithoutRun);
  queue.submit(1);
  queue.submit(4);
  answers.shift()!(true); await flush();               // the run for 1 ends; 4 is being saved
  expect(runs[0].isSuperseded()).toBe(true);
  queue.submit(5);                                     // waits behind 4
  answers.shift()!(false); await flush();              // 4 ended without a run, but 5 is still to come
  expect(onLastValueEndedWithoutRun).not.toHaveBeenCalled();
  expect(runs[0].isSuperseded()).toBe(true);
  answers.shift()!(false); await flush();              // 5, the last value, ended without a run (save failed, nothing to run)
  expect(onLastValueEndedWithoutRun).toHaveBeenCalledOnce();
  expect(runs[0].isSuperseded()).toBe(false);
  expect(queue.busy()).toBe(false);
});

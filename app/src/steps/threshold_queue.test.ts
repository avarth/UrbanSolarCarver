import { expect, test } from "vitest";
import { createThresholdUpdateQueue } from "./threshold_queue";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

test("threshold moves during a run give exactly one more run, with the last value", async () => {
  const calls: number[] = [];
  let finish!: () => void;
  const queue = createThresholdUpdateQueue((v) => { calls.push(v); return new Promise((r) => { finish = r; }); });
  queue.submit(1); queue.submit(2); queue.submit(3); queue.submit(4);
  expect(queue.busy()).toBe(true);
  finish(); await flush(); finish(); await flush();
  expect(calls).toEqual([1, 4]);
  expect(queue.busy()).toBe(false);
});

test("a value submitted while idle runs at once, and a failed run does not stop the next value", async () => {
  const calls: number[] = [];
  const queue = createThresholdUpdateQueue(async (v) => {
    calls.push(v);
    if (v === 1) throw new Error("the run could not start");
  });
  queue.submit(1);
  await flush();
  queue.submit(2);
  await flush();
  expect(calls).toEqual([1, 2]);
  expect(queue.busy()).toBe(false);
});

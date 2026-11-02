// The time strip of the sun tool: the time under the pointer and the time a key moves to.
import { expect, test } from "vitest";
import { minuteAfterKey, minuteAt } from "./SunPanel";

test("the time strip moves in 5 minute steps and an hour a page; the pointer's place along it gives the time", () => {
  expect(minuteAt(0.5)).toBe(720);
  expect(minuteAt(1)).toBe(1435);
  expect([minuteAfterKey(720, "ArrowRight"), minuteAfterKey(720, "PageDown"), minuteAfterKey(10, "Home"), minuteAfterKey(720, "x")])
    .toEqual([725, 660, 0, null]);
});

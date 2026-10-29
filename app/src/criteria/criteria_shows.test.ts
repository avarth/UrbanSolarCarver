// What the Criteria step shows when it opens for the first time.
import { expect, test } from "vitest";
import { firstCriteriaShows } from "./criteria_shows";

test("the step opens on the editor for one criterion, on the list otherwise", () => {
  expect(firstCriteriaShows(1)).toBe("editor");
  expect(firstCriteriaShows(2)).toBe("list");
  expect(firstCriteriaShows(0)).toBe("list");
});

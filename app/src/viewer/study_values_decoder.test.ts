import { expect, test } from "vitest";
import { decodeStudyValues, patchCorners } from "./study_values_decoder";
import { packedStudyValues } from "./study_values_for_test";

const ONE_SQUARE = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0];

test("decodeStudyValues reads the header, quads and columns", () => {
  const buffer = packedStudyValues({ frame: [1000, 2000, 10], point_count: 2, columns: ["open", "max_volume", "envelope"], unit: "h" },
                                   [...ONE_SQUARE, ...ONE_SQUARE.map((value, index) => (index % 3 === 0 ? value + 1 : value))],
                                   [[4, 4], [0, 2.5], [1, 3]]);
  const decoded = decodeStudyValues(buffer);
  expect(decoded.header).toEqual({ frame: [1000, 2000, 10], point_count: 2, columns: ["open", "max_volume", "envelope"], unit: "h" });
  expect(decoded.quads).toHaveLength(2 * 12);
  expect(Object.keys(decoded.values)).toEqual(["open", "max_volume", "envelope"]);
  expect(Array.from(decoded.values.open)).toEqual([4, 4]);
  expect(Array.from(decoded.values.max_volume)).toEqual([0, 2.5]);
  expect(Array.from(decoded.values.envelope)).toEqual([1, 3]);
  // The four corners of each patch, moved from the frame into the local origin.
  const corners = patchCorners(decoded, [1000, 2000, 0]);
  expect(corners).toHaveLength(2 * 4 * 3);
  expect(Array.from(corners.slice(0, 6))).toEqual([0, 0, 10, 1, 0, 10]);
  expect(Array.from(corners.slice(12 + 3, 12 + 6))).toEqual([2, 0, 10]);       // the second point's second corner
});

test("a result without test points decodes to empty columns", () => {
  const decoded = decodeStudyValues(packedStudyValues({ frame: [0, 0, 0], point_count: 0, columns: ["open", "max_volume"], unit: "%" }, [], [[], []]));
  expect(decoded.quads).toHaveLength(0);
  expect(decoded.values.max_volume).toHaveLength(0);
});

// Rectangles drawn with the site editor: the outline from the clicks, and where each click goes with snapping.
import { describe, expect, test } from "vitest";
import { placeShapePoint, shapeOutline, type ToScreen } from "./site_drawing";
import type { SitePoint } from "./site_geometry";

const toScreen: ToScreen = (point) => [point[0] * 10, -point[1] * 10];      // 10 pixels a metre, y up the screen

describe("rectangle", () => {
  test("two opposite corners give four corners with sides along x and y, in the order clicked", () => {
    expect(shapeOutline("rectangle", [[0, 0, 5], [20, 10, 5]])).toEqual([[0, 0, 5], [20, 0, 5], [20, 10, 5], [0, 10, 5]]);
    expect(shapeOutline("rectangle", [[20, 10, 0], [0, 0, 0]])).toEqual([[20, 10, 0], [0, 10, 0], [0, 0, 0], [20, 0, 0]]);
  });

  test("one corner, or two on one line, give no outline", () => {
    expect(shapeOutline("rectangle", [[0, 0, 0]])).toBeNull();
    expect(shapeOutline("rectangle", [[0, 0, 0], [20, 0, 0]])).toBeNull();
    expect(shapeOutline("rectangle", [[3, 4, 0], [3, 4, 0]])).toBeNull();
  });

  test("a corner snaps to another outline's vertex; Shift does not turn it", () => {
    const other: SitePoint[] = [[20, 0, 0], [30, 0, 0], [30, 10, 0]];
    expect(placeShapePoint("rectangle", [], [20.5, 0.5, 0], [205, -5], [other], toScreen, false)).toEqual({ point: [20, 0, 0], snap: "vertex" });
    expect(placeShapePoint("rectangle", [[0, 0, 0]], [10, 1, 0], [100, -10], [], toScreen, true)).toEqual({ point: [10, 1, 0], snap: null });
  });
});

describe("tilted rectangle", () => {
  test("the first side from two clicks, the width from the third, measured square to the side", () => {
    // A side of 10 m at 3-4-5; the third click 5 m to its left
    expect(shapeOutline("tilted_rectangle", [[0, 0, 0], [8, 6, 0], [5, 10, 0]])).toEqual([[0, 0, 0], [8, 6, 0], [5, 10, 0], [-3, 4, 0]]);
    // The third click off the square: only its distance from the side counts; to the right the width goes right
    const right = shapeOutline("tilted_rectangle", [[0, 0, 0], [10, 0, 0], [4, -3, 0]])!;
    expect(right).toEqual([[0, 0, 0], [10, 0, 0], [10, -3, 0], [0, -3, 0]]);
  });

  test("corners are kept to the millimetre", () => {
    const outline = shapeOutline("tilted_rectangle", [[0, 0, 0], [1, 1, 0], [0, 1, 0]])!;
    expect(outline[2]).toEqual([0.5, 1.5, 0]);
    expect(outline[3]).toEqual([-0.5, 0.5, 0]);
  });

  test("two clicks, a third on the side's line, or a side of no length give no outline", () => {
    expect(shapeOutline("tilted_rectangle", [[0, 0, 0], [10, 0, 0]])).toBeNull();
    expect(shapeOutline("tilted_rectangle", [[0, 0, 0], [10, 0, 0], [20, 0, 0]])).toBeNull();
    expect(shapeOutline("tilted_rectangle", [[0, 0, 0], [0, 0, 0], [5, 5, 0]])).toBeNull();
  });

  test("Shift holds the first side at 15 degree steps from the x axis; the width click only snaps", () => {
    const second = placeShapePoint("tilted_rectangle", [[0, 0, 0]], [10, 1, 0], [100, -10], [], toScreen, true);
    expect(second.snap).toBe("angle");
    expect(second.point[1]).toBeCloseTo(0);
    expect(placeShapePoint("tilted_rectangle", [[0, 0, 0], [10, 0, 0]], [12, 3, 0], [120, -30], [], toScreen, true)).toEqual({ point: [12, 3, 0], snap: null });
  });
});

test("a polygon's clicks are placed as before, closing on the first point", () => {
  const drawn: SitePoint[] = [[0, 0, 0], [10, 0, 0], [10, 10, 0]];
  expect(placeShapePoint("polygon", drawn, [0.3, 0.2, 0], [3, -2], [], toScreen, false)).toEqual({ point: [0, 0, 0], snap: "first_point" });
  expect(shapeOutline("polygon", drawn)).toBeNull();
});

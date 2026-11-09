import { describe, expect, test } from "vitest";
import { constrainedToAngle, drawingLevel, placePoint, type ToScreen } from "./site_drawing";
import {
  baseHeightOf, containsPoint, crossesItself, differsFromOriginal, maxHeightOf, nextSiteName, outlinePoints, planArea, pointAlong, siteProblems, siteRise, type SitePoint,
} from "./site_geometry";

const SQUARE: SitePoint[] = [[0, 0, 100], [40, 0, 102], [40, 30, 106], [0, 30, 101]];

describe("the site's geometry", () => {
  test("area, rise and the outline without a repeated last point", () => {
    expect(planArea(SQUARE)).toBe(1200);
    expect(planArea([...SQUARE].reverse())).toBe(1200);
    expect(siteRise(SQUARE)).toBe(6);
    expect(outlinePoints([...SQUARE, [0, 0, 100], [0, 0, 100]])).toEqual(SQUARE);
  });

  test("an outline that crosses itself is found, a concave one is not", () => {
    expect(crossesItself([[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0]])).toBe(true);
    expect(crossesItself([[0, 0, 0], [60, 0, 0], [60, 20, 0], [20, 20, 0], [20, 50, 0], [0, 50, 0]])).toBe(false);
  });

  test("the reasons are the engine's", () => {
    expect(siteProblems({ name: "a", points: SQUARE, height: 20 })).toEqual([]);
    expect(siteProblems({ name: "a", points: SQUARE, height: 6 })).toEqual(["this site rises 6.00 m, so its height must be more than 6.00 m"]);
    expect(siteProblems({ name: "a", points: SQUARE.slice(0, 2), height: 6 })).toEqual(["an outline needs at least 3 vertices"]);
    expect(siteProblems({ name: "a", points: [[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0]], height: 6 })).toEqual(["the outline crosses itself"]);
    expect(siteProblems({ name: "a", points: [[0, 0, 0], [0.5, 0, 0], [0.5, 0.5, 0]], height: 6 })[0]).toContain("less than 1");
    expect(siteProblems({ name: "a", points: SQUARE, height: 0 })).toEqual(["the height must be more than 0 m"]);
  });

  test("inside, along an edge, and the next name", () => {
    expect(containsPoint(SQUARE, 20, 15)).toBe(true);
    expect(containsPoint(SQUARE, 50, 15)).toBe(false);
    expect(pointAlong(SQUARE[0], SQUARE[1], 0.5)).toEqual([20, 0, 101]);
    expect(nextSiteName([{ name: "Site 2", points: SQUARE, height: 1 }])).toBe("Site 3");
    expect(nextSiteName([{ name: "Site 1", points: SQUARE, height: 1 }, { name: "Site 3", points: SQUARE, height: 1 }])).toBe("Site 4");
  });
});

describe("drawing", () => {
  const toScreen: ToScreen = (point) => [point[0] * 10, -point[1] * 10];      // 10 pixels a metre, y up the screen

  test("a click near the first point closes the outline once there are 3 points", () => {
    const drawn: SitePoint[] = [[0, 0, 0], [10, 0, 0], [10, 10, 0]];
    expect(placePoint(drawn, [0.3, 0.2, 0], [3, -2], [], toScreen, false)).toEqual({ point: [0, 0, 0], snap: "first_point" });
    expect(placePoint(drawn.slice(0, 2), [0.3, 0.2, 0], [3, -2], [], toScreen, false).snap).toBeNull();
  });

  test("the pointer snaps to another site's vertex, then to its edge, at the drawing level", () => {
    const other: SitePoint[] = [[20, 0, 50], [30, 0, 50], [30, 10, 50]];
    expect(placePoint([], [20.5, 0.5, 0], [205, -5], [other], toScreen, false)).toEqual({ point: [20, 0, 0], snap: "vertex" });
    expect(placePoint([], [25, 0.4, 0], [250, -4], [other], toScreen, false)).toEqual({ point: [25, 0, 0], snap: "edge" });
    expect(placePoint([], [25, 3, 0], [250, -30], [other], toScreen, false).snap).toBeNull();
  });

  test("Shift holds the segment at 15 degree steps from the previous one", () => {
    const [x, y] = constrainedToAngle(null, [0, 0, 0], [10, 1, 0]);
    expect(x).toBeCloseTo(Math.hypot(10, 1));
    expect(y).toBeCloseTo(0);
    const turned = constrainedToAngle([0, 0, 0], [10, 0, 0], [11, 9, 0]);      // about 84 degrees from the previous segment: 90
    expect(turned[0]).toBeCloseTo(10);
    expect(turned[1]).toBeCloseTo(Math.hypot(1, 9));
    expect(placePoint([[0, 0, 0]], [10, 1, 0], [100, -10], [], toScreen, true).snap).toBe("angle");
  });

  test("the drawing level is the lowest site vertex, else the surroundings' lowest level, else 0", () => {
    expect(drawingLevel([SQUARE], 20)).toBe(100);
    expect(drawingLevel([], 20)).toBe(20);
    expect(drawingLevel([], null)).toBe(0);
  });
});

test("with heights a site's max and base are the project's or its own, and a base not below the max is a problem", () => {
  const site = { name: "A", points: [[0, 0, 0], [10, 0, 0], [10, 10, 0]] as SitePoint[], height: 20, base_height: 25 };
  const perSite = { max: { for_all_sites: false }, base: { for_all_sites: false } };
  expect(siteProblems(site, perSite)).toEqual(["its base height (25 m) must be less than its max height (20 m)"]);
  expect(siteProblems(site, { max: { for_all_sites: true, value: 30 }, base: { for_all_sites: false } })).toEqual([]);
  expect(siteProblems(site, { max: { for_all_sites: false }, base: { for_all_sites: true, value: null } })).toEqual([]);
  expect(baseHeightOf(site, { max: { for_all_sites: false }, base: { for_all_sites: true, value: 8 } })).toBe(8);
  expect(maxHeightOf(site, perSite)).toBe(20);
});

test("a site differs from its original when a vertex moved, was added or was removed; a drawn site never does", () => {
  const original = { file: "plots.dxf", points: SQUARE };
  const site = { name: "A", points: SQUARE.map((point) => [...point] as SitePoint), height: 20, original };
  expect(differsFromOriginal(site)).toBe(false);
  expect(differsFromOriginal({ ...site, points: [[0, 0, 100 + 1e-12], ...SQUARE.slice(1)] })).toBe(false);     // within rounding
  expect(differsFromOriginal({ ...site, points: [[0, 0, 100.5], ...SQUARE.slice(1)] })).toBe(true);
  expect(differsFromOriginal({ ...site, points: [[0.1, 0, 100], ...SQUARE.slice(1)] })).toBe(true);
  expect(differsFromOriginal({ ...site, points: SQUARE.slice(0, 3) })).toBe(true);
  expect(differsFromOriginal({ ...site, points: [...SQUARE, [0, 15, 100]] })).toBe(true);
  expect(differsFromOriginal({ name: "B", points: SQUARE, height: 20 })).toBe(false);
  expect(differsFromOriginal({ name: "B", points: SQUARE, height: 20, original: null })).toBe(false);
});

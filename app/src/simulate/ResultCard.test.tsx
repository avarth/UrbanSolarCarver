import { act } from "react";
import { afterEach, expect, test } from "vitest";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { StudyStatistics } from "../viewer/study_values";
import { ResultCard } from "./ResultCard";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

/** A number and its unit as the card writes them: with a no-break space between. */
const u = (text: string) => text.replace(/(\d) (h|%|kWh\/m²)/g, "$1 $2");
const lines = (block = ".result-card") => [...rendered!.container.querySelectorAll(`${block} .result-card-line`)].map((line) => line.textContent);
const headings = () => [...rendered!.container.querySelectorAll(".result-card h3")].map((heading) => heading.textContent);
const facingRows = () => [...rendered!.container.querySelectorAll(".result-card-facing")]
  .map((row) => [...row.children].map((cell) => cell.textContent));
const NONE: StudyStatistics = { mean: NaN, lowestTenth: NaN, shareAtTarget: null, keptShare: null };

test("the result card shows what the study's surfaces keep, their mean, lowest tenth and share at the target, with no values beside them", () => {
  rendered = renderForTest(<ResultCard unit="h" surroundings={{ mean: 3.6, lowestTenth: 0.9, shareAtTarget: 0.92, keptShare: 0.989 }} building={null} />);
  expect(rendered.container.querySelector(".result-card")!.getAttribute("aria-label")).toBe("Result");
  expect(headings()).toEqual([]);         // one block needs no heading
  expect(lines()).toEqual(["keeps 99 % of the no-build value", "mean 3.6 h", "lowest tenth 0.9 h", "92 % at or above the target"].map(u));
});

test("a result without test points shows no card, not a mean of NaN", () => {
  rendered = renderForTest(<ResultCard unit="h" surroundings={NONE} building={null} />);
  expect(rendered.container.querySelector(".result-card")).toBeNull();
  expect(rendered.container.textContent).not.toContain("NaN");
});

test("a result whose no-build case gives nothing has no share line", () => {
  rendered = renderForTest(<ResultCard unit="h" surroundings={{ mean: 0, lowestTenth: 0, shareAtTarget: null, keptShare: null }} building={null} />);
  expect(lines()).toEqual(["mean 0 h", "lowest tenth 0 h"].map(u));
});

test("the faces of the study's geometry have a block of their own, with a table by facing", () => {
  const facing = (mean: number, share: number | null): StudyStatistics => ({ mean, lowestTenth: mean / 2, shareAtTarget: share, keptShare: 0.9 });
  rendered = renderForTest(
    <ResultCard unit="kWh/m²" surroundings={{ mean: 412.4, lowestTenth: 120, shareAtTarget: 0.5, keptShare: 0.783 }}
                building={{ stand: "massing", statistics: { mean: 300, lowestTenth: 80, shareAtTarget: 0.4, keptShare: 0.95 },
                            byFacing: { roof: facing(900, 1), N: facing(100, 0), E: null, S: facing(500, 0.75), W: NONE } }} />);
  expect(headings()).toEqual(["Study surfaces", "The massing"]);
  expect(lines(".result-card-building")).toEqual(["keeps 95 % of the no-build value", "mean 300 kWh/m²", "lowest tenth 80 kWh/m²",
                                                   "40 % at or above the target"].map(u));
  // A facing without points (east, west) is left out.
  expect(facingRows()).toEqual([["Roofs", "900", "450", u("100 %")], ["North", "100", "50", u("0 %")], ["South", "500", "250", u("75 %")]]);
});

test("the card minimises to its title bar and shows again; the table by facing is a fold, closed at first", () => {
  const facing: StudyStatistics = { mean: 4, lowestTenth: 2, shareAtTarget: null, keptShare: null };
  rendered = renderForTest(<ResultCard unit="h" surroundings={{ mean: 3, lowestTenth: 1, shareAtTarget: null, keptShare: null }}
                                       building={{ stand: "massing", statistics: facing, byFacing: { roof: facing, N: null, E: null, S: null, W: null } }} />);
  expect(rendered.container.querySelector<HTMLDetailsElement>(".result-card-facings-fold")!.open).toBe(false);
  const toggle = rendered.container.querySelector<HTMLButtonElement>(".result-card-toggle")!;
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  act(() => toggle.click());
  expect(lines()).toEqual([]);
  expect(rendered.container.querySelector(".result-card-title")!.textContent).toBe("Result");
  expect(toggle.getAttribute("aria-label")).toBe("Show the result");
  act(() => toggle.click());
  expect(lines()).toHaveLength(4);
});

test("a study of its geometry's faces alone shows only the building's block, and no target column without a target", () => {
  const facing: StudyStatistics = { mean: 4, lowestTenth: 2, shareAtTarget: null, keptShare: null };
  rendered = renderForTest(<ResultCard unit="h" surroundings={null}
                                       building={{ stand: "envelope", statistics: { mean: 4, lowestTenth: 2, shareAtTarget: null, keptShare: null },
                                                   byFacing: { roof: facing, N: null, E: null, S: null, W: null } }} />);
  expect(headings()).toEqual(["The envelope"]);
  expect(rendered.container.querySelectorAll(".result-card-facings th[scope=col]")).toHaveLength(3);
  expect(facingRows()).toEqual([["Roofs", "4", "2"]]);
});

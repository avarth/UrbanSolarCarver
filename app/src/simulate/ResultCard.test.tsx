import { afterEach, expect, test } from "vitest";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ResultCard } from "./ResultCard";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const lines = () => [...rendered!.container.querySelectorAll(".result-card-line")].map((line) => line.textContent);
const heading = () => rendered!.container.querySelector(".result-card h3")!.textContent;

test("the result card shows the geometry's values with the maximum volume's beside them", () => {
  rendered = renderForTest(<ResultCard geometry="envelope" unit="h" statistics={{ mean: 3.6, lowestTenth: 0.9, shareAtTarget: 0.92, keptShare: 0.989 }}
                                       baseline={{ mean: 4.1, lowestTenth: 1.2, shareAtTarget: 0.85, keptShare: 0.783 }} />);
  expect(rendered.container.querySelector(".result-card")!.getAttribute("aria-label")).toBe("Result");
  expect(heading()).toBe("Envelope (Max volume)");
  expect(lines()).toEqual(["keeps 99 % of the open-site value (78)", "mean 3.6 h (4.1)", "lowest tenth 0.9 h (1.2)", "at target 92 % (85)"]);
});

test("a result without test points shows no card, not a mean of NaN", () => {
  rendered = renderForTest(<ResultCard geometry="envelope" unit="h" statistics={{ mean: NaN, lowestTenth: NaN, shareAtTarget: null, keptShare: null }}
                                       baseline={{ mean: NaN, lowestTenth: NaN, shareAtTarget: null, keptShare: null }} />);
  expect(rendered.container.querySelector(".result-card")).toBeNull();
  expect(rendered.container.textContent).not.toContain("NaN");
});

test("a result whose open site gives nothing has no share line", () => {
  rendered = renderForTest(<ResultCard geometry="max_volume" unit="h" statistics={{ mean: 0, lowestTenth: 0, shareAtTarget: null, keptShare: null }} baseline={null} />);
  expect(lines()).toEqual(["mean 0 h", "lowest tenth 0 h"]);
});

test("without a target the card has the share kept, the mean and the lowest tenth; on the maximum volume no values beside them", () => {
  rendered = renderForTest(<ResultCard geometry="max_volume" unit="kWh/m²" statistics={{ mean: 412.4, lowestTenth: 120, shareAtTarget: null, keptShare: 0.783 }} baseline={null} />);
  expect(heading()).toBe("Max volume");
  expect(lines()).toEqual(["keeps 78 % of the open-site value", "mean 412 kWh/m²", "lowest tenth 120 kWh/m²"]);
});

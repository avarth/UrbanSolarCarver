import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { studyPaletteColour } from "../viewer/study_palettes";
import { TargetLegend, type TargetLegendProps } from "./TargetLegend";
import { press, renderForTest, type RenderedOverlay } from "./render_for_test";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const container = () => rendered!.container;
const bar = () => container().querySelector<HTMLElement>(".target-legend-bar")!;
const mark = (end: "low" | "high") => container().querySelector<HTMLElement>(`[role="slider"][data-end="${end}"]`);

function renderLegend(props: Partial<TargetLegendProps> = {}) {
  const onRangeEndChange = vi.fn();
  rendered = renderForTest(<TargetLegend label="Sun hours" unit="h" mode="value" scale={[0, 8]} low={2} high={6} palette="magma"
                                         onRangeEndChange={onRangeEndChange} {...props} />);
  // jsdom lays nothing out: the bar is 200 px wide, 25 px an hour.
  bar().getBoundingClientRect = () => ({ left: 0, width: 200, top: 0, height: 12, right: 200, bottom: 12, x: 0, y: 0, toJSON: () => ({}) });
  return onRangeEndChange;
}

function pointer(type: "pointerdown" | "pointermove" | "pointerup", clientX: number) {
  act(() => { bar().dispatchEvent(new PointerEvent(type, { bubbles: true, clientX, pointerId: 1, button: 0 })); });
}

const cssColour = (hex: string) => { const probe = document.createElement("span"); probe.style.color = hex; return probe.style.color; };

test("the legend shows the scale and the two ends of the colour range as sliders", () => {
  renderLegend();
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sun hours (h)");
  expect([...container().querySelectorAll(".target-legend-ends > span")].map((end) => end.textContent)).toEqual(["0", "8"]);
  expect(mark("low")!.getAttribute("aria-label")).toBe("Low end of the colours (target)");
  // An end stays 1 % of the bar (0.08 h) short of the other.
  expect([mark("low")!.getAttribute("aria-valuemin"), mark("low")!.getAttribute("aria-valuemax")]).toEqual(["0", "5.92"]);
  expect([mark("high")!.getAttribute("aria-valuemin"), mark("high")!.getAttribute("aria-valuemax")]).toEqual(["2.08", "8"]);
  expect(mark("low")!.getAttribute("aria-valuetext")).toBe("2 h");
  expect([mark("low")!.style.left, mark("high")!.style.left]).toEqual(["25%", "75%"]);
});

test("the bar is coloured as the view is: the low end's colour below it, the high end's above it, the palette between", () => {
  renderLegend();
  const background = bar().style.background;
  const first = cssColour(studyPaletteColour("magma", 0)), last = cssColour(studyPaletteColour("magma", 1));
  // 21 stops over 0 to 8: the first five (0 to 1.6 h) are below the low end, the last five (6.4 to 8 h) above the high end.
  const stops = background.slice(background.indexOf("(") + 1, -1).split(/,\s*(?=rgb)/).slice(1);
  expect(stops.slice(0, 5).every((stop) => stop.trim() === first)).toBe(true);
  expect(stops.slice(-5).every((stop) => stop.trim() === last)).toBe(true);
  expect(stops[10].trim()).toBe(cssColour(studyPaletteColour("magma", 0.5)));     // 4 h, the middle of 2 to 6
});

test("a press moves the nearer end; the drag gives its value once, at the release, and an end does not pass the other", () => {
  const onRangeEndChange = renderLegend();
  pointer("pointerdown", 150);                   // 6 h: the high end
  expect(document.activeElement).toBe(mark("high"));
  pointer("pointermove", 175);
  expect(mark("high")!.getAttribute("aria-valuenow")).toBe("7");
  expect(onRangeEndChange).not.toHaveBeenCalled();
  pointer("pointerup", 175);
  expect(onRangeEndChange).toHaveBeenCalledWith("high", 7);
  pointer("pointerdown", 40);                    // 1.6 h: the low end
  pointer("pointermove", 190);                   // past the high end (6): stops a step short of it
  pointer("pointerup", 190);
  expect(onRangeEndChange).toHaveBeenLastCalledWith("low", 5.92);
});

test("the high end dragged onto the low end stops a step above it, so the range never shrinks to one value", () => {
  const onRangeEndChange = renderLegend({ low: 0 });
  pointer("pointerdown", 150);                   // the high end
  pointer("pointermove", -50);                   // beyond the left of the bar
  pointer("pointerup", -50);
  expect(onRangeEndChange).toHaveBeenLastCalledWith("high", 0.08);
});

test("arrow keys move an end by 1 % of the bar, Home and End to its limits, Delete puts it back to its default", () => {
  const onRangeEndChange = renderLegend();
  expect(press(mark("low")!, "ArrowRight", { focus: true })).toBe(true);
  expect(onRangeEndChange).toHaveBeenLastCalledWith("low", 2.08);
  press(mark("high")!, "PageUp", { focus: true });
  expect(onRangeEndChange).toHaveBeenLastCalledWith("high", 6.8);
  press(mark("low")!, "End", { focus: true });
  expect(onRangeEndChange).toHaveBeenLastCalledWith("low", 5.92);       // up to a step short of the high end
  press(mark("high")!, "Delete", { focus: true });
  expect(onRangeEndChange).toHaveBeenLastCalledWith("high", null);
  expect(press(mark("low")!, "a", { focus: true })).toBe(false);
});

test("by share the scale is 0 to 100 % in viridis, the switch is offered, and no palette is chosen", () => {
  const onColourByChange = vi.fn();
  renderLegend({ mode: "share", scale: [0, 100], low: 20, high: 100, palette: "viridis", onColourByChange });
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sun hours, share of the no-build value");
  expect([...container().querySelectorAll(".target-legend-ends > span")].map((end) => end.textContent))
    .toEqual(["0 %", "100 %"]);
  const buttons = [...container().querySelectorAll<HTMLButtonElement>(".target-legend-colour-by button")];
  expect(buttons.map((button) => [button.textContent, button.getAttribute("aria-pressed")])).toEqual([["Value (h)", "false"], ["% of no-build", "true"]]);
  act(() => buttons[0].click());
  expect(onColourByChange).toHaveBeenCalledWith("value");
  expect(container().querySelector(".target-legend-palette")).toBeNull();
  expect(bar().style.background).toContain(cssColour(studyPaletteColour("viridis", 1)));
});

test("while disabled the ends do not move", () => {
  const onRangeEndChange = renderLegend({ disabled: true });
  expect(mark("low")!.getAttribute("aria-disabled")).toBe("true");
  pointer("pointerdown", 100);
  pointer("pointerup", 100);
  press(mark("low")!, "ArrowRight", { focus: true });
  expect(onRangeEndChange).not.toHaveBeenCalled();
});

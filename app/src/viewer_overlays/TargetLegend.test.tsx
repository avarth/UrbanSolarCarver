import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { studyPaletteColour } from "../viewer/study_palettes";
import { TargetLegend, type TargetLegendProps } from "./TargetLegend";
import { renderForTest, type RenderedOverlay } from "./render_for_test";

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

function keyDown(element: HTMLElement, key: string): boolean {
  act(() => element.focus());
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  act(() => { element.dispatchEvent(event); });
  return event.defaultPrevented;
}

const cssColour = (hex: string) => { const probe = document.createElement("span"); probe.style.color = hex; return probe.style.color; };

test("the legend shows the scale and the two ends of the colour range as sliders", () => {
  renderLegend();
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sun hours (h)");
  expect([...container().querySelectorAll(".target-legend-ends > span")].map((end) => end.textContent)).toEqual(["0", "8"]);
  expect(mark("low")!.getAttribute("aria-label")).toBe("Low end of the colours (target)");
  expect([mark("low")!.getAttribute("aria-valuemin"), mark("low")!.getAttribute("aria-valuemax")]).toEqual(["0", "6"]);   // not past the high end
  expect([mark("high")!.getAttribute("aria-valuemin"), mark("high")!.getAttribute("aria-valuemax")]).toEqual(["2", "8"]);
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
  pointer("pointermove", 190);                   // past the high end (6): stops there
  pointer("pointerup", 190);
  expect(onRangeEndChange).toHaveBeenLastCalledWith("low", 6);
});

test("arrow keys move an end by 1 % of the bar, Home and End to its limits, Delete puts it back to its default", () => {
  const onRangeEndChange = renderLegend();
  expect(keyDown(mark("low")!, "ArrowRight")).toBe(true);
  expect(onRangeEndChange).toHaveBeenLastCalledWith("low", 2.08);
  keyDown(mark("high")!, "PageUp");
  expect(onRangeEndChange).toHaveBeenLastCalledWith("high", 6.8);
  keyDown(mark("low")!, "End");
  expect(onRangeEndChange).toHaveBeenLastCalledWith("low", 6);          // up to the high end
  keyDown(mark("high")!, "Delete");
  expect(onRangeEndChange).toHaveBeenLastCalledWith("high", null);
  expect(keyDown(mark("low")!, "a")).toBe(false);
});

test("by share the scale is 0 to 100 %, and the switch and the palette are offered", () => {
  const onColourByChange = vi.fn(), onPaletteChange = vi.fn();
  renderLegend({ mode: "share", scale: [0, 100], low: 20, high: 100, onColourByChange, onPaletteChange });
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sun hours, share of the no-build value");
  expect([...container().querySelectorAll(".target-legend-ends > span")].map((end) => end.textContent))
    .toEqual(["0 %", "100 %"]);
  const buttons = [...container().querySelectorAll<HTMLButtonElement>(".target-legend-colour-by button")];
  expect(buttons.map((button) => [button.textContent, button.getAttribute("aria-pressed")])).toEqual([["Value (h)", "false"], ["% of no-build", "true"]]);
  act(() => buttons[0].click());
  expect(onColourByChange).toHaveBeenCalledWith("value");
  const select = container().querySelector<HTMLSelectElement>(".target-legend-palette")!;
  expect([...select.options].map((option) => option.textContent)).toEqual(["Magma", "Inferno", "Plasma", "Viridis"]);
  act(() => { select.value = "viridis"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(onPaletteChange).toHaveBeenCalledWith("viridis");
});

test("while disabled the ends do not move", () => {
  const onRangeEndChange = renderLegend({ disabled: true });
  expect(mark("low")!.getAttribute("aria-disabled")).toBe("true");
  pointer("pointerdown", 100);
  pointer("pointerup", 100);
  keyDown(mark("low")!, "ArrowRight");
  expect(onRangeEndChange).not.toHaveBeenCalled();
});

test("the change scale has no ends, and names losses when there are some", () => {
  renderLegend({ mode: "change", scale: [0, 2], hasLoss: true });
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Change from max volume (h)");
  expect(mark("low")).toBeNull();
  expect(container().querySelector(".target-legend-palette")).toBeNull();
  expect(container().querySelector(".target-legend-loss")!.textContent).toBe("Loss");
});

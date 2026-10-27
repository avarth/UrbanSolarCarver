import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { TargetLegend } from "./TargetLegend";
import { renderForTest, type RenderedOverlay } from "./render_for_test";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const container = () => rendered!.container;
const bar = () => container().querySelector<HTMLElement>(".target-legend-bar")!;
const mark = () => container().querySelector<HTMLElement>('[role="slider"]');

function renderLegend(target: number | null, mode: "value" | "change" = "value", disabled = false) {
  const onTargetChange = vi.fn();
  rendered = renderForTest(<TargetLegend label="Sun hours" unit="h" range={[0, 8]} target={target} onTargetChange={onTargetChange} mode={mode} disabled={disabled} />);
  // jsdom lays nothing out: the bar is 200 px wide, 25 px an hour.
  bar().getBoundingClientRect = () => ({ left: 0, width: 200, top: 0, height: 12, right: 200, bottom: 12, x: 0, y: 0, toJSON: () => ({}) });
  return onTargetChange;
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

test("the legend shows the scale in the study's unit and the target as a slider", () => {
  renderLegend(3);
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sun hours (h)");
  expect([...container().querySelectorAll(".target-legend-ends span")].map((end) => end.textContent)).toEqual(["0", "8"]);
  expect(mark()!.getAttribute("aria-label")).toBe("Target");
  expect(mark()!.getAttribute("aria-valuemin")).toBe("0");
  expect(mark()!.getAttribute("aria-valuemax")).toBe("8");
  expect(mark()!.getAttribute("aria-valuenow")).toBe("3");
  expect(mark()!.getAttribute("aria-valuetext")).toBe("3 h");
  expect(mark()!.style.left).toBe("37.5%");
  expect(container().querySelector(".target-legend-below")!.getAttribute("style")).toContain("width: 37.5%");
});

test("dragging the target mark moves it while dragging and gives the target once, at the release", () => {
  const onTargetChange = renderLegend(3);
  pointer("pointerdown", 100);
  expect(document.activeElement).toBe(mark());
  pointer("pointermove", 150);
  expect(mark()!.getAttribute("aria-valuenow")).toBe("6");
  expect(onTargetChange).not.toHaveBeenCalled();
  pointer("pointermove", 260);            // past the end: the top of the range
  expect(mark()!.getAttribute("aria-valuenow")).toBe("8");
  pointer("pointerup", 50);
  expect(onTargetChange).toHaveBeenCalledTimes(1);
  expect(onTargetChange).toHaveBeenCalledWith(8);
});

test("arrow keys move the target by 1 % of the range, Home and End to its ends, Delete clears it", () => {
  const onTargetChange = renderLegend(3);
  expect(keyDown(mark()!, "ArrowRight")).toBe(true);
  expect(onTargetChange).toHaveBeenLastCalledWith(3.08);
  keyDown(mark()!, "ArrowDown");
  expect(onTargetChange).toHaveBeenLastCalledWith(2.92);
  keyDown(mark()!, "End");
  expect(onTargetChange).toHaveBeenLastCalledWith(8);
  keyDown(mark()!, "Delete");
  expect(onTargetChange).toHaveBeenLastCalledWith(null);
  expect(keyDown(mark()!, "a")).toBe(false);
});

test("without a target the slider says so, and a press on the scale sets one", () => {
  const onTargetChange = renderLegend(null);
  expect(mark()!.getAttribute("aria-valuenow")).toBeNull();
  expect(mark()!.getAttribute("aria-valuetext")).toBe("No target");
  expect(container().querySelector(".target-legend-below")).toBeNull();
  keyDown(mark()!, "ArrowUp");
  expect(onTargetChange).toHaveBeenLastCalledWith(0.08);
  pointer("pointerdown", 50);
  pointer("pointerup", 50);
  expect(onTargetChange).toHaveBeenLastCalledWith(2);
});

test("while disabled the target does not move", () => {
  const onTargetChange = renderLegend(3, "value", true);
  expect(mark()!.getAttribute("aria-disabled")).toBe("true");
  pointer("pointerdown", 100);
  pointer("pointerup", 100);
  keyDown(mark()!, "ArrowRight");
  expect(onTargetChange).not.toHaveBeenCalled();
});

test("the change scale has no target, and names losses when there are some", () => {
  rendered = renderForTest(<TargetLegend label="Sun hours" unit="h" range={[0, 2]} target={3} onTargetChange={() => {}} mode="change" hasLoss />);
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Change from max volume (h)");
  expect(mark()).toBeNull();
  expect(container().querySelector(".target-legend-loss")!.textContent).toBe("Loss");
});

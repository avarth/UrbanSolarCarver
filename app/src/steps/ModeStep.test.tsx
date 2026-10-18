import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { renderForTest, click, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ModeStep, tileAfterArrowKey } from "./ModeStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function press(target: Element, key: string): void {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

function focus(element: HTMLElement): void {
  act(() => element.focus());
}

const tiles = () => [...rendered!.container.querySelectorAll<HTMLElement>('[role="radio"]')];

test("the six tiles form one radio group with the chosen mode checked and alone in the tab order", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  expect(rendered.container.querySelector('[role="radiogroup"]')).not.toBeNull();
  expect(tiles().map((tile) => tile.querySelector(".mode-tile-name")!.textContent))
    .toEqual(["Sun at set hours", "Solar energy", "Solar heat when cold", "Daylight", "Angle rule", "Night cooling"]);
  expect(tiles().map((tile) => tile.getAttribute("aria-checked"))).toEqual(["true", "false", "false", "false", "false", "false"]);
  expect(tiles().map((tile) => tile.tabIndex)).toEqual([0, -1, -1, -1, -1, -1]);
  expect(tiles()[5].textContent).toContain("Experimental");
  expect(rendered.container.textContent).toContain("Choosing a mode fills its starting values in Settings.");
});

test("arrow keys move the focus, Space or Enter chooses", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={onChoose} disabledReason={null} weatherDropZone={null} />);
  focus(tiles()[0]);
  press(tiles()[0], "ArrowRight");
  expect(document.activeElement).toBe(tiles()[1]);
  expect(onChoose).not.toHaveBeenCalled();
  press(tiles()[1], "ArrowDown");
  expect(document.activeElement).toBe(tiles()[4]);
  press(tiles()[4], " ");
  expect(onChoose).toHaveBeenLastCalledWith("tilted_plane");
  press(tiles()[4], "ArrowLeft");
  press(tiles()[3], "Enter");
  expect(onChoose).toHaveBeenLastCalledWith("daylight");
});

test("the arrows go round a row and stay in a column", () => {
  expect(tileAfterArrowKey(2, "ArrowRight", 6)).toBe(3);
  expect(tileAfterArrowKey(0, "ArrowLeft", 6)).toBe(5);
  expect(tileAfterArrowKey(1, "ArrowUp", 6)).toBeNull();
  expect(tileAfterArrowKey(4, "ArrowDown", 6)).toBeNull();
  expect(tileAfterArrowKey(4, "Tab", 6)).toBeNull();
});

test("focus on a tile shows its tooltip in the spec's order; Escape closes it", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  focus(tiles()[2]);
  const tooltip = document.querySelector('[role="tooltip"]')!;
  expect([...tooltip.children].map((part) => part.textContent)).toEqual([
    "Solar heat when cold",
    "Like solar energy, counting only hours cold enough to need heating.",
    "Needs a weather file and an analysis period.",
    "Engine name: benefit",
  ]);
  expect(tooltip.querySelector("code")!.textContent).toBe("benefit");
  expect(tiles()[2].getAttribute("aria-describedby")).toBe(tooltip.id);
  press(tiles()[2], "Escape");
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
});

test("the tile's i opens the same tooltip by click", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  click(rendered.container.querySelector('[aria-label="About Angle rule"]')!);
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Needs a plane angle.");
});

test("during a run the mode cannot change, and the reason is shown; the weather drop zone sits under the tiles", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={onChoose} disabledReason="A run is in progress" weatherDropZone={<p>weather box</p>} />);
  click(tiles()[3]);
  expect(onChoose).not.toHaveBeenCalled();
  expect(rendered.container.textContent).toContain("A run is in progress");
  expect(rendered.container.querySelector(".mode-step")!.lastElementChild!.textContent).toBe("weather box");
});

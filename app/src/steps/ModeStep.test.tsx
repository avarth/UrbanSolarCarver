import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest, renderForTest, click, type RenderedOverlay } from "../viewer_overlays/render_for_test";
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

test("the six tiles form one radio group, in the order of R2 3, with the chosen mode checked and alone in the tab order", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  expect(rendered.container.querySelector('[role="radiogroup"]')).not.toBeNull();
  expect(tiles().map((tile) => tile.querySelector(".mode-tile-name")!.textContent))
    .toEqual(["Angle rule", "Solar time-based", "Solar energy", "Solar usefulness", "Daylight", "Night cooling"]);
  expect(tiles().map((tile) => tile.getAttribute("aria-checked"))).toEqual(["false", "true", "false", "false", "false", "false"]);
  expect(tiles().map((tile) => tile.tabIndex)).toEqual([-1, 0, -1, -1, -1, -1]);
  expect(rendered.container.textContent).toContain("Choosing a mode fills its starting values in Settings.");
});

test("a tile shows its symbol and its name only", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  for (const tile of tiles()) {
    expect([...tile.children].map((part) => part.tagName.toLowerCase())).toEqual(["svg", "span"]);
    expect(tile.textContent).toBe(tile.querySelector(".mode-tile-name")!.textContent);
  }
});

test("every symbol has strokes in a colour of the theme, and the sun discs are filled in the sun colour", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  for (const tile of tiles()) {
    const symbol = tile.querySelector("svg")!;
    const strokeColours = [...symbol.querySelectorAll("[stroke]")].map((part) => part.getAttribute("stroke"));
    expect(strokeColours.some((colour) => /^var\(--colour-(accent|test-surface-on-dark|muted)\)$/.test(colour!))).toBe(true);
  }
  const sunDiscs = (index: number) => tiles()[index].querySelectorAll('svg [fill="var(--colour-sun)"]').length;
  expect([0, 1, 2, 3, 4, 5].map(sunDiscs)).toEqual([0, 1, 1, 1, 0, 0]);
});

test("each tile is described by its tooltip's text for a screen reader, before any tooltip is open", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  const description = document.getElementById(tiles()[3].getAttribute("aria-describedby")!)!;
  expect(description.textContent).toBe("Sun in hours that need heating. Like solar energy, counting only hours cold enough to need heating. "
    + "Needs a weather file and an analysis period. Engine name: benefit");
  expect(tiles()[3].contains(description)).toBe(false);       // not part of the tile's name
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
  expect(onChoose).toHaveBeenLastCalledWith("daylight");
  press(tiles()[4], "ArrowLeft");
  press(tiles()[3], "Enter");
  expect(onChoose).toHaveBeenLastCalledWith("benefit");
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
  focus(tiles()[3]);
  const tooltip = document.querySelector('[role="tooltip"]')!;
  expect([...tooltip.children].map((part) => part.textContent)).toEqual([
    "Solar usefulness",
    "Sun in hours that need heating",
    "Like solar energy, counting only hours cold enough to need heating.",
    "Needs a weather file and an analysis period.",
    "Engine name: benefit",
  ]);
  expect(tooltip.querySelector("code")!.textContent).toBe("benefit");
  press(tiles()[3], "Escape");
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
  click(tiles()[4]);
  expect(onChoose).not.toHaveBeenCalled();
  expect(rendered.container.textContent).toContain("A run is in progress");
  expect(rendered.container.querySelector(".mode-step")!.lastElementChild!.textContent).toBe("weather box");
});

// A pointer press on an element, as a browser sends it before the click: pointerdown, then mousedown.
function pressPointer(target: Element): void {
  act(() => {
    target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  });
}

// The pointer moves onto *target* from *from* (React's mouse enter and leave are read from mouseover and mouseout).
function movePointer(from: Element, target: Element): void {
  act(() => {
    from.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: target }));
    target.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, relatedTarget: from }));
  });
}

/** A click with the mouse, as a browser sends it: the press, the focus it gives the tile, the click. */
function clickWithPointer(target: HTMLElement): void {
  pressPointer(target);
  act(() => target.focus());
  click(target);
}

test("a click on a tile leaves no tooltip open once the pointer has left the tile", () => {
  const outside = document.createElement("button");
  document.body.appendChild(outside);
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  movePointer(outside, tiles()[3]);
  clickWithPointer(tiles()[3]);
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Solar usefulness");    // hovered
  movePointer(tiles()[3], outside);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  // The keyboard focus still shows the tooltip.
  focus(tiles()[1]);
  press(tiles()[1], "ArrowRight");
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Solar energy");
  outside.remove();
});

test("a tooltip pinned with the i closes when another tile is chosen or the pointer presses anywhere else", () => {
  const onChoose = vi.fn();
  const outside = document.createElement("button");
  document.body.appendChild(outside);
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={onChoose} disabledReason={null} weatherDropZone={null} />);
  const info = (name: string) => rendered!.container.querySelector(`[aria-label="About ${name}"]`)!;
  pressPointer(info("Daylight"));
  click(info("Daylight"));
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("overcast sky");
  // Another tile of the grid is chosen: the pinned tooltip goes.
  clickWithPointer(tiles()[2]);
  expect(onChoose).toHaveBeenLastCalledWith("irradiance");
  rendered.rerender(<ModeStep mode="irradiance" onChoose={onChoose} disabledReason={null} weatherDropZone={null} />);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  // Pinned again, then a press on another tile's i, which pins that tile's tooltip in its place.
  pressPointer(info("Daylight"));
  click(info("Daylight"));
  pressPointer(info("Angle rule"));
  click(info("Angle rule"));
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Needs a plane angle.");
  expect(document.querySelector('[role="tooltip"]')!.textContent).not.toContain("overcast sky");
  // A press outside the step closes it.
  pressPointer(outside);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  outside.remove();
});

test("the tooltip lets the pointer through, so a click on the tile under it reaches the tile", () => {
  const removeStyles = [addStyleSheetForTest("src/settings_form/settings_form.css"), addStyleSheetForTest("src/steps/steps.css")];
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null} />);
  focus(tiles()[0]);
  const tooltip = document.querySelector<HTMLElement>('[role="tooltip"]')!;
  expect(getComputedStyle(tooltip).pointerEvents).toBe("none");
  removeStyles.forEach((remove) => remove());
});

test("the settings a mode change set back to their defaults are named under the tiles", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null}
                                     valuesReset={{ settings: ["max_slope_deg", "voxel_size"], mode: "time-based" }} />);
  expect(rendered.container.querySelector(".mode-values-reset")!.textContent)
    .toBe("Steepest step between columns and voxel size are back to their defaults: Solar time-based cannot use the values you had set.");
  rendered.rerender(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} weatherDropZone={null}
                              valuesReset={{ settings: ["max_slope_deg"], mode: "time-based" }} />);
  expect(rendered.container.querySelector(".mode-values-reset")!.textContent)
    .toBe("Steepest step between columns is back to its default: Solar time-based cannot use the value you had set.");
});

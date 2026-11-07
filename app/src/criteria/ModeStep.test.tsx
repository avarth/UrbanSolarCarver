import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest, byRole, click, press, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ModeStep, tileAfterArrowKey } from "./ModeStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function focus(element: HTMLElement): void {
  act(() => element.focus());
}

const MODE_NAMES = ["Angle rule", "Sun hours", "Solar energy", "Solar heating", "Daylight", "Night cooling"];
const tiles = () => [...rendered!.container.querySelectorAll<HTMLElement>('[role="radio"]')];
/** The tile of the mode named *name* (its accessible name), so a new order of mode_tiles.json cannot make a test pick another mode. */
const tile = (name: string) => byRole(rendered!.container, "radio", name);

/** The "i" of the tile named *name*. */
function infoButtonOf(name: string): HTMLButtonElement {
  return tile(name).parentElement!.querySelector<HTMLButtonElement>(".mode-tile-info")!;
}

test("the six tiles form one radio group, in the order of R2 3, with the chosen mode checked and alone in the tab order", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  expect(rendered.container.querySelector('[role="radiogroup"]')).not.toBeNull();
  expect(tiles().map((each) => each.querySelector(".mode-tile-name")!.textContent)).toEqual(MODE_NAMES);
  expect(tiles().map((each) => each.getAttribute("aria-checked"))).toEqual(["false", "true", "false", "false", "false", "false"]);
  expect(tiles().map((each) => each.tabIndex)).toEqual([-1, 0, -1, -1, -1, -1]);
});

test("a tile shows its symbol and its name only", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  for (const each of tiles()) {
    expect(each.querySelectorAll("svg")).toHaveLength(1);                                   // one symbol
    expect(each.textContent).toBe(each.querySelector(".mode-tile-name")!.textContent);    // and no text but the name
  }
});

test("every symbol has strokes in a colour of the theme, and the sun discs are filled in the sun colour", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  for (const each of tiles()) {
    const symbol = each.querySelector("svg")!;
    // Every stroke and fill is a token of the theme (or currentColor, the tile's text colour, or none): a hard-coded colour keeps its
    // light-theme value in the dark theme. The svg itself is included, since its stroke is the one the parts without their own inherit.
    const parts = [symbol, ...symbol.querySelectorAll("*")];
    const strokeColours = parts.filter((part) => part.hasAttribute("stroke")).map((part) => part.getAttribute("stroke")!);
    const fillColours = parts.filter((part) => part.hasAttribute("fill")).map((part) => part.getAttribute("fill")!);
    expect(strokeColours.filter((colour) => !/^(var\(--colour-[a-z-]+\)|currentColor)$/.test(colour))).toEqual([]);
    expect(fillColours.filter((colour) => !/^(var\(--colour-[a-z-]+\)|none)$/.test(colour))).toEqual([]);
    // and no symbol is drawn in the text colour alone
    expect(strokeColours.some((colour) => /^var\(--colour-(accent|test-surface-on-dark|muted)\)$/.test(colour))).toBe(true);
  }
  const sunDiscs = (name: string) => tile(name).querySelectorAll('svg [fill="var(--colour-sun)"]').length;
  expect(Object.fromEntries(MODE_NAMES.map((name) => [name, sunDiscs(name)])))
    .toEqual({ "Angle rule": 0, "Sun hours": 1, "Solar energy": 1, "Solar heating": 1, Daylight: 0, "Night cooling": 0 });
});

test("each tile is described by its tooltip's text for a screen reader, before any tooltip is open", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  const description = document.getElementById(tile("Solar heating").getAttribute("aria-describedby")!)!;
  expect(description.textContent).toBe("Sun in hours that need heating. Like solar energy, counting only hours cold enough to need heating. "
    + "Needs a weather file and an analysis period. Engine name: benefit");
  expect(tile("Solar heating").contains(description)).toBe(false);       // not part of the tile's name
});

test("arrow keys move the focus, Space or Enter chooses", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={onChoose} disabledReason={null} />);
  focus(tile("Angle rule"));
  press(tile("Angle rule"), "ArrowRight");
  expect(document.activeElement).toBe(tile("Sun hours"));
  expect(onChoose).not.toHaveBeenCalled();
  press(tile("Sun hours"), "ArrowDown");
  expect(document.activeElement).toBe(tile("Daylight"));
  press(tile("Daylight"), " ");
  expect(onChoose).toHaveBeenLastCalledWith("daylight");
  press(tile("Daylight"), "ArrowLeft");
  expect(document.activeElement).toBe(tile("Solar heating"));
  press(tile("Solar heating"), "Enter");
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
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  focus(tile("Solar heating"));
  const tooltip = document.querySelector('[role="tooltip"]')!;
  expect([...tooltip.children].map((part) => part.textContent)).toEqual([
    "Solar heating",
    "Sun in hours that need heating",
    "Like solar energy, counting only hours cold enough to need heating.",
    "Needs a weather file and an analysis period.",
    "Engine name: benefit",
  ]);
  expect(tooltip.querySelector("code")!.textContent).toBe("benefit");
  press(tile("Solar heating"), "Escape");
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
});

test("the tile's i opens the same tooltip by click, and is hidden from a screen reader, which has the text as the tile's description", () => {
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  for (const name of MODE_NAMES) {
    expect(infoButtonOf(name).getAttribute("aria-hidden")).toBe("true");
    expect(infoButtonOf(name).hasAttribute("aria-expanded")).toBe(false);
  }
  click(infoButtonOf("Angle rule"));
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Uses a plane angle (45° to start).");
  expect(infoButtonOf("Angle rule").dataset.open).toBe("true");      // drawn pressed while its tooltip is pinned
  expect(infoButtonOf("Daylight").dataset.open).toBeUndefined();
});

test("during a run the mode cannot be chosen, and the reason is shown", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={onChoose} disabledReason="A run is in progress" />);
  click(tile("Daylight"));
  expect(onChoose).not.toHaveBeenCalled();
  expect(rendered.container.textContent).toContain("A run is in progress");
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
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  movePointer(outside, tile("Solar heating"));
  clickWithPointer(tile("Solar heating"));
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Solar heating");    // hovered
  movePointer(tile("Solar heating"), outside);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  // The keyboard focus still shows the tooltip.
  focus(tile("Sun hours"));
  press(tile("Sun hours"), "ArrowRight");
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Solar energy");
  outside.remove();
});

test("a tooltip pinned with the i closes when another tile is chosen or the pointer presses anywhere else", () => {
  const onChoose = vi.fn();
  const outside = document.createElement("button");
  document.body.appendChild(outside);
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={onChoose} disabledReason={null} />);
  const info = infoButtonOf;
  pressPointer(info("Daylight"));
  click(info("Daylight"));
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("overcast sky");
  // Another tile of the grid is chosen: the pinned tooltip goes.
  clickWithPointer(tile("Solar energy"));
  expect(onChoose).toHaveBeenLastCalledWith("irradiance");
  rendered.rerender(<ModeStep mode="irradiance" onChoose={onChoose} disabledReason={null} />);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  // Pinned again, then a press on another tile's i, which pins that tile's tooltip in its place.
  pressPointer(info("Daylight"));
  click(info("Daylight"));
  pressPointer(info("Angle rule"));
  click(info("Angle rule"));
  expect(document.querySelector('[role="tooltip"]')!.textContent).toContain("Uses a plane angle (45° to start).");
  expect(document.querySelector('[role="tooltip"]')!.textContent).not.toContain("overcast sky");
  // A press outside the step closes it.
  pressPointer(outside);
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  outside.remove();
});

test("the tooltip lets the pointer through, so a click on the tile under it reaches the tile", () => {
  const removeStyles = [addStyleSheetForTest("src/settings_form/settings_form.css"), addStyleSheetForTest("src/theme/panels.css")];
  rendered = renderForTest(<ModeStep mode="time-based" onChoose={() => {}} disabledReason={null} />);
  focus(tile("Angle rule"));
  const tooltip = document.querySelector<HTMLElement>('[role="tooltip"]')!;
  expect(getComputedStyle(tooltip).pointerEvents).toBe("none");
  removeStyles.forEach((remove) => remove());
});

test("with no mode chosen no tile is checked, the first is in the tab order, and any tile can be chosen", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ModeStep mode={null} onChoose={onChoose} disabledReason={null} />);
  expect(tiles().every((each) => each.getAttribute("aria-checked") === "false")).toBe(true);
  expect(tiles().map((each) => each.tabIndex)).toEqual([0, -1, -1, -1, -1, -1]);
  click(tile("Sun hours"));
  expect(onChoose).toHaveBeenCalledExactlyOnceWith("time-based");
});

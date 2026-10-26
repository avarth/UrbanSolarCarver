// The short menu of the modes under Add criterion: one item per mode (symbol, name, one line), an item that waits with its reason, the
// choice it reports and the keyboard. The tooltip text stays on the tiles of the panel's Mode section.
import { act, useRef, useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { MODE_TILES } from "../steps/step_summaries";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ModeMenu } from "./ModeMenu";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function Harness({ disabledReason = null, onChoose = () => {} }: { disabledReason?: string | null; onChoose?: (mode: string) => void }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button ref={anchor} type="button" onClick={() => setOpen(true)}>Add criterion</button>
      <button type="button">Next control</button>
      {open && <ModeMenu id="mode-menu" anchor={anchor} onChoose={onChoose} onClose={() => setOpen(false)} disabledReason={disabledReason} />}
    </>
  );
}

const openButton = () => [...rendered!.container.querySelectorAll("button")].find((button) => button.textContent === "Add criterion")!;
const items = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];

function press(element: Element, key: string) {
  act(() => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

test("the menu has one item per mode in the order of the tiles: symbol, name and its one line under it", () => {
  rendered = renderForTest(<Harness />);
  click(openButton());
  const menu = rendered.container.querySelector('[role="menu"]')!;
  expect(menu.getAttribute("aria-label")).toBe("Mode of the new criterion");
  expect(items()).toHaveLength(6);
  expect(items().map((item) => item.querySelector(".mode-menu-name")!.textContent)).toEqual(MODE_TILES.map((tile) => tile.plain_name));
  expect(items().map((item) => item.querySelector(".mode-menu-line")!.textContent)).toEqual(MODE_TILES.map((tile) => tile.one_line));
  expect(items().every((item) => item.querySelector("svg.mode-tile-symbol") !== null)).toBe(true);
  expect(items().some((item) => item.getAttribute("aria-disabled") === "true")).toBe(false);
  // Each item is named by its mode and described by its one line.
  expect(items().map((item) => item.getAttribute("aria-label"))).toEqual(MODE_TILES.map((tile) => tile.plain_name));
  expect(items().map((item) => document.getElementById(item.getAttribute("aria-describedby")!)!.textContent)).toEqual(MODE_TILES.map((tile) => tile.one_line));
});

test("choosing an item reports the engine name of its mode", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<Harness onChoose={onChoose} />);
  click(openButton());
  click(items().find((item) => item.querySelector(".mode-menu-name")!.textContent === "Solar usefulness")!);
  expect(onChoose).toHaveBeenCalledExactlyOnceWith("benefit");
});

test("with a reason the items wait: marked, the reason written under them, and choosing one does nothing", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<Harness disabledReason="A run of this project is in progress." onChoose={onChoose} />);
  click(openButton());
  expect(items().every((item) => item.getAttribute("aria-disabled") === "true")).toBe(true);
  const described = items()[0].getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual([MODE_TILES[0].one_line, "A run of this project is in progress."]);
  click(items()[1]);
  expect(onChoose).not.toHaveBeenCalled();
});

test("the menu opens on its first item; the arrows, Home and End move, and Escape closes it and gives the focus back", () => {
  rendered = renderForTest(<Harness />);
  click(openButton());
  expect(document.activeElement).toBe(items()[0]);
  press(document.activeElement!, "ArrowDown");
  expect(document.activeElement).toBe(items()[1]);
  press(document.activeElement!, "ArrowUp");
  press(document.activeElement!, "ArrowUp");
  expect(document.activeElement).toBe(items()[5]);
  press(document.activeElement!, "Home");
  expect(document.activeElement).toBe(items()[0]);
  press(document.activeElement!, "End");
  expect(document.activeElement).toBe(items()[5]);
  press(document.activeElement!, "Escape");
  expect(items()).toEqual([]);
  expect(document.activeElement).toBe(openButton());
});

test("Tab closes the menu and the focus goes on; a press elsewhere or a scroll closes it too", () => {
  rendered = renderForTest(<Harness />);
  click(openButton());
  press(document.activeElement!, "Tab");
  expect(items()).toEqual([]);
  click(openButton());
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(items()).toEqual([]);
  click(openButton());
  act(() => { window.dispatchEvent(new Event("scroll")); });
  expect(items()).toEqual([]);
});

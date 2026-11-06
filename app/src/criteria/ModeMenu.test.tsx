// The short menu of the modes under Add criterion: one item per mode (symbol, name, one line), an item that waits with its reason, the
// choice it reports, what it tells onClose and the tooltip beside an item. The keyboard and what closes a menu are useMenuPopup's (menu_popup.test.tsx).
import { act, useRef, useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { MODE_TILES } from "../modes";
import { click, press, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ModeMenu, placementBesideMenu } from "./ModeMenu";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

interface HarnessProps {
  disabledReason?: string | null;
  onChoose?: (mode: string) => void;
  onClose?: (focusedAnchor: boolean) => void;
}

function Harness({ disabledReason = null, onChoose = () => {}, onClose = () => {} }: HarnessProps) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button ref={anchor} type="button" onClick={() => setOpen(true)}>Add criterion</button>
      <button type="button">Next control</button>
      {open && <ModeMenu id="mode-menu" anchor={anchor} onChoose={onChoose} disabledReason={disabledReason}
                         onClose={(focusedAnchor) => { onClose(focusedAnchor); setOpen(false); }} />}
    </>
  );
}

const openButton = () => [...rendered!.container.querySelectorAll("button")].find((button) => button.textContent === "Add criterion")!;
const items = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];

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
  const described = (item: Element) => item.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(items().map(described)).toEqual(MODE_TILES.map((tile) => [tile.one_line, `${tile.tooltip} ${tile.needs}`]));
});

test("pointing at an item shows its tooltip beside the menu, and leaving the menu takes it away", () => {
  rendered = renderForTest(<Harness />);
  click(openButton());
  const tooltip = () => document.querySelector(".mode-menu-tooltip");
  expect(tooltip()).toBeNull();
  const item = items().find((each) => each.querySelector(".mode-menu-name")!.textContent === "Solar heating")!;
  const tile = MODE_TILES.find((each) => each.plain_name === "Solar heating")!;
  act(() => { item.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); });
  expect(tooltip()!.textContent).toContain(tile.tooltip);
  expect(tooltip()!.textContent).toContain(tile.needs);
  expect(tooltip()!.textContent).toContain("benefit");
  act(() => { rendered!.container.querySelector('[role="menu"]')!.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: document.body })); });
  expect(tooltip()).toBeNull();
});

test("the tooltip stands right of the menu, level with the item; a narrow or short window keeps it inside", () => {
  const rect = (left: number, top: number, right: number, bottom: number) => ({ left, top, right, bottom }) as DOMRect;
  const size = { width: 300, height: 200 };
  expect(placementBesideMenu(rect(10, 100, 370, 500), rect(10, 180, 370, 230), size, { width: 1400, height: 900 })).toEqual({ left: 378, top: 180 });
  expect(placementBesideMenu(rect(10, 100, 370, 500), rect(10, 450, 370, 500), size, { width: 500, height: 600 })).toEqual({ left: 192, top: 392 });
});

test("choosing an item reports the engine name of its mode", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<Harness onChoose={onChoose} />);
  click(openButton());
  click(items().find((item) => item.querySelector(".mode-menu-name")!.textContent === "Solar heating")!);
  expect(onChoose).toHaveBeenCalledExactlyOnceWith("benefit");
});

test("with a reason the items wait: marked, the reason written under them, and choosing one does nothing", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<Harness disabledReason="A run of this project is in progress." onChoose={onChoose} />);
  click(openButton());
  expect(items().every((item) => item.getAttribute("aria-disabled") === "true")).toBe(true);
  const described = items()[0].getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual([MODE_TILES[0].one_line, `${MODE_TILES[0].tooltip} ${MODE_TILES[0].needs}`, "A run of this project is in progress."]);
  click(items()[1]);
  expect(onChoose).not.toHaveBeenCalled();
});

test("the menu opens on its first item; onClose hears that Escape focused the anchor, and that Tab, a press elsewhere and a scroll did not", () => {
  const onClose = vi.fn();
  rendered = renderForTest(<Harness onClose={onClose} />);
  click(openButton());
  expect(document.activeElement).toBe(items()[0]);
  press(document.activeElement!, "Escape");
  expect(items()).toEqual([]);
  expect(document.activeElement).toBe(openButton());
  click(openButton());
  press(document.activeElement!, "Tab");
  click(openButton());
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  click(openButton());
  act(() => { window.dispatchEvent(new Event("scroll")); });
  expect(onClose.mock.calls).toEqual([[true], [false], [false], [false]]);
  expect(items()).toEqual([]);
});

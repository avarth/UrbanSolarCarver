// What every menu of the app gets from useMenuPopup: where the popup is placed (under its anchor, above it when there is no room
// below, by the anchor's left or right edge), the focus on its first item, the keyboard and what closes it. ActionMenu.test.tsx and
// ModeMenu.test.tsx test only what those menus add.
import { act, useRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { useMenuPopup, type MenuAlign } from "./menu_popup";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.restoreAllMocks();
});

function Menu({ align }: { align: MenuAlign }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const { place, open, popup, show, onMenuKeyDown } = useMenuPopup(anchor, align);
  return (
    <>
      <button ref={anchor} type="button" onClick={show}>Open</button>
      {open && (
        <div ref={popup} className="popup" style={place ?? undefined}>
          <ul role="menu" onKeyDown={onMenuKeyDown}>
            {["First", "Second", "Third"].map((label) => (
              <li key={label} role="none"><button type="button" role="menuitem" tabIndex={-1}>{label}</button></li>
            ))}
          </ul>
        </div>
      )}
      <button type="button">Next control</button>
    </>
  );
}

/** The anchor's box and the window's height, and the height the popup measures once it is shown. */
function stubLayout(anchor: { top: number; bottom: number; left: number; right: number }, windowHeight: number, popupHeight: number) {
  vi.spyOn(HTMLButtonElement.prototype, "getBoundingClientRect").mockReturnValue({ ...anchor, x: anchor.left, y: anchor.top, width: anchor.right - anchor.left,
                                                                                     height: anchor.bottom - anchor.top, toJSON: () => ({}) });
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(popupHeight);
  vi.stubGlobal("innerHeight", windowHeight);
}

const popupStyle = () => rendered!.container.querySelector<HTMLElement>(".popup")!.style;
const anchorButton = () => [...rendered!.container.querySelectorAll("button")].find((button) => button.textContent === "Open")!;
const open = () => click(anchorButton());
const items = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];

function press(element: Element, key: string) {
  act(() => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

test("the popup opens 4 px under its anchor, by its left edge for start", () => {
  stubLayout({ top: 100, bottom: 120, left: 40, right: 140 }, 800, 200);
  rendered = renderForTest(<Menu align="start" />);
  open();
  expect(popupStyle().top).toBe("124px");
  expect(popupStyle().left).toBe("40px");
});

test("the popup ends at the anchor's right edge for end", () => {
  stubLayout({ top: 100, bottom: 120, left: 40, right: 140 }, 800, 200);
  vi.stubGlobal("innerWidth", 1000);
  rendered = renderForTest(<Menu align="end" />);
  open();
  expect(popupStyle().right).toBe("860px");
});

test("with no room below and more above, the popup opens above its anchor", () => {
  stubLayout({ top: 680, bottom: 700, left: 40, right: 140 }, 720, 300);
  rendered = renderForTest(<Menu align="start" />);
  open();
  expect(popupStyle().top).toBe("376px");        // anchor top 680 - 4 - popup height 300
});

test("with no room below but less above, it stays under", () => {
  stubLayout({ top: 100, bottom: 120, left: 40, right: 140 }, 300, 300);
  rendered = renderForTest(<Menu align="start" />);
  open();
  expect(popupStyle().top).toBe("124px");
});

test("an open menu focuses its first item; the arrows go round, Home and End to the ends, Escape closes it and focuses the anchor", () => {
  rendered = renderForTest(<Menu align="start" />);
  open();
  expect(document.activeElement).toBe(items()[0]);
  press(document.activeElement!, "ArrowDown");
  expect(document.activeElement).toBe(items()[1]);
  press(document.activeElement!, "ArrowUp");
  press(document.activeElement!, "ArrowUp");
  expect(document.activeElement).toBe(items()[2]);          // up from the first item goes round to the last
  press(document.activeElement!, "ArrowDown");
  expect(document.activeElement).toBe(items()[0]);          // and down from the last to the first
  press(document.activeElement!, "End");
  expect(document.activeElement).toBe(items()[2]);
  press(document.activeElement!, "Home");
  expect(document.activeElement).toBe(items()[0]);
  press(document.activeElement!, "Escape");
  expect(items()).toEqual([]);
  expect(document.activeElement).toBe(anchorButton());
});

test("Tab closes the menu without focusing the anchor; a press elsewhere, a scroll or a resize closes it, a press inside does not", () => {
  rendered = renderForTest(<Menu align="start" />);
  open();
  press(document.activeElement!, "Tab");
  expect(items()).toEqual([]);
  expect(document.activeElement).not.toBe(anchorButton());   // the browser moves the focus on to the next control
  open();
  act(() => { items()[1].dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(items()).toHaveLength(3);
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(items()).toEqual([]);
  open();
  act(() => { window.dispatchEvent(new Event("scroll")); });
  expect(items()).toEqual([]);
  open();
  act(() => { window.dispatchEvent(new Event("resize")); });
  expect(items()).toEqual([]);
});

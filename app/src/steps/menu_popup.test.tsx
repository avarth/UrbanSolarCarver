// Where a menu popup is placed: under its anchor, above it when there is no room below, by the anchor's left or right edge. The
// keyboard and the closing are covered through ActionMenu.test.tsx and ModeMenu.test.tsx.
import { useRef } from "react";
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
          <ul role="menu" onKeyDown={onMenuKeyDown}><li role="none"><button type="button" role="menuitem">Item</button></li></ul>
        </div>
      )}
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
const open = () => click([...rendered!.container.querySelectorAll("button")].find((button) => button.textContent === "Open")!);

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

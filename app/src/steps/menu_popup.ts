// What the menus of the app share (ActionMenu, the modes of Add criterion): the popup is placed in the window under its anchor (above
// it when the room below is too short), so a scrolling list never clips it; an open menu puts the focus on its first item, closes when
// the page scrolls or the window is resized or a press lands elsewhere, and the keyboard moves through its items (arrows, Home, End),
// closes it with Escape (the focus goes back to the anchor) or with Tab (the focus goes on to the next control).
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type RefObject } from "react";

const GAP_UNDER_ANCHOR_PIXELS = 4;

/** "end": the menu ends at the anchor's right edge (a small button at the end of a row); "start": it opens under its left edge. */
export type MenuAlign = "start" | "end";

function placeUnder(anchor: HTMLElement, align: MenuAlign): CSSProperties {
  const box = anchor.getBoundingClientRect();
  const top = box.bottom + GAP_UNDER_ANCHOR_PIXELS;
  return align === "start" ? { top, left: box.left } : { top, right: window.innerWidth - box.right };
}

/**
 * The state of a menu behind (or under) an anchor. `place` is null while the menu is closed; `popup` goes on the element that holds the
 * items, and `onMenuKeyDown` on the element with role "menu". `show` opens it; `hide(true)` closes it and focuses the anchor, which
 * `onHide` is also told about (a menu that is shown only while open, as ModeMenu, takes itself away then). `startOpen`: open at once,
 * the anchor being in the page already.
 */
export function useMenuPopup(anchor: RefObject<HTMLElement | null>, align: MenuAlign, options: { startOpen?: boolean; onHide?: (focusAnchor: boolean) => void } = {}) {
  const { startOpen = false, onHide } = options;
  const [place, setPlace] = useState<CSSProperties | null>(() => (startOpen ? placeUnder(anchor.current!, align) : null));
  const popup = useRef<HTMLDivElement>(null);
  const open = place !== null;

  const show = () => setPlace(placeUnder(anchor.current!, align));
  const hide = (focusAnchor: boolean) => {
    setPlace(null);
    if (focusAnchor) anchor.current?.focus();
    onHide?.(focusAnchor);
  };

  // A menu that would run past the bottom of the window opens above its anchor instead, when there is more room there.
  useLayoutEffect(() => {
    if (!open) return;
    const box = anchor.current!.getBoundingClientRect();
    const menuHeight = popup.current!.offsetHeight;
    const roomBelow = window.innerHeight - box.bottom - GAP_UNDER_ANCHOR_PIXELS;
    const roomAbove = box.top - GAP_UNDER_ANCHOR_PIXELS;
    if (menuHeight > roomBelow && roomAbove > roomBelow) setPlace((current) => ({ ...current, top: box.top - GAP_UNDER_ANCHOR_PIXELS - menuHeight }));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    popup.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    const hideOnPressElsewhere = (event: Event) => {
      const target = event.target instanceof Node ? event.target : null;
      if (!(popup.current?.contains(target) || anchor.current?.contains(target))) hide(false);
    };
    const hideOnMove = () => hide(false);
    document.addEventListener("pointerdown", hideOnPressElsewhere);
    window.addEventListener("scroll", hideOnMove, true);       // capture: a scrolling list moves the anchor too
    window.addEventListener("resize", hideOnMove);
    return () => {
      document.removeEventListener("pointerdown", hideOnPressElsewhere);
      window.removeEventListener("scroll", hideOnMove, true);
      window.removeEventListener("resize", hideOnMove);
    };
  }, [open]);

  const onMenuKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      hide(true);
      return;
    }
    if (event.key === "Tab") return hide(false);       // the focus goes on to the next control of the page
    const entries = [...popup.current!.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    const current = entries.indexOf(document.activeElement as HTMLElement);
    const next = { ArrowDown: (current + 1) % entries.length, ArrowUp: (current - 1 + entries.length) % entries.length, Home: 0,
                   End: entries.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    entries[next].focus();
  };

  return { place, open, popup, show, hide, onMenuKeyDown };
}

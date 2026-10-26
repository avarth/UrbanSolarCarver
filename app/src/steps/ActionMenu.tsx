// A menu of actions behind a button (R2 7.2): a project's (ProjectMenu) and a criterion card's. It opens on a click, Enter, Space or
// the down arrow with the focus on its first item; the arrow keys, Home and End move through it; Escape closes it and gives the
// focus back to its button; Tab or a press elsewhere closes it. It is placed in the window under its button (above it when the room
// below is too short), so a scrolling list never clips it, and it closes when the page scrolls or the window is resized. An item
// with a reason waits: it is marked, the reason is written under the items, and choosing it does nothing.
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode, type Ref } from "react";
import "./steps.css";

const GAP_UNDER_BUTTON_PIXELS = 4;

export interface ActionMenuItem {
  key: string;
  label: string;
  /** Why the item waits now; absent or null when it can be chosen. */
  disabledReason?: string | null;
}

interface ActionMenuProps {
  /** The name of the button and of the menu, "Actions for Daylight on windows". */
  label: string;
  /** What the button shows. */
  symbol: ReactNode;
  items: ActionMenuItem[];
  /** Told the item chosen, once the menu has closed; the focus is then the caller's (a dialog takes it, or the button). */
  onChoose: (key: string) => void;
  /** "end": the menu ends at the button's right edge (a small button at the end of a row); "start": it opens under its left edge. */
  align?: "start" | "end";
  /** More classes of the wrapper and of the button. */
  className?: string;
  buttonClassName?: string;
  buttonRef?: Ref<HTMLButtonElement>;
  /** The id of the line that says why the whole menu waits; the button is then disabled. */
  waitReasonId?: string | null;
}

export function ActionMenu({ label, symbol, items, onChoose, align = "end", className = "", buttonClassName = "", buttonRef, waitReasonId = null }: ActionMenuProps) {
  const [menuPlace, setMenuPlace] = useState<CSSProperties | null>(null);     // null while the menu is closed
  const button = useRef<HTMLButtonElement | null>(null);
  const popup = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const reasonIdPrefix = useId();
  const open = menuPlace !== null;
  const reasons = [...new Set(items.flatMap((item) => (item.disabledReason ? [item.disabledReason] : [])))];
  const reasonIdOf = (reason: string) => `${reasonIdPrefix}-${reasons.indexOf(reason)}`;

  const setButton = (element: HTMLButtonElement | null) => {
    button.current = element;
    if (typeof buttonRef === "function") buttonRef(element);
    else if (buttonRef) buttonRef.current = element;
  };
  const openMenu = () => {
    const anchor = button.current!.getBoundingClientRect();
    const top = anchor.bottom + GAP_UNDER_BUTTON_PIXELS;
    setMenuPlace(align === "start" ? { top, left: anchor.left } : { top, right: window.innerWidth - anchor.right });
  };
  const closeMenu = (focusButton: boolean) => {
    setMenuPlace(null);
    if (focusButton) button.current?.focus();
  };

  // A menu that would run past the bottom of the window opens above its button instead, when there is more room there.
  useLayoutEffect(() => {
    if (!open) return;
    const anchor = button.current!.getBoundingClientRect();
    const menuHeight = popup.current!.offsetHeight;
    const roomBelow = window.innerHeight - anchor.bottom - GAP_UNDER_BUTTON_PIXELS;
    const roomAbove = anchor.top - GAP_UNDER_BUTTON_PIXELS;
    if (menuHeight > roomBelow && roomAbove > roomBelow) setMenuPlace((place) => ({ ...place, top: anchor.top - GAP_UNDER_BUTTON_PIXELS - menuHeight }));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    popup.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    const closeOnPressElsewhere = (event: Event) => {
      const target = event.target instanceof Node ? event.target : null;
      if (!(popup.current?.contains(target) || button.current?.contains(target))) closeMenu(false);
    };
    const closeOnMove = () => closeMenu(false);
    document.addEventListener("pointerdown", closeOnPressElsewhere);
    window.addEventListener("scroll", closeOnMove, true);       // capture: a scrolling list moves the button too
    window.addEventListener("resize", closeOnMove);
    return () => {
      document.removeEventListener("pointerdown", closeOnPressElsewhere);
      window.removeEventListener("scroll", closeOnMove, true);
      window.removeEventListener("resize", closeOnMove);
    };
  }, [open]);

  const openOnArrowDown = (event: KeyboardEvent) => {
    if (event.key !== "ArrowDown" || open) return;
    event.preventDefault();
    openMenu();
  };

  const moveThroughMenu = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
      return;
    }
    if (event.key === "Tab") return closeMenu(false);       // the focus goes on to the next control of the page
    const entries = [...popup.current!.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    const current = entries.indexOf(document.activeElement as HTMLElement);
    const next = { ArrowDown: (current + 1) % entries.length, ArrowUp: (current - 1 + entries.length) % entries.length, Home: 0,
                   End: entries.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    entries[next].focus();
  };

  const choose = (item: ActionMenuItem) => {
    if (item.disabledReason) return;
    closeMenu(false);
    onChoose(item.key);
  };

  return (
    <div className={`action-menu ${className}`.trim()}>
      <button ref={setButton} type="button" className={`action-menu-button ${buttonClassName}`.trim()} aria-label={label} aria-haspopup="menu"
              aria-expanded={open} aria-controls={open ? menuId : undefined} disabled={waitReasonId !== null} aria-describedby={waitReasonId ?? undefined}
              onClick={() => (open ? closeMenu(false) : openMenu())} onKeyDown={openOnArrowDown}>
        {symbol}
      </button>
      {open && (
        <div ref={popup} className="action-menu-popup" style={menuPlace}>
          <ul id={menuId} role="menu" aria-label={label} onKeyDown={moveThroughMenu}>
            {items.map((item) => (
              <li key={item.key} role="none">
                <button type="button" role="menuitem" tabIndex={-1} aria-disabled={item.disabledReason ? true : undefined}
                        aria-describedby={item.disabledReason ? reasonIdOf(item.disabledReason) : undefined} onClick={() => choose(item)}>
                  {item.label}
                </button>
              </li>
            ))}
          </ul>
          {reasons.map((reason) => <p key={reason} id={reasonIdOf(reason)} className="action-menu-reason">{reason}</p>)}
        </div>
      )}
    </div>
  );
}

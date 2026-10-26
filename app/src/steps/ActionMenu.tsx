// A menu of actions behind a button (R2 7.2): a project's (ProjectMenu) and a criterion card's. It opens on a click, Enter, Space or
// the down arrow with the focus on its first item; the arrow keys, Home and End move through it; Escape closes it and gives the
// focus back to its button; Tab or a press elsewhere closes it. It is placed in the window under its button (above it when the room
// below is too short), so a scrolling list never clips it, and it closes when the page scrolls or the window is resized. An item
// with a reason waits: it is marked, the reason is written under the items, and choosing it does nothing. The placement and the
// keyboard are menu_popup.ts's, shared with the menu of the modes under Add criterion (ModeMenu).
import { useId, useRef, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { useMenuPopup, type MenuAlign } from "./menu_popup";
import "./steps.css";

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
  align?: MenuAlign;
  /** More classes of the wrapper and of the button. */
  className?: string;
  buttonClassName?: string;
  buttonRef?: Ref<HTMLButtonElement>;
  /** The id of the line that says why the whole menu waits; the button is then disabled. */
  waitReasonId?: string | null;
}

export function ActionMenu({ label, symbol, items, onChoose, align = "end", className = "", buttonClassName = "", buttonRef, waitReasonId = null }: ActionMenuProps) {
  const button = useRef<HTMLButtonElement | null>(null);
  const { place, open, popup, show, hide, onMenuKeyDown } = useMenuPopup(button, align);
  const menuId = useId();
  const reasonIdPrefix = useId();
  const reasons = [...new Set(items.flatMap((item) => (item.disabledReason ? [item.disabledReason] : [])))];
  const reasonIdOf = (reason: string) => `${reasonIdPrefix}-${reasons.indexOf(reason)}`;

  const setButton = (element: HTMLButtonElement | null) => {
    button.current = element;
    if (typeof buttonRef === "function") buttonRef(element);
    else if (buttonRef) buttonRef.current = element;
  };

  const openOnArrowDown = (event: KeyboardEvent) => {
    if (event.key !== "ArrowDown" || open) return;
    event.preventDefault();
    show();
  };

  const choose = (item: ActionMenuItem) => {
    if (item.disabledReason) return;
    hide(false);
    onChoose(item.key);
  };

  return (
    <div className={`action-menu ${className}`.trim()}>
      <button ref={setButton} type="button" className={`action-menu-button ${buttonClassName}`.trim()} aria-label={label} aria-haspopup="menu"
              aria-expanded={open} aria-controls={open ? menuId : undefined} disabled={waitReasonId !== null} aria-describedby={waitReasonId ?? undefined}
              onClick={() => (open ? hide(false) : show())} onKeyDown={openOnArrowDown}>
        {symbol}
      </button>
      {open && (
        <div ref={popup} className="action-menu-popup" style={place ?? undefined}>
          <ul id={menuId} role="menu" aria-label={label} onKeyDown={onMenuKeyDown}>
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

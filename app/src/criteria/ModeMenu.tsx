// The short menu of the modes under Add criterion: one item per mode, in the order of the mode tiles, with its symbol, its name and
// its one line under it (the item is named by the mode, described by the line). The full tooltip text stays on the tiles of the panel's Mode section. It is shown only while open, under
// its anchor (the Add criterion button, which stays where it is); the placement and the keyboard are those of ActionMenu
// (menu_popup.ts). While `disabledReason` is set the items wait: they are marked, the reason is written under them and choosing
// one does nothing.
import { useId, type RefObject } from "react";
import { messages } from "../messages";
import { useMenuPopup } from "../steps/menu_popup";
import { ModeTileSymbol } from "../steps/ModeTileSymbols";
import { MODE_TILES } from "../steps/step_summaries";

interface ModeMenuProps {
  /** The menu's id, which the anchor names (aria-controls) while the menu is open. */
  id: string;
  /** The button the menu opens under; a press on it is not a press elsewhere. */
  anchor: RefObject<HTMLElement | null>;
  /** The engine name of the mode chosen. */
  onChoose: (mode: string) => void;
  /**
   * Told when the menu closes by itself (Escape, Tab, a press elsewhere, a scroll, a resize); true when it was Escape, which has tried
   * to give the focus back to the anchor (it cannot while the anchor is disabled).
   */
  onClose: (focusedAnchor: boolean) => void;
  /** Why the modes cannot be chosen now; null when they can. */
  disabledReason: string | null;
}

export function ModeMenu({ id, anchor, onChoose, onClose, disabledReason }: ModeMenuProps) {
  const { place, popup, onMenuKeyDown } = useMenuPopup(anchor, "start", { startOpen: true, onHide: onClose });
  const reasonId = useId();
  const lineIdPrefix = useId();
  return (
    <div ref={popup} className="action-menu-popup mode-menu" style={place ?? undefined}>
      <ul id={id} role="menu" aria-label={messages.newCriterionModeTitle} onKeyDown={onMenuKeyDown}>
        {MODE_TILES.map((tile) => (
          <li key={tile.engine_name} role="none">
            <button type="button" role="menuitem" tabIndex={-1} aria-disabled={disabledReason !== null ? true : undefined}
                    aria-label={tile.plain_name}
                    aria-describedby={disabledReason !== null ? `${lineIdPrefix}${tile.engine_name} ${reasonId}` : `${lineIdPrefix}${tile.engine_name}`}
                    onClick={() => { if (disabledReason === null) onChoose(tile.engine_name); }}>
              <ModeTileSymbol symbol={tile.symbol} />
              <span className="mode-menu-text">
                <span className="mode-menu-name">{tile.plain_name}</span>
                <span id={`${lineIdPrefix}${tile.engine_name}`} className="mode-menu-line">{tile.one_line}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {disabledReason !== null && <p id={reasonId} className="action-menu-reason">{disabledReason}</p>}
    </div>
  );
}

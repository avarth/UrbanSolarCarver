// The short menu of the modes under Add criterion: one item per mode, in the order of the mode tiles, with its symbol, its name and
// its one line under it (the item is named by the mode, described by the line and the tile's tooltip text). Pointing at an item, or
// reaching it with the keyboard, shows that text beside the menu, as a mode tile does. The menu is shown only while open, under
// its anchor (the Add criterion button, which stays where it is); the placement and the keyboard are those of ActionMenu
// (menu_popup.ts). While `disabledReason` is set the items wait: they are marked, the reason is written under them and choosing
// one does nothing.
import { useId, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { messages } from "../messages";
import { useMenuPopup } from "../common/menu_popup";
import { ModeTileSymbol } from "./ModeTileSymbols";
import { ModeTooltipContent } from "./ModeTooltipContent";
import { MODE_TILES } from "../modes";

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

const GAP_BESIDE_MENU_PIXELS = 8;
const WINDOW_MARGIN_PIXELS = 8;

/** Where the tooltip of an item goes: right of the menu, level with the item; over the menu when the window has no room, inside it always. */
export function placementBesideMenu(menu: DOMRect, item: DOMRect, tooltip: { width: number; height: number }, windowSize: { width: number; height: number }) {
  return {
    left: Math.max(WINDOW_MARGIN_PIXELS, Math.min(menu.right + GAP_BESIDE_MENU_PIXELS, windowSize.width - tooltip.width - WINDOW_MARGIN_PIXELS)),
    top: Math.max(WINDOW_MARGIN_PIXELS, Math.min(item.top, windowSize.height - tooltip.height - WINDOW_MARGIN_PIXELS)),
  };
}

export function ModeMenu({ id, anchor, onChoose, onClose, disabledReason }: ModeMenuProps) {
  const { place, popup, onMenuKeyDown } = useMenuPopup(anchor, "start", { startOpen: true, onHide: onClose });
  const reasonId = useId();
  const lineIdPrefix = useId();
  const helpIdPrefix = useId();
  const list = useRef<HTMLUListElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState<{ index: number; item: HTMLElement } | null>(null);
  const [tooltipPlace, setTooltipPlace] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    if (shown === null || list.current === null || tooltip.current === null) return;
    setTooltipPlace(placementBesideMenu(list.current.getBoundingClientRect(), shown.item.getBoundingClientRect(),
                                        { width: tooltip.current.offsetWidth, height: tooltip.current.offsetHeight },
                                        { width: window.innerWidth, height: window.innerHeight }));
  }, [shown]);
  const shownTile = shown === null ? null : MODE_TILES[shown.index];
  return (
    <div ref={popup} className="action-menu-popup mode-menu" style={place ?? undefined}>
      <ul ref={list} id={id} role="menu" aria-label={messages.newCriterionModeTitle} onKeyDown={onMenuKeyDown} onMouseLeave={() => setShown(null)}>
        {MODE_TILES.map((tile, index) => (
          <li key={tile.engine_name} role="none">
            <button type="button" role="menuitem" tabIndex={-1} aria-disabled={disabledReason !== null ? true : undefined}
                    aria-label={tile.plain_name}
                    aria-describedby={`${lineIdPrefix}${tile.engine_name} ${helpIdPrefix}${tile.engine_name}${disabledReason !== null ? ` ${reasonId}` : ""}`}
                    onMouseEnter={(event) => setShown({ index, item: event.currentTarget })}
                    onFocus={(event) => { if (event.currentTarget.matches(":focus-visible")) setShown({ index, item: event.currentTarget }); }}
                    onBlur={() => setShown(null)}
                    onClick={() => { if (disabledReason === null) onChoose(tile.engine_name); }}>
              <ModeTileSymbol symbol={tile.symbol} />
              <span className="mode-menu-text">
                <span className="mode-menu-name">{tile.plain_name}</span>
                <span id={`${lineIdPrefix}${tile.engine_name}`} className="mode-menu-line">{tile.one_line}</span>
              </span>
              <span id={`${helpIdPrefix}${tile.engine_name}`} className="visually-hidden">{`${tile.tooltip} ${tile.needs}`}</span>
            </button>
          </li>
        ))}
      </ul>
      {disabledReason !== null && <p id={reasonId} className="action-menu-reason">{disabledReason}</p>}
      {shownTile !== null && (
        // Seen, not read: a screen reader has the same text as the item's description already.
        <div ref={tooltip} role="tooltip" aria-hidden="true" className="setting-tooltip mode-tooltip mode-menu-tooltip"
             style={tooltipPlace === null ? { visibility: "hidden" } : tooltipPlace}>
          <ModeTooltipContent tile={shownTile} />
        </div>
      )}
    </div>
  );
}

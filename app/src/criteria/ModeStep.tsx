// The mode of a new project's first criterion (UX 5.3, 12; R2 3), shown by the Criteria step until it is chosen: six tiles in a 3 x 2
// radio group, each with its symbol and plain name only. Arrow keys move the focus, Space or Enter chooses. Hovering a tile, focusing it with the keyboard, or clicking its "i", shows the tile's tooltip
// (plain name, one line, longer description, what the mode needs, engine name), which Escape closes. The same text, after the
// name, is the tile's description for a screen reader at all times. The focus a mouse click gives a tile does not hold the
// tooltip open: it goes when the pointer leaves. A tooltip pinned with the "i" goes when a press lands anywhere but on that
// tile's "i", or another mode is chosen. The tooltip lets the pointer through, so it never takes a click meant for the tile under it.
// The "i" is for the pointer and touch only: a screen reader has its text as the tile's description already.
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { useChangedDuringRender } from "../hooks/use_changed_during_render";
import { messages } from "../messages";
import { placedTooltipStyle, placementUnder, type TooltipPlacement } from "../settings_form/SettingTooltip";
import { ModeTileSymbol } from "./ModeTileSymbols";
import { ModeTooltipContent } from "./ModeTooltipContent";
import { MODE_TILES } from "../modes";
import "../theme/panels.css";

const TILES_PER_ROW = 3;

interface ModeStepProps {
  /** The mode shown as chosen; null while none is. */
  mode: string | null;
  onChoose: (mode: string) => void;
  /** Why the mode cannot be chosen now (a run is in progress); null when it can. */
  disabledReason: string | null;
}

/** The tile the focus moves to from *index* for an arrow key; null for another key or a move off the grid. */
export function tileAfterArrowKey(index: number, key: string, tileCount: number): number | null {
  const moves: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: TILES_PER_ROW, ArrowUp: -TILES_PER_ROW };
  if (!(key in moves)) return null;
  const next = index + moves[key];
  if (key === "ArrowRight" || key === "ArrowLeft") return (next + tileCount) % tileCount;      // round the grid
  return next >= 0 && next < tileCount ? next : null;                                          // stay in the column
}

const chosenIndexOf = (mode: string | null) => Math.max(0, MODE_TILES.findIndex((tile) => tile.engine_name === mode));

export function ModeStep({ mode, onChoose, disabledReason }: ModeStepProps) {
  const chosenIndex = chosenIndexOf(mode);
  const [focusIndex, setFocusIndex] = useState(chosenIndex);    // the tile in the tab order
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);
  const [pinnedIndex, setPinnedIndex] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState(false);       // Escape closes the tooltip while the pointer or focus is still on it
  const [placement, setPlacement] = useState<TooltipPlacement | null>(null);
  const tiles = useRef<(HTMLDivElement | null)[]>([]);
  const infoButtons = useRef<(HTMLButtonElement | null)[]>([]);
  // A pointer press is under way: the focus it gives a tile is not the keyboard's, and opens no tooltip.
  const pointerPressing = useRef(false);
  const tooltip = useRef<HTMLDivElement>(null);
  const descriptionIdPrefix = useId();
  const groupLabelId = useId();
  const openIndex = pinnedIndex ?? (dismissed ? null : hoveredIndex ?? focusedIndex);
  const disabled = disabledReason !== null;

  useChangedDuringRender(mode, (modeBefore) => {
    if (chosenIndexOf(modeBefore) !== chosenIndex) setFocusIndex(chosenIndex);
    setPinnedIndex(null);                                   // another mode was chosen: a pinned tooltip goes
  });

  useEffect(() => {
    const pressStarts = () => { pointerPressing.current = true; };
    const pressEnds = () => { pointerPressing.current = false; };
    document.addEventListener("pointerdown", pressStarts, true);
    // A touch focuses the tile after the pointer is up, so the press ends with its click (or the next key, after a drag).
    document.addEventListener("click", pressEnds, true);
    document.addEventListener("keydown", pressEnds, true);
    return () => {
      document.removeEventListener("pointerdown", pressStarts, true);
      document.removeEventListener("click", pressEnds, true);
      document.removeEventListener("keydown", pressEnds, true);
    };
  }, []);
  useEffect(() => {
    if (openIndex === null) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setPinnedIndex(null);
      setDismissed(true);
    };
    // A press on the pinned tile's own "i" toggles it there; any other press, another tile included, unpins it.
    const unpinOnPointerDownElsewhere = (event: Event) => {
      setPinnedIndex((pinned) => {
        const pinnedInfo = pinned === null ? null : infoButtons.current[pinned];
        return event.target instanceof Node && pinnedInfo?.contains(event.target) ? pinned : null;
      });
    };
    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", unpinOnPointerDownElsewhere);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", unpinOnPointerDownElsewhere);
    };
  }, [openIndex]);

  const [placedIndex, setPlacedIndex] = useState(openIndex);
  if (placedIndex !== openIndex) {
    setPlacedIndex(openIndex);
    setPlacement(null);
  }
  useLayoutEffect(() => {
    if (openIndex === null) return;
    const place = () => {
      const tile = tiles.current[openIndex];
      if (tile && tooltip.current) setPlacement(placementUnder(tile, tooltip.current));
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [openIndex]);

  const choose = (index: number) => {
    if (!disabled && MODE_TILES[index].engine_name !== mode) onChoose(MODE_TILES[index].engine_name);
  };
  const onTileKeyDown = (event: KeyboardEvent, index: number) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      choose(index);
      return;
    }
    const next = tileAfterArrowKey(index, event.key, MODE_TILES.length);
    if (next === null) return;
    event.preventDefault();
    setFocusIndex(next);
    tiles.current[next]?.focus();
  };

  const openTile = openIndex === null ? null : MODE_TILES[openIndex];
  return (
    <div className="mode-step">
      <span id={groupLabelId} className="visually-hidden">{messages.modeGroupLabel}</span>
      <div className="mode-tiles" role="radiogroup" aria-labelledby={groupLabelId} aria-disabled={disabled || undefined}>
        {MODE_TILES.map((tile, index) => {
          const chosen = tile.engine_name === mode;
          const descriptionId = `${descriptionIdPrefix}-${index}`;
          return (
            <div key={tile.engine_name} className="mode-tile-cell"
                 onMouseEnter={() => { setHoveredIndex(index); setDismissed(false); }}
                 onMouseLeave={() => setHoveredIndex((current) => (current === index ? null : current))}>
              <div ref={(element) => { tiles.current[index] = element; }} className="mode-tile" data-line={tile.one_line} role="radio" aria-checked={chosen}
                   aria-disabled={disabled || undefined} aria-describedby={descriptionId}
                   tabIndex={index === focusIndex ? 0 : -1} onClick={() => choose(index)} onKeyDown={(event) => onTileKeyDown(event, index)}
                   onFocus={() => {
                     setFocusIndex(index);
                     if (pointerPressing.current) return;
                     setFocusedIndex(index);
                     setDismissed(false);
                   }}
                   onBlur={() => setFocusedIndex((current) => (current === index ? null : current))}>
                <ModeTileSymbol symbol={tile.symbol} />
                <span className="mode-tile-name">{tile.plain_name}</span>
              </div>
              {/* outside the radio, so it describes the tile without becoming part of its name */}
              <span id={descriptionId} className="visually-hidden">
                {messages.modeTileDescription(tile.one_line, tile.tooltip, tile.needs, tile.engine_name)}
              </span>
              {/* outside the radio, so the tile holds no control of its own; the tile's focus already opens the tooltip */}
              <button ref={(element) => { infoButtons.current[index] = element; }} type="button" className="setting-info mode-tile-info" tabIndex={-1}
                      aria-hidden="true" data-open={openIndex === index || undefined}
                      onClick={() => { setDismissed(pinnedIndex === index); setPinnedIndex(pinnedIndex === index ? null : index); }}>
                i
              </button>
            </div>
          );
        })}
      </div>
      {openTile && (
        // Seen, not read: a screen reader has the same text as the tile's description already.
        <div ref={tooltip} role="tooltip" aria-hidden="true" className="setting-tooltip mode-tooltip"
             style={placedTooltipStyle(placement)}>
          <ModeTooltipContent tile={openTile} />
        </div>
      )}
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
    </div>
  );
}

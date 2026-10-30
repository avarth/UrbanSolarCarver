// The "i" beside a setting and its tooltip (UX 7, 12): the help text, then the config name and default in 12 px muted with the
// name in monospace, then an extra line (the grid of the voxel size). Beside a result (a number tile) it holds the help alone. It
// opens on hover, focus and click and closes with Escape; a click opens it until the next click or a press elsewhere. The pointer
// may move from the "i" onto the tooltip without closing it. It is placed in the window, under its "i", so the panel's scrolling
// never clips it.
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { messages, type MessagePart } from "../messages";
import "./settings_form.css";

const WINDOW_MARGIN_PIXELS = 8;
const GAP_UNDER_INFO_BUTTON_PIXELS = 8;

interface SettingTooltipProps {
  settingLabel: string;
  help: string;
  /** The config name and default of a setting; a result's "i" (a number tile) has neither. */
  configName?: string;
  defaultText?: string;
  extraLine?: string;
}

export interface TooltipPlacement {
  top: number;
  left: number;
  arrowLeft: number;
  /** The tooltip opens over its anchor, its arrow at its foot. */
  above: boolean;
}

/**
 * Under the anchor (an "i", a mode tile), centred on it, moved sideways as little as keeps it inside the window; over the anchor
 * when under it would leave the window or cover a part that stays clear of tooltips (data-tooltips-stay-clear: the pinned run
 * bar, whose buttons must stay in view), and there is room over it.
 */
export function placementUnder(infoButton: HTMLElement, tooltip: HTMLElement): TooltipPlacement {
  const anchor = infoButton.getBoundingClientRect();
  const anchorCentre = anchor.left + anchor.width / 2;
  const widestLeft = window.innerWidth - tooltip.offsetWidth - WINDOW_MARGIN_PIXELS;
  const left = Math.max(WINDOW_MARGIN_PIXELS, Math.min(anchorCentre - tooltip.offsetWidth / 2, widestLeft));
  const under = anchor.bottom + GAP_UNDER_INFO_BUTTON_PIXELS;
  let lowestBottom = window.innerHeight - WINDOW_MARGIN_PIXELS;
  for (const clear of document.querySelectorAll<HTMLElement>("[data-tooltips-stay-clear]")) {
    const rect = clear.getBoundingClientRect();
    if (rect.top >= anchor.bottom && rect.left < left + tooltip.offsetWidth && rect.right > left) lowestBottom = Math.min(lowestBottom, rect.top - WINDOW_MARGIN_PIXELS);
  }
  const over = anchor.top - GAP_UNDER_INFO_BUTTON_PIXELS - tooltip.offsetHeight;
  const above = under + tooltip.offsetHeight > lowestBottom && over >= WINDOW_MARGIN_PIXELS;
  return { top: above ? over : under, left, arrowLeft: anchorCentre - left, above };
}

/** The style of a tooltip at *placement*; hidden until it is placed, so it never shows where it would first land. */
export function placedTooltipStyle(placement: TooltipPlacement | null): CSSProperties {
  if (placement === null) return { visibility: "hidden" };
  const style: Record<string, string | number> = { top: placement.top, left: placement.left, "--setting-tooltip-arrow-left": `${placement.arrowLeft}px` };
  if (placement.above) Object.assign(style, { "--setting-tooltip-arrow-top": "calc(100% - 5px)", "--setting-tooltip-arrow-turn": "225deg", "--setting-tooltip-bridge-top": "100%" });
  return style as CSSProperties;
}

export function MessageParts({ parts }: { parts: MessagePart[] }) {
  return <>{parts.map((part, index) => (typeof part === "string" ? part : <code key={index}>{part.code}</code>))}</>;
}

export function SettingTooltip({ settingLabel, help, configName, defaultText, extraLine }: SettingTooltipProps) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinnedByClick, setPinnedByClick] = useState(false);
  // Escape, or the click that unpins it, closes the tooltip even while the pointer or the focus is still on the "i".
  const [dismissed, setDismissed] = useState(false);
  const [placement, setPlacement] = useState<TooltipPlacement | null>(null);
  const tooltipId = useId();
  const infoButton = useRef<HTMLButtonElement>(null);
  const tooltip = useRef<HTMLSpanElement>(null);
  const anchor = useRef<HTMLSpanElement>(null);     // the "i" and the tooltip: the pointer over either keeps the tooltip open
  const open = pinnedByClick || ((hovered || focused) && !dismissed);

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setPinnedByClick(false);
      setDismissed(true);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const closeOnPointerDownElsewhere = (event: Event) => {
      if (!(event.target instanceof Node && anchor.current?.contains(event.target))) close();
    };
    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOnPointerDownElsewhere);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", closeOnPointerDownElsewhere);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      if (infoButton.current && tooltip.current) setPlacement(placementUnder(infoButton.current, tooltip.current));
    };
    place();
    window.addEventListener("scroll", place, true);     // capture: the panel's own scrolling moves the "i" too
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  const toggleByClick = () => {
    setDismissed(pinnedByClick);
    setPinnedByClick(!pinnedByClick);
  };
  const tooltipStyle = placedTooltipStyle(placement);

  return (
    <span ref={anchor} className="setting-info-anchor"
          onMouseEnter={() => { setHovered(true); setDismissed(false); }}
          onMouseLeave={() => setHovered(false)}>
      <button ref={infoButton} type="button" className="setting-info" aria-label={messages.aboutSetting(settingLabel)}
              aria-expanded={open} aria-describedby={open ? tooltipId : undefined}
              onFocus={() => { setFocused(true); setDismissed(false); }} onBlur={() => setFocused(false)} onClick={toggleByClick}>
        i
      </button>
      {open && (
        <span ref={tooltip} id={tooltipId} role="tooltip" className="setting-tooltip" style={tooltipStyle}>
          <span className="setting-tooltip-help">{help}</span>
          {configName !== undefined && defaultText !== undefined && (
            <span className="setting-tooltip-config"><MessageParts parts={messages.configNameAndDefault(configName, defaultText)} /></span>
          )}
          {extraLine && <span className="setting-tooltip-extra">{extraLine}</span>}
        </span>
      )}
    </span>
  );
}

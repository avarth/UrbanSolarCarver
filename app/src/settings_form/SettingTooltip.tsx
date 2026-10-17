// The "i" beside a setting and its tooltip (UX 7, 12): the help text, then the config name and default in 12 px muted with the
// name in monospace, then an extra line (the grid of the voxel size). It opens on hover, focus and click and closes with Escape;
// a click opens it until the next click. It is placed in the window, under its "i", so the panel's scrolling never clips it.
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { messages, type MessagePart } from "../messages";
import "./settings_form.css";

const WINDOW_MARGIN_PIXELS = 8;
const GAP_UNDER_INFO_BUTTON_PIXELS = 8;

interface SettingTooltipProps {
  settingLabel: string;
  help: string;
  configName: string;
  defaultText: string;
  extraLine?: string;
}

interface TooltipPlacement {
  top: number;
  left: number;
  arrowLeft: number;
}

/** Under the "i", centred on it, moved sideways as little as keeps it inside the window. */
function placementUnder(infoButton: HTMLElement, tooltip: HTMLElement): TooltipPlacement {
  const anchor = infoButton.getBoundingClientRect();
  const anchorCentre = anchor.left + anchor.width / 2;
  const widestLeft = window.innerWidth - tooltip.offsetWidth - WINDOW_MARGIN_PIXELS;
  const left = Math.max(WINDOW_MARGIN_PIXELS, Math.min(anchorCentre - tooltip.offsetWidth / 2, widestLeft));
  return { top: anchor.bottom + GAP_UNDER_INFO_BUTTON_PIXELS, left, arrowLeft: anchorCentre - left };
}

function MessageParts({ parts }: { parts: MessagePart[] }) {
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
  const open = pinnedByClick || ((hovered || focused) && !dismissed);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setPinnedByClick(false);
      setDismissed(true);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
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
  const tooltipStyle = placement === null ? { visibility: "hidden" } as CSSProperties
    : { top: placement.top, left: placement.left, "--setting-tooltip-arrow-left": `${placement.arrowLeft}px` } as CSSProperties;

  return (
    <span className="setting-info-anchor"
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
          <span className="setting-tooltip-config"><MessageParts parts={messages.configNameAndDefault(configName, defaultText)} /></span>
          {extraLine && <span className="setting-tooltip-extra">{extraLine}</span>}
        </span>
      )}
    </span>
  );
}

// The layers menu of UX 8.2, top right of the 3D view: the layers of the current mode and results, each with a check box; a
// layer whose stage has no result says so; the sky dome entry has a transparency slider.
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { messages } from "../messages";
import { LAYER_NAMES } from "../viewer/layers";
import type { LayerName, ViewportTheme } from "../viewer/scene";
import "./overlays.css";

export interface LayersMenuEntry {
  name: LayerName;
  available: boolean;       // false: the layer belongs to this mode, but the last run stopped before its stage
  visible: boolean;
  /** Entries under this one, each with its own check box and swatch (the test surfaces of each criterion). */
  parts?: LayersMenuPart[];
}

export interface LayersMenuPart {
  id: string;
  label: string;
  colour: string | null;     // "#RRGGBB" of the swatch
  visible: boolean;
}

interface LayersMenuProps {
  entries: LayersMenuEntry[];
  skyDomeOpacity: number;
  theme: ViewportTheme;
  onVisibleChange: (name: LayerName, visible: boolean) => void;
  onPartVisibleChange?: (name: LayerName, partId: string, visible: boolean) => void;
  onSkyDomeOpacityChange: (opacity: number) => void;
}

export function LayersMenu({ entries, skyDomeOpacity, theme, onVisibleChange, onPartVisibleChange, onSkyDomeOpacityChange }: LayersMenuProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    setOpen(false);
    button.current?.focus();
  };
  return (
    <div className="viewer-overlay viewer-layers-menu" data-viewport-theme={theme} onKeyDown={closeOnEscape}>
      <button ref={button} type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>{messages.layers}</button>
      {open && (
        <ul id={panelId} className="viewer-layers-panel">
          {[...entries].sort((first, second) => LAYER_NAMES.indexOf(first.name) - LAYER_NAMES.indexOf(second.name)).map((entry) => (
            <li key={entry.name}>
              <label>
                <input type="checkbox" checked={entry.available && entry.visible} disabled={!entry.available}
                       onChange={(event) => onVisibleChange(entry.name, event.target.checked)} />
                {messages.layerNames[entry.name]}
              </label>
              {entry.parts && entry.parts.length > 0 && (
                <ul className="viewer-layer-parts" aria-label={messages.layerNames[entry.name]}>
                  {entry.parts.map((part) => (
                    <li key={part.id}>
                      <label>
                        <input type="checkbox" checked={part.visible} onChange={(event) => onPartVisibleChange?.(entry.name, part.id, event.target.checked)} />
                        {part.colour !== null && <span className="viewer-criterion-swatch" style={{ background: part.colour }} aria-hidden="true" />}
                        {part.label}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {!entry.available && <p className="viewer-layer-note viewer-muted">{entry.name === "carved_by_criterion" ? messages.carvedByCriterionMissing : messages.noResultForStage}</p>}
              {entry.available && entry.name === "sky_dome" && (
                <label className="viewer-sky-dome-slider">
                  {messages.skyDomeTransparency}
                  <input type="range" min="0" max="100" step="5" value={Math.round((1 - skyDomeOpacity) * 100)}
                         onChange={(event) => onSkyDomeOpacityChange(1 - Number(event.target.value) / 100)} />
                </label>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

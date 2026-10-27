// The menu of Add study (simulate design, section 4): the criteria first, each as "Like <name>" (a study with its metric, period,
// mode settings and files), then the metrics, each with its unit. A metric whose inputs are missing (the weather file) is marked and
// described by the reason, and choosing it does nothing. It is shown only while open, under its anchor; the placement and the keyboard
// are those of the app's other menus (menu_popup.ts).
import { useId, type RefObject } from "react";
import type { CriterionEntry, MetricInfo, StudySource } from "../api_client/client";
import { messages } from "../messages";
import { useMenuPopup } from "../steps/menu_popup";

interface AddStudyMenuProps {
  /** The menu's id, which the anchor names (aria-controls) while the menu is open. */
  id: string;
  /** The Add study button; a press on it is not a press elsewhere. */
  anchor: RefObject<HTMLElement | null>;
  criteria: CriterionEntry[];
  metrics: MetricInfo[];
  onChoose: (source: StudySource) => void;
  /** Told when the menu closes by itself (Escape, Tab, a press elsewhere, a scroll, a resize). */
  onClose: (focusedAnchor: boolean) => void;
}

interface MenuItem {
  key: string;
  label: string;
  unit: string | null;
  source: StudySource;
  available: boolean;
}

export function AddStudyMenu({ id, anchor, criteria, metrics, onChoose, onClose }: AddStudyMenuProps) {
  const { place, popup, onMenuKeyDown } = useMenuPopup(anchor, "start", { startOpen: true, onHide: onClose });
  const reasonId = useId();
  const items: MenuItem[] = [
    ...criteria.map((criterion) => ({ key: `criterion-${criterion.id}`, label: messages.likeCriterion(criterion.name), unit: null,
                                      source: { from_criterion: criterion.id }, available: true })),
    ...metrics.map((metric) => ({ key: `metric-${metric.name}`, label: metric.label, unit: metric.unit, source: { metric: metric.name },
                                  available: metric.available })),
  ];
  const someUnavailable = items.some((item) => !item.available);
  return (
    <div ref={popup} className="action-menu-popup add-study-menu" style={place ?? undefined}>
      <ul id={id} role="menu" aria-label={messages.addStudyMenuTitle} onKeyDown={onMenuKeyDown}>
        {items.map((item) => (
          <li key={item.key} role="none">
            <button type="button" role="menuitem" tabIndex={-1} aria-disabled={item.available ? undefined : true}
                    aria-label={item.unit === null ? undefined : messages.metricOption(item.label, item.unit)} aria-describedby={item.available ? undefined : reasonId} onClick={() => { if (item.available) onChoose(item.source); }}>
              <span className="add-study-menu-label">{item.label}</span>
              {item.unit !== null && <span className="add-study-menu-unit">{item.unit}</span>}
            </button>
          </li>
        ))}
      </ul>
      {someUnavailable && <p id={reasonId} className="action-menu-reason">{messages.metricNeedsWeatherFile}</p>}
    </div>
  );
}

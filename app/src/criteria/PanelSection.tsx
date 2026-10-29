// One folded section of a criterion's panel (CriterionPanel): a header button with the section's title and, while it is closed,
// what it holds in one line, with a warning icon and in the warning colour (and "Needs attention" for screen readers) when the
// section has something to fix; the content only while it is open, its headings one level under the section's. The open sections belong to the workspace (usePanelSections), not to one criterion: they stay as they
// are when another criterion is selected, and when the Criteria step is closed and opened again.
import { useId, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import { SubheadingLevel } from "../settings_form/Subheading";
import { DEFAULT_OPEN_SECTIONS, type PanelSectionId } from "./section_summaries";
import "../steps/steps.css";

interface PanelSectionProps {
  /** A section of the panel (PanelSectionId), or a group of the typical building's window (TypicalBuildingSheet). */
  id: string;
  title: string;
  summary: string;
  open: boolean;
  onToggle: () => void;
  /** The section has something to fix: its summary has a warning icon and is in the warning colour. */
  problem: boolean;
  /** What the section shows under its header open or closed (a live region that must stay on the page); absent: nothing. */
  alwaysShown?: ReactNode;
  children: ReactNode;
}

export function PanelSection({ id, title, summary, open, onToggle, problem, alwaysShown, children }: PanelSectionProps) {
  const contentId = useId();
  return (
    <section className={open ? "panel-section panel-section-open" : "panel-section"} data-section={id}>
      <h3 className="panel-section-heading">
        <button type="button" className="panel-section-header" aria-expanded={open} aria-controls={open ? contentId : undefined} onClick={onToggle}>
          <span className="panel-section-title">{title}</span>
          {!open && (
            <span className={problem ? "panel-section-summary panel-section-summary-problem" : "panel-section-summary"}>
              {problem && <WarningIcon />}{summary}
            </span>
          )}
          {!open && problem && <span className="visually-hidden">{messages.sectionNeedsAttention}</span>}
        </button>
      </h3>
      <SubheadingLevel.Provider value={4}>
        {alwaysShown}
        {open && <div id={contentId} className="panel-section-content">{children}</div>}
      </SubheadingLevel.Provider>
    </section>
  );
}

/** A request to open a section: a link to a setting the section holds. Each link is a new request. */
export interface OpenSectionRequest {
  section: PanelSectionId;
}

export interface PanelSections {
  openSections: ReadonlySet<PanelSectionId>;
  onToggleSection: (id: PanelSectionId) => void;
  /** Opens sections that have something to show (a problem, a notice), leaving the others as they are. */
  onOpenSections: (ids: readonly PanelSectionId[]) => void;
}

const withSections = (open: ReadonlySet<PanelSectionId>, ids: readonly PanelSectionId[]) => (ids.every((id) => open.has(id)) ? open : new Set([...open, ...ids]));

/**
 * The open sections of the panel, the default ones at first. A request opens its section in the same render, so a field it
 * holds is on the page when the focus goes to it.
 */
export function usePanelSections(request: OpenSectionRequest | null): PanelSections {
  const [openSections, setOpenSections] = useState<ReadonlySet<PanelSectionId>>(() => withSections(DEFAULT_OPEN_SECTIONS, request === null ? [] : [request.section]));
  const [requestSeen, setRequestSeen] = useState(request);
  if (request !== requestSeen) {
    setRequestSeen(request);
    if (request !== null) setOpenSections((open) => withSections(open, [request.section]));
  }
  return {
    openSections,
    onToggleSection: (id) => setOpenSections((open) => {
      const next = new Set(open);
      if (!next.delete(id)) next.add(id);
      return next;
    }),
    onOpenSections: (ids) => setOpenSections((open) => withSections(open, ids)),
  };
}

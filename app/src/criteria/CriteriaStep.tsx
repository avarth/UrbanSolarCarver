// The Criteria step (spec 7.1, 7.2). The cards come first, also with one criterion (CriterionList, with Add criterion under the
// last one), then, with two or more criteria, what the chain kept (one line), then the selected criterion's panel. While a card
// just selected waits for its settings the panel says so (or why they could not be read) instead of showing another criterion's;
// a run refused because it protects nothing is said over its panel. After a delete, a duplicate or an add the focus goes to the
// card selected then, or to the panel when no cards are left. The panel's open sections are the step's (usePanelSections): they
// stay as they are when another criterion is selected, and a link to a setting opens the section that holds it.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { CriterionList, type CriterionListProps } from "./CriterionList";
import { usePanelSections, type OpenSectionRequest, type PanelSections } from "./PanelSection";
import type { SelectionLoad } from "./use_criterion_selection";
import "../steps/steps.css";

interface CriteriaStepProps {
  /** The panel of the selected criterion, with the step's open sections. */
  panel: (sections: PanelSections) => ReactNode;
  /** The criteria and their requests. */
  list: CriterionListProps;
  /** Whether the selected criterion's settings are in; absent: they are. */
  load?: SelectionLoad;
  /** What keeps a run from starting that is the selected criterion's to fix (it protects nothing), said over its panel; absent: none. */
  panelProblem?: string | null;
  /** What the chain kept (chainSummaryLine), under the cards, of two or more criteria; absent or null: no line. */
  chainLine?: string | null;
  /** A link to a setting of the panel: its section opens (a new request each time); absent or null: none. */
  openSectionRequest?: OpenSectionRequest | null;
}

export function CriteriaStep({ panel, list, load = { state: "ready" }, panelProblem = null, chainLine = null, openSectionRequest = null }: CriteriaStepProps) {
  const step = useRef<HTMLDivElement>(null);
  const sections = usePanelSections(openSectionRequest);
  const [focusRequest, setFocusRequest] = useState(0);
  const selectedName = list.criteria.find((criterion) => criterion.id === list.selectedId)?.name ?? "";

  useEffect(() => {
    if (focusRequest === 0) return;
    const selectedCard = step.current?.querySelector<HTMLElement>('.criterion-card[aria-current="true"] .criterion-card-select');
    (selectedCard ?? step.current?.querySelector<HTMLElement>(".criterion-panel-frame"))?.focus();
  }, [focusRequest]);
  // A change that removes or adds a card moves the selection: the focus follows it once it is done.
  const focusSelectedIfDone = (reason: string | null) => {
    if (reason === null) setFocusRequest((count) => count + 1);
    return reason;
  };
  const shownList: CriterionListProps = {
    ...list,
    onDelete: async (id) => focusSelectedIfDone(await list.onDelete(id)),
    onDuplicate: async (id) => focusSelectedIfDone(await list.onDuplicate(id)),
    onAdd: async (mode) => focusSelectedIfDone(await list.onAdd(mode)),
  };

  const panelFrame = (
    <div className="criterion-panel-frame" tabIndex={-1} role="group" aria-label={selectedName || undefined}>
      {load.state === "ready" ? <>{panelProblem !== null && <p className="setting-error criterion-panel-problem" role="alert">{panelProblem}</p>}{panel(sections)}</>
        : load.state === "loading" ? <p className="step-reason criterion-panel-waits" role="status">{messages.loadingCriterion(selectedName)}</p>
        : <p className="setting-error criterion-panel-waits" role="alert">{load.problem}</p>}
    </div>
  );
  return (
    <div ref={step} className="criteria-step">
      <CriterionList {...shownList} />
      {chainLine !== null && <p className="chain-summary">{chainLine}</p>}
      {panelFrame}
    </div>
  );
}

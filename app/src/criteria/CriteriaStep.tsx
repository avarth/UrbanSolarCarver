// The Criteria step (spec 7.1, 7.2). With one criterion it opens straight on that criterion's panel (CriterionPanel), with no list
// around it, so a one-criterion project reads as the Mode and Carving steps did, in one step; the only new thing is a quiet "Add
// another criterion" link at its end. With two or more, the cards come first (CriterionList, with Add criterion under the last
// one), then the selected criterion's panel. While a card just selected waits for its settings the panel says so (or why they
// could not be read) instead of showing another criterion's; a run refused because it protects nothing is said over its panel.
// After a delete, a duplicate or an add the focus goes to the card selected then, or to the panel when no cards are left.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { AddCriterion, CriterionList, type CriterionListProps } from "./CriterionList";
import type { SelectionLoad } from "./use_criterion_selection";
import "../steps/steps.css";

interface CriteriaStepProps {
  /** The panel of the selected criterion. */
  panel: ReactNode;
  /** The criteria and their requests. */
  list: CriterionListProps;
  /** Whether the selected criterion's settings are in; absent: they are. */
  load?: SelectionLoad;
  /** What keeps a run from starting that is the selected criterion's to fix (it protects nothing), said over its panel; absent: none. */
  panelProblem?: string | null;
}

export function CriteriaStep({ panel, list, load = { state: "ready" }, panelProblem = null }: CriteriaStepProps) {
  const step = useRef<HTMLDivElement>(null);
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
      {load.state === "ready" ? <>{panelProblem !== null && <p className="setting-error criterion-panel-problem" role="alert">{panelProblem}</p>}{panel}</>
        : load.state === "loading" ? <p className="step-reason criterion-panel-waits" role="status">{messages.loadingCriterion(selectedName)}</p>
        : <p className="setting-error criterion-panel-waits" role="alert">{load.problem}</p>}
    </div>
  );
  if (list.criteria.length < 2) {
    return (
      <div ref={step} className="criteria-step">
        {panelFrame}
        <AddCriterion label={messages.addAnotherCriterion} onAdd={shownList.onAdd} disabledReason={list.disabledReason} />
      </div>
    );
  }
  return (
    <div ref={step} className="criteria-step">
      <CriterionList {...shownList} />
      {panelFrame}
    </div>
  );
}

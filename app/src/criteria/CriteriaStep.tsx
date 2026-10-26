// The Criteria step (spec 7.1, 7.2). With one criterion it opens straight on that criterion's panel (CriterionPanel), with no list
// around it, so a one-criterion project reads as the Mode and Carving steps did, in one step; the only new thing is a quiet "Add
// another criterion" link at its end. With two or more, the cards come first (CriterionList, with Add criterion under the last
// one), then the selected criterion's panel.
import type { ReactNode } from "react";
import { messages } from "../messages";
import { AddCriterion, CriterionList, type CriterionListProps } from "./CriterionList";
import "../steps/steps.css";

interface CriteriaStepProps {
  /** The panel of the selected criterion. */
  panel: ReactNode;
  /** The criteria and their requests. */
  list: CriterionListProps;
}

export function CriteriaStep({ panel, list }: CriteriaStepProps) {
  if (list.criteria.length < 2) {
    return (
      <div className="criteria-step">
        {panel}
        <AddCriterion label={messages.addAnotherCriterion} onAdd={list.onAdd} disabledReason={list.disabledReason} />
      </div>
    );
  }
  return (
    <div className="criteria-step">
      <CriterionList {...list} />
      {panel}
    </div>
  );
}

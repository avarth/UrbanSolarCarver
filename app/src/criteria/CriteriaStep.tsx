// The Criteria step (spec 7.1): with one criterion it opens straight on that criterion's panel (CriterionPanel), with no list
// around it, so a one-criterion project reads as the Mode and Carving steps did, in one step.
import type { ReactNode } from "react";
import "../steps/steps.css";

interface CriteriaStepProps {
  /** The panel of the selected criterion. */
  panel: ReactNode;
}

export function CriteriaStep({ panel }: CriteriaStepProps) {
  return <div className="criteria-step">{panel}</div>;
}

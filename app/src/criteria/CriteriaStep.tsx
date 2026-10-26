// The Criteria step (spec 7.1): with one criterion it opens straight on that criterion's panel (CriterionPanel), with no list
// around it, so a one-criterion project reads as the Mode and Carving steps did, in one step.
import type { ReactNode } from "react";
import type { CriterionEntry } from "../api_client/client";
import "../steps/steps.css";

interface CriteriaStepProps {
  criteria: CriterionEntry[];
  selectedId: string;
  /** The panel of a criterion (null when the project lists none, which still has the settings of one). */
  panelOf: (criterion: CriterionEntry | null) => ReactNode;
}

export function CriteriaStep({ criteria, selectedId, panelOf }: CriteriaStepProps) {
  const selected = criteria.find((criterion) => criterion.id === selectedId) ?? criteria[0] ?? null;
  return <div className="criteria-step">{panelOf(selected)}</div>;
}

// The bar pinned under the Criteria step's list: Run analysis and Build envelope and massing side by side, each with the reason it
// waits, then the progress and outcome of the runs the step's controls start (a refusal, a failure with its links to the settings
// to fix, a carving update), so they are in view whichever section of the criterion's panel is open.
import type { ReactNode } from "react";
import { messages } from "../messages";
import { RunAnalysisButton } from "./SettingsStep";
import "./steps.css";

interface CriteriaRunBarProps {
  /** Why Run analysis cannot start; null when it can. */
  runBlocker: string | null;
  onRunAnalysis: () => void;
  /** Why the build cannot start; null when it can. */
  buildBlocker: string | null;
  onBuild: () => void;
  /** The progress and outcome of Run analysis and of the carving updates. */
  feedback: ReactNode;
}

export function CriteriaRunBar({ runBlocker, onRunAnalysis, buildBlocker, onBuild, feedback }: CriteriaRunBarProps) {
  return (
    <div className="criteria-run-bar">
      <div className="criteria-run-buttons">
        <RunAnalysisButton blocker={runBlocker} onRunAnalysis={onRunAnalysis} />
        <RunAnalysisButton blocker={buildBlocker} label={messages.buildEnvelopeAndMassing} onRunAnalysis={onBuild} secondary />
      </div>
      {feedback}
    </div>
  );
}

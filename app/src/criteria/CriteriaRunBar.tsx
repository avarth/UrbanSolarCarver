// The bar pinned under the Criteria step's list: the run the project needs and Build envelope and massing side by side, each with
// the reason it waits, then the progress and outcome of the runs the step's controls start (a refusal, a failure with its links to
// the settings to fix, a carving update), so they are in view whichever section of the criterion's panel is open. The run is Run
// analysis while an analysis is missing or out of date, Update carving while only a carving is, and no button while everything is
// current: the build is then the primary button. A reason that names a setting to fix in the project settings window has Open
// settings after it.
import { useId, type ReactNode } from "react";
import { messages } from "../messages";
import { RunAnalysisButton } from "../settings_form/SettingsStep";
import type { RunAction } from "./criteria_state";
import "../theme/panels.css";

interface CriteriaRunBarProps {
  /** The run the project needs; null: none, and no button for it. */
  runAction: RunAction;
  /** Why a run cannot start; null when it can. */
  runBlocker: string | null;
  onRun: () => void;
  /** Why the build cannot start; null when it can. */
  buildBlocker: string | null;
  onBuild: () => void;
  /** The progress and outcome of Run analysis and of the carving updates. */
  feedback: ReactNode;
  /** What leads to the place of the setting the run's reason names (Open settings); absent: nothing. */
  runBlockerAction?: ReactNode;
}

export function CriteriaRunBar({ runAction, runBlocker, onRun, buildBlocker, onBuild, feedback, runBlockerAction }: CriteriaRunBarProps) {
  const sharedReasonId = useId();
  // A reason that blocks every run (a run in progress, no test surfaces) is said once, under both buttons; the build's own
  // reason (the analysis or a carving is not current) is said under the build only.
  const shared = runBlocker !== null && runBlocker === buildBlocker;
  return (
    <div className="criteria-run-bar">
      <div className="criteria-run-buttons">
        {runAction !== null && (
          <RunAnalysisButton blocker={runBlocker} label={runAction === "carving" ? messages.updateCarving : messages.runAnalysis} onRunAnalysis={onRun}
                             sharedReasonId={shared ? sharedReasonId : undefined} reasonAction={runBlockerAction} />
        )}
        <RunAnalysisButton blocker={buildBlocker} label={messages.buildEnvelopeAndMassing} onRunAnalysis={onBuild} secondary={runAction !== null}
                           sharedReasonId={shared ? sharedReasonId : undefined} />
      </div>
      {shared && <p id={sharedReasonId} className="run-button-reason">{runBlocker}</p>}
      {shared && runBlockerAction}
      {feedback}
    </div>
  );
}

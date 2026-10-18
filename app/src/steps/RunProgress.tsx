// What a run shows under the button that started it (UX 6.3, 11): while it runs, each stage in plain words with its state,
// the batch count during the ray tracing, the elapsed time and Cancel; once it ended, how it ended (a failure with a Details
// fold and a link to the setting it names, "Cancelled.") and the warnings it reported. A notice of the run loop shows for three
// seconds: "Results are up to date" when the service had nothing to run, "A run is in progress" for a press during a run.
import { useEffect, useState } from "react";
import { messages } from "../messages";
import { presentedSettingOf, settingView } from "../settings_form/presentation";
import { formatNumber } from "./format_numbers";
import { stageDisplayName, type RunLoop, type RunOrigin, type RunRecord, type RunState } from "./run_state";
import "./steps.css";

const ELAPSED_TICK_MILLISECONDS = 100;
const STAGE_CHAIN_ERROR = "StageChainError";

/** Seconds since the run started, counted on while it runs. */
function useElapsedSeconds(state: RunState): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (state.endedAt !== null) return;
    const timer = setInterval(() => setNow(Date.now()), ELAPSED_TICK_MILLISECONDS);
    return () => clearInterval(timer);
  }, [state.endedAt]);
  return Math.max(0, ((state.endedAt ?? now) - state.startedAt) / 1000);
}

/** "6.4 s". */
export function secondsText(seconds: number): string {
  return formatNumber(seconds, messages.units.seconds, 1);
}

function StageList({ state, onCancel }: { state: RunState; onCancel: () => void }) {
  const elapsedSeconds = useElapsedSeconds(state);
  return (
    <div className="run-progress-stages">
      <ol aria-label={messages.runProgress}>
        {state.order.map((stage) => {
          const progress = state.stages[stage];
          const isRayTracing = progress.state === "running" && progress.total > 1;
          return (
            <li key={stage} className={`run-stage run-stage-${progress.state}`}>
              <span className="run-stage-name">{stageDisplayName(stage)}</span>
              <span className="run-stage-state">{isRayTracing ? messages.rayBatches(progress.done, progress.total) : messages.stageStates[progress.state]}</span>
            </li>
          );
        })}
      </ol>
      <div className="run-progress-footer">
        <span className="run-progress-elapsed">{messages.elapsedTime(secondsText(elapsedSeconds))}</span>
        <button type="button" className="secondary-button" onClick={onCancel}>{messages.cancelRun}</button>
      </div>
    </div>
  );
}

function RunFailure({ record, mode, onGoToSetting }: { record: RunRecord; mode: string; onGoToSetting: (settingName: string) => void }) {
  const failure = record.state.failure!;
  if (failure.error_type === STAGE_CHAIN_ERROR) return <p className="run-outcome run-outcome-error">{messages.resultsOutOfDate}</p>;
  const namedSettings = [...new Set(failure.field_errors.map((fieldError) => (fieldError.field === null ? null : presentedSettingOf(fieldError.field)))
    .filter((name): name is string => name !== null))];
  return (
    <div className="run-outcome run-outcome-error">
      <p>{messages.runFailed}</p>
      {namedSettings.map((name) => (
        <button key={name} type="button" className="link-button" onClick={() => onGoToSetting(name)}>{messages.goToSetting(settingView(name, mode).label)}</button>
      ))}
      <details className="run-failure-details">
        <summary>{messages.details}</summary>
        <p>{messages.errorType(failure.error_type)}</p>
        <p className="run-failure-message">{failure.message}</p>
        {failure.field_errors.map((fieldError, index) => (
          <p key={index} className="run-failure-message">{fieldError.field === null ? fieldError.message : `${fieldError.field}: ${fieldError.message}`}</p>
        ))}
      </details>
    </div>
  );
}

function RunEnded({ record, mode, onGoToSetting }: { record: RunRecord; mode: string; onGoToSetting: (settingName: string) => void }) {
  if (record.refusal !== null) return <p className="run-outcome run-outcome-error">{record.refusal}</p>;
  switch (record.state.final) {
    case "failed":
      return <RunFailure record={record} mode={mode} onGoToSetting={onGoToSetting} />;
    case "cancelled":
      return <p className="run-outcome">{messages.runCancelled}</p>;
    case "connection_lost":
      return <p className="run-outcome run-outcome-error">{messages.runConnectionLost}</p>;
    default:
      return null;
  }
}

interface RunProgressProps {
  runs: Pick<RunLoop, "current" | "notice" | "cancel">;
  project: string;
  origin: RunOrigin;
  mode: string;
  /** Opens the step that holds a setting a failed run names and moves the focus to it. */
  onGoToSetting: (settingName: string) => void;
}

export function RunProgress({ runs, project, origin, mode, onGoToSetting }: RunProgressProps) {
  const record = runs.current;
  const isThisButton = record !== null && record.project === project && record.origin === origin;
  const notice = runs.notice !== null && runs.notice.project === project && runs.notice.origin === origin ? runs.notice.message : null;
  if (!isThisButton && notice === null) return null;
  return (
    <div className="run-progress" role="status">
      {notice !== null && <p className="run-outcome">{notice}</p>}
      {isThisButton && notice === null && (
        <>
          {record.state.final === null && record.refusal === null ? <StageList state={record.state} onCancel={runs.cancel} />
            : <RunEnded record={record} mode={mode} onGoToSetting={onGoToSetting} />}
          {record.state.issues.length > 0 && (
            <div className="run-issues">
              <p className="run-issues-title">{messages.warningsTitle}</p>
              <ul>{record.state.issues.map((issue, index) => <li key={index}>{issue.message}</li>)}</ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

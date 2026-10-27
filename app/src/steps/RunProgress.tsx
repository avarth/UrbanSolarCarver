// What a run shows under the button that started it (UX 6.3, 11): while it runs, each stage in plain words with its state (a
// criterion's stages named with the criterion when the project has several, spec 7.3),
// the batch count during the ray tracing, the elapsed time and Cancel; once it ended, how it ended (a failure with a Details
// fold and a link to the setting it names, "Cancelled.") and the warnings it reported, listed or, in the Criteria step's pinned bar,
// folded behind one line ("2 warnings"). A notice of the run loop shows for three seconds: "Results are up to date" when the
// service had nothing to run, "A run is in progress" for a press during a run.
import { useEffect, useId, useState } from "react";
import { messages } from "../messages";
import { presentedSettingOf } from "../settings_form/presentation";
import { formatNumber } from "./format_numbers";
import { criterionOfKey, SIMULATE_STAGE, stageDisplayName, stageOfKey, type RunLoop, type RunOrigin, type RunRecord, type RunState } from "./run_state";
import { shownLabelOf } from "./SettingsStep";
import "./steps.css";

/** Goes to a setting a failed run names; *criterion*: the criterion whose settings the run found it in, null when it named none. */
export type GoToSetting = (settingName: string, criterion?: string | null) => void;

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

/** The name of a criterion's stage in the list: "Daylight on windows: Carving" with several criteria, "Carving" with one. */
function stageLabel(key: string, criterionNameOf: (id: string) => string | null): string {
  const criterion = criterionOfKey(key);
  const stageName = stageDisplayName(stageOfKey(key));
  const criterionName = criterion === null ? null : criterionNameOf(criterion);
  return criterionName === null ? stageName : messages.criterionStage(criterionName, stageName);
}

interface StageListProps {
  state: RunState;
  onCancel: () => void;
  criterionNameOf: (id: string) => string | null;
  studyNameOf: (id: string) => string | null;
}

function StageList({ state, onCancel, criterionNameOf, studyNameOf }: StageListProps) {
  const elapsedSeconds = useElapsedSeconds(state);
  // A simulation's one stage is named by the study the engine is running, once its progress has named one.
  const studyName = state.study == null ? null : studyNameOf(state.study);
  return (
    <div className="run-progress-stages">
      <ol aria-label={messages.runProgress}>
        {state.order.map((key) => {
          const progress = state.stages[key];
          const isRayTracing = progress.state === "running" && progress.total > 1;
          return (
            <li key={key} className={`run-stage run-stage-${progress.state}`}>
              <span className="run-stage-name">{stageOfKey(key) === SIMULATE_STAGE && studyName !== null ? studyName : stageLabel(key, criterionNameOf)}</span>
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

/** What a run's end is said with: the shown mode, the link to a setting, the criterion shown and the criteria's names. */
interface EndedRunContext {
  mode: string;
  onGoToSetting: GoToSetting;
  shownCriterionId?: string;
  criterionNames?: Readonly<Record<string, string>>;
  criterionKeys?: ReadonlySet<string>;
}

function RunFailure({ record, mode, onGoToSetting, shownCriterionId, criterionNames, criterionKeys }: EndedRunContext & { record: RunRecord }) {
  const failure = record.state.failure!;
  if (failure.error_type === STAGE_CHAIN_ERROR) return <p className="run-outcome run-outcome-error">{messages.resultsOutOfDate}</p>;
  // The mode has no field but its tiles, which its link goes to.
  const settingOf = (field: string | null) => (field === null ? null : field === "mode" ? field : presentedSettingOf(field));
  const namedSettings = [...new Set(failure.field_errors.map((fieldError) => settingOf(fieldError.field)).filter((name): name is string => name !== null))];
  // The settings of a criterion other than the one shown are said with its name, so they are not taken for the shown one's; a
  // shared setting (not a criterion key) is the project's, and is said without it.
  const criterion = failure.criterion ?? null;
  const isCriterionSetting = (name: string) => criterionKeys?.has(name) ?? true;
  const aboutCriterion = namedSettings.length === 0 || namedSettings.some(isCriterionSetting);
  const otherName = criterion !== null && criterion !== shownCriterionId && aboutCriterion ? criterionNames?.[criterion] ?? null : null;
  return (
    <div className="run-outcome run-outcome-error">
      <p>{otherName === null ? messages.runFailed : messages.runFailedForCriterion(otherName)}</p>
      {namedSettings.map((name) => {
        const label = shownLabelOf(name, mode);
        const ofCriterion = isCriterionSetting(name);
        return (
          <button key={name} type="button" className="link-button" onClick={() => onGoToSetting(name, ofCriterion ? criterion : null)}>
            {otherName === null || !ofCriterion ? messages.goToSetting(label) : messages.goToSettingOf(label, otherName)}
          </button>
        );
      })}
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

function RunEnded(props: EndedRunContext & { record: RunRecord }) {
  const { record } = props;
  if (record.refusal !== null) return <p className="run-outcome run-outcome-error">{record.refusal}</p>;
  switch (record.state.final) {
    case "failed":
      return <RunFailure {...props} />;
    case "cancelled":
      return <p className="run-outcome">{messages.runCancelled}</p>;
    case "connection_lost":
      return <p className="run-outcome run-outcome-error">{messages.runConnectionLost}</p>;
    default:
      return null;
  }
}

/** The warnings a run reported: listed under a title, or folded behind a toggle that says how many. */
function RunIssues({ issues, folded }: { issues: RunState["issues"]; folded: boolean }) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const list = <ul id={listId}>{issues.map((issue, index) => <li key={index}>{issue.message}</li>)}</ul>;
  if (!folded) {
    return (
      <div className="run-issues">
        <p className="run-issues-title">{messages.warningsTitle}</p>
        {list}
      </div>
    );
  }
  return (
    <div className="run-issues">
      <button type="button" className="link-button run-issues-toggle" aria-expanded={open} aria-controls={open ? listId : undefined}
              onClick={() => setOpen((shown) => !shown)}>
        {messages.warningCount(issues.length)}
      </button>
      {open && list}
    </div>
  );
}

interface RunProgressProps {
  runs: Pick<RunLoop, "current" | "notice" | "cancel">;
  project: string;
  origin: RunOrigin;
  mode: string;
  /** Opens the step that holds a setting a failed run names (selecting the criterion the run named) and moves the focus to it. */
  onGoToSetting: GoToSetting;
  /** The criterion whose panel is shown: a failure of another criterion's settings is said with that one's name. */
  shownCriterionId?: string;
  /** The settings that belong to a criterion: a failure on any other setting (a shared one) names no criterion; absent: every one does. */
  criterionKeys?: ReadonlySet<string>;
  /**
   * The names of the criteria, by id, which label each criterion's stages; absent with one criterion, whose stages keep their
   * names alone.
   */
  criterionNames?: Readonly<Record<string, string>>;
  /** The warnings fold behind one line, so a bar that holds the progress stays short; absent: they are listed. */
  foldWarnings?: boolean;
  /** The names of the studies, by id: a simulation's progress names the study being run. */
  studyNames?: Readonly<Record<string, string>>;
}

export function RunProgress({ runs, project, origin, mode, onGoToSetting, criterionNames, shownCriterionId, criterionKeys, foldWarnings = false,
                              studyNames }: RunProgressProps) {
  const record = runs.current;
  const isThisButton = record !== null && record.project === project && record.origin === origin;
  const notice = runs.notice !== null && runs.notice.project === project && runs.notice.origin === origin ? runs.notice.message : null;
  if (!isThisButton && notice === null) return null;
  return (
    <div className="run-progress" role="status">
      {notice !== null && <p className="run-outcome">{notice}</p>}
      {isThisButton && notice === null && (
        <>
          {record.state.final === null && record.refusal === null
            ? <StageList state={record.state} onCancel={runs.cancel} criterionNameOf={(id) => criterionNames?.[id] ?? null}
                         studyNameOf={(id) => studyNames?.[id] ?? null} />
            : <RunEnded record={record} mode={mode} onGoToSetting={onGoToSetting} shownCriterionId={shownCriterionId} criterionNames={criterionNames}
                        criterionKeys={criterionKeys} />}
          {record.state.issues.length > 0 && <RunIssues key={record.serial} issues={record.state.issues} folded={foldWarnings} />}
        </>
      )}
    </div>
  );
}

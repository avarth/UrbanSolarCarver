// The parts that show and start runs (UX 5.5 to 5.7, 6): the criterion's carving rule and its Run analysis (in its panel), the
// Envelope and massing and Export steps, their buttons (Build envelope and massing pinned under the steps in Criteria, Build
// envelope and Build massing in the two parts of their step, R2 5), the progress under the button that started a run, and what
// the 3D view draws of the results (dimmed while out of date or replaced, listed as missing after a run that stopped before their
// stage). ProjectWorkspace gives them the project's form, stage status and run loop; the results are fetched here and again as
// each stage of a run is done.
import { useMemo, useRef, useState, type ReactNode } from "react";
import { downloadWithToken, failureTextOf, serviceProblemOf, type RunSummary } from "../api_client/client";
import { messages } from "../messages";
import { analysisDiffersFromStored, shownValue, type FormState, type SaveOutcome } from "../settings_form/form_state";
import type { StepFormAction } from "../settings_form/two_forms";
import type { Point3 } from "../viewer/local_origin";
import type { LayerName } from "../viewer/scene";
import type { ViewerPaneProps } from "../viewer_overlays/ViewerPane";
import { CarvingStep, thresholdControlOf, useAutoUpdate } from "./CarvingStep";
import { EnvelopeAndMassingStep } from "./EnvelopeAndMassingStep";
import { CarveFurtherSection } from "./CarveFurther";
import { exportDownloads, ExportStep, type ExportDownload } from "./ExportStep";
import { RunProgress } from "./RunProgress";
import { RunReportPanel } from "./RunReportPanel";
import { runAnalysisAfterSaving, RunAnalysisButton, SettingsToFix } from "./SettingsStep";
import { criterionProgressOf, runProgressShare, runStages, stageRunState, type RunFailure, type RunLoop, type RunOrigin, type RunOutcome, type RunRecord } from "./run_state";
import { useResultsFollowingRun, useRunResults, type RunResults } from "./run_results";
import type { PipelineStage, StageState, StepName } from "./step_summaries";
import { createThresholdUpdateQueue } from "./threshold_queue";

export const ANALYSIS_STAGES: PipelineStage[] = ["thresholding"];     // Run analysis: preprocessing is added when it is out of date
export const CARVING_STAGES: PipelineStage[] = ["thresholding"];
export const BUILD_STAGES: PipelineStage[] = ["exporting", "massing"];     // Build envelope and massing, pinned in Criteria
// Build envelope and Build massing (R2 5): the massing reads the carving, not the envelope, so each runs its own stage. A mesh
// format change runs the envelope's.
export const ENVELOPE_STAGES: PipelineStage[] = ["exporting"];
export const MASSING_STAGES: PipelineStage[] = ["massing"];
const PIPELINE_STAGES: readonly PipelineStage[] = ["preprocessing", "thresholding", "exporting", "massing"];
/** The stages each criterion runs on its own; exporting and massing read the whole chain. */
const ANALYSIS_OF_CRITERION: readonly PipelineStage[] = ["preprocessing", "thresholding"];

/** The step whose summary counts the warnings of a run started by each button. */
const STEP_OF_ORIGIN: Record<RunOrigin, StepName> = {
  settings_run_analysis: "site_and_grid",
  carving_run_analysis: "criteria",
  carving_update: "criteria",
  build: "envelope_and_massing",
  build_envelope: "envelope_and_massing",
  build_massing: "envelope_and_massing",
  export_format: "export",
};

/** The layers each stage's results are drawn in. */
const LAYERS_OF_STAGE: Record<PipelineStage, LayerName[]> = {
  preprocessing: ["sky_dome"],
  thresholding: ["kept_voxels", "carved_voxels", "carved_by_criterion"],
  exporting: ["envelope"],
  massing: ["building_massing"],
};

/** Whether the results hold what a layer draws: the voxels need the score points with the carving's mask and its summary. */
function layerHasData(layer: LayerName, results: RunResults): boolean {
  switch (layer) {
    case "kept_voxels":
    case "carved_voxels":
      return results.scorePoints?.kept != null && results.summary?.carving != null;
    case "sky_dome":
      return results.skyDome !== null;
    case "envelope":
      return results.envelope !== null;
    case "building_massing":
      return results.massing !== null;
    default:
      return true;
  }
}

/**
 * Whether a stage's layers are dimmed: while a run of the project brings the stage up to date, until the run has done it;
 * after a run of a value the user has since left, whose results were not fetched (the run that follows brings them); while
 * the stage's results are fetched again (*stagesBeingFetched*), since what is on screen may be older; otherwise while its stage
 * status is not current (UX 6.3).
 */
export function isStageDimmed(stage: PipelineStage, record: RunRecord | null, stages: Record<PipelineStage, StageState>,
                              stagesBeingFetched: readonly PipelineStage[] = [], criterion?: string): boolean {
  if (stagesBeingFetched.includes(stage)) return true;
  // The selected criterion's analysis and carving (*criterion*) are dimmed by a run that has that stage to do for it, until the
  // run is done with the stage for every criterion (its results are fetched then); a run that thresholds only the criteria after
  // it leaves its carving as it is.
  const ownStageInRun = record !== null && stageRunState(record.state, stage, criterion) !== null;
  const inRun = ownStageInRun ? stageRunState(record.state, stage) : null;
  const runUnderWay = record !== null && record.state.final === null && record.refusal === null;
  if (runUnderWay && inRun !== null) return inRun !== "done";
  if (record !== null && inRun !== null && (record.isSuperseded?.() ?? false)) return true;
  return stages[stage] !== "current";
}

/** *criterion*: the selected one, whose analysis and carving are drawn (isStageDimmed). */
export function dimmedLayersOf(record: RunRecord | null, stages: Record<PipelineStage, StageState>,
                               stagesBeingFetched: readonly PipelineStage[] = [], criterion?: string): LayerName[] {
  return (Object.keys(LAYERS_OF_STAGE) as PipelineStage[])
    .filter((stage) => isStageDimmed(stage, record, stages, stagesBeingFetched, ANALYSIS_OF_CRITERION.includes(stage) ? criterion : undefined))
    .flatMap((stage) => LAYERS_OF_STAGE[stage]);
}

/** The layers of a run that was cancelled or failed whose stage left no data: listed with the missing-result note (UX 8.2). */
export function missingLayersOf(record: RunRecord | null, results: RunResults, isWeightedMode: boolean): LayerName[] {
  if (record === null || (record.state.final !== "cancelled" && record.state.final !== "failed")) return [];
  // layerHasData has no case for the by-criterion layer, which exists only with several criteria: useResultSteps lists it as missing then.
  return runStages(record.state).flatMap((stage) => LAYERS_OF_STAGE[stage as PipelineStage] ?? [])
    .filter((layer) => (layer !== "sky_dome" || isWeightedMode) && !layerHasData(layer, results));
}

/**
 * The stages whose results to fetch when the service answers that *produce* is up to date: the stages asked for, and the
 * earlier ones the page does not hold as current. "Up to date" says all of them are current, and a page that did not follow
 * the run that made them (it was reloaded during the run, or the run was started in another tab) holds an older status and
 * no results or older ones for them.
 */
export function stagesToFetchWhenUpToDate(produce: readonly string[], stages: Record<PipelineStage, StageState>): PipelineStage[] {
  const lastAskedFor = Math.max(...produce.map((stage) => PIPELINE_STAGES.indexOf(stage as PipelineStage)));
  return PIPELINE_STAGES.filter((stage, index) => produce.includes(stage) || (index < lastAskedFor && stages[stage] !== "current"));
}

/**
 * The carving of the selected criterion in the run summary (its entry of the chain's criteria); without a criterion, or from a
 * summary that lists none, the carving of the last criterion that is on.
 */
export function carvingOfCriterion(summary: RunSummary | null, criterionId?: string): RunSummary["carving"] {
  const entries = summary?.criteria ?? [];
  if (criterionId === undefined || entries.length === 0) return summary?.carving ?? null;
  return entries.find((entry) => entry.id === criterionId)?.carving ?? null;
}

export interface ResultStepsContext {
  token: string;
  project: string;
  /** The selected criterion, whose carving, score points and sky dome are shown; absent: the service's default. */
  criterionId?: string;
  /** The selected criterion's stages with output (run_results.ts asks for its score points and sky dome only then). */
  criterionStagesWithResults?: readonly string[];
  /** The criteria that are on, in chain order, when there are two or more and every one has run: the by-criterion layer is asked for then. */
  carvedByCriterionIds?: readonly string[] | null;
  /** Two or more criteria are on: the by-criterion layer belongs to the view, and is listed as missing while it has no data. */
  carvedByCriterionWanted?: boolean;
  /** The thresholding of some criterion that is on is not current (as shown): the by-criterion layer is dimmed. */
  carvedByCriterionOutOfDate?: boolean;
  /**
   * The selected criterion's own analysis and carving stages, as shown (out of date while the form differs from the stored
   * settings): its carving rule locks while its own analysis is out of date. Absent: the project's stages.
   */
  criterionStages?: Record<"preprocessing" | "thresholding", StageState>;
  /** The ids of the criteria in chain order: the order of their stages in a run's progress. */
  chainOrder?: readonly string[];
  /** The criteria's names by id, which label their stages in a run's progress; absent with one criterion. */
  criterionNames?: Readonly<Record<string, string>>;
  /**
   * Another criterion that is on and whose analysis is not current (and whether it protects nothing): a carving change of the
   * selected one is then saved but runs nothing, since the run would trace that criterion first, which only Run analysis starts
   * (M10). Absent or null: none.
   */
  analysisWaitsFor?: { name: string; protectsNothing: boolean } | null;
  /** The selected criterion is bypassed: its panel says so in place of a carving rule. */
  criterionBypassed?: boolean;
  /**
   * Saves threshold values to a criterion that is not the one shown (a value of the threshold queue whose turn came after another
   * card was selected): its settings with the values, if it still has *mode*. Resolves with whether they were stored.
   */
  saveToCriterion?: (criterionId: string, mode: string, values: Record<string, unknown>) => Promise<boolean>;
  /**
   * Shows a run refused for another criterion's settings: selects that criterion and marks the fields once its settings are
   * shown. Absent: the fields are marked in the forms shown.
   */
  showRefusalOfCriterion?: (criterionId: string, fieldErrors: RunFailure["field_errors"]) => void;
  form: FormState;
  /** The form after every action so far, read after a save is awaited. */
  currentForm: () => FormState;
  /** Changes the settings, each in the form that owns it (bothForms). */
  dispatch: (action: StepFormAction) => void;
  flushSave: () => Promise<SaveOutcome>;
  changeAndSave: (values: Record<string, unknown>) => Promise<SaveOutcome>;
  isWeightedMode: boolean;
  stages: Record<PipelineStage, StageState>;
  /** Asks for the stage status again; *completedStages* count as current until the reply. */
  refreshStageStatus: (completedStages?: readonly string[]) => void;
  runs: RunLoop;
  /** Why no run can start now (a run, the inputs, a setting, the warm-up), as Criteria says it; null when one can. */
  runBlocker: string | null;
  /** Every criterion that is on has a current carving: Criteria pins Build envelope and massing. */
  everyCriterionCarved: boolean;
  /** A run of this project is starting or in progress: the service refuses to save its settings. */
  projectRunActive: boolean;
  origin: Point3;
  openStep: (step: StepName) => void;
  goToSetting: (settingName: string) => void;
  onServiceProblem: (error: unknown) => void;
  /** Makes the built envelope the maximum volume (CarveFurther.tsx); resolves with the reason it was refused, or null. */
  onCarveFurther: () => Promise<string | null>;
}

/** A value of the threshold queue: the threshold settings and the mode they were given in (the queue keys it by criterion). */
interface ThresholdValue {
  values: Record<string, unknown>;
  mode: string;
}

export interface ResultSteps {
  content: Record<"envelope_and_massing" | "export", ReactNode>;
  /** The criterion's carving rule, or, before its first analysis, why there is none yet. */
  carvingRule: ReactNode;
  /** The criterion's Run analysis, with the progress of its run. */
  criterionRunAnalysis: ReactNode;
  pinnedAction: Partial<Record<StepName, ReactNode>>;
  viewer: Pick<ViewerPaneProps, "results" | "dimmedLayers" | "missingLayers" | "runProgress" | "overlayContent">;
  results: RunResults;
  /** The criteria whose thresholding the last run did and whose new numbers are not in yet: their cards say Running. */
  criteriaAwaitingNumbers: ReadonlySet<string>;
  /** The warnings of the project's last run, by the step that started it. */
  warningsOfStep: Partial<Record<StepName, number>>;
  /** The progress and outcome shown under a button. */
  feedback: (origin: RunOrigin) => ReactNode;
  /** How the last run a step started ended, for a step that cannot be used now (a cancelled first analysis). */
  feedbackWhenNotUsable: Partial<Record<StepName, ReactNode>>;
  /** Starts a run of the project from a button; when the service has nothing to run, the results it holds are fetched. */
  startRun: (produce: string[], origin: RunOrigin) => Promise<RunOutcome>;
}

export function useResultSteps(context: ResultStepsContext): ResultSteps {
  const { token, project, form, dispatch, flushSave, changeAndSave, stages, runs, runBlocker, projectRunActive } = context;
  const meshFormat = String(shownValue(form, "final_mesh_format") ?? "ply");
  const [results, reloadResults, reloadSummary] = useRunResults({
    token, project, origin: context.origin, criterionId: context.criterionId, criterionStagesWithResults: context.criterionStagesWithResults,
    carvedByCriterionIds: context.carvedByCriterionIds,
    onServiceProblem: context.onServiceProblem,
    stagesWithResults: (Object.keys(stages) as PipelineStage[]).filter((stage) => stages[stage] !== "missing"),
  });
  const [autoUpdate, setAutoUpdate] = useAutoUpdate(project);
  const [lastAnalysisSeconds, setLastAnalysisSeconds] = useState<number | null>(null);
  const [runReportOpen, setRunReportOpen] = useState(false);
  const [downloadProblem, setDownloadProblem] = useState<string | null>(null);
  const [fetchesUnderWay, setFetchesUnderWay] = useState<Partial<Record<PipelineStage, number>>>({});
  const record: RunRecord | null = runs.current?.project === project ? runs.current : null;
  const running = record !== null && record.state.final === null && record.refusal === null;

  useResultsFollowingRun(record, reloadResults, (endedRun) => {
    const { state } = endedRun;
    const superseded = endedRun.isSuperseded?.() ?? false;     // its results were not fetched, so its stages are not shown as current
    context.refreshStageStatus(state.final === "finished" && !superseded ? runStages(state) : []);
    if (state.final === "finished" && runStages(state).includes("preprocessing") && state.endedAt !== null) {
      setLastAnalysisSeconds((state.endedAt - state.startedAt) / 1000);
    }
    // A setting the run found invalid is marked in the form, as a refused save would mark it; a start refused for a criterion's
    // settings marks them in that criterion's panel, which it selects.
    if (state.failure !== null && state.failure.field_errors.length > 0) {
      const { criterion, field_errors: fieldErrors } = state.failure;
      if (criterion != null && context.showRefusalOfCriterion !== undefined) context.showRefusalOfCriterion(criterion, fieldErrors);
      else dispatch({ type: "save_rejected", reply: { field_errors: fieldErrors, grid_plan: form.gridPlan } });
    }
  }, () => void reloadSummary());

  // A criterion whose thresholding the run has done shows its numbers once a run summary fetched since is in: until then its card
  // goes on saying Running (the summary held before has its numbers from before the run).
  const summaryWhenCarved = useRef<{ serial: number | null; byCriterion: Map<string, RunSummary | null> }>({ serial: null, byCriterion: new Map() });
  if (record !== null && summaryWhenCarved.current.serial !== record.serial) summaryWhenCarved.current = { serial: record.serial, byCriterion: new Map() };
  if (record !== null) {
    for (const [id, progress] of Object.entries(criterionProgressOf(record.state))) {
      if (progress.thresholding === "done" && !summaryWhenCarved.current.byCriterion.has(id)) summaryWhenCarved.current.byCriterion.set(id, results.summary);
    }
  }
  const criteriaAwaitingNumbers = new Set([...summaryWhenCarved.current.byCriterion].filter(([, summary]) => summary === results.summary).map(([id]) => id));

  // The results the service holds, fetched again with the stage status, when the page may show older ones. After the last
  // threshold value ended without a run (its save was not stored, its run did not start, or the service had nothing to run),
  // the run before it is no longer superseded, but its results were not fetched; and "up to date" may come to a page that did
  // not follow the run that made the results. The stages stay dimmed until those fetches have ended, so results from before
  // are never shown as current.
  const showResultsTheServiceHolds = useRef((_stagesToFetch: readonly PipelineStage[]) => {});
  showResultsTheServiceHolds.current = (stagesToFetch) => {
    const countFetches = (change: number) => setFetchesUnderWay((current) => ({
      ...current, ...Object.fromEntries(stagesToFetch.map((stage) => [stage, (current[stage] ?? 0) + change])),
    }));
    countFetches(1);
    void reloadResults(stagesToFetch).then(() => countFetches(-1));
    context.refreshStageStatus();
  };
  const stagesBeingFetched = PIPELINE_STAGES.filter((stage) => (fetchesUnderWay[stage] ?? 0) > 0);

  // On "up to date" the steps would otherwise go on saying, from an old stage status, that a stage has not run.
  const startRun = async (produce: string[], origin: RunOrigin): Promise<RunOutcome> => {
    const outcome = await runs.start(project, produce, origin, { chainOrder: context.chainOrder });
    if (outcome === "up_to_date") showResultsTheServiceHolds.current(stagesToFetchWhenUpToDate(produce, stages));
    return outcome;
  };
  const startAfterSaving = (produce: string[], origin: RunOrigin) => runAnalysisAfterSaving(flushSave, () => void startRun(produce, origin));

  // The selected criterion's carving is locked while its own analysis is out of date for the settings shown (ProjectWorkspace
  // counts every stage out of date while the form's mode or analysis settings are not the stored ones). A carving run then would
  // run the analysis first. While another criterion's analysis is not current, a carving change is saved and runs nothing
  // (analysisWaitsFor). The builds read the whole chain: they wait while any criterion's analysis is out of date.
  const ownStages: Record<PipelineStage, StageState> = context.criterionStages === undefined ? stages : { ...stages, ...context.criterionStages };
  const analysisOutOfDate = ownStages.preprocessing !== "current";
  const chainAnalysisOutOfDate = stages.preprocessing !== "current";
  const buildsLocked = useRef(chainAnalysisOutOfDate);
  buildsLocked.current = chainAnalysisOutOfDate;
  // What the threshold queue, made once, reads when a value's turn comes: this render's context and locks.
  const latest = useRef({ context, analysisOutOfDate });
  latest.current = { context, analysisOutOfDate };
  /** Every criterion that is on has a current analysis (the selected one's, and the others' by analysisWaitsFor). */
  const carvingRunsNow = () => !latest.current.analysisOutOfDate && (latest.current.context.analysisWaitsFor ?? null) === null;
  /** Whether the save just stored changed what the analysis reads, or the form still shows other analysis settings. */
  const analysisChangedBy = (revisionBefore: number) => {
    const shownForm = latest.current.context.currentForm();
    return shownForm.storedAnalysisRevision !== revisionBefore || analysisDiffersFromStored(shownForm);
  };
  // Update carving: saved first, and run only when the save left the analysis as it was.
  const updateCarvingAfterSaving = async () => {
    if (!carvingRunsNow()) return;
    const revisionBefore = context.currentForm().storedAnalysisRevision;
    const outcome = await flushSave();
    if ((outcome === "saved" || outcome === "none") && !analysisChangedBy(revisionBefore) && carvingRunsNow()) void startRun(CARVING_STAGES, "carving_update");
  };

  // Threshold changes with auto-update on go through the queue: one carving run at a time, the last value of each criterion next.
  // A run whose value the user left while it ran is marked so (RunRecord.isSuperseded): its results are not fetched and the
  // carving stays dimmed until the next value's run, or, when none follows, until the results the service holds have been fetched.
  // Each value is saved to the criterion it was given for, with the mode it was given in: through the form while that criterion is
  // shown, else straight to it (saveToCriterion); a value of a mode the criterion no longer has, or of a criterion gone, is dropped.
  const thresholdQueue = useMemo(() => createThresholdUpdateQueue<ThresholdValue>(async ({ values, mode }, isSuperseded, criterionId) => {
    const now = latest.current.context;
    if (thresholdControlOf(mode) === null) return false;
    if (criterionId === (now.criterionId ?? "")) {
      if (now.form.mode !== mode || latest.current.analysisOutOfDate) return false;
      const revisionBefore = now.currentForm().storedAnalysisRevision;
      const outcome = await now.changeAndSave(values);
      if (outcome !== "saved" && outcome !== "none") return false;
      // The save stored a mode or an analysis setting a refused save had left in the form: the carving waits for Run analysis.
      if (analysisChangedBy(revisionBefore)) return false;
    } else if (now.saveToCriterion === undefined || !(await now.saveToCriterion(criterionId, mode, values))) {
      return false;
    }
    if (!carvingRunsNow()) return false;
    // The service thresholds again from the first criterion whose carving is not current, this one, and the criteria after it.
    const runOutcome = await now.runs.start(project, CARVING_STAGES, "carving_update", { isSuperseded, chainOrder: latest.current.context.chainOrder });
    return runOutcome !== "up_to_date" && runOutcome !== "not_started";
  }, () => showResultsTheServiceHolds.current(CARVING_STAGES)), []);
  const submitThreshold = (values: Record<string, unknown>) => thresholdQueue.submit({ values, mode: form.mode }, context.criterionId ?? "");

  const feedback = (origin: RunOrigin) => (
    <RunProgress runs={runs} project={project} origin={origin} mode={form.mode} onGoToSetting={context.goToSetting} criterionNames={context.criterionNames} />
  );

  const carvingUpdateRunning = runs.activeRun?.project === project && runs.activeRun.origin === "carving_update";
  const otherRunActive = runs.activeRun !== null && !(autoUpdate && carvingUpdateRunning);
  const settingsDisabledReason = projectRunActive ? messages.runInProgress : null;
  const thresholdView = thresholdControlOf(form.mode);
  const changeSettings = (values: Record<string, unknown>) => dispatch({ type: "values_changed", values });

  // A build reads the carving of every criterion, so it waits while the analysis of any is out of date: it would run that analysis
  // first, which only Run analysis starts (M10). The first reason that blocks a run comes first, as for Run analysis.
  const buildBlocker = runBlocker ?? (chainAnalysisOutOfDate ? messages.buildWaitsForAnalysis : null);
  const buildButton = (label: string, produce: PipelineStage[], origin: RunOrigin) => (
    <RunAnalysisButton blocker={buildBlocker} label={label} feedback={feedback(origin)} onRunAnalysis={() => void startAfterSaving(produce, origin)} />
  );
  // The button pinned in Criteria builds both parts; its run is shown in the Envelope and massing step, which it opens.
  const buildFromCarvingButton = (
    <RunAnalysisButton blocker={buildBlocker} label={messages.buildEnvelopeAndMassing}
                       onRunAnalysis={() => {
                         context.openStep("envelope_and_massing");
                         void startAfterSaving(BUILD_STAGES, "build");
                       }} />
  );

  const download = (file: ExportDownload) => {
    setDownloadProblem(null);
    downloadWithToken(token, file.address, file.fileName).catch((error) => {
      if (serviceProblemOf(error) !== "other") context.onServiceProblem(error);
      else setDownloadProblem(failureTextOf(error));
    });
  };
  // A format change rebuilds the parts that exist (the envelope, the massing or both), so every file is in the new format at once.
  // They read the carving: while Carving is locked the format is stored and the parts keep their out-of-date marks, as the build
  // buttons wait (M10).
  const formatRunReason = chainAnalysisOutOfDate ? messages.buildWaitsForAnalysis : null;
  const changeMeshFormat = async (format: string) => {
    const outcome = await changeAndSave({ final_mesh_format: format });
    const partsBuilt = BUILD_STAGES.filter((stage) => stages[stage] !== "missing");
    if ((outcome === "saved" || outcome === "none") && partsBuilt.length > 0 && !buildsLocked.current) void startRun(partsBuilt, "export_format");
  };

  // A part's results show once its stage is recorded, or done in the run under way (as isStageDimmed counts it): a run that wrote
  // the envelope and then failed recorded neither part, and the step does not call a missing stage's results built.
  const builtBy = (stage: PipelineStage) => stages[stage] !== "missing" || (running && stageRunState(record.state, stage) === "done");
  const envelopeBuilt = builtBy("exporting"), massingBuilt = builtBy("massing");
  // The stages the run under way has still to finish: each removes its old files when it begins, so Export does not offer them.
  const stagesStillToFinish = running ? runStages(record.state).filter((stage) => stageRunState(record.state, stage) !== "done") : [];
  const criterionCarving = carvingOfCriterion(results.summary, context.criterionId);
  // A carving change of the selected criterion waits for another criterion's analysis: said over the carving when it updates on
  // its own, at Update carving otherwise.
  const waitsFor = context.analysisWaitsFor ?? null;
  const carvingWaitReason = analysisOutOfDate || waitsFor === null ? null
    : waitsFor.protectsNothing ? messages.addTestSurfacesTo(waitsFor.name) : messages.carvingWaitsForAnalysisOf(waitsFor.name);
  const carvingUpdatesOnItsOwn = autoUpdate && thresholdView !== null;
  // Before the selected criterion's first analysis there is no carving to show: the reason, how the last carving update ended,
  // and the carving settings a refused save marked, so they can be fixed. A bypassed criterion has no carving in the chain.
  const carvingRule = context.criterionBypassed === true ? <p className="step-reason">{messages.criterionBypassedNote}</p>
    : ownStages.thresholding === "missing" ? (
    <>
      <p className="step-not-usable">{messages.carvingNeedsAnalysis}</p>
      {feedback("carving_update")}
      <SettingsToFix step="carving" form={form} onChange={changeSettings} disabledReason={settingsDisabledReason} />
    </>
  ) : (
    <>
      {carvingWaitReason !== null && carvingUpdatesOnItsOwn && <p className="step-reason">{carvingWaitReason}</p>}
      <CarvingStep form={form} isWeightedMode={context.isWeightedMode} summary={criterionCarving} scorePoints={results.scorePoints}
                   analysisOutOfDate={analysisOutOfDate}
                   carvingDimmed={isStageDimmed("thresholding", record, ownStages, stagesBeingFetched, context.criterionId)}
                   autoUpdate={autoUpdate} onAutoUpdateChange={setAutoUpdate}
                   thresholdDisabledReason={otherRunActive ? messages.runInProgress : null} settingsDisabledReason={settingsDisabledReason}
                   runBlocker={runBlocker ?? carvingWaitReason} onChange={changeSettings}
                   onThresholdCommit={submitThreshold}
                   onCarvingSettingCommit={() => { if (thresholdView !== null) submitThreshold({}); }}
                   onUpdateCarving={() => void updateCarvingAfterSaving()}
                   lastAnalysisSeconds={lastAnalysisSeconds} carvingFeedback={feedback("carving_update")} showsDisabledReason={false} />
    </>
  );
  const criterionRunAnalysis = (
    <RunAnalysisButton blocker={runBlocker} feedback={feedback("carving_run_analysis")}
                       onRunAnalysis={() => void startAfterSaving(ANALYSIS_STAGES, "carving_run_analysis")} />
  );
  const content = {
    envelope_and_massing: (
      <EnvelopeAndMassingStep form={form} onChange={changeSettings} disabledReason={settingsDisabledReason}
                              envelope={envelopeBuilt ? results.summary?.envelope ?? null : null} envelopeOutOfDate={stages.exporting === "out_of_date"}
                              envelopeButton={buildButton(messages.buildEnvelope, ENVELOPE_STAGES, "build_envelope")}
                              massing={massingBuilt ? results.summary?.massing ?? null : null} platesFile={massingBuilt ? results.platesFile : null}
                              massingOutOfDate={stages.massing === "out_of_date"}
                              massingButton={buildButton(messages.buildMassing, MASSING_STAGES, "build_massing")} buildFeedback={feedback("build")}
                              hasRunReport={stages.exporting !== "missing" || stages.massing !== "missing"} onOpenRunReport={() => setRunReportOpen(true)} />
    ),
    export: (
      <ExportStep form={form} disabledReason={runs.activeRun !== null ? messages.runInProgress : null} formatRunReason={formatRunReason}
                  onFormatChange={(format) => void changeMeshFormat(format)}
                  downloads={exportDownloads({ project, meshFormat, envelopeFile: results.summary?.envelope?.mesh_file ?? null, envelope: stages.exporting,
                                               massingFile: results.summary?.massing?.export_mesh_file ?? null, massing: stages.massing,
                                               stagesBeingRebuilt: stagesStillToFinish })}
                  onDownload={download} formatFeedback={feedback("export_format")} downloadProblem={downloadProblem}
                  carveFurther={<CarveFurtherSection onCarveFurther={context.onCarveFurther}
                                                     disabledReason={runs.activeRun !== null ? messages.runInProgress
                                                       : stages.exporting !== "current" ? messages.carveFurtherNeedsCurrentEnvelope : null} />} />
    ),
  };

  // The 3D view follows the step: a part written by a run that then failed is not drawn, as its stage is not recorded.
  const viewerResults: RunResults = { ...results, envelope: envelopeBuilt ? results.envelope : null, massing: massingBuilt ? results.massing : null };
  const warningsOfStep: Partial<Record<StepName, number>> = {};
  if (record !== null && record.state.final !== null && record.state.issues.length > 0) warningsOfStep[STEP_OF_ORIGIN[record.origin]] = record.state.issues.length;

  return {
    content,
    carvingRule,
    criterionRunAnalysis,
    pinnedAction: context.everyCriterionCarved ? { criteria: buildFromCarvingButton } : {},
    viewer: {
      results: { scorePoints: viewerResults.scorePoints, carving: criterionCarving, skyDome: viewerResults.skyDome,
                 envelope: viewerResults.envelope, massing: viewerResults.massing, carvedByCriterion: viewerResults.carvedByCriterion },
      // The by-criterion layer follows every criterion that is on, not only the selected one: it is dimmed too when any of them is not current.
      dimmedLayers: [...new Set([...dimmedLayersOf(record, ownStages, stagesBeingFetched, context.criterionId),
                                 ...(context.carvedByCriterionOutOfDate === true ? ["carved_by_criterion" as const] : [])])],
      missingLayers: [...missingLayersOf(record, viewerResults, context.isWeightedMode),
                      ...(context.carvedByCriterionWanted === true && viewerResults.carvedByCriterion === null ? ["carved_by_criterion" as const] : [])],
      runProgress: running ? runProgressShare(record.state) : null,
      overlayContent: runReportOpen
        ? <RunReportPanel token={token} project={project} onClose={() => setRunReportOpen(false)} onServiceProblem={context.onServiceProblem} />
        : null,
    },
    results,
    criteriaAwaitingNumbers,
    warningsOfStep,
    feedback,
    feedbackWhenNotUsable: {
      envelope_and_massing: <>{feedback("build")}{feedback("build_envelope")}{feedback("build_massing")}</>,
    },
    startRun,
  };
}

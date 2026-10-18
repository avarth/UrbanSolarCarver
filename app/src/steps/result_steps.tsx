// The steps that show and start runs (UX 5.5 to 5.7, 6): Carving, Envelope and massing and Export, their buttons (Carving's
// pinned under the steps, Build envelope and Build massing in the two parts of their step, R2 5), the progress under the button
// that started a run, and what the 3D view draws of the results (dimmed while out of date or replaced, listed as missing after a
// run that stopped before their stage). ProjectWorkspace gives them the project's form, stage status and run loop; the results
// are fetched here and again as each stage of a run is done.
import { useMemo, useRef, useState, type ReactNode } from "react";
import { downloadWithToken, failureTextOf, serviceProblemOf } from "../api_client/client";
import { messages } from "../messages";
import { analysisDiffersFromStored, shownValue, type FormState, type FormAction, type SaveOutcome } from "../settings_form/form_state";
import type { Point3 } from "../viewer/local_origin";
import type { LayerName } from "../viewer/scene";
import type { ViewerPaneProps } from "../viewer_overlays/ViewerPane";
import { CarvingStep, thresholdControlNumber, thresholdControlOf, thresholdControlValues, useAutoUpdate } from "./CarvingStep";
import { EnvelopeAndMassingStep } from "./EnvelopeAndMassingStep";
import { exportDownloads, ExportStep, type ExportDownload } from "./ExportStep";
import { RunProgress } from "./RunProgress";
import { RunReportPanel } from "./RunReportPanel";
import { runAnalysisAfterSaving, RunAnalysisButton } from "./SettingsStep";
import { runProgressShare, type RunLoop, type RunOrigin, type RunOutcome, type RunRecord } from "./run_state";
import { useResultsFollowingRun, useRunResults, type RunResults } from "./run_results";
import type { PipelineStage, StageState, StepName } from "./step_summaries";
import { createThresholdUpdateQueue } from "./threshold_queue";

export const ANALYSIS_STAGES: PipelineStage[] = ["thresholding"];     // Run analysis: preprocessing is added when it is out of date
export const CARVING_STAGES: PipelineStage[] = ["thresholding"];
export const BUILD_STAGES: PipelineStage[] = ["exporting", "massing"];     // Carving's Build envelope and massing
// Build envelope and Build massing (R2 5): the massing reads the carving, not the envelope, so each runs its own stage. A mesh
// format change runs the envelope's.
export const ENVELOPE_STAGES: PipelineStage[] = ["exporting"];
export const MASSING_STAGES: PipelineStage[] = ["massing"];
const PIPELINE_STAGES: readonly PipelineStage[] = ["preprocessing", "thresholding", "exporting", "massing"];

/** The step whose summary counts the warnings of a run started by each button. */
const STEP_OF_ORIGIN: Record<RunOrigin, StepName> = {
  settings_run_analysis: "settings",
  carving_run_analysis: "carving",
  carving_update: "carving",
  build: "envelope_and_massing",
  build_envelope: "envelope_and_massing",
  build_massing: "envelope_and_massing",
  export_format: "export",
};

/** The layers each stage's results are drawn in. */
const LAYERS_OF_STAGE: Record<PipelineStage, LayerName[]> = {
  preprocessing: ["sky_dome"],
  thresholding: ["kept_voxels", "carved_voxels"],
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
                              stagesBeingFetched: readonly PipelineStage[] = []): boolean {
  if (stagesBeingFetched.includes(stage)) return true;
  const runUnderWay = record !== null && record.state.final === null && record.refusal === null;
  if (runUnderWay && record.state.order.includes(stage)) return record.state.stages[stage].state !== "done";
  if (record !== null && record.state.order.includes(stage) && (record.isSuperseded?.() ?? false)) return true;
  return stages[stage] !== "current";
}

export function dimmedLayersOf(record: RunRecord | null, stages: Record<PipelineStage, StageState>,
                               stagesBeingFetched: readonly PipelineStage[] = []): LayerName[] {
  return (Object.keys(LAYERS_OF_STAGE) as PipelineStage[]).filter((stage) => isStageDimmed(stage, record, stages, stagesBeingFetched))
    .flatMap((stage) => LAYERS_OF_STAGE[stage]);
}

/** The layers of a run that was cancelled or failed whose stage left no data: listed with the missing-result note (UX 8.2). */
export function missingLayersOf(record: RunRecord | null, results: RunResults, isWeightedMode: boolean): LayerName[] {
  if (record === null || (record.state.final !== "cancelled" && record.state.final !== "failed")) return [];
  return record.state.order.flatMap((stage) => LAYERS_OF_STAGE[stage as PipelineStage] ?? [])
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

export interface ResultStepsContext {
  token: string;
  project: string;
  form: FormState;
  /** The form after every action so far, read after a save is awaited. */
  currentForm: () => FormState;
  dispatch: (action: FormAction) => void;
  flushSave: () => Promise<SaveOutcome>;
  changeAndSave: (values: Record<string, unknown>) => Promise<SaveOutcome>;
  isWeightedMode: boolean;
  stages: Record<PipelineStage, StageState>;
  /** Asks for the stage status again; *completedStages* count as current until the reply. */
  refreshStageStatus: (completedStages?: readonly string[]) => void;
  runs: RunLoop;
  /** Why no run can start now (a run, the inputs, a setting, the warm-up); null when one can. */
  runBlocker: string | null;
  /** A run of this project is starting or in progress: the service refuses to save its settings. */
  projectRunActive: boolean;
  origin: Point3;
  openStep: (step: StepName) => void;
  goToSetting: (settingName: string) => void;
  onServiceProblem: (error: unknown) => void;
}

export interface ResultSteps {
  content: Record<"carving" | "envelope_and_massing" | "export", ReactNode>;
  pinnedAction: Partial<Record<StepName, ReactNode>>;
  viewer: Pick<ViewerPaneProps, "results" | "dimmedLayers" | "missingLayers" | "runProgress" | "overlayContent">;
  results: RunResults;
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
  const [results, reloadResults] = useRunResults({
    token, project, origin: context.origin, onServiceProblem: context.onServiceProblem,
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
    context.refreshStageStatus(state.final === "finished" && !superseded ? state.order : []);
    if (state.final === "finished" && state.order.includes("preprocessing") && state.endedAt !== null) {
      setLastAnalysisSeconds((state.endedAt - state.startedAt) / 1000);
    }
    // A setting the run found invalid is marked in the form, as a refused save would mark it.
    if (state.failure !== null && state.failure.field_errors.length > 0) {
      dispatch({ type: "save_rejected", reply: { field_errors: state.failure.field_errors, grid_plan: form.gridPlan } });
    }
  });

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
    const outcome = await runs.start(project, produce, origin);
    if (outcome === "up_to_date") showResultsTheServiceHolds.current(stagesToFetchWhenUpToDate(produce, stages));
    return outcome;
  };
  const startAfterSaving = (produce: string[], origin: RunOrigin) => runAnalysisAfterSaving(flushSave, () => void startRun(produce, origin));

  // The carving is locked while the analysis is out of date for the settings shown (ProjectWorkspace counts every stage out of
  // date while the form's mode or analysis settings are not the stored ones). A carving run then would run the analysis first.
  const analysisOutOfDate = stages.preprocessing !== "current";
  const carvingLocked = useRef(analysisOutOfDate);
  carvingLocked.current = analysisOutOfDate;
  /** Whether the save just stored changed what the analysis reads, or the form still shows other analysis settings. */
  const analysisChangedBy = (revisionBefore: number) => {
    const latest = context.currentForm();
    return latest.storedAnalysisRevision !== revisionBefore || analysisDiffersFromStored(latest);
  };
  // Update carving: saved first, and run only when the save left the analysis as it was.
  const updateCarvingAfterSaving = async () => {
    if (carvingLocked.current) return;
    const revisionBefore = context.currentForm().storedAnalysisRevision;
    const outcome = await flushSave();
    if ((outcome === "saved" || outcome === "none") && !analysisChangedBy(revisionBefore) && !carvingLocked.current) void startRun(CARVING_STAGES, "carving_update");
  };

  // Threshold changes with auto-update on go through the queue: one carving run at a time, the last value next. A run whose value
  // the user left while it ran is marked so (RunRecord.isSuperseded): its results are not fetched and the carving stays dimmed
  // until the next value's run, or, when none follows, until the results the service holds have been fetched.
  const thresholdQueue = useMemo(() => createThresholdUpdateQueue(async (shownNumber, isSuperseded) => {
    const view = thresholdControlOf(form.mode);
    if (view === null || carvingLocked.current) return false;
    const revisionBefore = context.currentForm().storedAnalysisRevision;
    const outcome = await changeAndSave(thresholdControlValues(view, shownNumber));
    if (outcome !== "saved" && outcome !== "none") return false;
    // The save stored a mode or an analysis setting a refused save had left in the form: the carving waits for Run analysis.
    if (analysisChangedBy(revisionBefore) || carvingLocked.current) return false;
    const runOutcome = await runs.start(project, CARVING_STAGES, "carving_update", isSuperseded);
    return runOutcome !== "up_to_date" && runOutcome !== "not_started";
  }, () => showResultsTheServiceHolds.current(CARVING_STAGES)), [form.mode]);

  const feedback = (origin: RunOrigin) => (
    <RunProgress runs={runs} project={project} origin={origin} mode={form.mode} onGoToSetting={context.goToSetting} />
  );

  const carvingUpdateRunning = runs.activeRun?.project === project && runs.activeRun.origin === "carving_update";
  const otherRunActive = runs.activeRun !== null && !(autoUpdate && carvingUpdateRunning);
  const settingsDisabledReason = projectRunActive ? messages.runInProgress : null;
  const thresholdView = thresholdControlOf(form.mode);
  const changeSettings = (values: Record<string, unknown>) => dispatch({ type: "values_changed", values });

  // A build reads the carving, so it waits while Carving is locked: it would run the analysis first, which only Run analysis
  // starts (M10). The first reason that blocks a run comes first, as for Run analysis.
  const buildBlocker = runBlocker ?? (analysisOutOfDate ? messages.buildWaitsForAnalysis : null);
  const buildButton = (label: string, produce: PipelineStage[], origin: RunOrigin) => (
    <RunAnalysisButton blocker={buildBlocker} label={label} feedback={feedback(origin)} onRunAnalysis={() => void startAfterSaving(produce, origin)} />
  );
  // Carving's button builds both parts; its run is shown in the Envelope and massing step, which it opens.
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
  // A format change rebuilds the envelope, which reads the carving: while Carving is locked the format is stored and the envelope
  // keeps its out-of-date mark, as the build buttons wait (M10).
  const formatRunReason = analysisOutOfDate ? messages.buildWaitsForAnalysis : null;
  const changeMeshFormat = async (format: string) => {
    const outcome = await changeAndSave({ final_mesh_format: format });
    if ((outcome === "saved" || outcome === "none") && stages.exporting !== "missing" && !carvingLocked.current) void startRun(ENVELOPE_STAGES, "export_format");
  };

  // A part's results show once its stage is recorded, or done in the run under way (as isStageDimmed counts it): a run that wrote
  // the envelope and then failed recorded neither part, and the step does not call a missing stage's results built.
  const builtBy = (stage: PipelineStage) => stages[stage] !== "missing" || (running && record.state.stages[stage]?.state === "done");
  const envelopeBuilt = builtBy("exporting"), massingBuilt = builtBy("massing");
  // The stages the run under way has still to finish: each removes its old files when it begins, so Export does not offer them.
  const stagesStillToFinish = running ? record.state.order.filter((stage) => record.state.stages[stage].state !== "done") : [];
  const content = {
    carving: (
      <CarvingStep form={form} isWeightedMode={context.isWeightedMode} summary={results.summary?.carving ?? null} scorePoints={results.scorePoints}
                   analysisOutOfDate={analysisOutOfDate} carvingDimmed={isStageDimmed("thresholding", record, stages, stagesBeingFetched)}
                   autoUpdate={autoUpdate} onAutoUpdateChange={setAutoUpdate}
                   thresholdDisabledReason={otherRunActive ? messages.runInProgress : null} settingsDisabledReason={settingsDisabledReason}
                   runBlocker={runBlocker} onChange={changeSettings}
                   onThresholdCommit={(shownNumber) => thresholdQueue.submit(shownNumber)}
                   onCarvingSettingCommit={() => { if (thresholdView !== null) thresholdQueue.submit(thresholdControlNumber(form, thresholdView)); }}
                   onUpdateCarving={() => void updateCarvingAfterSaving()}
                   onRunAnalysis={() => void startAfterSaving(ANALYSIS_STAGES, "carving_run_analysis")}
                   lastAnalysisSeconds={lastAnalysisSeconds} carvingFeedback={feedback("carving_update")}
                   analysisFeedback={feedback("carving_run_analysis")} />
    ),
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
                                               massing: stages.massing, stagesBeingRebuilt: stagesStillToFinish })}
                  onDownload={download} formatFeedback={feedback("export_format")} downloadProblem={downloadProblem} />
    ),
  };

  // The 3D view follows the step: a part written by a run that then failed is not drawn, as its stage is not recorded.
  const viewerResults: RunResults = { ...results, envelope: envelopeBuilt ? results.envelope : null, massing: massingBuilt ? results.massing : null };
  const warningsOfStep: Partial<Record<StepName, number>> = {};
  if (record !== null && record.state.final !== null && record.state.issues.length > 0) warningsOfStep[STEP_OF_ORIGIN[record.origin]] = record.state.issues.length;

  return {
    content,
    pinnedAction: { carving: buildFromCarvingButton },
    viewer: {
      results: { scorePoints: viewerResults.scorePoints, carving: viewerResults.summary?.carving ?? null, skyDome: viewerResults.skyDome,
                 envelope: viewerResults.envelope, massing: viewerResults.massing },
      dimmedLayers: dimmedLayersOf(record, stages, stagesBeingFetched),
      missingLayers: missingLayersOf(record, viewerResults, context.isWeightedMode),
      runProgress: running ? runProgressShare(record.state) : null,
      overlayContent: runReportOpen
        ? <RunReportPanel token={token} project={project} onClose={() => setRunReportOpen(false)} onServiceProblem={context.onServiceProblem} />
        : null,
    },
    results,
    warningsOfStep,
    feedback,
    feedbackWhenNotUsable: {
      carving: <>{feedback("carving_run_analysis")}{feedback("carving_update")}</>,
      envelope_and_massing: <>{feedback("build")}{feedback("build_envelope")}{feedback("build_massing")}</>,
    },
    startRun,
  };
}

// The steps that show and start runs (UX 5.5 to 5.7, 6): Carving, Envelope and massing and Export, their pinned buttons, the
// progress under the button that started a run, and what the 3D view draws of the results (dimmed while out of date or
// replaced, listed as missing after a run that stopped before their stage). ProjectWorkspace gives them the project's form,
// stage status and run loop; the results are fetched here and again as each stage of a run is done.
import { useMemo, useState, type ReactNode } from "react";
import { downloadWithToken, refusalDetailOf, serviceProblemOf } from "../api_client/client";
import { messages } from "../messages";
import { shownValue, type FormState, type FormAction, type SaveOutcome } from "../settings_form/form_state";
import type { Point3 } from "../viewer/local_origin";
import type { LayerName } from "../viewer/scene";
import type { ViewerPaneProps } from "../viewer_overlays/ViewerPane";
import { CarvingStep, thresholdControlNumber, thresholdControlOf, thresholdControlValues, useAutoUpdate } from "./CarvingStep";
import { EnvelopeAndMassingStep } from "./EnvelopeAndMassingStep";
import { exportDownloads, ExportStep, type ExportDownload } from "./ExportStep";
import { RunProgress } from "./RunProgress";
import { RunReportPanel } from "./RunReportPanel";
import { runAnalysisAfterSaving, RunAnalysisButton } from "./SettingsStep";
import { runProgressShare, type RunLoop, type RunOrigin, type RunRecord } from "./run_state";
import { useResultsFollowingRun, useRunResults, type RunResults } from "./run_results";
import type { PipelineStage, StageState, StepName } from "./step_summaries";
import { createThresholdUpdateQueue } from "./threshold_queue";

export const ANALYSIS_STAGES = ["thresholding"];                 // Run analysis: preprocessing is added when it is out of date
export const CARVING_STAGES = ["thresholding"];
export const BUILD_STAGES = ["exporting", "massing"];
export const ENVELOPE_MESH_STAGES = ["exporting"];

/** The step whose summary counts the warnings of a run started by each button. */
const STEP_OF_ORIGIN: Record<RunOrigin, StepName> = {
  settings_run_analysis: "settings",
  carving_run_analysis: "carving",
  carving_update: "carving",
  build: "envelope_and_massing",
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
 * after a run of a value the user has since left, whose results were not fetched (the run that follows brings them); otherwise
 * while its stage status is not current (UX 6.3).
 */
export function isStageDimmed(stage: PipelineStage, record: RunRecord | null, stages: Record<PipelineStage, StageState>): boolean {
  const runUnderWay = record !== null && record.state.final === null && record.refusal === null;
  if (runUnderWay && record.state.order.includes(stage)) return record.state.stages[stage].state !== "done";
  if (record !== null && record.state.order.includes(stage) && (record.isSuperseded?.() ?? false)) return true;
  return stages[stage] !== "current";
}

export function dimmedLayersOf(record: RunRecord | null, stages: Record<PipelineStage, StageState>): LayerName[] {
  return (Object.keys(LAYERS_OF_STAGE) as PipelineStage[]).filter((stage) => isStageDimmed(stage, record, stages)).flatMap((stage) => LAYERS_OF_STAGE[stage]);
}

/** The layers of a run that was cancelled or failed whose stage left no data: listed with the missing-result note (UX 8.2). */
export function missingLayersOf(record: RunRecord | null, results: RunResults, isWeightedMode: boolean): LayerName[] {
  if (record === null || (record.state.final !== "cancelled" && record.state.final !== "failed")) return [];
  return record.state.order.flatMap((stage) => LAYERS_OF_STAGE[stage as PipelineStage] ?? [])
    .filter((layer) => (layer !== "sky_dome" || isWeightedMode) && !layerHasData(layer, results));
}

export interface ResultStepsContext {
  token: string;
  project: string;
  form: FormState;
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
}

export function useResultSteps(context: ResultStepsContext): ResultSteps {
  const { token, project, form, dispatch, flushSave, changeAndSave, stages, runs, runBlocker, projectRunActive } = context;
  const meshFormat = String(shownValue(form, "final_mesh_format") ?? "ply");
  const [results, reloadResults] = useRunResults({
    token, project, origin: context.origin, meshFormat, onServiceProblem: context.onServiceProblem,
    stagesWithResults: (Object.keys(stages) as PipelineStage[]).filter((stage) => stages[stage] !== "missing"),
  });
  const [autoUpdate, setAutoUpdate] = useAutoUpdate(project);
  const [lastAnalysisSeconds, setLastAnalysisSeconds] = useState<number | null>(null);
  const [runReportOpen, setRunReportOpen] = useState(false);
  const [downloadProblem, setDownloadProblem] = useState<string | null>(null);
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

  const startAfterSaving = (produce: string[], origin: RunOrigin) =>
    runAnalysisAfterSaving(flushSave, () => void runs.start(project, produce, origin));

  // Threshold changes with auto-update on go through the queue: one carving run at a time, the last value next. A run whose value
  // the user left while it ran is marked so (RunRecord.isSuperseded): its results are not fetched and the carving stays dimmed.
  const thresholdQueue = useMemo(() => createThresholdUpdateQueue(async (shownNumber, isSuperseded) => {
    const view = thresholdControlOf(form.mode);
    if (view === null) return;
    const outcome = await changeAndSave(thresholdControlValues(view, shownNumber));
    if (outcome === "saved" || outcome === "none") await runs.start(project, CARVING_STAGES, "carving_update", isSuperseded);
  }), [form.mode]);

  const feedback = (origin: RunOrigin) => (
    <RunProgress runs={runs} project={project} origin={origin} mode={form.mode} onGoToSetting={context.goToSetting} />
  );


  const analysisOutOfDate = stages.preprocessing !== "current";
  const carvingUpdateRunning = runs.activeRun?.project === project && runs.activeRun.origin === "carving_update";
  const otherRunActive = runs.activeRun !== null && !(autoUpdate && carvingUpdateRunning);
  const settingsDisabledReason = projectRunActive ? messages.runInProgress : null;
  const thresholdView = thresholdControlOf(form.mode);
  const changeSettings = (values: Record<string, unknown>) => dispatch({ type: "values_changed", values });

  const buildButton = (opensEnvelopeStep: boolean) => (
    <RunAnalysisButton blocker={runBlocker} label={messages.buildEnvelopeAndMassing}
                       feedback={opensEnvelopeStep ? null : feedback("build")}
                       onRunAnalysis={() => {
                         if (opensEnvelopeStep) context.openStep("envelope_and_massing");
                         void startAfterSaving(BUILD_STAGES, "build");
                       }} />
  );

  const download = (file: ExportDownload) => {
    setDownloadProblem(null);
    downloadWithToken(token, file.address, file.fileName).catch((error) => {
      if (serviceProblemOf(error) !== "other") context.onServiceProblem(error);
      else setDownloadProblem(refusalDetailOf(error) ?? String(error));
    });
  };
  const changeMeshFormat = async (format: string) => {
    const outcome = await changeAndSave({ final_mesh_format: format });
    if ((outcome === "saved" || outcome === "none") && stages.exporting !== "missing") void runs.start(project, ENVELOPE_MESH_STAGES, "export_format");
  };

  const content = {
    carving: (
      <CarvingStep form={form} isWeightedMode={context.isWeightedMode} summary={results.summary?.carving ?? null} scorePoints={results.scorePoints}
                   analysisOutOfDate={analysisOutOfDate} carvingDimmed={isStageDimmed("thresholding", record, stages)}
                   autoUpdate={autoUpdate} onAutoUpdateChange={setAutoUpdate}
                   thresholdDisabledReason={otherRunActive ? messages.runInProgress : null} settingsDisabledReason={settingsDisabledReason}
                   runBlocker={runBlocker} onChange={changeSettings}
                   onThresholdCommit={(shownNumber) => thresholdQueue.submit(shownNumber)}
                   onCarvingSettingCommit={() => { if (thresholdView !== null) thresholdQueue.submit(thresholdControlNumber(form, thresholdView)); }}
                   onUpdateCarving={() => void startAfterSaving(CARVING_STAGES, "carving_update")}
                   onRunAnalysis={() => void startAfterSaving(ANALYSIS_STAGES, "carving_run_analysis")}
                   lastAnalysisSeconds={lastAnalysisSeconds} carvingFeedback={feedback("carving_update")}
                   analysisFeedback={feedback("carving_run_analysis")} />
    ),
    envelope_and_massing: (
      <EnvelopeAndMassingStep form={form} onChange={changeSettings} disabledReason={settingsDisabledReason} massing={results.summary?.massing ?? null}
                              platesFile={results.platesFile} outOfDate={stages.exporting === "out_of_date" || stages.massing === "out_of_date"}
                              hasRunReport={stages.exporting !== "missing" || stages.massing !== "missing"} onOpenRunReport={() => setRunReportOpen(true)} />
    ),
    export: (
      <ExportStep form={form} disabledReason={runs.activeRun !== null ? messages.runInProgress : null} onFormatChange={(format) => void changeMeshFormat(format)}
                  downloads={exportDownloads({ project, meshFormat, envelopeOutOfDate: stages.exporting === "out_of_date", massingOutOfDate: stages.massing === "out_of_date" })}
                  onDownload={download} formatFeedback={feedback("export_format")} downloadProblem={downloadProblem} />
    ),
  };

  const warningsOfStep: Partial<Record<StepName, number>> = {};
  if (record !== null && record.state.final !== null && record.state.issues.length > 0) warningsOfStep[STEP_OF_ORIGIN[record.origin]] = record.state.issues.length;

  return {
    content,
    pinnedAction: { carving: buildButton(true), envelope_and_massing: buildButton(false) },
    viewer: {
      results: { scorePoints: results.scorePoints, carving: results.summary?.carving ?? null, skyDome: results.skyDome, envelope: results.envelope,
                 massing: results.massing },
      dimmedLayers: dimmedLayersOf(record, stages),
      missingLayers: missingLayersOf(record, results, context.isWeightedMode),
      runProgress: running ? runProgressShare(record.state) : null,
      overlayContent: runReportOpen
        ? <RunReportPanel token={token} project={project} onClose={() => setRunReportOpen(false)} onServiceProblem={context.onServiceProblem} />
        : null,
    },
    results,
    warningsOfStep,
    feedback,
    feedbackWhenNotUsable: { carving: <>{feedback("carving_run_analysis")}{feedback("carving_update")}</>, envelope_and_massing: feedback("build") },
  };
}

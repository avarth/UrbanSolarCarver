// An open project (UX 4): the step accordion in the left panel and the 3D view beside it. It holds what the steps share: the
// input files, the settings form (the Mode step and the Settings step both change it), the stage status the step summaries
// read, and the input meshes (input_meshes.ts) and the sun path (sun_path_request.ts) the 3D view draws. The steps that
// start runs and show their results (Carving, Envelope and massing, Export) are put together in result_steps.tsx from these
// and the app's run loop.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  addInput, ApiError, failureTextOf, getStageStatus, removeInput, serviceProblemOf,
  type HealthReply, type InputFileInfo, type InputFilesReply, type ModeInfo, type ProjectDetail,
} from "../api_client/client";
import { listedWithAnd, messages } from "../messages";
import { hemisphereOfLatitude, seasonsOfLatitude, type Hemisphere } from "../settings_form/analysis_period";
import { analysisDiffersFromStored, shownValue, useSettingsForm, type SaveOutcome } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, fieldSettingOf, SETTING_PRESENTATIONS } from "../settings_form/presentation";
import { localOrigin, type Bounds3, type Point3 } from "../viewer/local_origin";
import type { LayerName } from "../viewer/scene";
import { sceneHemisphere } from "../viewer/sky_dome";
import { ViewerPane } from "../viewer_overlays/ViewerPane";
import { useColdPeriod } from "./cold_period_request";
import { boundsOf, useInputGeometry, type MeshRole } from "./input_meshes";
import { InputBox, InputsStep, type AddInputFiles, type InputRole, type RemoveInputFile } from "./InputsStep";
import { ModeStep } from "./ModeStep";
import { ANALYSIS_STAGES, useResultSteps } from "./result_steps";
import type { RunLoop } from "./run_state";
import {
  RunAnalysisButton, runAnalysisAfterSaving, runAnalysisBlocker, SaveFailureNotice, saveFailureTextOf, SettingsStep, SettingsToFix, settingsToFixByStep,
} from "./SettingsStep";
import { StepAccordion, type AccordionStep } from "./StepAccordion";
import {
  plainModeName, STEP_NAMES, stepMark, stepNotUsableYet, stepSummary, type PipelineStage, type ProjectViewState, type StageState, type StepName,
} from "./step_summaries";
import { analysisPeriodOf, useSunPathOfStoredPeriod } from "./sun_path_request";
import { periodChangedSince, weatherChangeSuggestion, type WeatherFileChange } from "./weather_change_notice";

const NO_SHIFT: Point3 = [0, 0, 0];
const STEPS_WITH_SOLID_MAX_VOLUME: readonly StepName[] = ["inputs", "mode", "settings"];
// The layers each step shows by default (UX 8.2); the later steps add their result layers.
const LAYERS_SHOWN_IN_STEP: Record<StepName, readonly LayerName[]> = {
  inputs: ["max_volume", "test_surfaces"],
  mode: ["max_volume", "test_surfaces"],
  settings: ["max_volume", "test_surfaces", "sun_path"],
  carving: ["test_surfaces", "sun_path", "kept_voxels", "carved_voxels", "sky_dome"],
  envelope_and_massing: ["envelope", "building_massing"],
  export: ["envelope", "building_massing"],
};

interface ProjectWorkspaceProps {
  token: string;
  project: ProjectDetail;
  schema: Record<string, unknown>;
  modes: ModeInfo[];
  warmUpState: HealthReply["warm_up"]["state"] | null;
  /** The app's runs, one at a time: while one of this project is active the service refuses uploads, removals and saves. */
  runs: RunLoop;
  /** A request failed: the app shows the engine-stopped or access-lost overlay when the failure is one of those. */
  onServiceProblem: (error: unknown) => void;
  onShowProjects: () => void;
  /**
   * Given the saver of the settings once the workspace is open, and null when it closes: before a rename, reset or delete the app
   * waits for the input files under way, then saves or drops.
   */
  onSettingsSaverReady?: (saver: OpenProjectSettingsSaver | null) => void;
  /** The steps to open with (the workspace made again for a renamed project); absent: Inputs. */
  startSteps?: WorkspaceSteps;
  /** Told the open step and the step the view shows whenever either changes. */
  onStepsChange?: (steps: WorkspaceSteps) => void;
}

/** The step open in the panel (null when all are closed) and the step whose layers the 3D view shows: the last one opened. */
export interface WorkspaceSteps {
  open: StepName | null;
  view: StepName;
}

/** The settings saver of the open project, as the app uses it around a rename, reset or delete of that project. */
export interface OpenProjectSettingsSaver {
  /** Sends a waiting or failed save now; resolves with how it ended. */
  flush: () => Promise<SaveOutcome>;
  /** Drops a waiting or failed save, so closing the project sends nothing. */
  cancel: () => void;
  /** Resolves once the uploads and removals of input files under way have ended, so none reaches a renamed, reset or deleted project. */
  waitForInputChanges: () => Promise<void>;
}

/** Why a request about the inputs failed, in words for the file box. */
function inputProblemText(error: unknown, fileName: string): string {
  if (error instanceof ApiError && error.status === 409) return messages.runInProgress;
  const detail = failureTextOf(error);
  return detail.includes(fileName) ? detail : messages.fileProblem(fileName, detail);
}

export function ProjectWorkspace(props: ProjectWorkspaceProps) {
  const { token, project, modes, warmUpState, runs, onServiceProblem } = props;
  const formStart = useMemo(() => ({ schema: props.schema, modes, settings: project.settings, gridPlan: project.grid_plan }), []);
  const { form, dispatch, flushSave, cancelSave, changeAndSave, currentForm } = useSettingsForm(token, project.name, formStart);
  const runActive = runs.activeRun?.project === project.name;
  // The uploads and removals of input files under way, each until its reply (and the save it may start) is in.
  const inputChangesUnderWay = useRef(new Set<Promise<unknown>>());
  const waitForInputChanges = async () => {
    await Promise.allSettled(inputChangesUnderWay.current);
  };
  const followedInputChange = <Reply,>(change: Promise<Reply>): Promise<Reply> => {
    inputChangesUnderWay.current.add(change);
    void change.finally(() => inputChangesUnderWay.current.delete(change)).catch(() => {});
    return change;
  };
  useEffect(() => {
    props.onSettingsSaverReady?.({ flush: flushSave, cancel: cancelSave, waitForInputChanges });
    return () => props.onSettingsSaverReady?.(null);
  }, []);
  const [files, setFiles] = useState<Record<InputRole, InputFileInfo[]>>({
    max_volume: project.inputs.max_volume ?? [], test_surfaces: project.inputs.test_surfaces ?? [], weather: project.inputs.weather ?? [],
  });
  const [joinedBounds, setJoinedBounds] = useState<Bounds3 | null>(project.joined_bounds as Bounds3 | null);
  const [weatherLocation, setWeatherLocation] = useState(project.weather_location);
  const [weatherLatitude, setWeatherLatitude] = useState(project.weather_latitude);
  const [inputRevisions, setInputRevisions] = useState<Record<MeshRole, number>>({ max_volume: 0, test_surfaces: 0 });
  // Goes up whenever the weather file is added, replaced or removed: the service keeps one name for it, so its file list may not change.
  const [weatherFileRevision, setWeatherFileRevision] = useState(0);
  const weatherFileRevisionNow = useRef(0);
  // The weather file added or replaced last in this session, for the notice in Settings; null before one, and once it is dismissed.
  const [weatherFileChange, setWeatherFileChange] = useState<WeatherFileChange | null>(null);
  // The hemisphere of the last weather file the project had with seasons, kept across a removal and across a file within the tropics
  // or without a latitude: what the period was likely chosen for.
  const hemisphereOfLastWeatherFile = useRef<Hemisphere>(hemisphereOfLatitude(project.weather_latitude));
  const [stages, setStages] = useState(project.stage_status.stages as Record<PipelineStage, StageState>);
  // The stored analysis settings (FormState.storedAnalysisRevision) the last stage status used was asked for after.
  const [revisionOfStageStatus, setRevisionOfStageStatus] = useState(0);
  const storedAnalysisRevision = useRef(form.storedAnalysisRevision);
  storedAnalysisRevision.current = form.storedAnalysisRevision;
  const [openStep, setOpenStep] = useState<StepName | null>(props.startSteps?.open ?? "inputs");
  const [viewStep, setViewStep] = useState<StepName>(props.startSteps?.view ?? "inputs");
  useEffect(() => props.onStepsChange?.({ open: openStep, view: viewStep }), [openStep, viewStep]);
  const [framingRequest, setFramingRequest] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const [addFilesRequest, setAddFilesRequest] = useState(0);
  const [settingToFocus, setSettingToFocus] = useState<{ name: string } | null>(null);

  const modeInfo = modes.find((candidate) => candidate.name === form.mode);
  const modeNeedsWeatherFile = modeInfo?.needs_epw ?? false;
  const hasWeatherFile = files.weather.length > 0;
  const origin = joinedBounds === null ? NO_SHIFT : localOrigin(joinedBounds);
  const frameAllInputs = () => setFramingRequest((count) => count + 1);
  const maxVolumeMesh = useInputGeometry(token, project.name, "max_volume", files.max_volume, origin, inputRevisions.max_volume, frameAllInputs, onServiceProblem);
  const testSurfacesMesh = useInputGeometry(token, project.name, "test_surfaces", files.test_surfaces, origin, inputRevisions.test_surfaces, frameAllInputs,
                                        onServiceProblem);
  const maxVolume = maxVolumeMesh.geometry, testSurfaces = testSurfacesMesh.geometry;
  // The bounds of the maximum volume and the test surfaces loaded so far: the sun path and the sky dome are drawn around them (R2 2)
  const inputsBounds = useMemo(() => boundsOf([maxVolume, testSurfaces]), [maxVolume, testSurfaces]);
  const sceneSphere = useMemo(() => (inputsBounds === null ? null : sceneHemisphere(inputsBounds)), [inputsBounds]);
  const northDegrees = Number(shownValue(form, "north_deg") ?? 0);

  // A stage status read across a run of this project says "missing" for results still on screen: such a reply is not used
  // (RunLoop.replyStillHolds), and the run's end asks again. *completedStages*: the stages a run just completed are current at
  // once, so their layers are not dimmed until the reply.
  const refreshStageStatus = (completedStages: readonly string[] = []) => {
    if (completedStages.length > 0) setStages((current) => ({ ...current, ...Object.fromEntries(completedStages.map((stage) => [stage, "current"])) }));
    const replyStillHolds = runs.replyStillHolds(project.name);
    const revisionAsked = storedAnalysisRevision.current;
    getStageStatus(token, project.name).then((reply) => {
      if (!replyStillHolds()) return;
      setStages(reply.stages as Record<PipelineStage, StageState>);
      setRevisionOfStageStatus((revision) => Math.max(revision, revisionAsked));
    }).catch(onServiceProblem);
  };

  // The stage status describes the stored settings. While the form's mode or analysis settings are not those (a save waits or
  // was refused), or a save changed them and the stage status since is still to come, the analysis is out of date for the
  // settings shown: every stage counts as out of date, so Carving is locked and its results are dimmed (UX 5.5), and no
  // carving change can start the analysis of a mode the form does not show.
  const analysisOfOtherSettings = analysisDiffersFromStored(form) || revisionOfStageStatus < form.storedAnalysisRevision;
  const shownStages: Record<PipelineStage, StageState> = analysisOfOtherSettings
    ? Object.fromEntries(Object.entries(stages).map(([stage, state]) => [stage, state === "current" ? "out_of_date" : state])) as Record<PipelineStage, StageState>
    : stages;

  // A save changes what the stages were run with; its reply is in once no save waits.
  useEffect(() => {
    if (form.changeCount > 0 && !form.pendingSave) refreshStageStatus();
  }, [form.pendingSave]);

  useEffect(() => {
    if (form.saveFailure !== null && serviceProblemOf(form.saveFailure) !== "other") onServiceProblem(form.saveFailure);
  }, [form.saveFailure]);

  // The sun path of the stored period (UX 8.2), as soon as the weather file and the period are there, before any run.
  const sunPath = useSunPathOfStoredPeriod({ token, project: project.name, form, hasWeatherFile, northDegrees, onServiceProblem });
  const { coldPeriod, answeredWeatherFileRevision } = useColdPeriod({ token, project: project.name, form, hasWeatherFile, weatherFileRevision, onServiceProblem });
  const modeReadsPeriod = modeInfo?.needs_period ?? false;
  const periodShown = analysisPeriodOf(form, modeReadsPeriod);
  const weatherChangeSuggestionNow = weatherChangeSuggestion(weatherFileChange, {
    mode: form.mode, modeReadsPeriod, period: periodShown, coldPeriod, answeredWeatherFileRevision,
  });
  // Once the period is not the one the new file came with, the notice has nothing more to say about it, even if the period comes back.
  const weatherChangeOutlived = weatherFileChange !== null && periodChangedSince(weatherFileChange, periodShown);
  useEffect(() => {
    if (weatherChangeOutlived) setWeatherFileChange(null);
  }, [weatherChangeOutlived]);

  const inputsDisabledReason = runActive ? messages.runInProgress : null;

  const applyFilesReply = (reply: InputFilesReply) => {
    setFiles((current) => ({ ...current, [reply.role]: reply.files }));
    setJoinedBounds(reply.joined_bounds as Bounds3 | null);
    setWeatherLocation(reply.weather_location);
    setWeatherLatitude(reply.weather_latitude);
    if (reply.role === "weather") {
      weatherFileRevisionNow.current += 1;
      setWeatherFileRevision(weatherFileRevisionNow.current);
    } else {
      setInputRevisions((current) => ({ ...current, [reply.role]: current[reply.role as MeshRole] + 1 }));
    }
  };
  // A weather file added or replaced: the notice in Settings is about it and the period the form shows now (a later one replaces it).
  const noteNewWeatherFile = (reply: InputFilesReply) => {
    const shownForm = currentForm();
    const readsPeriod = modes.find((candidate) => candidate.name === shownForm.mode)?.needs_period ?? false;
    const newHemisphere = seasonsOfLatitude(reply.weather_latitude);
    setWeatherFileChange({
      weatherFileRevision: weatherFileRevisionNow.current, location: reply.weather_location, previousHemisphere: hemisphereOfLastWeatherFile.current,
      newHemisphere, periodBefore: analysisPeriodOf(shownForm, readsPeriod),
    });
    if (newHemisphere !== null) hemisphereOfLastWeatherFile.current = newHemisphere;
  };
  const afterInputsChanged = (role: InputRole) => {
    refreshStageStatus();
    // The grid follows the maximum volume; a save of the unchanged settings brings its new plan.
    if (role === "max_volume") dispatch({ type: "values_changed", values: {} });
  };

  const addFilesOneByOne: AddInputFiles = async (role, chosenFiles) => {
    const problems: string[] = [];
    for (const file of chosenFiles) {
      try {
        const reply = await addInput(token, project.name, role, file);
        applyFilesReply(reply);
        if (role === "weather") noteNewWeatherFile(reply);
      } catch (error) {
        if (serviceProblemOf(error) !== "other") {
          onServiceProblem(error);
          break;
        }
        problems.push(inputProblemText(error, file.name));
      }
    }
    if (problems.length < chosenFiles.length) afterInputsChanged(role);
    return problems;
  };

  const removeFileAndApply: RemoveInputFile = async (role, fileName) => {
    try {
      applyFilesReply(await removeInput(token, project.name, role, fileName));
      if (role === "weather") setWeatherFileChange(null);         // the notice was about the file removed
      afterInputsChanged(role);
      return null;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return inputProblemText(error, fileName);
    }
  };
  // The app waits for both before a rename, reset or delete of the project (waitForInputChanges).
  const addFiles: AddInputFiles = (role, chosenFiles) => followedInputChange(addFilesOneByOne(role, chosenFiles));
  const removeFile: RemoveInputFile = (role, fileName) => followedInputChange(removeFileAndApply(role, fileName));

  const openTheStep = (step: StepName | null) => {
    setOpenStep(step);
    if (step !== null) setViewStep(step);
  };

  // A failed run's link to the setting it names: the step that holds the setting opens and the focus goes to its field.
  const goToSetting = (settingName: string) => {
    const shownName = fieldSettingOf(settingName);
    const step = SETTING_PRESENTATIONS[shownName]?.step;
    if (step === undefined) return;
    openTheStep(step);
    setSettingToFocus({ name: shownName });
  };
  useEffect(() => {
    if (settingToFocus === null) return;
    // The input the field's label targets: the number field of a slider, the balance temperature's number of the balance widget.
    const field = panel.current?.querySelector<HTMLElement>(`[data-setting="${settingToFocus.name}"]`);
    const labelled = field?.dataset.inputId === undefined ? null : document.getElementById(field.dataset.inputId);
    (labelled ?? field?.querySelector<HTMLElement>(":is(input, select)"))?.focus();
  }, [settingToFocus]);

  // Either button of the notice ends it; the focus, on a button that goes away, moves to the period the notice was about.
  const endWeatherChangeNotice = () => {
    setWeatherFileChange(null);
    setSettingToFocus({ name: fieldSettingOf(ANALYSIS_PERIOD_FIELDS[0]) });
  };

  const runBlocker = runAnalysisBlocker({
    runActive: runs.activeRun !== null, maxVolumeFiles: files.max_volume.length, testSurfaceFiles: files.test_surfaces.length, modeNeedsWeatherFile,
    hasWeatherFile, form, warmUpState,
  });
  const resultSteps = useResultSteps({
    token, project: project.name, form, currentForm, dispatch, flushSave, changeAndSave, isWeightedMode: modeInfo?.score_kind === "weighted_sum", stages: shownStages,
    refreshStageStatus, runs, runBlocker, projectRunActive: runActive, origin, openStep: openTheStep, goToSetting, onServiceProblem,
  });

  const viewState: ProjectViewState = {
    maxVolumeFiles: files.max_volume.length,
    testSurfaceFiles: files.test_surfaces.length,
    hasWeatherFile,
    mode: form.mode,
    analysisPeriod: analysisPeriodOf(form, modeInfo?.needs_period ?? false),
    voxelSize: Number(shownValue(form, "voxel_size")),
    settingsToFix: settingsToFixByStep(form),
    stages: shownStages,
    keptPercent: resultSteps.results.summary?.carving?.retention_pct ?? null,
    totalFloorArea: resultSteps.results.summary?.massing?.total_floor_area_m2 ?? null,
    storeys: resultSteps.results.summary?.massing?.storeys_built ?? null,
  };

  const weatherHint = messages.weatherNeededFor(listedWithAnd(modes.filter((mode) => mode.needs_epw).map((mode) => plainModeName(mode.name))));
  const weatherBox = (
    <InputBox role="weather" files={files.weather} weatherLocation={weatherLocation} weatherHint={weatherHint} onAddFiles={addFiles}
              onRemoveFile={removeFile} disabledReason={inputsDisabledReason} weatherNeeded />
  );
  const stepContent: Record<StepName, ReactNode> = {
    inputs: (
      <InputsStep files={files} weatherLocation={weatherLocation} weatherHint={weatherHint} inputsBounds={inputsBounds} onAddFiles={addFiles}
                  onRemoveFile={removeFile} disabledReason={inputsDisabledReason}
                  drawingProblems={{ max_volume: maxVolumeMesh.drawingProblems, test_surfaces: testSurfacesMesh.drawingProblems }} />
    ),
    mode: (
      <ModeStep mode={form.mode} onChoose={(mode) => dispatch({ type: "mode_chosen", mode })} disabledReason={inputsDisabledReason}
                valuesReset={form.valuesResetByModeChange}
                weatherDropZone={modeNeedsWeatherFile && !hasWeatherFile ? weatherBox : null} />
    ),
    settings: <SettingsStep form={form} onChange={(values) => dispatch({ type: "values_changed", values })} disabledReason={inputsDisabledReason}
                            coldPeriod={coldPeriod} hemisphere={hemisphereOfLatitude(weatherLatitude)}
                            weatherChangeNotice={weatherChangeSuggestionNow === null ? null
                              : { suggestion: weatherChangeSuggestionNow, onDismiss: endWeatherChangeNotice }} />,
    ...resultSteps.content,
  };
  const summaryOf = (name: StepName) => {
    const warnings = resultSteps.warningsOfStep[name];
    const summary = stepSummary(name, viewState);
    return warnings === undefined ? summary : messages.summaryWithWarnings(summary, messages.warningCount(warnings));
  };
  const steps: AccordionStep[] = STEP_NAMES.map((name) => ({
    name,
    title: messages.stepTitles[name],
    summary: summaryOf(name),
    mark: stepMark(name, viewState),
    notUsableYet: stepNotUsableYet(name, viewState),
    content: stepContent[name],
    // A step that cannot be used yet shows the fields it holds with an error, so a setting to fix is never out of reach.
    feedbackWhenNotUsable: (
      <>
        {resultSteps.feedbackWhenNotUsable[name]}
        {name !== "inputs" && name !== "mode" && (
          <SettingsToFix step={name} form={form} onChange={(values) => dispatch({ type: "values_changed", values })} disabledReason={inputsDisabledReason} />
        )}
      </>
    ),
  }));

  const runAnalysis = () => void runAnalysisAfterSaving(flushSave, () => {
    void resultSteps.startRun(ANALYSIS_STAGES, "settings_run_analysis").then((outcome) => { if (outcome === "finished") openTheStep("carving"); });
  });
  const pinnedActions: Partial<Record<StepName, ReactNode>> = {
    settings: <RunAnalysisButton blocker={runBlocker} onRunAnalysis={runAnalysis} feedback={resultSteps.feedback("settings_run_analysis")} />,
    ...resultSteps.pinnedAction,
  };
  const openStepUsable = openStep !== null && stepNotUsableYet(openStep, viewState) === null;
  const openStepAction = openStep !== null && openStepUsable ? (pinnedActions[openStep] ?? null) : null;
  // A save that failed without field errors leaves the form showing values the service did not store: said whichever step is open.
  const saveFailureText = saveFailureTextOf(form.saveFailure);
  const saveFailureNotice = saveFailureText === null ? null : <SaveFailureNotice text={saveFailureText} onSaveAgain={() => void flushSave()} />;

  // The empty view's "Add files" leads to the Inputs step, where each role has its own box: the focus goes to the first one's button.
  useEffect(() => {
    if (addFilesRequest > 0) panel.current?.querySelector<HTMLButtonElement>(".inputs-step .input-add")?.focus();
  }, [addFilesRequest]);
  const hasNoMeshInputs = files.max_volume.length === 0 && files.test_surfaces.length === 0;
  const emptyViewContent = hasNoMeshInputs && (
    <div className="viewer-empty-state">
      <p>{messages.noInputsYet}</p>
      <button type="button" className="primary-button" onClick={() => { openTheStep("inputs"); setAddFilesRequest((count) => count + 1); }}>
        {messages.addFiles}
      </button>
      <button type="button" className="link-button" onClick={props.onShowProjects}>{messages.orTryAnExample}</button>
    </div>
  );

  return (
    <div className="workspace">
      <aside ref={panel} className="workspace-panel">
        <StepAccordion steps={steps} openStep={openStep} onOpenStep={openTheStep}
                       pinnedAction={saveFailureNotice === null && openStepAction === null ? null : <>{saveFailureNotice}{openStepAction}</>} />
      </aside>
      <section className="workspace-view">
        <ViewerPane maxVolume={maxVolume} testSurfaces={testSurfaces} sunPath={sunPath}
                    hemisphere={sceneSphere}
                    maxVolumeAppearance={STEPS_WITH_SOLID_MAX_VOLUME.includes(viewStep) ? "solid" : "ghost"}
                    shownByDefault={LAYERS_SHOWN_IN_STEP[viewStep]} northDegrees={northDegrees} framingRequest={framingRequest}
                    centreContent={emptyViewContent} localOrigin={origin} mode={form.mode}
                    analysisCurrent={shownStages.preprocessing === "current"} {...resultSteps.viewer} />
      </section>
    </div>
  );
}

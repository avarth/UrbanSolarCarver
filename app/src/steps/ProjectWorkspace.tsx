// An open project (UX 4, spec 7.1): the step accordion in the left panel (Inputs, Site and grid, Criteria, Envelope and massing,
// Export) and the 3D view beside it. It holds what the steps share: the input files and their meshes (use_input_files.ts), the
// criteria (useCriteria) and their cards' requests, the two settings forms (the shared settings, shown in Site and grid, and the
// selected criterion's, shown in its panel; the steps read them as one), the stage status the step summaries read
// (use_stage_status.ts, workspace_view_state.ts), and the sun path (sun_path_request.ts) the 3D view draws. The criteria's selection,
// run conditions and cards are in use_workspace_criteria.ts. The parts that start runs and show their results (the criterion's
// carving rule, Envelope and massing, Export) are put together in result_steps.tsx from these and the app's run loop. In Simulate the
// steps are hidden and the studies (use_studies.ts) are shown over the view (SimulateView), the selected one's values drawn on the
// geometry Simulate shows (use_study_view.ts).
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  putSharedSettings, serviceProblemOf, updateCriterion, type HealthReply, type ModeInfo, type ProjectDetail,
} from "../api_client/client";
import { filesOfOtherCriteria } from "../criteria/criteria_state";
import { CriteriaStep } from "../criteria/CriteriaStep";
import { CriterionPanel } from "../criteria/CriterionPanel";
import { usePanelSections } from "../criteria/PanelSection";
import { sectionOfSetting } from "../criteria/section_summaries";
import { testSurfaceCallsOf } from "../criteria/test_surface_calls";
import { useCriteria } from "../criteria/use_criteria";
import { useWorkspaceCriteria } from "../criteria/use_workspace_criteria";
import { listedWithAnd, messages } from "../messages";
import { hemisphereOfLatitude } from "../settings_form/analysis_period";
import { shownValue, useSettingsForm, type FormStart, type SaveOutcome, type SettingsSend } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, fieldSettingOf } from "../settings_form/presentation";
import { sharedRefusalShown, splitSettings, useBothForms } from "../settings_form/two_forms";
import type { LayerName, ViewportTheme } from "../viewer/scene";
import { sceneHemisphere } from "../viewer/sky_dome";
import { SimulateView } from "../simulate/SimulateView";
import type { StudyGeometry } from "../simulate/study_values";
import { useStudies } from "../simulate/use_studies";
import { useStudyView } from "../simulate/use_study_view";
import { ViewerPane } from "../viewer_overlays/ViewerPane";
import { useColdPeriod } from "./cold_period_request";
import { boundsOf } from "./input_meshes";
import { carvedByNote, InputBox, InputsStep, type InputRole } from "./InputsStep";
import { ANALYSIS_STAGES, useResultSteps } from "./result_steps";
import type { RunLoop } from "./run_state";
import { RunAnalysisButton, runAnalysisAfterSaving, SaveFailureNotice, saveFailureTextOf, SettingsToFix, stepOfSetting } from "./SettingsStep";
import { SiteAndGridStep } from "./SiteAndGridStep";
import { StepAccordion, type AccordionStep } from "./StepAccordion";
import { testSurfaceGroupsOf, testSurfaceOwners } from "./test_surface_groups";
import { plainModeName, STEP_NAMES, stepMark, stepNotUsableYet, stepSummary, type StepName } from "./step_summaries";
import { analysisPeriodOf, useSunPathOfStoredPeriod } from "./sun_path_request";
import { useInputFiles } from "./use_input_files";
import { InputChangesNotice } from "./InputChangesNotice";
import { useKeptScroll } from "./use_kept_scroll";
import { useStageStatus } from "./use_stage_status";
import { periodChangedSince, weatherChangeSuggestion } from "./weather_change_notice";
import { projectViewStateOf } from "./workspace_view_state";
import type { WorkspaceMode } from "./WorkspaceModeSwitch";

// The id the service gives the first criterion of a project (a new one's, or an earlier version's made a chain of one).
const FIRST_CRITERION_ID = "1";
const STEPS_WITH_SOLID_MAX_VOLUME: readonly StepName[] = ["inputs", "site_and_grid"];
// The layers each step shows by default (UX 8.2); the later steps add their result layers. The carved voxels start hidden, as
// they cover the kept ones; the Layers menu shows them. Criteria shows what the Mode and Carving steps showed together, the maximum
// volume as a ghost.
export const LAYERS_SHOWN_IN_STEP: Record<StepName, readonly LayerName[]> = {
  inputs: ["max_volume", "test_surfaces", "context", "terrain"],
  site_and_grid: ["max_volume", "test_surfaces", "context", "terrain", "sun_path"],
  criteria: ["max_volume", "test_surfaces", "context", "terrain", "sun_path", "kept_voxels", "sky_dome"],
  envelope_and_massing: ["context", "terrain", "envelope", "building_massing"],
  export: ["context", "terrain", "envelope", "building_massing"],
};
// The layers Simulate shows by default, for each geometry its study values are shown on.
const LAYERS_SHOWN_IN_SIMULATE: Record<StudyGeometry, readonly LayerName[]> = {
  max_volume: ["max_volume", "context", "terrain", "study_values"],
  envelope: ["envelope", "context", "terrain", "study_values"],
  massing: ["building_massing", "context", "terrain", "study_values"],
};

interface ProjectWorkspaceProps {
  /** Design: the steps beside the 3D view. Simulate: the steps are hidden and the view has the whole window. */
  mode: WorkspaceMode;
  token: string;
  project: ProjectDetail;
  schema: Record<string, unknown>;
  modes: ModeInfo[];
  /** The names of the settings that belong to a criterion (GET criterion-keys); every other setting is shared by the criteria. */
  criterionKeys: ReadonlySet<string>;
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

export function ProjectWorkspace(props: ProjectWorkspaceProps) {
  const { token, project, modes, criterionKeys, warmUpState, runs, onServiceProblem } = props;
  const criteria = useCriteria(token, project);
  // The studies of Simulate, kept while Design is shown (the selection stays); SimulateView reads them when Simulate opens.
  const studies = useStudies(token, project.name, onServiceProblem);
  // The criterion whose settings the criterion form holds: the selected one, once its settings are in (a card just selected waits
  // for GET criteria/{id}/settings). Its panel, its results and the run's check of its test surfaces follow it. A project that lists
  // none (its migration failed) still has the settings of one.
  const [shownCriterionId, setShownCriterionId] = useState(criteria.selectedId);
  const formCriterionId = shownCriterionId === "" ? FIRST_CRITERION_ID : shownCriterionId;
  // The shown criterion; while a deleted one's place waits for the next one's settings, the selected one.
  const criterion = criteria.criteria.find((entry) => entry.id === shownCriterionId) ?? criteria.criteria.find((entry) => entry.id === criteria.selectedId) ?? null;
  const criterionId = criterion?.id ?? FIRST_CRITERION_ID;
  const resultsCriterionId = criteria.criteria.length > 0 ? formCriterionId : undefined;
  // The project's settings are the shared ones with the first criterion's: each form starts from its own. The shared form takes
  // the criterion's mode, which decides the settings it shows, but does not save it.
  const formStarts = useMemo((): { shared: FormStart; criterion: FormStart } => {
    const { shared, criterion } = splitSettings(project.settings, criterionKeys);
    return {
      shared: { schema: props.schema, modes, settings: { ...shared, mode: criterion.mode }, gridPlan: project.grid_plan, savesMode: false },
      criterion: { schema: props.schema, modes, settings: criterion, gridPlan: null },
    };
  }, []);
  // A criterion's save replaces its settings; a new mode may rename it, so its entry is kept. The save goes to the criterion whose
  // settings the form holds (the form reads this send when a save goes out).
  const saveCriterionSettings: SettingsSend = async (formToken, projectName, values) => {
    const entry = await updateCriterion(formToken, projectName, formCriterionId, { values });
    criteria.applyReply(entry);
    return entry;
  };
  // A shared value refused by a criterion's own setting is said in Site and grid, with that criterion's name (sharedRefusalShown).
  const saveSharedSettings: SettingsSend = (formToken, projectName, values) => putSharedSettings(formToken, projectName, values).catch((error: unknown) => {
    const now = criteria.current().criteria;
    throw sharedRefusalShown(error, criterionKeys, (id) => now.find((entry) => entry.id === id) ?? null, now.length >= 2);
  });
  const sharedForm = useSettingsForm(token, project.name, formStarts.shared, saveSharedSettings);
  const criterionForm = useSettingsForm(token, project.name, formStarts.criterion, saveCriterionSettings);
  // The steps show the settings of both forms as one; each change goes to the form of its settings.
  const { form, dispatch, flushSave, cancelSave, changeAndSave, currentForm } = useBothForms(sharedForm, criterionForm, criterionKeys);
  const runActive = runs.activeRun?.project === project.name;
  // Files changed in the project folder, found by a stage status read: their lists and meshes are asked for again (the input files'
  // hook, set below), and so are the studies, which may now be out of date.
  const reloadInputRoles = useRef<(roles: string[]) => void>(() => {});
  const { criterionStages, refreshStageStatus, shownAs, shownStages, everyCriterionCarved, inputChanges, dismissChanges } = useStageStatus({
    token, project, criteria: criteria.criteria, form, runs, onServiceProblem,
    onInputFilesChanged: (roles) => {
      reloadInputRoles.current(roles);
      void studies.refresh();
    },
  });
  const [framingRequest, setFramingRequest] = useState(0);
  const frameAllInputs = () => setFramingRequest((count) => count + 1);
  const { files, origin, weather, meshes, addFiles, removeFile, storeTestSurfaceFiles, reloadRoles, followedInputChange, waitForInputChanges } = useInputFiles({
    token, project, modes, currentForm, sharedForm, refreshStageStatus, onInputsLoaded: frameAllInputs, onServiceProblem,
  });
  reloadInputRoles.current = reloadRoles;
  const inputChangesNotice = <InputChangesNotice changes={inputChanges} onDismiss={dismissChanges} />;
  useEffect(() => {
    props.onSettingsSaverReady?.({ flush: flushSave, cancel: cancelSave, waitForInputChanges });
    return () => props.onSettingsSaverReady?.(null);
  }, []);
  const [openStep, setOpenStep] = useState<StepName | null>(props.startSteps?.open ?? "inputs");
  const [viewStep, setViewStep] = useState<StepName>(props.startSteps?.view ?? "inputs");
  useEffect(() => props.onStepsChange?.({ open: openStep, view: viewStep }), [openStep, viewStep]);
  const panel = useRef<HTMLElement>(null);
  // In Simulate the panel is hidden, not unmounted (Design then finds its open step, folds and forms as left); its scroll is kept.
  const keepScroll = useKeptScroll(panel, props.mode === "design");
  const [addFilesRequest, setAddFilesRequest] = useState(0);
  const [settingToFocus, setSettingToFocus] = useState<{ name: string } | null>(null);

  const modeInfo = modes.find((candidate) => candidate.name === form.mode);
  const modeNeedsWeatherFile = modeInfo?.needs_epw ?? false;
  const hasWeatherFile = files.weather.length > 0;
  const maxVolumeMesh = meshes.max_volume, testSurfacesMesh = meshes.test_surfaces, contextMesh = meshes.context, terrainMesh = meshes.terrain;
  const maxVolume = maxVolumeMesh.geometry, testSurfaces = testSurfacesMesh.geometry;
  // The bounds of the maximum volume and the test surfaces loaded so far: the sun path and the sky dome are drawn around them (R2 2)
  const inputsBounds = useMemo(() => boundsOf([maxVolume, testSurfaces]), [maxVolume, testSurfaces]);
  // Each criterion's test surfaces are drawn in its colour; the layers menu has a toggle for each (kept here, so a change of criterion or
  // of step leaves it as it is; a new criterion starts with its toggle on).
  const [hiddenTestSurfaceCriteria, setHiddenTestSurfaceCriteria] = useState<ReadonlySet<string>>(new Set());
  const setTestSurfacesShown = (ids: readonly string[], shown: boolean) => setHiddenTestSurfaceCriteria((hidden) => {
    const next = new Set(hidden);
    for (const id of ids) {
      if (shown) next.delete(id);
      else next.add(id);
    }
    return next;
  });
  const criterionIdsKey = criteria.criteria.map((entry) => entry.id).join("\n");
  useEffect(() => setHiddenTestSurfaceCriteria((hidden) => {
    const kept = new Set([...hidden].filter((id) => criteria.criteria.some((entry) => entry.id === id)));
    return kept.size === hidden.size ? hidden : kept;
  }), [criterionIdsKey]);
  // What the groups hold, not which criterion is selected: a selection that moves no file to another criterion draws nothing again.
  const testSurfaceDrawingKey = JSON.stringify([criteria.criteria.map((entry) => [entry.id, entry.name, entry.colour, entry.bypassed]),
                                                [...testSurfaceOwners(criteria.criteria, criterion?.id ?? null, hiddenTestSurfaceCriteria)].sort(),
                                                [...hiddenTestSurfaceCriteria].sort()]);
  const testSurfaceGroups = useMemo(
    () => testSurfaceGroupsOf(criteria.criteria, criterion?.id ?? null, hiddenTestSurfaceCriteria, testSurfacesMesh.byFile, testSurfaces),
    [testSurfaces, testSurfacesMesh.byFile, testSurfaceDrawingKey]);
  const sceneSphere = useMemo(() => (inputsBounds === null ? null : sceneHemisphere(inputsBounds)), [inputsBounds]);
  const northDegrees = Number(shownValue(form, "north_deg") ?? 0);

  useEffect(() => {
    if (form.saveFailure !== null && serviceProblemOf(form.saveFailure) !== "other") onServiceProblem(form.saveFailure);
  }, [form.saveFailure]);

  // The sun path of the stored period (UX 8.2), as soon as the weather file and the period are there, before any run.
  const sunPath = useSunPathOfStoredPeriod({ token, project: project.name, form, hasWeatherFile, northDegrees, criterionId: resultsCriterionId, onServiceProblem });
  const { coldPeriod, answeredWeatherFileRevision } = useColdPeriod({ token, project: project.name, form, hasWeatherFile, weatherFileRevision: weather.fileRevision, onServiceProblem });
  const modeReadsPeriod = modeInfo?.needs_period ?? false;
  const periodShown = analysisPeriodOf(form, modeReadsPeriod);
  const weatherChangeSuggestionNow = weatherChangeSuggestion(weather.fileChange, {
    mode: form.mode, modeReadsPeriod, period: periodShown, coldPeriod, answeredWeatherFileRevision,
  });
  // Once the period is not the one the new file came with, the notice has nothing more to say about it, even if the period comes back.
  const weatherChangeOutlived = weather.fileChange !== null && periodChangedSince(weather.fileChange, periodShown);
  useEffect(() => {
    if (weatherChangeOutlived) weather.setFileChange(null);
  }, [weatherChangeOutlived]);

  const inputsDisabledReason = runActive ? messages.runInProgress : null;
  const inputRolesWithFiles = (Object.keys(files) as InputRole[]).filter((role) => files[role].length > 0);

  // The criterion's test surfaces (test_surface_calls.ts): the 3D view loads the stored files again after each change (a replaced
  // file keeps its name). The local origin follows the maximum volume only, so it does not change with them.
  const testSurfaceCalls = testSurfaceCallsOf({
    token, project: project.name, criteria, criterionId, refreshStageStatus, followed: followedInputChange, onServiceProblem,
    onStoredFiles: storeTestSurfaceFiles,
  });
  // The criterion's files as stored, in its order; a file just added shows once the stored files have been asked for again.
  const criterionTestSurfaces = criterion === null ? files.test_surfaces
    : (criterion.test_surface_files ?? []).flatMap((name) => files.test_surfaces.filter((file) => file.name === name));

  const openTheStep = (step: StepName | null) => {
    setOpenStep(step);
    if (step !== null) setViewStep(step);
  };

  useEffect(() => {
    if (settingToFocus === null) return;
    // The input the field's label targets: the number field of a slider, the balance temperature's number of the balance widget;
    // for the mode, its chosen tile (the one in the tab order).
    const field = panel.current?.querySelector<HTMLElement>(`[data-setting="${settingToFocus.name}"]`);
    const labelled = field?.dataset.inputId === undefined ? null : document.getElementById(field.dataset.inputId);
    (labelled ?? field?.querySelector<HTMLElement>(':is(input, select, [role="radio"][tabindex="0"])'))?.focus();
  }, [settingToFocus]);
  // The criterion panel's open sections, kept here so they outlast the Criteria step while it is closed (not stored). A setting of
  // the panel to focus opens the section that holds it first, in the same render.
  const openSectionRequest = useMemo(() => (settingToFocus === null || stepOfSetting(settingToFocus.name, criterionKeys) !== "criteria" ? null
    : { section: sectionOfSetting(settingToFocus.name) }), [settingToFocus, criterionKeys]);
  const panelSections = usePanelSections(openSectionRequest);

  // Either button of the notice ends it; the focus, on a button that goes away, moves to the period the notice was about.
  const endWeatherChangeNotice = () => {
    weather.setFileChange(null);
    setSettingToFocus({ name: fieldSettingOf(ANALYSIS_PERIOD_FIELDS[0]) });
  };

  // The criteria's part: the selection, the requests of the cards, why a run cannot start, and what the results and cards read.
  const workspaceCriteria = useWorkspaceCriteria({
    token, project: project.name, criteria, shownCriterionId, setShownCriterionId, criterion, resultsCriterionId, sharedForm, criterionForm, form, dispatch,
    currentForm, schema: props.schema, modes, criterionKeys, runs, warmUpState, maxVolumeFiles: files.max_volume.length,
    testSurfaceFiles: files.test_surfaces.length, hasWeatherFile, modeNeedsWeatherFile, criterionStages, shownAs, refreshStageStatus,
    followed: followedInputChange, reloadTestSurfaces: testSurfaceCalls.reloadStoredFiles, openStep: openTheStep,
    focusSetting: (settingName) => setSettingToFocus({ name: fieldSettingOf(settingName) }), onServiceProblem,
  });
  const { selection, active, ownStages } = workspaceCriteria;
  const resultSteps = useResultSteps({
    ...workspaceCriteria.ofResults,
    token, project: project.name, criterionId: resultsCriterionId, criterionKeys,
    form, currentForm, dispatch, flushSave, changeAndSave, isWeightedMode: modeInfo?.score_kind === "weighted_sum", stages: shownStages,
    refreshStageStatus, runs, runBlocker: workspaceCriteria.runBlocker, everyCriterionCarved, projectRunActive: runActive, origin, openStep: openTheStep,
    goToSetting: workspaceCriteria.goToSetting, onServiceProblem,
  });
  const cards = workspaceCriteria.cardsOf(resultSteps, inputsDisabledReason);
  const viewState = projectViewStateOf({
    files, form, sharedForm: sharedForm.form, criterionForm: criterionForm.form, criterionKeys, northDegrees, stages: shownStages,
    summary: resultSteps.results.summary, criteria: criteria.criteria, active,
  });

  const weatherHint = messages.weatherNeededFor(listedWithAnd(modes.filter((mode) => mode.needs_epw).map((mode) => plainModeName(mode.name))));
  const weatherBox = (
    <InputBox role="weather" files={files.weather} weatherLocation={weather.location} weatherHint={weatherHint} onAddFiles={addFiles}
              onRemoveFile={removeFile} disabledReason={inputsDisabledReason} weatherNeeded showsDisabledReason={false} />
  );
  const changeSettings = (values: Record<string, unknown>) => dispatch({ type: "values_changed", values });
  // A criterion that is off (the chain skips it) needs no test surfaces nor weather file: its panel asks for neither.
  const criterionOn = !(criterion?.bypassed ?? false);
  const stepContent: Record<StepName, ReactNode> = {
    inputs: (
      <InputsStep files={files} weatherLocation={weather.location} weatherHint={weatherHint} inputsBounds={inputsBounds} onAddFiles={addFiles}
                  onRemoveFile={removeFile} disabledReason={inputsDisabledReason} maxVolumeNote={carvedByNote(project.carving_chain ?? [])}
                  drawingProblems={{ max_volume: maxVolumeMesh.drawingProblems, context: contextMesh.drawingProblems, terrain: terrainMesh.drawingProblems }} />
    ),
    site_and_grid: (
      <SiteAndGridStep form={form} stepErrors={sharedForm.form.stepErrors} criterionKeys={criterionKeys} onChange={changeSettings}
                       disabledReason={inputsDisabledReason} inputRoles={inputRolesWithFiles} />
    ),
    criteria: (
      <CriteriaStep list={cards.list} load={selection.load} chainLine={cards.chainLine}
                    panelProblem={workspaceCriteria.panelProblem} panel={
        <CriterionPanel key={criterionId} {...panelSections} testSurfaces={criterionTestSurfaces} criterionOn={criterionOn} testSurfaceDrawingProblems={testSurfacesMesh.drawingProblems} onAddTestSurfaces={testSurfaceCalls.add}
                        onRemoveTestSurface={testSurfaceCalls.remove} otherTestSurfaces={filesOfOtherCriteria(criteria.criteria, criterionId)}
                        onUseTestSurface={testSurfaceCalls.use} form={form} stepErrors={criterionForm.form.stepErrors} criterionKeys={criterionKeys}
                        onChange={changeSettings} onChooseMode={(mode) => dispatch({ type: "mode_chosen", mode })} disabledReason={inputsDisabledReason}
                        weatherDropZone={criterionOn && modeNeedsWeatherFile && !hasWeatherFile ? weatherBox : null} inputRoles={inputRolesWithFiles}
                        coldPeriod={coldPeriod} hemisphere={hemisphereOfLatitude(weather.latitude)}
                        weatherChangeNotice={weatherChangeSuggestionNow === null ? null : { suggestion: weatherChangeSuggestionNow, onDismiss: endWeatherChangeNotice }}
                        carvingRule={resultSteps.carvingRule} scoreUnit={modeInfo?.score_unit} />
      } />
    ),
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
        {(name === "envelope_and_massing" || name === "export") && (
          <SettingsToFix step={name} form={form} onChange={changeSettings} disabledReason={inputsDisabledReason} />
        )}
      </>
    ),
  }));

  const runAnalysis = () => void runAnalysisAfterSaving(flushSave, () => {
    void resultSteps.startRun(ANALYSIS_STAGES, "settings_run_analysis").then((outcome) => { if (outcome === "finished") openTheStep("criteria"); });
  });
  const pinnedActions: Partial<Record<StepName, ReactNode>> = {
    site_and_grid: (
      <RunAnalysisButton blocker={workspaceCriteria.siteAndGridRunBlocker} onRunAnalysis={runAnalysis} feedback={resultSteps.feedback("settings_run_analysis")} />
    ),
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
  // Shown in Design only: its "Add files" leads to the Inputs step, which Simulate hides.
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

  // Simulate draws the selected study's values on the geometry it shows, with Design's layers of that geometry and its own choice of
  // them: the maximum volume solid, the envelope see-through; the criteria's test surfaces off, the surroundings on. A study out of
  // date is dimmed with the stamp; Design's out of date parts are not (the geometry switch marks them).
  const simulating = props.mode === "simulate";
  const designResults = resultSteps.viewer.results;
  const studyView = useStudyView({
    token, project: project.name, studies, active: simulating, runs, envelopeBuilt: designResults?.envelope != null, massingBuilt: designResults?.massing != null,
    envelopeStage: shownStages.exporting, massingStage: shownStages.massing, editDisabled: runActive, onServiceProblem,
  });
  const simulateView = (theme: ViewportTheme) => (
    <SimulateView project={project.name} studies={studies} criteria={criteria.criteria} storedTestSurfaces={files.test_surfaces} runs={runs}
                  onStoredFilesChange={() => { void testSurfaceCalls.reloadStoredFiles(); refreshStageStatus(); }} onServiceProblem={onServiceProblem} studyView={studyView}
                  theme={theme} notice={inputChangesNotice} />
  );
  const simulateViewer = { overlayContent: simulateView, study: studyView.view, studyOutOfDate: studyView.studyOutOfDate,
                           envelopeSeeThrough: studyView.geometry === "envelope", dimmedLayers: [] };

  return (
    <div className="workspace">
      <aside ref={panel} className="workspace-panel" hidden={props.mode !== "design"} onScrollCapture={keepScroll}>
        {inputChangesNotice}
        <StepAccordion steps={steps} openStep={openStep} onOpenStep={openTheStep}
                       pinnedAction={saveFailureNotice === null && openStepAction === null ? null : <>{saveFailureNotice}{openStepAction}</>} />
      </aside>
      <section className="workspace-view">
        <ViewerPane maxVolume={maxVolume} testSurfaces={testSurfaceGroups} onTestSurfacesShownChange={setTestSurfacesShown}
                    criteria={active.map(({ id, name, colour }) => ({ id, name, colour }))} context={contextMesh.geometry} terrain={terrainMesh.geometry} sunPath={sunPath}
                    hemisphere={sceneSphere}
                    maxVolumeAppearance={simulating || STEPS_WITH_SOLID_MAX_VOLUME.includes(viewStep) ? "solid" : "ghost"}
                    shownByDefault={simulating ? LAYERS_SHOWN_IN_SIMULATE[studyView.geometry] : LAYERS_SHOWN_IN_STEP[viewStep]}
                    northDegrees={northDegrees} framingRequest={framingRequest}
                    centreContent={props.mode === "design" && emptyViewContent} localOrigin={origin} mode={form.mode}
                    analysisCurrent={(ownStages ?? shownStages).preprocessing === "current"} {...resultSteps.viewer}
                    {...(simulating ? simulateViewer : {})} />
      </section>
    </div>
  );
}

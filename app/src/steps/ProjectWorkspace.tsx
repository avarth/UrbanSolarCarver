// An open project (UX 4, spec 7.1): the step accordion in the left panel (Inputs, Site and grid, Criteria, Envelope and massing,
// Export) and the 3D view beside it. It holds what the steps share: the input files, the criteria (useCriteria) and their cards'
// requests, the two settings forms (the shared settings, shown in Site and grid, and the selected criterion's, shown in its panel;
// the steps read them as one), the stage status the step summaries read, and the input meshes (input_meshes.ts) and the sun path
// (sun_path_request.ts) the 3D view draws. The parts that start runs and show their results (the criterion's carving rule, Envelope and massing, Export) are
// put together in result_steps.tsx from these and the app's run loop.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  addInput, getStageStatus, putSharedSettings, removeInput, serviceProblemOf, updateCriterion,
  type CriterionEntry, type HealthReply, type InputFileInfo, type InputFilesReply, type ModeInfo, type ProjectDetail,
} from "../api_client/client";
import {
  activeCriteria, cardLineOf, chainSummaryLine, criteriaProtectingNothing, criterionStatus, filesOfOtherCriteria, stagesByCriterionOf, stagesDuringRun, type StagesByCriterion,
} from "../criteria/criteria_state";
import type { CriterionListProps } from "../criteria/CriterionList";
import { CriteriaStep } from "../criteria/CriteriaStep";
import { CriterionPanel, TurnOnCriterion } from "../criteria/CriterionPanel";
import { testSurfaceCallsOf } from "../criteria/test_surface_calls";
import { useCriteria } from "../criteria/use_criteria";
import { useCriterionSelection } from "../criteria/use_criterion_selection";
import { useRefusalSelection } from "../criteria/use_refusal_selection";
import { listedWithAnd, messages } from "../messages";
import { hemisphereOfLatitude, seasonsOfLatitude, type Hemisphere } from "../settings_form/analysis_period";
import {
  analysisDiffersFromStored, shownValue, useSettingsForm, type FormStart, type SaveOutcome, type SettingsSend,
} from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, fieldSettingOf } from "../settings_form/presentation";
import { sharedRefusalShown, splitSettings, useBothForms } from "../settings_form/two_forms";
import { localOrigin, type Bounds3, type Point3 } from "../viewer/local_origin";
import type { LayerName } from "../viewer/scene";
import { sceneHemisphere } from "../viewer/sky_dome";
import { ViewerPane } from "../viewer_overlays/ViewerPane";
import { useColdPeriod } from "./cold_period_request";
import { boundsOf, joinedGeometryOf, useInputGeometry, type MeshRole } from "./input_meshes";
import { carvedByNote, InputBox, inputProblemText, InputsStep, type AddInputFiles, type InputRole, type RemoveInputFile } from "./InputsStep";
import { ANALYSIS_STAGES, useResultSteps } from "./result_steps";
import { criterionProgressOf, runningCriterion, type RunFailure, type RunLoop } from "./run_state";
import {
  RunAnalysisButton, runAnalysisAfterSaving, runAnalysisBlocker, SaveFailureNotice, saveFailureTextOf, SettingsToFix, settingsToFixByStep, stepOfSetting,
} from "./SettingsStep";
import { SiteAndGridStep } from "./SiteAndGridStep";
import { StepAccordion, type AccordionStep } from "./StepAccordion";
import {
  plainModeName, STEP_NAMES, stepMark, stepNotUsableYet, stepSummary, type PipelineStage, type ProjectViewState, type StageState, type StepName,
} from "./step_summaries";
import { analysisPeriodOf, useSunPathOfStoredPeriod } from "./sun_path_request";
import { periodChangedSince, weatherChangeSuggestion, type WeatherFileChange } from "./weather_change_notice";

const NO_SHIFT: Point3 = [0, 0, 0];

/** A criterion's stages that have output (none for a criterion the stage status does not list: bypassed, or new). */
function stagesWithOutputOf(stages: StagesByCriterion[string] | undefined): string[] {
  return stages === undefined ? [] : (["preprocessing", "thresholding"] as const).filter((stage) => stages[stage] !== "missing");
}
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

interface ProjectWorkspaceProps {
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
    max_volume: project.inputs.max_volume ?? [], test_surfaces: project.inputs.test_surfaces ?? [], context: project.inputs.context ?? [],
    terrain: project.inputs.terrain ?? [], weather: project.inputs.weather ?? [],
  });
  const [joinedBounds, setJoinedBounds] = useState<Bounds3 | null>(project.joined_bounds as Bounds3 | null);
  const [weatherLocation, setWeatherLocation] = useState(project.weather_location);
  const [weatherLatitude, setWeatherLatitude] = useState(project.weather_latitude);
  const [inputRevisions, setInputRevisions] = useState<Record<MeshRole, number>>({ max_volume: 0, test_surfaces: 0, context: 0, terrain: 0 });
  // Goes up whenever the weather file is added, replaced or removed: the service keeps one name for it, so its file list may not change.
  const [weatherFileRevision, setWeatherFileRevision] = useState(0);
  const weatherFileRevisionNow = useRef(0);
  // The weather file added or replaced last in this session, for the notice over the criterion's settings; null before one, and
  // once it is dismissed.
  const [weatherFileChange, setWeatherFileChange] = useState<WeatherFileChange | null>(null);
  // The hemisphere of the last weather file the project had with seasons, kept across a removal and across a file within the tropics
  // or without a latitude: what the period was likely chosen for.
  const hemisphereOfLastWeatherFile = useRef<Hemisphere>(hemisphereOfLatitude(project.weather_latitude));
  const [stages, setStages] = useState(project.stage_status.stages as Record<PipelineStage, StageState>);
  const [criterionStages, setCriterionStages] = useState<StagesByCriterion>(() => stagesByCriterionOf(project.criterion_status));
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
  const contextMesh = useInputGeometry(token, project.name, "context", files.context, origin, inputRevisions.context, frameAllInputs, onServiceProblem);
  const terrainMesh = useInputGeometry(token, project.name, "terrain", files.terrain, origin, inputRevisions.terrain, frameAllInputs, onServiceProblem);
  const maxVolume = maxVolumeMesh.geometry, testSurfaces = testSurfacesMesh.geometry;
  // The bounds of the maximum volume and the test surfaces loaded so far: the sun path and the sky dome are drawn around them (R2 2)
  const inputsBounds = useMemo(() => boundsOf([maxVolume, testSurfaces]), [maxVolume, testSurfaces]);
  // With several criteria the shown criterion's test surfaces are drawn at full strength and every other stored file dimmed (a file both
  // use is highlighted; a criterion with no files highlights nothing and dims them all); with one criterion, all of them at full strength.
  const shownCriterionFiles = criteria.criteria.length < 2 || criterion === null ? undefined : criterion.test_surface_files ?? [];
  const shownCriterionFilesKey = shownCriterionFiles?.join("\n");
  const testSurfaceDrawing = useMemo(() => {
    if (shownCriterionFiles === undefined) return { highlighted: testSurfaces, dimmed: null };
    const others = Object.keys(testSurfacesMesh.byFile).filter((name) => !shownCriterionFiles.includes(name));
    if (others.length === 0) return { highlighted: testSurfaces, dimmed: null };
    return { highlighted: joinedGeometryOf(testSurfacesMesh.byFile, shownCriterionFiles), dimmed: joinedGeometryOf(testSurfacesMesh.byFile, others) };
  }, [testSurfaces, testSurfacesMesh.byFile, shownCriterionFilesKey]);
  const sceneSphere = useMemo(() => (inputsBounds === null ? null : sceneHemisphere(inputsBounds)), [inputsBounds]);
  const northDegrees = Number(shownValue(form, "north_deg") ?? 0);

  // A stage status read across a run of this project says "missing" for results still on screen: such a reply is not used
  // (RunLoop.replyStillHolds), and the run's end asks again. *completedStages*: the stages a run just completed are current at
  // once, so their layers are not dimmed until the reply.
  const refreshStageStatus = (completedStages: readonly string[] = []) => {
    if (completedStages.length > 0) {
      const completed = Object.fromEntries(completedStages.map((stage) => [stage, "current"]));
      setStages((current) => ({ ...current, ...completed }));
      const completedOfCriteria = Object.fromEntries(completedStages.filter((stage) => stage === "preprocessing" || stage === "thresholding")
        .map((stage) => [stage, "current"]));
      setCriterionStages((current) => Object.fromEntries(Object.entries(current).map(([id, ofCriterion]) => [id, { ...ofCriterion, ...completedOfCriteria }])));
    }
    const replyStillHolds = runs.replyStillHolds(project.name);
    const revisionAsked = storedAnalysisRevision.current;
    getStageStatus(token, project.name).then((reply) => {
      if (!replyStillHolds()) return;
      setStages(reply.stages as Record<PipelineStage, StageState>);
      setCriterionStages(stagesByCriterionOf(reply.criteria));
      setRevisionOfStageStatus((revision) => Math.max(revision, revisionAsked));
    }).catch(onServiceProblem);
  };

  // The stage status describes the stored settings. While the form's mode or analysis settings are not those (a save waits or
  // was refused), or a save changed them and the stage status since is still to come, the analysis is out of date for the
  // settings shown: every stage counts as out of date, so the carving rule is locked and its results are dimmed (UX 5.5), and no
  // carving change can start the analysis of a mode the form does not show.
  const analysisOfOtherSettings = analysisDiffersFromStored(form) || revisionOfStageStatus < form.storedAnalysisRevision;
  const shownAs = <Stage extends string>(stagesOf: Record<Stage, StageState>): Record<Stage, StageState> => (analysisOfOtherSettings
    ? Object.fromEntries(Object.entries(stagesOf).map(([stage, state]) => [stage, state === "current" ? "out_of_date" : state])) as Record<Stage, StageState>
    : stagesOf);
  const shownStages = shownAs(stages);
  // Criteria pins Build envelope and massing once every criterion that is on has a current carving (disabled, with the reason,
  // while the settings shown differ from those it was made with).
  const everyCriterionCarved = activeCriteria(criteria.criteria).length > 0
    && activeCriteria(criteria.criteria).every((criterion) => criterionStages[criterion.id]?.thresholding === "current");

  // A save changes what the stages were run with; its reply is in once no save waits.
  useEffect(() => {
    if (form.changeCount > 0 && !form.pendingSave) refreshStageStatus();
  }, [form.pendingSave]);

  useEffect(() => {
    if (form.saveFailure !== null && serviceProblemOf(form.saveFailure) !== "other") onServiceProblem(form.saveFailure);
  }, [form.saveFailure]);

  // The sun path of the stored period (UX 8.2), as soon as the weather file and the period are there, before any run.
  const sunPath = useSunPathOfStoredPeriod({ token, project: project.name, form, hasWeatherFile, northDegrees, criterionId: resultsCriterionId, onServiceProblem });
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
  const inputRolesWithFiles = (Object.keys(files) as InputRole[]).filter((role) => files[role].length > 0);

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
  // A weather file added or replaced: the notice over the criterion's settings is about it and the period the form shows now (a
  // later one replaces it).
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
    // The grid follows the maximum volume; a save of the unchanged shared settings brings its new plan.
    if (role === "max_volume") sharedForm.dispatch({ type: "values_changed", values: {} });
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
  // The app waits for these before a rename, reset or delete of the project (waitForInputChanges).
  const addFiles: AddInputFiles = (role, chosenFiles) => followedInputChange(addFilesOneByOne(role, chosenFiles));
  const removeFile: RemoveInputFile = (role, fileName) => followedInputChange(removeFileAndApply(role, fileName));
  // The criterion's test surfaces (test_surface_calls.ts): the 3D view loads the stored files again after each change (a replaced
  // file keeps its name). The local origin follows the maximum volume only, so it does not change with them.
  const testSurfaceCalls = testSurfaceCallsOf({
    token, project: project.name, criteria, criterionId, refreshStageStatus, followed: followedInputChange, onServiceProblem,
    onStoredFiles: (stored) => {
      setFiles((current) => ({ ...current, test_surfaces: stored }));
      setInputRevisions((current) => ({ ...current, test_surfaces: current.test_surfaces + 1 }));
    },
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

  // The selection of a card and the requests that change the criteria (use_criterion_selection.ts).
  const selection = useCriterionSelection({
    token, project: project.name, criteria, shownCriterionId, setShownCriterionId, criterionForm, sharedForm, refreshStageStatus, onServiceProblem,
    afterDelete: testSurfaceCalls.reloadStoredFiles,
    criterionStartOf: (settings) => ({ schema: props.schema, modes, settings: splitSettings(settings, criterionKeys).criterion, gridPlan: null }),
  });
  // A start refused for another criterion's settings marks them once that criterion's panel shows them, with the forms then.
  const latestForms = useRef({ dispatch, currentForm });
  latestForms.current = { dispatch, currentForm };
  const markRunErrors = (fieldErrors: RunFailure["field_errors"]) => {
    latestForms.current.dispatch({ type: "save_rejected", reply: { field_errors: fieldErrors, grid_plan: latestForms.current.currentForm().gridPlan } });
  };
  const showRefusalOfCriterion = (id: string, fieldErrors: RunFailure["field_errors"]) => selection.showCriterion(id, () => markRunErrors(fieldErrors));
  // A failed run's link to the setting it names: the step that holds the setting opens and the focus goes to its field. A setting
  // of the criterion the run named is focused in that criterion's panel, selected first, with the run's errors marked there again.
  const goToSetting = (settingName: string, criterionId: string | null = null) => {
    const step = stepOfSetting(settingName, criterionKeys);
    if (step === null) return;
    openTheStep(step);
    const focusField = () => setSettingToFocus({ name: fieldSettingOf(settingName) });
    if (step !== "criteria" || criterionId === null || criterionId === shownCriterionId || !criteria.criteria.some((entry) => entry.id === criterionId)) {
      focusField();
      return;
    }
    const failure = runs.current?.project === project.name ? runs.current.state.failure : null;
    selection.showCriterion(criterionId, () => {
      if (failure?.criterion === criterionId) markRunErrors(failure.field_errors);
      focusField();
    });
  };

  // Run analysis is in Criteria and pinned in Site and grid: each names a setting to fix in another step with that step. Every
  // criterion that is on needs test surfaces (a bypassed one needs none).
  const active = activeCriteria(criteria.criteria);
  const protectingNothing = criteriaProtectingNothing(criteria.criteria);
  // The only criterion, bypassed (project.json edited by hand): it has no card, so its panel offers to turn it on.
  const onlyCriterionBypassed = criteria.criteria.length === 1 && criteria.criteria[0].bypassed;
  const severalCriteria = criteria.criteria.length >= 2;
  // The criteria that are on whose mode needs a weather file (the shown one by the mode its form shows): the run needs it for each.
  const needingWeatherFile = active.filter((entry) => modes.find((mode) => mode.name === (entry.id === criterion?.id ? form.mode : entry.settings?.mode))?.needs_epw);
  const runConditions = {
    runActive: runs.activeRun !== null, maxVolumeFiles: files.max_volume.length,
    testSurfaceFiles: criterion === null ? files.test_surfaces.length : criterion.bypassed ? 1 : (criterion.test_surface_files ?? []).length,
    otherCriterionWithoutTestSurfaces: protectingNothing.find((entry) => entry.id !== criterion?.id)?.name ?? null,
    noCriterionOn: criteria.criteria.length > 0 && active.length === 0,
    modeNeedsWeatherFile: modeNeedsWeatherFile && !(criterion?.bypassed ?? false),
    otherCriterionNeedingWeatherFile: needingWeatherFile.find((entry) => entry.id !== criterion?.id)?.name ?? null,
    hasWeatherFile, form, warmUpState, criterionKeys,
    stepErrorsByStep: { site_and_grid: sharedForm.form.stepErrors, criteria: criterionForm.form.stepErrors },
  };
  const runBlocker = runAnalysisBlocker({ ...runConditions, shownIn: "criteria" });
  // Site and grid shows no criterion: with several, the one without test surfaces or that needs a weather file is named, the shown one too.
  const siteAndGridRunBlocker = runAnalysisBlocker(severalCriteria
    ? { ...runConditions, shownIn: "site_and_grid", testSurfaceFiles: 1, otherCriterionWithoutTestSurfaces: protectingNothing[0]?.name ?? null,
        modeNeedsWeatherFile: false, otherCriterionNeedingWeatherFile: needingWeatherFile[0]?.name ?? null }
    : { ...runConditions, shownIn: "site_and_grid" });
  // The shown criterion's own analysis and carving: its carving rule locks while its analysis is out of date; another criterion's
  // analysis out of date keeps a carving change from running (result_steps.tsx).
  const ownStages = resultsCriterionId === undefined ? undefined
    : shownAs(criterionStages[resultsCriterionId] ?? { preprocessing: "missing", thresholding: "missing" });
  const waitedFor = active.find((entry) => entry.id !== resultsCriterionId && criterionStages[entry.id]?.preprocessing !== "current");
  const analysisWaitsFor = waitedFor === undefined ? null : { name: waitedFor.name, protectsNothing: protectingNothing.includes(waitedFor) };
  // With several criteria the builds name the first criterion that is on whose analysis is not current (the shown one as shown).
  const notAnalysed = active.find((entry) => (entry.id === resultsCriterionId ? ownStages : criterionStages[entry.id])?.preprocessing !== "current");
  const buildWaitReason = !severalCriteria || notAnalysed === undefined ? null
    : protectingNothing.includes(notAnalysed) ? messages.addTestSurfacesFirst(notAnalysed.name) : messages.carvingWaitsForAnalysisOf(notAnalysed.name);
  // A threshold value of another criterion, whose turn in the threshold queue came after this one was selected: its settings with
  // the value, while it is there with the mode the value was given in.
  const saveToCriterion = async (id: string, mode: string, values: Record<string, unknown>): Promise<boolean> => {
    const entry = criteria.current().criteria.find((candidate) => candidate.id === id);
    if (entry === undefined || entry.settings?.mode !== mode) return false;
    try {
      criteria.applyReply(await updateCriterion(token, project.name, id, { values: { ...entry.settings, ...values } }));
      refreshStageStatus();
      return true;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return false;
    }
  };
  // Which criterion removed each voxel: asked for with two or more criteria on, once every one has thresholding output (the service
  // answers 404 before), and again whenever the criteria that are on change.
  const carvedByCriterionWanted = active.length >= 2;
  const carvedByCriterionIds = carvedByCriterionWanted && active.every((entry) => stagesWithOutputOf(criterionStages[entry.id]).includes("thresholding"))
    ? active.map((entry) => entry.id) : null;
  const resultSteps = useResultSteps({
    token, project: project.name, criterionId: resultsCriterionId, criterionStagesWithResults: resultsCriterionId === undefined ? undefined : stagesWithOutputOf(criterionStages[resultsCriterionId]),
    carvedByCriterionIds, carvedByCriterionWanted,
    carvedByCriterionOutOfDate: active.some((entry) => shownAs(criterionStages[entry.id] ?? { preprocessing: "missing", thresholding: "missing" }).thresholding !== "current"),
    criterionStages: ownStages, chainOrder: criteria.criteria.map((entry) => entry.id), analysisWaitsFor, buildWaitReason, showRefusalOfCriterion, saveToCriterion,
    criterionBypassed: criterion?.bypassed ?? false,
    criterionNames: criteria.criteria.length < 2 ? undefined : Object.fromEntries(criteria.criteria.map((entry) => [entry.id, entry.name])),
    form, currentForm, dispatch, flushSave, changeAndSave, isWeightedMode: modeInfo?.score_kind === "weighted_sum", stages: shownStages,
    refreshStageStatus, runs, runBlocker, everyCriterionCarved, projectRunActive: runActive, origin, openStep: openTheStep, goToSetting, onServiceProblem,
  });

  // The cards (CriteriaStep): their lines from the criteria's stages and the run summary. While a run of the project goes on, the
  // criterion it works on says Running and the stages it has done or still has to do count as current or out of date.
  const record = runs.current?.project === project.name ? runs.current : null;
  const runUnderWay = record !== null && record.state.final === null && record.refusal === null;
  const runningId = runUnderWay ? runningCriterion(record.state) : null;
  const cardStages = runUnderWay ? stagesDuringRun(criterionStages, criterionProgressOf(record.state)) : criterionStages;
  const summaryCriteria = resultSteps.results.summary?.criteria ?? [];
  const carvingSummaryOf = (entry: CriterionEntry) => summaryCriteria.find((summary) => summary.id === entry.id);
  // What the chain kept, under the cards, only while every card that is on shows its current result: otherwise its numbers are those
  // of the run before.
  const chainCurrent = active.every((entry) => !resultSteps.criteriaAwaitingNumbers.has(entry.id)
    && criterionStatus(entry, criteria.criteria, cardStages, runningId).kind === "current");
  const chainLine = chainCurrent ? chainSummaryLine(resultSteps.results.summary?.chain, active.length) : null;
  const criterionList: CriterionListProps = {
    criteria: criteria.criteria,
    selectedId: criteria.selectedId,
    lineOf: (entry) => cardLineOf(resultSteps.criteriaAwaitingNumbers.has(entry.id) ? { kind: "running" }
      : criterionStatus(entry, criteria.criteria, cardStages, runningId), carvingSummaryOf(entry)),
    runningId,
    disabledReason: inputsDisabledReason,
    ...selection.requests,
  };

  // A start refused because criteria that are on protect nothing selects the first of them; its panel asks for test surfaces.
  const panelProblem = useRefusalSelection({
    record, criteria: criteria.criteria, selectedId: criteria.selectedId, shownCriterion: criterion, showCriterion: (id) => selection.showCriterion(id),
  });

  const viewState: ProjectViewState = {
    maxVolumeFiles: files.max_volume.length,
    hasWeatherFile,
    contextFiles: files.context.length,
    terrainFiles: files.terrain.length,
    mode: form.mode,
    northDegrees,
    voxelSize: Number(shownValue(form, "voxel_size")),
    settingsToFix: settingsToFixByStep(sharedForm.form, criterionForm.form, criterionKeys),
    stages: shownStages,
    keptPercent: resultSteps.results.summary?.carving?.retention_pct ?? null,
    criteriaInChain: criteria.criteria.length < 2 ? null
      : activeCriteria(criteria.criteria).map((entry) => ({ name: entry.name, keptPercent: carvingSummaryOf(entry)?.carving?.retention_pct ?? null })),
    totalFloorArea: resultSteps.results.summary?.massing?.total_floor_area_m2 ?? null,
    storeys: resultSteps.results.summary?.massing?.storeys_built ?? null,
  };

  const weatherHint = messages.weatherNeededFor(listedWithAnd(modes.filter((mode) => mode.needs_epw).map((mode) => plainModeName(mode.name))));
  const weatherBox = (
    <InputBox role="weather" files={files.weather} weatherLocation={weatherLocation} weatherHint={weatherHint} onAddFiles={addFiles}
              onRemoveFile={removeFile} disabledReason={inputsDisabledReason} weatherNeeded showsDisabledReason={false} />
  );
  const changeSettings = (values: Record<string, unknown>) => dispatch({ type: "values_changed", values });
  const stepContent: Record<StepName, ReactNode> = {
    inputs: (
      <InputsStep files={files} weatherLocation={weatherLocation} weatherHint={weatherHint} inputsBounds={inputsBounds} onAddFiles={addFiles}
                  onRemoveFile={removeFile} disabledReason={inputsDisabledReason} maxVolumeNote={carvedByNote(project.carving_chain ?? [])}
                  drawingProblems={{ max_volume: maxVolumeMesh.drawingProblems, context: contextMesh.drawingProblems, terrain: terrainMesh.drawingProblems }} />
    ),
    site_and_grid: (
      <SiteAndGridStep form={form} stepErrors={sharedForm.form.stepErrors} criterionKeys={criterionKeys} onChange={changeSettings}
                       disabledReason={inputsDisabledReason} inputRoles={inputRolesWithFiles} />
    ),
    criteria: (
      <CriteriaStep list={criterionList} load={selection.load} chainLine={chainLine}
                    panelProblem={panelProblem} panel={
        <CriterionPanel testSurfaces={criterionTestSurfaces} testSurfaceDrawingProblems={testSurfacesMesh.drawingProblems} onAddTestSurfaces={testSurfaceCalls.add}
                        onRemoveTestSurface={testSurfaceCalls.remove} otherTestSurfaces={filesOfOtherCriteria(criteria.criteria, criterionId)}
                        onUseTestSurface={testSurfaceCalls.use} form={form} stepErrors={criterionForm.form.stepErrors} criterionKeys={criterionKeys}
                        onChange={changeSettings} onChooseMode={(mode) => dispatch({ type: "mode_chosen", mode })} disabledReason={inputsDisabledReason}
                        weatherDropZone={modeNeedsWeatherFile && !hasWeatherFile ? weatherBox : null} inputRoles={inputRolesWithFiles}
                        coldPeriod={coldPeriod} hemisphere={hemisphereOfLatitude(weatherLatitude)}
                        weatherChangeNotice={weatherChangeSuggestionNow === null ? null : { suggestion: weatherChangeSuggestionNow, onDismiss: endWeatherChangeNotice }}
                        carvingRule={onlyCriterionBypassed
                          ? <TurnOnCriterion onTurnOn={() => selection.requests.onSetBypassed(criterionId, false)} disabledReason={inputsDisabledReason} />
                          : resultSteps.carvingRule}
                        runAnalysis={resultSteps.criterionRunAnalysis} />
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
    site_and_grid: <RunAnalysisButton blocker={siteAndGridRunBlocker} onRunAnalysis={runAnalysis} feedback={resultSteps.feedback("settings_run_analysis")} />,
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
        <ViewerPane maxVolume={maxVolume} testSurfaces={testSurfaceDrawing.highlighted} dimmedTestSurfaces={testSurfaceDrawing.dimmed}
                    criteria={active.map(({ id, name, colour }) => ({ id, name, colour }))} context={contextMesh.geometry} terrain={terrainMesh.geometry} sunPath={sunPath}
                    hemisphere={sceneSphere}
                    maxVolumeAppearance={STEPS_WITH_SOLID_MAX_VOLUME.includes(viewStep) ? "solid" : "ghost"}
                    shownByDefault={LAYERS_SHOWN_IN_STEP[viewStep]} northDegrees={northDegrees} framingRequest={framingRequest}
                    centreContent={emptyViewContent} localOrigin={origin} mode={form.mode}
                    analysisCurrent={(ownStages ?? shownStages).preprocessing === "current"} {...resultSteps.viewer} />
      </section>
    </div>
  );
}

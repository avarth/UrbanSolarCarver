// An open project (UX 4, spec 7.1): the step accordion in the left panel (Inputs, Criteria, Envelope and massing, Export) and the 3D
// view beside it. It holds what the steps share: the input files and their meshes (use_input_files.ts), the criteria (useCriteria)
// and their cards' requests, the two settings forms (the shared settings, shown in the project settings window that the Settings
// button in the top bar opens, ProjectSettingsDialog, and the selected criterion's, shown in its panel; the steps read them as one),
// the stage status the step summaries read
// (use_stage_status.ts, workspace_view_state.ts), and the sun path (sun_path_request.ts) the 3D view draws. The criteria's selection,
// run conditions and cards are in use_workspace_criteria.ts. The parts that start runs and show their results (the criterion's
// carving rule, Envelope and massing, Export) are put together in result_steps.tsx from these and the app's run loop. In Simulate the
// steps are hidden and the studies (use_studies.ts) are shown over the view (SimulateView), the selected one's values drawn on the
// geometry Simulate shows (use_study_view.ts). In Inspect the steps are hidden too and the Geometries panel (InspectView) is shown over the
// view, which draws the orientation of the test surfaces (use_inspection.ts); turns not saved are reported to the app, which asks
// before Inspect is left. The project's typical building (use_typical_building.ts) is read once the shown criterion counts its hours
// by it (Energy-weighted, in Solar heating).
import { useEffect, useEffectEvent, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  failureTextOf, getSurfacePicks, markModeChosen, pickSurfaceSet, readOutlines, renameSurfaceSet, reportServiceProblem, setCarvingUpdates, terrainHeights, type HealthReply, type OutlinesReply, type ModeInfo, type ProjectDetail,
} from "../api_client/client";
import { ProjectSessionContext } from "../api_client/project_session";
import { activeCriteria } from "../criteria/criteria_state";
import { SurfaceSetsBox } from "../common/SurfaceSetsBox";
import { useGroundSurfaces, type GroundTool } from "./use_ground_surfaces";
import { LastRemovalContext } from "../common/last_removal";
import { CriteriaStep, type CriteriaShows } from "../criteria/CriteriaStep";
import { firstCriteriaShows } from "../criteria/criteria_shows";
import { CriterionPanel } from "../criteria/CriterionPanel";
import { FirstMode } from "../criteria/FirstMode";
import { usePanelSections } from "../criteria/PanelSection";
import { sectionOfSetting } from "../criteria/section_summaries";
import { useTestSurfaceCalls } from "../criteria/test_surface_calls";
import { useCriteria } from "../criteria/use_criteria";
import { useTypicalBuilding } from "../criteria/use_typical_building";
import { useWorkspaceCriteria } from "../criteria/use_workspace_criteria";
import { useChangedDuringRender } from "../hooks/use_changed_during_render";
import { AnalysisOutOfDateNotice, InspectView } from "../inspect/InspectView";
import type { InspectTurns } from "../inspect/UnsavedTurnsDialog";
import { useInspectView } from "../inspect/use_inspection";
import { listedWithAnd, messages } from "../messages";
import { hemisphereOfLatitude } from "../settings_form/analysis_period";
import { shownValue, type SaveOutcome } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, fieldSettingOf } from "../settings_form/presentation";
import type { LayerName, ViewerScene, ViewportTheme } from "../viewer/scene";
import { sceneHemisphere } from "../viewer/sky_dome";
import { SimulateView } from "../simulate/SimulateView";
import type { StudyStand } from "../viewer/study_values";
import { useStudies } from "../simulate/use_studies";
import { useStudyView } from "../simulate/use_study_view";
import { useSunStudy } from "../simulate/use_sun_study";
import { SunPanel } from "../simulate/SunPanel";
import { NO_VIEWER_RESULTS, ViewerPane } from "../viewer_overlays/ViewerPane";
import { useColdPeriod } from "../settings_form/cold_period_request";
import { boundsOf, joinedOrNull } from "../steps/input_meshes";
import { carvedByNote, InputsStep } from "../steps/InputsStep";
import { InputBox, type InputRole } from "../common/InputBox";
import { useResultSteps } from "./result_steps";
import type { RunLoop } from "../common/run_state";
import { placeOfSetting, SaveFailureNotice, saveFailureTextOf, SettingsStep, SettingsToFix } from "../settings_form/SettingsStep";
import { ProjectSettingsButton, ProjectSettingsDialog } from "./ProjectSettingsDialog";
import { StepAccordion, type AccordionStep } from "./StepAccordion";
import { projectSettingsSummary, settingsToFixIn, stepMark, stepNotUsableYet, stepSummary } from "./step_summaries";
import { plainModeName } from "../modes";
import { STEP_NAMES, type SettingPlace, type StepName } from "../stages";
import { analysisPeriodOf, useSunPathOfStoredPeriod } from "../steps/sun_path_request";
import { useInputFiles } from "./use_input_files";
import { InputChoice, SiteBox, SwitchInputLink } from "../sites/SiteInput";
import { ProjectSetupDialog } from "./ProjectSetupDialog";
import { ImportSitesDialog } from "../sites/ImportSitesDialog";
import { ContextPicker, type PickTarget, type SurfacePick } from "../viewer_overlays/ContextPicker";
import { browserAutoUpdateChoice, forgetBrowserAutoUpdateChoice } from "../criteria/CarvingStep";
import { Subheading } from "../settings_form/Subheading";
import { HeightsSettings } from "../sites/HeightsSettings";
import { SiteEditor, SitePicker, type SiteTool } from "../sites/SiteEditor";
import { ContextBlocksList } from "../sites/ContextBlocksList";
import { drawingLevel } from "../sites/site_drawing";
import {
  allPoints, elevationRange, holesOf, nextSiteName, ringsOf, siteArea, siteRise, withRings, type Site, type SitePoint,
} from "../sites/site_geometry";
import { InputChangesNotice } from "./InputChangesNotice";
import { useProjectForms } from "./use_project_forms";
import { useTestSurfaceDrawing } from "./use_test_surface_drawing";
import { useWorkspaceInspection } from "./use_workspace_inspection";
import { useKeptScroll } from "./use_kept_scroll";
import { useStageStatus } from "./use_stage_status";
import { periodChangedSince, weatherChangeSuggestion } from "../settings_form/weather_change_notice";
import { projectViewStateOf } from "./workspace_view_state";
import type { WorkspaceMode } from "../common/WorkspaceModeSwitch";

// The id the service gives the first criterion of a project (a new one's, or an earlier version's made a chain of one).
const FIRST_CRITERION_ID = "1";
const DEFAULT_SITE_HEIGHT = 30;     // m, the height of a project's first site
const STEPS_WITH_SOLID_MAX_VOLUME: readonly StepName[] = ["inputs"];
// A drawn context block starts this high, in m (design/context-blocks.md).
const NEW_BLOCK_HEIGHT = 10;

/** The first "Block N" not taken by a block. */
function nextBlockName(blocks: readonly Site[]): string {
  const taken = new Set(blocks.map((block) => block.name.toLowerCase()));
  let number = 1;
  while (taken.has(messages.blockNamed(number).toLowerCase())) number += 1;
  return messages.blockNamed(number);
}

// The layers each step shows by default (UX 8.2); the later steps add their result layers. The carved voxels start hidden, as
// they cover the kept ones; the Layers menu shows them. Criteria shows what the Mode and Carving steps showed together, the maximum
// volume as a ghost. Envelope and massing shows the base volume (only listed with a base height), so the built mass reads against
// the level below which nothing is carved.
export const LAYERS_SHOWN_IN_STEP: Record<StepName, readonly LayerName[]> = {
  inputs: ["max_volume", "test_surfaces", "context", "terrain"],
  criteria: ["max_volume", "test_surfaces", "context", "terrain", "sun_path", "kept_voxels", "sky_dome"],
  envelope_and_massing: ["base_volume", "test_surfaces", "context", "terrain", "envelope", "building_massing"],
  export: ["context", "terrain", "envelope", "building_massing"],
};
// The layers Simulate shows by default, for each geometry its study values are shown on.
const LAYERS_SHOWN_IN_SIMULATE: Record<StudyStand, readonly LayerName[]> = {
  none: ["max_volume", "context", "terrain", "study_values"],     // the maximum volume as a ghost, so the site still reads
  max_volume: ["max_volume", "context", "terrain", "study_values"],
  base_volume: ["base_volume", "context", "terrain", "study_values"],
  envelope: ["envelope", "context", "terrain", "study_values"],
  massing: ["building_massing", "context", "terrain", "study_values"],
};
// The layers Inspect shows by default, besides the orientation of the test surfaces: the other inputs, the maximum volume as a ghost.
const LAYERS_SHOWN_IN_INSPECT: readonly LayerName[] = ["max_volume", "context", "terrain"];

interface ProjectWorkspaceProps {
  /** Design: the steps beside the 3D view. Simulate and Inspect: the steps are hidden and the view has the whole window. */
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
  /** The steps to open with (the workspace made again for a renamed project); absent: Site. */
  startSteps?: WorkspaceSteps;
  /** A project Create project has just made: the setup window opens over it (design/new-project-setup.md). */
  startsWithSetup?: boolean;
  /** The setup window closed (Start, Skip setup): it is not shown again for this project. */
  onSetupClosed?: () => void;
  /** Told the open step and the step the view shows whenever either changes. */
  onStepsChange?: (steps: WorkspaceSteps) => void;
  /**
   * Told whether Inspect holds turned surfaces not saved or has a save or restore under way, whenever that changes (false once the
   * workspace closes).
   */
  onInspectUnsavedChange?: (unsaved: boolean) => void;
  /** Given what saves, drops and waits for the turns not saved once the workspace is open, and null when it closes. */
  onInspectTurnsReady?: (turns: InspectTurns | null) => void;
  /** Goes from Inspect to Carve, as the switch in the header does. */
  onGoToCarve?: () => void;
  /** The place in the top bar where the Settings button is drawn; null or absent: no button (the window still opens from a run's reason). */
  settingsButtonSlot?: HTMLElement | null;
}

/**
 * The step open in the panel (null when all are closed) and the step whose layers the 3D view shows: the last one opened, and what the
 * Criteria step shows (the list or the editor of a criterion) once it has been decided; absent before the Criteria step first opened.
 */
export interface WorkspaceSteps {
  open: StepName | null;
  view: StepName;
  criteria?: { shows: CriteriaShows; criterionId: string };
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

/** Picking test surfaces on the surroundings, from the Site step (design/test-surfaces-on-context.md). */
interface PickingState {
  /** Edit picks: the set edited, with its name and picks. */
  editing?: { file: string; name: string; picks: SurfacePick[] };
  busy: boolean;
  problem: string | null;
}

/** The Carving group of Settings (data-setting), whose switch the carving's reruns follow. */
const CARVING_UPDATES_SETTING = "carving_updates_itself";
/** What a reason that leads to the weather file focuses in Settings: its box (data-setting). */
const WEATHER_SETTING = "weather_file";
const NO_STEP_ERRORS: readonly string[] = [];

export function ProjectWorkspace(props: ProjectWorkspaceProps) {
  // The token, the project's name and the app's handler of failed requests, for the hooks and panels of the open project.
  const { token, project: { name }, onServiceProblem } = props;
  const session = useMemo(() => ({ token, project: name, onServiceProblem }), [token, name, onServiceProblem]);
  return <ProjectSessionContext value={session}><OpenProject {...props} /></ProjectSessionContext>;
}

function OpenProject(props: ProjectWorkspaceProps) {
  const { token, project, modes, criterionKeys, warmUpState, runs, onServiceProblem } = props;
  const criteria = useCriteria(token, project, props.startSteps?.criteria?.criterionId);
  // The studies of Simulate, kept while Design is shown (the selection stays); SimulateView reads them when Simulate opens.
  const studies = useStudies();
  // The criterion whose settings the criterion form holds: the selected one, once its settings are in (a card just selected waits
  // for GET criteria/{id}/settings). Its panel, its results and the run's check of its test surfaces follow it. A project that lists
  // none (its migration failed) still has the settings of one.
  // The form starts from the first criterion's settings (formStarts), so that is the criterion it holds at the start; a workspace made
  // again on another criterion asks for its settings as a press on its card does.
  const [shownCriterionId, setShownCriterionId] = useState(criteria.criteria[0]?.id ?? "");
  const formCriterionId = shownCriterionId === "" ? FIRST_CRITERION_ID : shownCriterionId;
  // The shown criterion; while a deleted one's place waits for the next one's settings, the selected one.
  const criterion = criteria.criteria.find((entry) => entry.id === shownCriterionId) ?? criteria.criteria.find((entry) => entry.id === criteria.selectedId) ?? null;
  const criterionId = criterion?.id ?? FIRST_CRITERION_ID;
  const resultsCriterionId = criteria.criteria.length > 0 ? formCriterionId : undefined;
  const { sharedForm, criterionForm, form, dispatch, flushSave, cancelSave, changeAndSave, currentForm } = useProjectForms({
    token, project, schema: props.schema, modes, criterionKeys, criteria, formCriterionId,
  });
  const runActive = runs.activeRun?.project === project.name;
  // Files changed in the project folder, found by a stage status read: their lists and meshes are asked for again (the input files'
  // hook, set below), and so are the studies, which may now be out of date.
  const reloadInputRoles = useRef<(roles: string[]) => void>(() => {});
  // The inspection is read again too while Inspect is shown: turns staged on a file replaced by hand are then dropped at once.
  const reloadInspection = useRef<() => void>(() => {});
  const { criterionStages, refreshStageStatus, shownAs, shownStages, everyCriterionCarved, inputChanges, dismissChanges } = useStageStatus({
    project, criteria: criteria.criteria, form, runs,
    onInputFilesChanged: (roles) => {
      reloadInputRoles.current(roles);
      reloadInspection.current();
      void studies.refresh();
    },
  });
  const [framingRequest, setFramingRequest] = useState(0);
  const frameAllInputs = () => setFramingRequest((count) => count + 1);
  const { files, origin, weather, meshes, baseVolume, addFiles, removeFile, lastRemoval, removedFiles, storeTestSurfaceFiles, reloadRoles, followedInputChange, waitForInputChanges,
          sites: siteInput, contextBlocks, contextBlocksMesh } = useInputFiles({
    project, modes, currentForm, sharedForm, refreshStageStatus, onInputsLoaded: frameAllInputs,
  });
  // The studies are read again when the sites, their heights or the source of the maximum volume change: a study on the base volume
  // waits once there is no base height, and the others go out of date (also when the change is made in Settings while in Simulate)
  const refreshStudiesAfterSites = useEffectEvent(() => void studies.refresh());
  const sitesKey = JSON.stringify([siteInput.heights, siteInput.sites, siteInput.source]);     // the values, not the objects read again
  const sitesSeen = useRef<string | null>(null);
  useEffect(() => {
    if (sitesSeen.current !== null && sitesSeen.current !== sitesKey) refreshStudiesAfterSites();
    sitesSeen.current = sitesKey;
  }, [sitesKey]);
  // A site as the input (design/site-input.md): the tool drawing or editing a site in the view, and the tile chosen before any content
  const [siteTool, setSiteTool] = useState<SiteTool | null>(null);
  // Drawing or editing a context block (design/context-blocks.md); one of the two tools at a time
  const [blockTool, setBlockTool] = useState<SiteTool | null>(null);
  const [focusBlockHeight, setFocusBlockHeight] = useState<number | null>(null);
  const [siteToolSeen, setSiteToolSeen] = useState<SiteTool | null>(null);
  if (siteTool !== siteToolSeen) {        // a site tool started: the block tool ends
    setSiteToolSeen(siteTool);
    if (siteTool !== null && blockTool !== null) setBlockTool(null);
  }
  const [picking, setPicking] = useState<PickingState | null>(null);
  // An outline file read and shown in the import window (design/site-import.md), and what the last import or placing said
  const [importing, setImporting] = useState<{ found: OutlinesReply; busy: boolean } | null>(null);
  const [siteNote, setSiteNote] = useState<{ text: string; warning: boolean } | null>(null);
  const [maxVolumeChosen, setMaxVolumeChosen] = useState(false);
  const inputChangesNotice = <InputChangesNotice changes={inputChanges} onDismiss={dismissChanges} />;
  const tellSettingsSaver = useEffectEvent((open: boolean) => {
    props.onSettingsSaverReady?.(open ? { flush: flushSave, cancel: cancelSave, waitForInputChanges } : null);
  });
  useEffect(() => {
    tellSettingsSaver(true);
    return () => tellSettingsSaver(false);
  }, []);
  const [openStep, setOpenStep] = useState<StepName | null>(props.startSteps?.open ?? "inputs");
  const [viewStep, setViewStep] = useState<StepName>(props.startSteps?.view ?? "inputs");
  // What the Criteria step shows, the list or the editor of the selected criterion. Null until the step first opens: a project with one
  // criterion then opens on its editor, one with several on the list (criteria_shows.ts). From then on it is kept while the project
  // stays open (also in the steps reported for a renamed project), whatever opens the step. The criterion reported is the selected one,
  // also while its settings are on their way, so the workspace made again after a rename opens on it.
  const [criteriaShows, setCriteriaShows] = useState<CriteriaShows | null>(props.startSteps?.criteria?.shows ?? null);
  const reportSteps = useEffectEvent((steps: WorkspaceSteps) => props.onStepsChange?.(steps));
  useEffect(() => reportSteps({
    open: openStep, view: viewStep, ...(criteriaShows === null ? {} : { criteria: { shows: criteriaShows, criterionId: criteria.selectedId } }),
  }), [openStep, viewStep, criteriaShows, criteria.selectedId]);
  const panel = useRef<HTMLElement>(null);
  // In Simulate the panel is hidden, not unmounted (Design then finds its open step, folds and forms as left); its scroll is kept.
  const keepScroll = useKeptScroll(panel, props.mode === "design");
  const [addFilesRequest, setAddFilesRequest] = useState(0);
  const [settingToFocus, setSettingToFocus] = useState<{ name: string } | null>(null);
  // The project settings window, opened from the Settings button or from a reason or link that names one of its settings.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(props.startsWithSetup === true);
  // The carving reruns as its settings change: the project's choice (project.json), in Settings > Carving. A choice an earlier
  // version kept in this browser is moved into the project once.
  const [carvingUpdatesItself, setCarvingUpdatesItselfShown] = useState(
    () => browserAutoUpdateChoice(props.project.name) ?? props.project.carving_updates_itself ?? true);
  const changeCarvingUpdates = (on: boolean) => {
    setCarvingUpdatesItselfShown(on);
    setCarvingUpdates(props.token, props.project.name, on).catch((error: unknown) => {
      if (!reportServiceProblem(error, props.onServiceProblem)) setCarvingUpdatesItselfShown(!on);
    });
  };
  const moveBrowserChoice = useEffectEvent(() => {
    const kept = browserAutoUpdateChoice(props.project.name);
    if (kept === null) return;
    forgetBrowserAutoUpdateChoice(props.project.name);
    if (kept !== (props.project.carving_updates_itself ?? true)) {
      setCarvingUpdates(props.token, props.project.name, kept).catch((error: unknown) => reportServiceProblem(error, props.onServiceProblem));
    }
  });
  useEffect(() => moveBrowserChoice(), []);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsContent = useRef<HTMLDivElement>(null);
  const closeSettings = () => {
    setSettingsOpen(false);
    settingsButton.current?.focus();
  };
  // A criterion's setting to focus is in its editor, a shared one in the project settings window: either is shown in the same render
  // that asks for the focus, so its field is there.
  const focusSettingInPanel = (settingName: string) => {
    const place = placeOfSetting(settingName, criterionKeys);
    if (place === "criteria") setCriteriaShows("editor");
    if (place === "project_settings") setSettingsOpen(true);
    setSettingToFocus({ name: settingName });
  };

  const modeInfo = modes.find((candidate) => candidate.name === form.mode);
  const modeNeedsWeatherFile = modeInfo?.needs_epw ?? false;
  const hasWeatherFile = files.weather.length > 0;
  const maxVolumeMesh = meshes.max_volume, testSurfacesMesh = meshes.test_surfaces, contextMesh = meshes.context, terrainMesh = meshes.terrain;
  // The Context layer draws the context files and the drawn blocks together (design/context-blocks.md)
  const contextGeometry = useMemo(() => joinedOrNull([contextMesh.geometry, contextBlocksMesh.geometry]), [contextMesh.geometry, contextBlocksMesh.geometry]);
  const hasContext = files.context.length > 0 || contextBlocks.blocks.length > 0;
  const maxVolume = maxVolumeMesh.geometry, testSurfaces = testSurfacesMesh.geometry;
  // The bounds of the maximum volume and the test surfaces loaded so far: the sun path and the sky dome are drawn around them (R2 2)
  const inputsBounds = useMemo(() => boundsOf([maxVolume, testSurfaces]), [maxVolume, testSurfaces]);
  const { testSurfaceGroups, setTestSurfacesShown } = useTestSurfaceDrawing(criteria.criteria, criterion, testSurfacesMesh, testSurfaces);
  const sceneSphere = useMemo(() => (inputsBounds === null ? null : sceneHemisphere(inputsBounds)), [inputsBounds]);
  const northDegrees = Number(shownValue(form, "north_deg") ?? 0);
  // The test point spacing of the carving (the grid step, else half the voxel size), which a study follows until it has its own.
  const gridStep = shownValue(form, "grid_step");
  const carvingSpacing = typeof gridStep === "number" && gridStep > 0 ? gridStep : Number(shownValue(form, "voxel_size") ?? 1) / 2;

  const reportSaveProblem = useEffectEvent((error: unknown) => reportServiceProblem(error, onServiceProblem));
  useEffect(() => {
    if (form.saveFailure !== null) reportSaveProblem(form.saveFailure);
  }, [form.saveFailure]);

  // The sun path of the stored period (UX 8.2), as soon as the weather file and the period are there, before any run.
  const sunPath = useSunPathOfStoredPeriod({ form, hasWeatherFile, northDegrees, criterionId: resultsCriterionId });
  const { coldPeriod, answeredWeatherFileRevision } = useColdPeriod({ form, hasWeatherFile, weatherFileRevision: weather.fileRevision });
  const modeReadsPeriod = modeInfo?.needs_period ?? false;
  const periodShown = analysisPeriodOf(form, modeReadsPeriod);
  // The cold period belongs to the cold hours rule: an energy-weighted criterion is offered no cold period, by the notice nor the preset.
  const weatherChangeSuggestionNow = weatherChangeSuggestion(weather.fileChange, {
    mode: form.mode, modeReadsPeriod, period: periodShown, coldPeriod: criterion?.energy_weighted ? null : coldPeriod, answeredWeatherFileRevision,
  });
  // Once the period is not the one the new file came with, the notice has nothing more to say about it, even if the period comes back.
  const weatherChangeOutlived = weather.fileChange !== null && periodChangedSince(weather.fileChange, periodShown);
  const setWeatherFileChange = weather.setFileChange;
  useEffect(() => {
    if (weatherChangeOutlived) setWeatherFileChange(null);
  }, [weatherChangeOutlived, setWeatherFileChange]);

  const inputsDisabledReason = runActive ? messages.runInProgress : null;
  const inputRolesWithFiles = (Object.keys(files) as InputRole[]).filter((role) => files[role].length > 0);

  // The criterion's test surfaces (test_surface_calls.ts): the 3D view loads the stored files again after each change (a replaced
  // file keeps its name). The local origin follows the maximum volume only, so it does not change with them.
  const testSurfaceCalls = useTestSurfaceCalls({
    criteria, criterionId, refreshStageStatus, followed: followedInputChange, onStoredFiles: storeTestSurfaceFiles,
  });
  const inspecting = props.mode === "inspect";
  const { inspection, surfacesChanged } = useWorkspaceInspection({
    inspecting, refreshStageStatus, reloadStoredFiles: testSurfaceCalls.reloadStoredFiles,
    onUnsavedChange: props.onInspectUnsavedChange, onTurnsReady: props.onInspectTurnsReady,
  });
  const inspectView = useInspectView(inspection, origin, inspecting);
  // Set once the render is committed: the hooks above call these with a reply.
  useLayoutEffect(() => {
    reloadInspection.current = inspection.reload;
    reloadInputRoles.current = reloadRoles;
  });

  // The criterion's files as stored, in its order; a file just added shows once the stored files have been asked for again.
  const criterionTestSurfaces = criterion === null ? files.test_surfaces
    : (criterion.test_surface_files ?? []).flatMap((name) => files.test_surfaces.filter((file) => file.name === name));

  const openTheStep = (step: StepName | null) => {
    setOpenStep(step);
    if (step !== null) setViewStep(step);
  };
  const openPlace = (place: SettingPlace) => {
    if (place === "project_settings") setSettingsOpen(true);
    else openTheStep(place);
  };

  useEffect(() => {
    if (settingToFocus === null) return;
    // The input the field's label targets: the number field of a slider, the balance temperature's number of the balance widget.
    const selector = `[data-setting="${settingToFocus.name}"]`;
    const field = settingsContent.current?.querySelector<HTMLElement>(selector) ?? panel.current?.querySelector<HTMLElement>(selector);
    const labelled = field?.dataset.inputId === undefined ? null : document.getElementById(field.dataset.inputId);
    // A field's input, or a box's button (the weather file's Add files)
    (labelled ?? field?.querySelector<HTMLElement>(":is(input:not([type=file]), select)") ?? field?.querySelector<HTMLElement>("button"))?.focus();
  }, [settingToFocus]);
  // The criterion panel's open sections, kept here so they outlast the Criteria step while it is closed (not stored). A setting of
  // the panel to focus opens the section that holds it first, in the same render.
  const openSectionRequest = useMemo(() => (settingToFocus === null || placeOfSetting(settingToFocus.name, criterionKeys) !== "criteria" ? null
    : { section: sectionOfSetting(settingToFocus.name) }), [settingToFocus, criterionKeys]);
  const panelSections = usePanelSections(openSectionRequest);

  // Either button of the notice ends it; the focus, on a button that goes away, moves to the period the notice was about.
  const endWeatherChangeNotice = () => {
    weather.setFileChange(null);
    focusSettingInPanel(fieldSettingOf(ANALYSIS_PERIOD_FIELDS[0]));
  };

  // The criteria's part: the selection, the requests of the cards, why a run cannot start, and what the results and cards read.
  const workspaceCriteria = useWorkspaceCriteria({
    criteria, shownCriterionId, setShownCriterionId, criterion, resultsCriterionId, sharedForm, criterionForm, form, dispatch,
    currentForm, schema: props.schema, modes, criterionKeys, runs, warmUpState,
    maxVolumeFiles: siteInput.source === "sites" ? siteInput.sites.length : files.max_volume.length, maxVolumeFromSites: siteInput.source === "sites",
    testSurfaceFiles: files.test_surfaces.length, hasWeatherFile, modeNeedsWeatherFile, criterionStages, shownAs, refreshStageStatus,
    followed: followedInputChange, reloadTestSurfaces: testSurfaceCalls.reloadStoredFiles, openPlace,
    focusSetting: (settingName) => focusSettingInPanel(fieldSettingOf(settingName)), onShowCriterion: () => setCriteriaShows("editor"),
  });
  // The first time the Criteria step opens, before the first paint of it.
  const criteriaCount = criteria.criteria.length;
  if (openStep === "criteria" && criteriaShows === null) setCriteriaShows(firstCriteriaShows(criteriaCount));
  // A new weather file's notice belongs to the criterion whose form it is shown in: while it waits, the Criteria step opens on that
  // editor. It does so as the step opens or the notice comes; the list can be chosen after.
  const editorForWeatherNotice = openStep === "criteria" && weatherChangeSuggestionNow !== null;
  useChangedDuringRender(editorForWeatherNotice, () => {
    if (editorForWeatherNotice) setCriteriaShows("editor");
  }, { before: false });
  const { selection, active, ownStages } = workspaceCriteria;
  const resultSteps = useResultSteps({
    ...workspaceCriteria.ofResults,
    criterionId: resultsCriterionId, criterionKeys,
    form, currentForm, dispatch, flushSave, changeAndSave, isWeightedMode: modeInfo?.score_kind === "weighted_sum", stages: shownStages,
    refreshStageStatus, runs, runBlocker: workspaceCriteria.runBlocker, everyCriterionCarved, projectRunActive: runActive, origin, openStep: openTheStep,
    carvingUpdatesItself,
    // A reason that names a setting of the project settings leads there: the window opens on that field. A reason that names another
    // criterion without test surfaces leads to that criterion, its Test surfaces section open.
    runBlockerAction: workspaceCriteria.runBlockerCriterion !== null ? (
      <button type="button" className="link-button run-button-reason-action" onClick={() => {
        const blocking = workspaceCriteria.runBlockerCriterion;
        if (blocking === null) return;
        openTheStep("criteria");
        selection.showCriterion(blocking.id, () => panelSections.onOpenSections(["test_surfaces"]));
      }}>{messages.openCriterion(workspaceCriteria.runBlockerCriterion.name)}</button>
    ) : workspaceCriteria.runBlockerPlace === "project_settings" && (
      <button type="button" className="link-button run-button-reason-action" onClick={() => {
        const firstShared = Object.keys(sharedForm.form.fieldErrors)[0];
        if (firstShared !== undefined) focusSettingInPanel(fieldSettingOf(firstShared));
        else {
          setSettingsOpen(true);
          if (!hasWeatherFile) setSettingToFocus({ name: WEATHER_SETTING });
        }
      }}>{messages.openProjectSettings}</button>
    ),
    goToSetting: workspaceCriteria.goToSetting,
  });
  const cards = workspaceCriteria.cardsOf(resultSteps, inputsDisabledReason);
  const viewState = projectViewStateOf({
    files, form, sharedForm: sharedForm.form, criterionForm: criterionForm.form, criterionKeys, northDegrees, stages: shownStages,
    summary: resultSteps.results.summary, criteria: criteria.criteria, active,
    sites: siteInput.source === "sites" ? { count: siteInput.sites.length, area: siteInput.sites.reduce((sum, site) => sum + siteArea(site), 0) } : null,
  });

  const weatherHint = messages.weatherNeededFor(listedWithAnd(modes.filter((mode) => mode.needs_epw).map((mode) => plainModeName(mode.name))));
  const weatherBox = (
    <InputBox role="weather" files={files.weather} weatherLocation={weather.location} weatherHint={weatherHint} onAddFiles={addFiles}
              onRemoveFile={removeFile} disabledReason={inputsDisabledReason} weatherNeeded showsDisabledReason={false} />
  );
  // The weather file in the Location group of Settings (design/new-project-setup.md)
  const settingsWeatherBox = (
    <InputBox role="weather" files={files.weather} weatherLocation={weather.location} weatherHint={weatherHint} onAddFiles={addFiles}
              onRemoveFile={removeFile} disabledReason={inputsDisabledReason} showsDisabledReason={false} />
  );
  const changeSettings = (values: Record<string, unknown>) => dispatch({ type: "values_changed", values });
  // A new project asks for the mode of its first criterion once: the mode goes with the criterion's settings, its editor opens.
  const [modeToChoose, setModeToChoose] = useState(project.mode_to_choose);
  const chooseFirstMode = (mode: string) => {
    dispatch({ type: "mode_chosen", mode });
    setModeToChoose(false);
    setCriteriaShows("editor");
    markModeChosen(token, project.name).catch(onServiceProblem);
  };
  // A criterion that is off (the chain skips it) needs no test surfaces nor weather file: its panel asks for neither.
  const criterionOn = !(criterion?.bypassed ?? false);
  // Which hours count of a Solar heating criterion; the switch changes its config, so its stages are read again.
  const energyWeighted = criterion?.energy_weighted ?? false;
  const typicalBuilding = useTypicalBuilding({
    active: form.mode === "benefit" && energyWeighted, runActive, weatherRevision: weather.fileRevision,
  });
  const changeEnergyWeighted = async (on: boolean): Promise<string | null> => {
    try {
      await criteria.setEnergyWeighted(criterionId, on);
      refreshStageStatus();
      return null;
    } catch (error) {
      return reportServiceProblem(error, onServiceProblem) ? null : failureTextOf(error);
    }
  };
  const usesSites = siteInput.source === "sites";
  const choosingInput = siteInput.source === "mesh" && files.max_volume.length === 0 && siteInput.sites.length === 0 && !maxVolumeChosen
    && (project.carving_chain ?? []).length === 0;
  const lastHeight = siteInput.sites.length ? siteInput.sites[siteInput.sites.length - 1].height : DEFAULT_SITE_HEIGHT;
  const surroundings = boundsOf([contextGeometry, terrainMesh.geometry]);
  const siteLevel = drawingLevel(siteInput.sites.map((site) => allPoints(site)), surroundings === null ? null : surroundings[0][2] + origin[2]);
  const changeSite = (index: number, site: Site) => siteInput.save(siteInput.sites.map((other, at) => (at === index ? site : other)));
  const deleteSite = (index: number) => {
    if (siteTool?.kind === "edit") setSiteTool(null);
    void siteInput.save(siteInput.sites.filter((_, at) => at !== index));
  };
  // The height a new site gets: the last site's, or more when the site rises more
  const newSiteHeight = (points: SitePoint[]) => Math.max(lastHeight, Math.ceil(siteRise(points) + 1));
  // Draw makes a new site; Draw hole in a site's editor draws a hole of that site, its vertices at the site's lowest elevation
  // (user, 2026-11-12: holes are drawn on purpose, and sites may not overlap or nest, which the service refuses). One save, one undo;
  // a refused hole leaves the drawing open with the reason.
  const finishDrawing = (points: SitePoint[]) => {
    if (siteTool?.kind === "draw_hole") {
      const index = siteTool.index;
      const site = siteInput.sites[index];
      if (!site) return;
      const lowest = elevationRange(allPoints(site))[0];
      const hole = points.map((point): SitePoint => [point[0], point[1], lowest]);
      void siteInput.save(siteInput.sites.map((other, at) => (at === index ? withRings(site, [...ringsOf(site), hole]) : other)))
        .then((refused) => { if (refused === null) setSiteTool({ kind: "edit", index }); });
      return;
    }
    const added = [...siteInput.sites, { name: nextSiteName(siteInput.sites), points, height: newSiteHeight(points) }];
    void siteInput.save(added).then((refused) => { if (refused === null) setSiteTool({ kind: "edit", index: added.length - 1 }); });
  };
  // A site lying wholly inside another made that one's hole, and a hole made a site again or deleted (design/site-holes.md): one save each
  const makeHoleOf = (index: number, outerIndex: number) => {
    const inner = siteInput.sites[index], outer = siteInput.sites[outerIndex];
    if (!inner || !outer) return;
    if (siteTool?.kind === "edit") setSiteTool(null);
    void siteInput.save(siteInput.sites.flatMap((site, at) => (at === index ? [] : at === outerIndex ? [withRings(outer, [...ringsOf(outer), inner.points])] : [site])));
  };
  const deleteHole = (index: number, hole: number) => {
    const site = siteInput.sites[index];
    if (!site || !holesOf(site)[hole]) return;
    void changeSite(index, withRings(site, ringsOf(site).filter((_, ring) => ring !== hole + 1)));
  };
  // Sites from DXF and OBJ files and Place on terrain (design/site-import.md): the service reads and places the outlines; they are
  // added here as one undoable change, as a drawing adds a site
  const hasTerrain = files.terrain.length > 0;
  // Each vertex of the rings (an outline and its holes) takes the terrain's height below it, in one request
  const onTerrain = async (rings: SitePoint[][]): Promise<{ rings: SitePoint[][]; off: number }> => {
    const reply = await terrainHeights(token, project.name, rings.flat().map((point) => [point[0], point[1]]));
    let off = 0, at = 0;
    const placed = rings.map((ring) => ring.map((point): SitePoint => {
      const height = reply.heights[at++];
      if (height === null || height === undefined) {
        off += 1;
        return point;
      }
      return [point[0], point[1], height];
    }));
    return { rings: placed, off };
  };
  const reportSiteProblem = (error: unknown) => {
    if (reportServiceProblem(error, onServiceProblem)) return;
    setSiteNote({ text: failureTextOf(error), warning: true });
  };
  // The names the outlines are added with: their own, or the next "Site n" after the sites there and those before them
  const importedNames = (found: OutlinesReply): string[] => {
    const named: Site[] = [...siteInput.sites];
    return found.outlines.map((outline) => {
      const siteName = (outline.name || nextSiteName(named)).slice(0, 80);
      named.push({ name: siteName, points: [], height: 1 });
      return siteName;
    });
  };
  const importOutlines = (file: File) => {
    setSiteNote(null);
    readOutlines(token, project.name, file).then((found) => setImporting({ found, busy: false }), reportSiteProblem);
  };
  const finishImport = async (placeOnTerrain: boolean) => {
    if (importing === null) return;
    setImporting({ ...importing, busy: true });
    try {
      const sites = [...siteInput.sites];
      const names = importedNames(importing.found);
      let off = 0;
      for (const [index, outline] of importing.found.outlines.entries()) {
        const asRing = (ring: number[][]) => ring.map((point) => [point[0], point[1], point[2]] as SitePoint);
        const originalRings = [asRing(outline.points), ...(outline.holes ?? []).map(asRing)];
        let rings = originalRings;
        if (placeOnTerrain) {
          const placed = await onTerrain(originalRings);
          rings = placed.rings;
          off += placed.off;
        }
        const original = originalRings.length > 1 ? { file: importing.found.file, points: originalRings[0], holes: originalRings.slice(1) }
          : { file: importing.found.file, points: originalRings[0] };
        sites.push(withRings({ name: names[index], points: rings[0], height: newSiteHeight(rings.flat()), original }, rings));
      }
      setImporting(null);
      const refused = await siteInput.save(sites);
      if (refused === null) {
        if (off > 0) setSiteNote({ text: messages.placedOffTerrain(off), warning: false });
        frameAllInputs();
      }
    } catch (error) {
      setImporting(null);
      reportSiteProblem(error);
    }
  };
  // Drawn context blocks: Draw block adds one 10 m high (its height field then takes the focus), Draw hole a hole of the edited one
  const startBlockTool = (tool: SiteTool) => {
    setSiteTool(null);
    setBlockTool(tool);
  };
  const changeBlock = (index: number, block: Site) => contextBlocks.save(contextBlocks.blocks.map((other, at) => (at === index ? block : other)));
  const removeBlock = (index: number) => {
    setBlockTool(null);
    void contextBlocks.save(contextBlocks.blocks.filter((_, at) => at !== index));
  };
  const finishBlockDrawing = (points: SitePoint[]) => {
    if (blockTool?.kind === "draw_hole") {
      const index = blockTool.index;
      const block = contextBlocks.blocks[index];
      if (!block) return;
      const lowest = elevationRange(allPoints(block))[0];
      const hole = points.map((point): SitePoint => [point[0], point[1], lowest]);
      void changeBlock(index, withRings(block, [...ringsOf(block), hole])).then((refused) => { if (refused === null) setBlockTool({ kind: "edit", index }); });
      return;
    }
    const added = [...contextBlocks.blocks, { name: nextBlockName(contextBlocks.blocks), points, height: NEW_BLOCK_HEIGHT }];
    void contextBlocks.save(added).then((refused) => {
      if (refused !== null) return;
      setBlockTool(null);
      setFocusBlockHeight(added.length - 1);
    });
  };
  const placeBlockOnTerrain = async (index: number) => {
    setSiteNote(null);
    try {
      const block = contextBlocks.blocks[index];
      const placed = await onTerrain(ringsOf(block));
      const refused = await changeBlock(index, withRings(block, placed.rings));
      if (refused === null && placed.off > 0) setSiteNote({ text: messages.placedOffTerrain(placed.off), warning: false });
    } catch (error) {
      reportSiteProblem(error);
    }
  };
  const placeSiteOnTerrain = async (index: number) => {
    setSiteNote(null);
    try {
      const site = siteInput.sites[index];
      const placed = await onTerrain(ringsOf(site));
      const refused = await changeSite(index, withRings(site, placed.rings));
      if (refused === null && placed.off > 0) setSiteNote({ text: messages.placedOffTerrain(placed.off), warning: false });
    } catch (error) {
      reportSiteProblem(error);
    }
  };
  const restoreOriginal = (index: number) => {
    const site = siteInput.sites[index];
    if (site.original) void changeSite(index, withRings(site, [site.original.points, ...(site.original.holes ?? [])]));
  };
  const maxVolumeBox = siteInput.source === null ? undefined : choosingInput ? (
    <InputChoice disabledReason={inputsDisabledReason} onChooseMaxVolume={() => setMaxVolumeChosen(true)}
                 onChooseSite={() => { void siteInput.setSource("sites"); }} />
  ) : usesSites ? (
    <SiteBox sites={siteInput.sites} heights={siteInput.heights} tool={siteTool} refusal={siteInput.refusal} disabledReason={inputsDisabledReason}
             onDraw={() => setSiteTool({ kind: "draw" })} onEdit={(index) => setSiteTool({ kind: "edit", index })}
             onChangeSite={changeSite} onDeleteSite={deleteSite} onImport={importOutlines} onPlaceOnTerrain={(index) => { void placeSiteOnTerrain(index); }}
             onRestoreOriginal={restoreOriginal} hasTerrain={hasTerrain} note={siteNote} overlaps={siteInput.overlaps}
             onMakeHole={makeHoleOf} onDeleteHole={deleteHole}
             onSwitch={() => { setSiteTool(null); setMaxVolumeChosen(true); void siteInput.setSource("mesh"); }} />
  ) : undefined;
  const maxVolumeFooter = siteInput.source === "mesh" && !choosingInput ? (
    <SwitchInputLink toSite asks={files.max_volume.length > 0} disabledReason={inputsDisabledReason} onSwitch={() => { void siteInput.setSource("sites"); }} />
  ) : null;
  // The site tools work while Inputs is open in Carve; a run in progress stops them. The block tools too, whatever the maximum
  // volume is made from.
  const inputsToolsOpen = props.mode === "design" && openStep === "inputs" && inputsDisabledReason === null;
  // Test surfaces drawn on the ground (design/test-surfaces-on-ground.md), with the site editor; one tool open at a time
  const ground = useGroundSurfaces({
    token, project: project.name, sets: files.test_surfaces, onServiceProblem,
    onSaved: async () => {
      await testSurfaceCalls.reloadStoredFiles();
      reloadRoles(["test_surfaces"]);
      refreshStageStatus();
    },
  });
  if (ground.tool !== null && (!inputsToolsOpen || siteTool !== null || blockTool !== null
    || (ground.editedFile !== null && !files.test_surfaces.some((file) => file.name === ground.editedFile)))) ground.end();
  const startGround = (tool: GroundTool) => {
    setSiteTool(null);
    setBlockTool(null);
    setPicking(null);
    ground.start(tool);
  };
  const siteToolShown = inputsToolsOpen && usesSites ? siteTool : null;
  const blockToolShown = inputsToolsOpen ? blockTool : null;
  const pickedSites = usesSites ? siteInput.sites : [];
  const sceneTool = blockToolShown !== null ? (scene: ViewerScene) => (
      <SiteEditor scene={scene} origin={origin} sites={contextBlocks.blocks} snapSites={siteInput.sites} tool={blockToolShown} level={siteLevel}
                  newSiteName={nextBlockName(contextBlocks.blocks)} onFinishDrawing={finishBlockDrawing}
                  onChangeSite={(index, block) => { void changeBlock(index, block); }}
                  onClose={() => setBlockTool(blockTool?.kind === "draw_hole" ? { kind: "edit", index: blockTool.index } : null)}
                  onDrawHole={(index) => setBlockTool({ kind: "draw_hole", index })}
                  onUndo={contextBlocks.undo} onRedo={contextBlocks.redo} canUndo={contextBlocks.canUndo} canRedo={contextBlocks.canRedo}
                  refusal={contextBlocks.refusal} />
    )
    : !inputsToolsOpen ? null
    : ground.editorTool !== null ? (scene: ViewerScene) => (
      <SiteEditor scene={scene} origin={origin} sites={ground.site ? [ground.site] : []} snapSites={[...siteInput.sites, ...contextBlocks.blocks]}
                  tool={ground.editorTool!} level={ground.site ? ground.site.points[0][2] : siteLevel} newSiteName={ground.newName} onFinishDrawing={ground.finishDrawing}
                  onChangeSite={(_, site) => ground.change(site)} onClose={ground.close} onDrawHole={ground.startHole}
                  onUndo={ground.undo} onRedo={ground.redo} canUndo={ground.canUndo} canRedo={ground.canRedo} refusal={ground.refusal} flatElevation />
    )
    : siteToolShown !== null ? (scene: ViewerScene) => (
      <SiteEditor scene={scene} origin={origin} sites={siteInput.sites} snapSites={contextBlocks.blocks} tool={siteToolShown} level={siteLevel} newSiteName={nextSiteName(siteInput.sites)}
                  onFinishDrawing={finishDrawing} onChangeSite={(index, site) => { void changeSite(index, site); }}
                  onClose={() => setSiteTool(siteTool?.kind === "draw_hole" ? { kind: "edit", index: siteTool.index } : null)}
                  onDrawHole={(index) => setSiteTool({ kind: "draw_hole", index })}
                  onUndo={siteInput.undo} onRedo={siteInput.redo} canUndo={siteInput.canUndo} canRedo={siteInput.canRedo} refusal={siteInput.refusal}
                  heights={siteInput.heights} />
    ) : pickedSites.length === 0 && contextBlocks.blocks.length === 0 ? null
    : (scene: ViewerScene) => (
      // A click in a site or a block edits it (the smaller outline where both are under the click), whatever the maximum volume is made of
      <SitePicker scene={scene} origin={origin} sites={pickedSites} onPick={(index) => setSiteTool({ kind: "edit", index })}
                  blocks={contextBlocks.blocks} onPickBlock={(index) => startBlockTool({ kind: "edit", index })} />
    );
  // Test surfaces picked on the surroundings (design/test-surfaces-on-context.md): picking starts in the Site step's Test surfaces box
  // and ends when the step is not shown any more. Use makes a surface set (or adds to one, or saves an edit), which no criterion uses
  // until it is switched on there; the stored files and the test surfaces drawn are read again.
  const hasSurroundingsFiles = files.context.length > 0;
  const setNames: Record<string, string> = Object.fromEntries(files.test_surfaces.map((file) => [file.name, file.shown_name ?? file.name]));
  const pickedSets = files.test_surfaces.filter((file) => file.picked === true).map((file) => ({ file: file.name, name: file.shown_name ?? file.name }));
  const nextPickedName = () => {
    const shown = new Set(files.test_surfaces.map((file) => (file.shown_name ?? file.name).toLowerCase()));
    let number = 1;
    while (shown.has(`picked ${number}`)) number += 1;
    return `Picked ${number}`;
  };
  const pickingApplies = picking !== null && props.mode === "design" && openStep === "inputs";
  if (picking !== null && !pickingApplies) setPicking(null);
  const startPicking = () => {
    ground.end();
    setPicking({ busy: false, problem: null });
  };
  const reportPickProblem = (error: unknown) => {
    if (!reportServiceProblem(error, onServiceProblem)) setPicking((now) => now && { ...now, busy: false, problem: failureTextOf(error) });
  };
  const editPicks = async (fileName: string) => {
    try {
      const reply = await getSurfacePicks(token, project.name, fileName);
      setPicking({ editing: { file: fileName, name: setNames[fileName] ?? fileName, picks: reply.picks }, busy: false, problem: null });
    } catch (error) {
      reportServiceProblem(error, onServiceProblem);
    }
  };
  const renameSet = async (fileName: string, setName: string): Promise<string | null> => {
    try {
      await renameSurfaceSet(token, project.name, fileName, setName);
      await testSurfaceCalls.reloadStoredFiles();
      return null;
    } catch (error) {
      return reportServiceProblem(error, onServiceProblem) ? null : failureTextOf(error);
    }
  };
  const savePicks = async (picks: SurfacePick[], target: PickTarget) => {
    if (picking === null) return;
    const now = picking;
    setPicking({ ...now, busy: true, problem: null });
    try {
      if (now.editing !== undefined) {
        await pickSurfaceSet(token, project.name, { picks, replace: now.editing.file });
      } else if (target.kind === "add") {
        const before = await getSurfacePicks(token, project.name, target.file);
        await pickSurfaceSet(token, project.name, { picks: [...before.picks, ...picks], replace: target.file });
      } else {
        await pickSurfaceSet(token, project.name, { picks, name: target.name.trim() });
      }
      await testSurfaceCalls.reloadStoredFiles();
      reloadRoles(["test_surfaces"]);
      refreshStageStatus();
      setPicking(null);
    } catch (error) {
      reportPickProblem(error);
    }
  };
  const pickingColour = "#4477aa";
  const pickerTool = picking === null || !pickingApplies || contextMesh.geometry === null ? null : (scene: ViewerScene) => (
    <ContextPicker scene={scene} origin={origin} geometry={contextMesh.geometry!} colour={pickingColour}
                   editing={picking.editing === undefined ? undefined : { name: picking.editing.name, picks: picking.editing.picks }}
                   pickedSets={pickedSets} newSetName={nextPickedName()} busy={picking.busy} problem={picking.problem}
                   onUse={(picks, target) => { void savePicks(picks, target); }} onCancel={() => setPicking(null)} />
  );
  const testSurfacesBox = (
    <SurfaceSetsBox files={files.test_surfaces} onAddFiles={addFiles} onRemoveFile={removeFile} disabledReason={inputsDisabledReason}
                    drawingProblems={testSurfacesMesh.drawingProblems} onPickFromSurroundings={hasSurroundingsFiles && props.mode === "design" ? startPicking : undefined}
                    onRenameSet={renameSet} onEditPicks={(fileName) => { void editPicks(fileName); }}
                    onDraw={props.mode === "design" ? () => startGround({ kind: "draw" }) : undefined}
                    onEditOutline={props.mode === "design" ? (fileName) => startGround({ kind: "edit", file: fileName }) : undefined} />
  );
  const stepContent: Record<StepName, ReactNode> = {
    inputs: (
      <InputsStep files={files} inputsBounds={inputsBounds} onAddFiles={addFiles} testSurfacesBox={testSurfacesBox}
                  onRemoveFile={removeFile} disabledReason={inputsDisabledReason} maxVolumeNote={carvedByNote(project.carving_chain ?? [])}
                  maxVolumeBox={maxVolumeBox} maxVolumeFooter={maxVolumeFooter} removedFiles={removedFiles}
                  contextExtraAction={(
                    <button type="button" className="input-add" disabled={inputsDisabledReason !== null}
                            onClick={() => startBlockTool({ kind: "draw" })}>{messages.drawBlock}</button>
                  )}
                  contextFooter={(
                    <ContextBlocksList blocks={contextBlocks.blocks} disabledReason={inputsDisabledReason} hasTerrain={hasTerrain}
                                       focusHeightOf={focusBlockHeight} refusal={contextBlocks.refusal}
                                       editing={blockToolShown !== null && blockToolShown.kind !== "draw" ? blockToolShown.index : null}
                                       onEdit={(index) => startBlockTool({ kind: "edit", index })} onChange={changeBlock} onRemove={removeBlock}
                                       onDrawHole={(index) => startBlockTool({ kind: "draw_hole", index })}
                                       onPlaceOnTerrain={(index) => { void placeBlockOnTerrain(index); }}
                                       canUndo={contextBlocks.canUndo} onUndo={contextBlocks.undo} />
                  )}
                  drawingProblems={{ max_volume: maxVolumeMesh.drawingProblems, context: contextMesh.drawingProblems, terrain: terrainMesh.drawingProblems }} />
    ),
    criteria: (
      <CriteriaStep list={cards.list} load={selection.load} chainLine={cards.chainLine} shows={criteriaShows ?? firstCriteriaShows(criteriaCount)} onShowsChange={setCriteriaShows}
                    firstMode={modeToChoose ? <FirstMode onChoose={chooseFirstMode} disabledReason={inputsDisabledReason} /> : null}
                    panelProblem={workspaceCriteria.panelProblem} panel={
        <CriterionPanel key={criterionId} {...panelSections} testSurfaces={criterionTestSurfaces} criterionOn={criterionOn} testSurfaceDrawingProblems={testSurfacesMesh.drawingProblems}
                        surfaceSets={files.test_surfaces} onOpenSite={() => openTheStep("inputs")}
                        onToggleTestSurface={(fileName, on) => (on ? testSurfaceCalls.use(fileName) : testSurfaceCalls.remove(fileName))} form={form}
                        stepErrors={criterionForm.form.stepErrors} criterionKeys={criterionKeys}
                        onChange={changeSettings} disabledReason={inputsDisabledReason}
                        weatherDropZone={criterionOn && modeNeedsWeatherFile && !hasWeatherFile ? weatherBox : null} inputRoles={inputRolesWithFiles}
                        coldPeriod={coldPeriod} hemisphere={hemisphereOfLatitude(weather.latitude)}
                        weatherChangeNotice={weatherChangeSuggestionNow === null ? null : { suggestion: weatherChangeSuggestionNow, onDismiss: endWeatherChangeNotice }}
                        carvingRule={resultSteps.carvingRule} scoreUnit={modeInfo?.score_unit}
                        hoursCounted={{ energyWeighted, onChange: changeEnergyWeighted, building: typicalBuilding, hasWeatherFile }} />
      } />
    ),
    ...resultSteps.content,
  };
  const summaryOf = (name: StepName) => {
    const warnings = resultSteps.warningsOfStep[name];
    const summary = name === "criteria" && modeToChoose ? messages.chooseModeSummary : stepSummary(name, viewState);
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

  const pinnedActions: Partial<Record<StepName, ReactNode>> = resultSteps.pinnedAction;
  const openStepUsable = openStep !== null && stepNotUsableYet(openStep, viewState) === null;
  const openStepAction = openStep !== null && openStepUsable ? (pinnedActions[openStep] ?? null) : null;
  // A save that failed without field errors leaves the form showing values the service did not store: said whichever step is open.
  const saveFailureText = saveFailureTextOf(form.saveFailure);
  const saveFailureNotice = saveFailureText === null ? null : <SaveFailureNotice text={saveFailureText} onSaveAgain={() => void flushSave()} />;

  // The empty view's "Import" leads to the Inputs step, where each role has its own box: the focus goes to the first one's button.
  useEffect(() => {
    if (addFilesRequest > 0) panel.current?.querySelector<HTMLButtonElement>(".inputs-step .input-add")?.focus();
  }, [addFilesRequest]);
  // Shown in Design only: its "Import" leads to the Inputs step, which Simulate hides.
  const hasNoMeshInputs = files.max_volume.length === 0 && files.test_surfaces.length === 0 && siteInput.sites.length === 0 && siteInput.source !== "sites";
  const emptyViewContent = hasNoMeshInputs && (
    <div className="viewer-empty-state">
      <p>{messages.noInputsYet}</p>
      <button type="button" className="primary-button" onClick={() => { openTheStep("inputs"); setAddFilesRequest((count) => count + 1); }}>
        {messages.addFiles}
      </button>
      <button type="button" className="link-button" onClick={props.onShowProjects}>{messages.orTryAnExample}</button>
    </div>
  );

  // Simulate draws the selected study's values with the geometry the study stands on the plot, Design's layer of that geometry: the
  // maximum volume solid (a ghost for a study on nothing), the envelope see-through; the criteria's test surfaces off, the surroundings
  // on. The sky dome is the selected study's, not Design's (none for sun hours). A study out of date is dimmed with the stamp, and its
  // dome with it; Design's out of date parts are not.
  const simulating = props.mode === "simulate";
  const designResults = resultSteps.viewer.results;
  const studyView = useStudyView({
    studies, active: simulating, runs, northDegrees, editDisabled: runActive,
  });
  const sunStudy = useSunStudy({ active: true, hasWeatherFile });
  const sunTool = { open: sunStudy.settings.open, onToggle: () => sunStudy.change({ open: !sunStudy.settings.open }),
                    panel: <SunPanel sunStudy={sunStudy} /> };
  const simulateView = (theme: ViewportTheme) => (
    <SimulateView studies={studies} criteria={criteria.criteria} storedTestSurfaces={files.test_surfaces} runs={runs}
                  hasSurroundings={hasContext} hasTerrain={files.terrain.length > 0}
                  envelopeBuilt={designResults?.envelope != null} massingBuilt={designResults?.massing != null} hasBaseVolume={baseVolume.geometry !== null} carvingSpacing={carvingSpacing}
                  onStoredFilesChange={() => { void testSurfaceCalls.reloadStoredFiles(); refreshStageStatus(); }} studyView={studyView}
                  theme={theme} notice={inputChangesNotice} />
  );
  const simulateViewer = { overlayContent: simulateView, study: studyView.view, studyOutOfDate: studyView.studyOutOfDate,
                           envelopeSeeThrough: studyView.geometry === "envelope",
                           results: { ...(designResults ?? NO_VIEWER_RESULTS), skyDome: studyView.skyDome }, skyDomeTitle: studyView.skyDomeTitle,
                           dimmedLayers: studyView.studyOutOfDate ? ["sky_dome" as const] : [],
                           missingLayers: studyView.skyDomeMissing ? ["sky_dome" as const] : [],
                           missingLayerNotes: { sky_dome: messages.studySkyDomeNeedsRun } };
  const criteriaOutOfDate = activeCriteria(criteria.criteria).filter((criterion) => criterionStages[criterion.id]?.preprocessing === "out_of_date").length;
  const inspectNotice = (
    <>
      {inputChangesNotice}
      {surfacesChanged && criteriaOutOfDate > 0 && <AnalysisOutOfDateNotice criteria={criteriaOutOfDate} onGoToCarve={props.onGoToCarve} />}
    </>
  );
  // Inspect draws the inputs as Design does, the orientation of the test surfaces in place of the test surfaces, and no results.
  const inspectViewer = {
    overlayContent: <InspectView inspection={inspection} origin={origin} saveDisabledReason={inputsDisabledReason} notice={inspectNotice} />,
    dimmedLayers: [],
  };
  const shownByDefault = simulating ? LAYERS_SHOWN_IN_SIMULATE[studyView.geometry] : inspecting ? LAYERS_SHOWN_IN_INSPECT : LAYERS_SHOWN_IN_STEP[viewStep];

  // The Settings button, drawn in the top bar, and its window.
  const settingsButtonElement = props.settingsButtonSlot != null && createPortal(
    <ProjectSettingsButton summary={projectSettingsSummary(viewState, hasWeatherFile ? weather.location : null)} settingsToFix={settingsToFixIn("project_settings", viewState)} open={settingsOpen}
                           onOpen={() => setSettingsOpen(true)} buttonRef={settingsButton} />,
    props.settingsButtonSlot,
  );
  const settingsDialog = settingsOpen && (
    <ProjectSettingsDialog form={form} stepErrors={sharedForm.form.stepErrors} criterionKeys={criterionKeys} onChange={changeSettings}
                           disabledReason={inputsDisabledReason} inputRoles={inputRolesWithFiles} onClose={closeSettings} contentRef={settingsContent}
                           weather={<div data-setting={WEATHER_SETTING}>{settingsWeatherBox}</div>}
                           carving={(
                             <div className="setting-group" data-setting={CARVING_UPDATES_SETTING}>
                               <Subheading className="setting-group-title">{messages.carvingGroup}</Subheading>
                               <label className="switch-row">
                                 <input type="checkbox" role="switch" className="setting-switch" checked={carvingUpdatesItself}
                                        onChange={(event) => changeCarvingUpdates(event.target.checked)} />
                                 {messages.updateWhenThresholdChanges}
                               </label>
                               <p className="setting-note">{messages.updateWhenThresholdChangesHelp}</p>
                             </div>
                           )}
                           heights={siteInput.source === null ? undefined : (
                             <HeightsSettings fromSites={siteInput.source === "sites"} heights={siteInput.heights} onChange={siteInput.setHeights}
                                              startingMax={siteInput.sites[0]?.height ?? DEFAULT_SITE_HEIGHT} disabledReason={inputsDisabledReason} />
                           )} />
  );

  // The setup of a new project: the Location group as in Settings, the way in, the heights; Start opens the Site step on the way chosen
  const setupWay = usesSites ? "sites" : maxVolumeChosen ? "mesh" : null;
  const closeSetup = () => {
    setSetupOpen(false);
    props.onSetupClosed?.();
  };
  const setupDialog = setupOpen && !settingsOpen && (
    <ProjectSetupDialog way={setupWay} disabledReason={inputsDisabledReason}
                        location={(
                          <SettingsStep form={form} stepErrors={NO_STEP_ERRORS} onChange={changeSettings} disabledReason={inputsDisabledReason}
                                        settingShown={(name) => name === "north_deg"} groupLeads={{ Location: settingsWeatherBox }} />
                        )}
                        onChooseWay={(way) => {
                          if (way === "sites") void siteInput.setSource("sites");
                          else {
                            setMaxVolumeChosen(true);
                            if (usesSites) void siteInput.setSource("mesh");
                          }
                        }}
                        heights={(way) => siteInput.source === null ? null : (
                          <HeightsSettings fromSites={way === "sites"} heights={siteInput.heights} onChange={siteInput.setHeights}
                                           startingMax={siteInput.sites[0]?.height ?? DEFAULT_SITE_HEIGHT} disabledReason={inputsDisabledReason} />
                        )}
                        onSkip={closeSetup}
                        onStart={(way) => {
                          closeSetup();
                          openTheStep("inputs");
                          if (way === "sites" && inputsDisabledReason === null) setSiteTool({ kind: "draw" });
                        }} />
  );

  return (
    <LastRemovalContext.Provider value={lastRemoval}>
    <div className="workspace">
      {settingsButtonElement}
      {settingsDialog}
      {setupDialog}
      {importing !== null && (
        <ImportSitesDialog found={importing.found} names={importedNames(importing.found)} hasTerrain={hasTerrain} busy={importing.busy} onImport={(placeOnTerrain) => { void finishImport(placeOnTerrain); }}
                           onCancel={() => setImporting(null)} />
      )}
      <aside ref={panel} className="workspace-panel" hidden={props.mode !== "design"} onScrollCapture={keepScroll}>
        {inputChangesNotice}
        <StepAccordion steps={steps} openStep={openStep} onOpenStep={openTheStep}
                       pinnedAction={saveFailureNotice === null && openStepAction === null ? null : <>{saveFailureNotice}{openStepAction}</>} />
      </aside>
      <section className="workspace-view">
        <ViewerPane maxVolume={maxVolume} baseVolume={baseVolume.geometry} testSurfaces={testSurfaceGroups} onTestSurfacesShownChange={setTestSurfacesShown}
                    sunStudy={sunStudy.view} sunTool={sunTool}
                    criteria={active.map(({ id, name, colour }) => ({ id, name, colour }))} context={contextGeometry} terrain={terrainMesh.geometry} sunPath={sunPath}
                    hemisphere={sceneSphere} skyDomeChoiceRemembered={props.mode === "design"}
                    maxVolumeAppearance={!inspecting && (simulating ? studyView.geometry !== "none" : STEPS_WITH_SOLID_MAX_VOLUME.includes(viewStep)) ? "solid" : "ghost"}
                    shownByDefault={shownByDefault} northDegrees={northDegrees} framingRequest={framingRequest}
                    centreContent={props.mode === "design" && emptyViewContent} localOrigin={origin} mode={form.mode}
                    analysisCurrent={(ownStages ?? shownStages).preprocessing === "current"} {...resultSteps.viewer} inspect={inspectView}
                    stampAction={props.mode === "design" ? resultSteps.stampAction : null}
                    {...(simulating ? simulateViewer : {})} {...(inspecting ? inspectViewer : {})} sceneTool={pickerTool ?? sceneTool} />
      </section>
    </div>
    </LastRemovalContext.Provider>
  );
}

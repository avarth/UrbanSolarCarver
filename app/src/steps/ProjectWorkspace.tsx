// An open project (UX 4): the step accordion in the left panel and the 3D view beside it. It holds what the steps share: the
// input files, the settings form (the Mode step and the Settings step both change it), the stage status and run summary the
// step summaries read, and the input meshes and sun path the 3D view draws.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import {
  addInput, ApiError, getRunSummary, getStageStatus, getSunPath, inputFileUrl, refusalDetailOf, removeInput, serviceProblemOf,
  type HealthReply, type InputFileInfo, type InputFilesReply, type ModeInfo, type ProjectDetail, type RunSummary, type SunPath,
} from "../api_client/client";
import { listedWithAnd, messages } from "../messages";
import { shownValue, useSettingsForm, type FormState } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS } from "../settings_form/presentation";
import { loadMesh } from "../viewer/loaders";
import { localBounds, localOrigin, type Bounds3, type Point3 } from "../viewer/local_origin";
import type { LayerName } from "../viewer/scene";
import { hemisphere } from "../viewer/sky_dome";
import { ViewerPane } from "../viewer_overlays/ViewerPane";
import { InputBox, InputsStep, type AddInputFiles, type InputRole, type RemoveInputFile } from "./InputsStep";
import { ModeStep } from "./ModeStep";
import { RunAnalysisButton, runAnalysisBlocker, SettingsStep, settingsToFixCount } from "./SettingsStep";
import { StepAccordion, type AccordionStep } from "./StepAccordion";
import {
  plainModeName, STEP_NAMES, stepMark, stepNotUsableYet, stepSummary, type AnalysisPeriod, type PipelineStage, type ProjectViewState,
  type StageState, type StepName,
} from "./step_summaries";

type MeshRole = Exclude<InputRole, "weather">;

const NO_SHIFT: Point3 = [0, 0, 0];
const STEPS_WITH_SOLID_MAX_VOLUME: readonly StepName[] = ["inputs", "mode", "settings"];
// The layers each step shows by default (UX 8.2); the later steps add their result layers.
const LAYERS_SHOWN_IN_STEP: Record<StepName, readonly LayerName[]> = {
  inputs: ["max_volume", "test_surfaces"],
  mode: ["max_volume", "test_surfaces"],
  settings: ["max_volume", "test_surfaces", "sun_path"],
  carving: ["test_surfaces", "sun_path"],
  envelope_and_massing: [],
  export: [],
};
const MODE_WITH_SUN_PATH = "time-based";

interface ProjectWorkspaceProps {
  token: string;
  project: ProjectDetail;
  schema: Record<string, unknown>;
  modes: ModeInfo[];
  warmUpState: HealthReply["warm_up"]["state"] | null;
  /** A run of this project is active; the service then refuses uploads, removals and saves of the settings. */
  runActive: boolean;
  /** A request failed: the app shows the engine-stopped or access-lost overlay when the failure is one of those. */
  onServiceProblem: (error: unknown) => void;
  onShowProjects: () => void;
  onRunAnalysis: () => void;
}

function extensionOf(fileName: string): string {
  return fileName.slice(fileName.lastIndexOf(".") + 1);
}

/** The meshes of several files as one geometry (triangle soup, positions only, as the view draws them). */
function joinedGeometry(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  return mergeGeometries(parts.map((part) => (part.index ? part.toNonIndexed() : part))) ?? new THREE.BufferGeometry();
}

function boundsOf(geometries: (THREE.BufferGeometry | null)[]): Bounds3 | null {
  const box = new THREE.Box3();
  for (const geometry of geometries) {
    if (!geometry) continue;
    geometry.computeBoundingBox();
    box.union(geometry.boundingBox!);
  }
  return box.isEmpty() ? null : [box.min.toArray(), box.max.toArray()];
}

/** The joined mesh of a role's files in local coordinates; reloaded when the files, their contents or the local origin change. */
function useInputGeometry(token: string, project: string, role: MeshRole, files: InputFileInfo[], origin: Point3, revision: number,
                          onLoaded: () => void, onServiceProblem: (error: unknown) => void): THREE.BufferGeometry | null {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);
  const reloadKey = JSON.stringify([files.map((file) => file.name), origin, revision]);
  useEffect(() => {
    if (files.length === 0) {
      setGeometry(null);
      return;
    }
    let stale = false;
    Promise.all(files.map((file) => loadMesh(inputFileUrl(project, role, file.name), token, extensionOf(file.name), origin)))
      .then((parts) => {
        if (stale) return;
        setGeometry(joinedGeometry(parts));
        onLoaded();
      })
      .catch((error) => {
        // A refused request may be a lost token; a file the service accepted that the view cannot read stays undrawn.
        if (!stale && error instanceof ApiError) onServiceProblem(error);
      });
    return () => {
      stale = true;
    };
  }, [reloadKey]);
  return geometry;
}

/** The analysis period the form holds, when the mode reads one and every part of it is set. */
function analysisPeriodOf(form: FormState, modeReadsPeriod: boolean): AnalysisPeriod | null {
  const values = ANALYSIS_PERIOD_FIELDS.map((name) => shownValue(form, name));
  if (!modeReadsPeriod || !values.every((value) => typeof value === "number")) return null;
  const [startMonth, startDay, startHour, endMonth, endDay, endHour] = values as number[];
  return { startMonth, startDay, startHour, endMonth, endDay, endHour };
}

/** Why a request about the inputs failed, in words for the file box. */
function inputProblemText(error: unknown, fileName: string): string {
  if (error instanceof ApiError && error.status === 409) return messages.runInProgress;
  const detail = refusalDetailOf(error) ?? String(error);
  return detail.includes(fileName) ? detail : messages.fileProblem(fileName, detail);
}

export function ProjectWorkspace(props: ProjectWorkspaceProps) {
  const { token, project, modes, warmUpState, runActive, onServiceProblem } = props;
  const formStart = useMemo(() => ({ schema: props.schema, modes, settings: project.settings, gridPlan: null }), []);
  const { form, dispatch, flushSave } = useSettingsForm(token, project.name, formStart);
  const [files, setFiles] = useState<Record<InputRole, InputFileInfo[]>>({
    max_volume: project.inputs.max_volume ?? [], test_surfaces: project.inputs.test_surfaces ?? [], weather: project.inputs.weather ?? [],
  });
  const [joinedBounds, setJoinedBounds] = useState<Bounds3 | null>(project.joined_bounds as Bounds3 | null);
  const [weatherLocation, setWeatherLocation] = useState(project.weather_location);
  const [inputRevisions, setInputRevisions] = useState<Record<MeshRole, number>>({ max_volume: 0, test_surfaces: 0 });
  const [stages, setStages] = useState(project.stage_status.stages);
  const [runSummary, setRunSummary] = useState<RunSummary | null>(null);
  const [openStep, setOpenStep] = useState<StepName | null>("inputs");
  const [viewStep, setViewStep] = useState<StepName>("inputs");     // the step whose layers the view shows: the last one opened
  const [sunPath, setSunPath] = useState<SunPath | null>(null);
  const [framingRequest, setFramingRequest] = useState(0);
  const emptyStatePicker = useRef<HTMLInputElement>(null);
  const [emptyStateProblems, setEmptyStateProblems] = useState<string[]>([]);

  const modeInfo = modes.find((candidate) => candidate.name === form.mode);
  const modeNeedsWeatherFile = modeInfo?.needs_epw ?? false;
  const hasWeatherFile = files.weather.length > 0;
  const origin = joinedBounds === null ? NO_SHIFT : localOrigin(joinedBounds);
  const frameAllInputs = () => setFramingRequest((count) => count + 1);
  const maxVolume = useInputGeometry(token, project.name, "max_volume", files.max_volume, origin, inputRevisions.max_volume, frameAllInputs, onServiceProblem);
  const testSurfaces = useInputGeometry(token, project.name, "test_surfaces", files.test_surfaces, origin, inputRevisions.test_surfaces, frameAllInputs,
                                        onServiceProblem);
  const inputsBounds = boundsOf([maxVolume, testSurfaces]);
  const sunPathSphere = useMemo(() => (joinedBounds === null ? null : hemisphere(localBounds(joinedBounds, localOrigin(joinedBounds)))), [joinedBounds]);
  const northDegrees = Number(shownValue(form, "north_deg") ?? 0);

  const refreshStageStatus = () => {
    getStageStatus(token, project.name).then((reply) => setStages(reply.stages)).catch(onServiceProblem);
  };

  useEffect(() => {
    if (stages.thresholding === "missing" && stages.massing === "missing") return;
    getRunSummary(token, project.name).then(setRunSummary).catch(onServiceProblem);
  }, []);

  // A save changes what the stages were run with; its reply is in once no save waits.
  useEffect(() => {
    if (form.changeCount > 0 && !form.pendingSave) refreshStageStatus();
  }, [form.pendingSave]);

  useEffect(() => {
    if (form.saveFailure !== null && serviceProblemOf(form.saveFailure) !== "other") onServiceProblem(form.saveFailure);
  }, [form.saveFailure]);

  // The sun path of the stored period (UX 8.2), as soon as the weather file and the period are there, before any run.
  const sunPathKey = JSON.stringify([form.mode, ANALYSIS_PERIOD_FIELDS.map((name) => shownValue(form, name)), northDegrees, hasWeatherFile]);
  const sunPathWanted = form.mode === MODE_WITH_SUN_PATH && hasWeatherFile && analysisPeriodOf(form, true) !== null;
  const sunPathRequestKey = useRef<string | null>(null);      // the period last asked for; only its reply is kept
  useEffect(() => {
    if (!sunPathWanted) {
      sunPathRequestKey.current = null;
      setSunPath(null);
      return;
    }
    // The service reads the stored settings: wait for the save, and keep the last path while the form holds a refused change.
    if (form.pendingSave || settingsToFixCount(form) > 0 || sunPathRequestKey.current === sunPathKey) return;
    const requestKey = sunPathKey;
    sunPathRequestKey.current = requestKey;
    getSunPath(token, project.name).then((reply) => { if (sunPathRequestKey.current === requestKey) setSunPath(reply); }).catch((error) => {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    });
  }, [sunPathKey, sunPathWanted, form.pendingSave]);

  const inputsDisabledReason = runActive ? messages.runInProgress : null;

  const applyFilesReply = (reply: InputFilesReply) => {
    setFiles((current) => ({ ...current, [reply.role]: reply.files }));
    setJoinedBounds(reply.joined_bounds as Bounds3 | null);
    setWeatherLocation(reply.weather_location);
    if (reply.role !== "weather") setInputRevisions((current) => ({ ...current, [reply.role]: current[reply.role as MeshRole] + 1 }));
  };
  const afterInputsChanged = (role: InputRole) => {
    refreshStageStatus();
    // The grid follows the maximum volume; a save of the unchanged settings brings its new plan.
    if (role === "max_volume") dispatch({ type: "values_changed", values: {} });
  };

  const addFiles: AddInputFiles = async (role, chosenFiles) => {
    const problems: string[] = [];
    for (const file of chosenFiles) {
      try {
        applyFilesReply(await addInput(token, project.name, role, file));
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

  const removeFile: RemoveInputFile = async (role, fileName) => {
    try {
      applyFilesReply(await removeInput(token, project.name, role, fileName));
      afterInputsChanged(role);
      return null;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return inputProblemText(error, fileName);
    }
  };

  const openTheStep = (step: StepName | null) => {
    setOpenStep(step);
    if (step !== null) setViewStep(step);
  };

  const viewState: ProjectViewState = {
    maxVolumeFiles: files.max_volume.length,
    testSurfaceFiles: files.test_surfaces.length,
    hasWeatherFile,
    mode: form.mode,
    analysisPeriod: analysisPeriodOf(form, modeInfo?.needs_period ?? false),
    voxelSize: Number(shownValue(form, "voxel_size")),
    settingsToFix: settingsToFixCount(form),
    stages: stages as Record<PipelineStage, StageState>,
    keptPercent: runSummary?.carving?.retention_pct ?? null,
    totalFloorArea: runSummary?.massing?.total_floor_area_m2 ?? null,
    storeys: runSummary?.massing?.storeys_built ?? null,
  };

  const weatherHint = messages.weatherNeededFor(listedWithAnd(modes.filter((mode) => mode.needs_epw).map((mode) => plainModeName(mode.name))));
  const weatherBox = (
    <InputBox role="weather" files={files.weather} weatherLocation={weatherLocation} weatherHint={weatherHint} onAddFiles={addFiles}
              onRemoveFile={removeFile} disabledReason={inputsDisabledReason} />
  );
  const stepContent: Record<StepName, ReactNode> = {
    inputs: (
      <InputsStep files={files} weatherLocation={weatherLocation} weatherHint={weatherHint} inputsBounds={inputsBounds} onAddFiles={addFiles}
                  onRemoveFile={removeFile} disabledReason={inputsDisabledReason} />
    ),
    mode: (
      <ModeStep mode={form.mode} onChoose={(mode) => dispatch({ type: "mode_chosen", mode })} disabledReason={inputsDisabledReason}
                weatherDropZone={modeNeedsWeatherFile && !hasWeatherFile ? weatherBox : null} />
    ),
    settings: <SettingsStep form={form} onChange={(values) => dispatch({ type: "values_changed", values })} disabledReason={inputsDisabledReason} />,
    carving: null,      // the carving, envelope and export steps come with the run loop
    envelope_and_massing: null,
    export: null,
  };
  const steps: AccordionStep[] = STEP_NAMES.map((name) => ({
    name,
    title: messages.stepTitles[name],
    summary: stepSummary(name, viewState),
    mark: stepMark(name, viewState),
    notUsableYet: stepNotUsableYet(name, viewState),
    content: stepContent[name],
  }));

  const runBlocker = runAnalysisBlocker({
    runActive, maxVolumeFiles: viewState.maxVolumeFiles, testSurfaceFiles: viewState.testSurfaceFiles, modeNeedsWeatherFile, hasWeatherFile,
    form, warmUpState,
  });
  const runAnalysis = async () => {
    await flushSave();      // the run reads the stored settings, so a change still waiting is saved first
    props.onRunAnalysis();
  };

  const hasNoMeshInputs = files.max_volume.length === 0 && files.test_surfaces.length === 0;
  const addFromEmptyView = async (chosenFiles: File[]) => {
    openTheStep("inputs");
    setEmptyStateProblems(await addFiles("max_volume", chosenFiles));
  };
  const emptyViewContent = hasNoMeshInputs && (
    <div className="viewer-empty-state">
      <p>{messages.noInputsYet}</p>
      <input ref={emptyStatePicker} type="file" hidden multiple accept=".ply,.obj,.stl,.glb"
             onChange={(event) => { void addFromEmptyView(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
      <button type="button" className="primary-button" disabled={inputsDisabledReason !== null} onClick={() => emptyStatePicker.current?.click()}>
        {messages.addFiles}
      </button>
      <button type="button" className="link-button" onClick={props.onShowProjects}>{messages.orTryAnExample}</button>
      {emptyStateProblems.map((problem) => <p key={problem} className="setting-error">{problem}</p>)}
    </div>
  );

  return (
    <div className="workspace">
      <aside className="workspace-panel">
        <StepAccordion steps={steps} openStep={openStep} onOpenStep={openTheStep}
                       pinnedAction={openStep === "settings" ? <RunAnalysisButton blocker={runBlocker} onRunAnalysis={() => void runAnalysis()} /> : null} />
      </aside>
      <section className="workspace-view">
        <ViewerPane maxVolume={maxVolume} testSurfaces={testSurfaces} sunPath={sunPath}
                    hemisphere={sunPathSphere}
                    maxVolumeAppearance={STEPS_WITH_SOLID_MAX_VOLUME.includes(viewStep) ? "solid" : "ghost"}
                    shownByDefault={LAYERS_SHOWN_IN_STEP[viewStep]} northDegrees={northDegrees} framingRequest={framingRequest}
                    centreContent={emptyViewContent} />
      </section>
    </div>
  );
}

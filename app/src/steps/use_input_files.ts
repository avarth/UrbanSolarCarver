// The input files of an open project (ProjectWorkspace): the lists the service keeps for each role, the weather file's location and
// latitude and the notice about a new weather file, the local origin the meshes are drawn around, the meshes themselves
// (input_meshes.ts), and the requests that add or remove a file. The uploads and removals under way are followed, so the app can
// wait for them before a rename, reset or delete of the project.
import { useRef, useState } from "react";
import {
  addInput, getInputFiles, getProject, removeInput, serviceProblemOf, type InputFileInfo, type InputFilesReply, type ModeInfo, type ProjectDetail,
} from "../api_client/client";
import { hemisphereOfLatitude, seasonsOfLatitude, type Hemisphere } from "../settings_form/analysis_period";
import type { FormState, SettingsForm } from "../settings_form/form_state";
import { localOrigin, type Bounds3, type Point3 } from "../viewer/local_origin";
import { useInputGeometry, type InputGeometry, type MeshRole } from "./input_meshes";
import { inputProblemText, type AddInputFiles, type InputRole, type RemoveInputFile } from "./InputsStep";
import { analysisPeriodOf } from "./sun_path_request";
import type { WeatherFileChange } from "./weather_change_notice";

const NO_SHIFT: Point3 = [0, 0, 0];

export interface InputFilesContext {
  token: string;
  project: ProjectDetail;
  modes: ModeInfo[];
  /** The form the steps show, read when a weather file is added. */
  currentForm: () => FormState;
  /** The shared settings' form: a save of its unchanged settings brings the grid plan that follows a new maximum volume. */
  sharedForm: Pick<SettingsForm, "dispatch">;
  refreshStageStatus: () => void;
  /** Told whenever a role's meshes are loaded: the view frames the inputs. */
  onInputsLoaded: () => void;
  onServiceProblem: (error: unknown) => void;
}

export interface InputFiles {
  files: Record<InputRole, InputFileInfo[]>;
  joinedBounds: Bounds3 | null;
  /** The corner the meshes are drawn around; it follows the maximum volume only. */
  origin: Point3;
  weather: {
    location: string | null;
    latitude: number | null;
    /** Goes up whenever the weather file is added, replaced or removed: the service keeps one name for it, so its file list may not change. */
    fileRevision: number;
    /**
     * The weather file added or replaced last in this session, for the notice over the criterion's settings; null before one, and
     * once it is dismissed.
     */
    fileChange: WeatherFileChange | null;
    setFileChange: (change: WeatherFileChange | null) => void;
  };
  /** Goes up for a mesh role whenever its files change, so their meshes are fetched again. */
  inputRevisions: Record<MeshRole, number>;
  addFiles: AddInputFiles;
  removeFile: RemoveInputFile;
  /** The stored test surface files, as the service lists them after a change by a criterion: the 3D view loads them again. */
  storeTestSurfaceFiles: (stored: InputFileInfo[]) => void;
  /**
   * Asks for the files of *roles* again after the service built files changed in the project folder into the project: their
   * lists (triangle counts) and meshes, and for a maximum volume or weather file the bounds, the place and the latitude.
   */
  reloadRoles: (roles: string[]) => void;
  /** Follows a request until its reply is in (the app waits for it before a rename, reset or delete of the project). */
  followedInputChange: <Reply>(change: Promise<Reply>) => Promise<Reply>;
  inputChangesUnderWay: { current: Set<Promise<unknown>> };
  /** Resolves once the uploads and removals of input files under way have ended. */
  waitForInputChanges: () => Promise<void>;
  meshes: Record<MeshRole, InputGeometry>;
}

export function useInputFiles(context: InputFilesContext): InputFiles {
  const { token, project, modes, currentForm, sharedForm, refreshStageStatus, onInputsLoaded, onServiceProblem } = context;
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
  const [files, setFiles] = useState<Record<InputRole, InputFileInfo[]>>({
    max_volume: project.inputs.max_volume ?? [], test_surfaces: project.inputs.test_surfaces ?? [], context: project.inputs.context ?? [],
    terrain: project.inputs.terrain ?? [], weather: project.inputs.weather ?? [],
  });
  const [joinedBounds, setJoinedBounds] = useState<Bounds3 | null>(project.joined_bounds as Bounds3 | null);
  const [weatherLocation, setWeatherLocation] = useState(project.weather_location);
  const [weatherLatitude, setWeatherLatitude] = useState(project.weather_latitude);
  const [inputRevisions, setInputRevisions] = useState<Record<MeshRole, number>>({ max_volume: 0, test_surfaces: 0, context: 0, terrain: 0 });
  const [weatherFileRevision, setWeatherFileRevision] = useState(0);
  const weatherFileRevisionNow = useRef(0);
  const [weatherFileChange, setWeatherFileChange] = useState<WeatherFileChange | null>(null);
  // The hemisphere of the last weather file the project had with seasons, kept across a removal and across a file within the tropics
  // or without a latitude: what the period was likely chosen for.
  const hemisphereOfLastWeatherFile = useRef<Hemisphere>(hemisphereOfLatitude(project.weather_latitude));

  const origin = joinedBounds === null ? NO_SHIFT : localOrigin(joinedBounds);
  const maxVolume = useInputGeometry(token, project.name, "max_volume", files.max_volume, origin, inputRevisions.max_volume, onInputsLoaded, onServiceProblem);
  const testSurfaces = useInputGeometry(token, project.name, "test_surfaces", files.test_surfaces, origin, inputRevisions.test_surfaces, onInputsLoaded,
                                        onServiceProblem);
  const contextMesh = useInputGeometry(token, project.name, "context", files.context, origin, inputRevisions.context, onInputsLoaded, onServiceProblem);
  const terrain = useInputGeometry(token, project.name, "terrain", files.terrain, origin, inputRevisions.terrain, onInputsLoaded, onServiceProblem);

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
  const storeTestSurfaceFiles = (stored: InputFileInfo[]) => {
    setFiles((current) => ({ ...current, test_surfaces: stored }));
    setInputRevisions((current) => ({ ...current, test_surfaces: current.test_surfaces + 1 }));
  };
  const reloadRoles = (roles: string[]) => {
    for (const role of roles) {
      if (role === "weather") {
        weatherFileRevisionNow.current += 1;
        setWeatherFileRevision(weatherFileRevisionNow.current);
        continue;
      }
      getInputFiles(token, project.name, role).then((stored) => {
        setFiles((current) => ({ ...current, [role]: stored }));
        setInputRevisions((current) => ({ ...current, [role]: current[role as MeshRole] + 1 }));
      }).catch(onServiceProblem);
      if (role === "max_volume") sharedForm.dispatch({ type: "values_changed", values: {} });     // the new grid plan, as after an upload
    }
    // The bounds of the maximum volume and the weather file's place are in the project's detail only.
    if (roles.includes("weather") || roles.includes("max_volume")) {
      getProject(token, project.name).then((detail) => {
        setJoinedBounds(detail.joined_bounds as Bounds3 | null);
        setWeatherLocation(detail.weather_location);
        setWeatherLatitude(detail.weather_latitude);
      }).catch(onServiceProblem);
    }
  };

  return {
    files, joinedBounds, origin,
    weather: { location: weatherLocation, latitude: weatherLatitude, fileRevision: weatherFileRevision, fileChange: weatherFileChange,
               setFileChange: setWeatherFileChange },
    inputRevisions, addFiles, removeFile, storeTestSurfaceFiles, reloadRoles, followedInputChange, inputChangesUnderWay, waitForInputChanges,
    meshes: { max_volume: maxVolume, test_surfaces: testSurfaces, context: contextMesh, terrain },
  };
}

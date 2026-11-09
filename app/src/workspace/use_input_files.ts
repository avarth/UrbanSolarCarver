// The input files of an open project (ProjectWorkspace): the lists the service keeps for each role, the weather file's location and
// latitude and the notice about a new weather file, the local origin the meshes are drawn around, the meshes themselves
// (input_meshes.ts), and the requests that add or remove a file. The uploads and removals under way are followed, so the app can
// wait for them before a rename, reset or delete of the project.
import { useEffect, useRef, useState } from "react";
import {
  addInput, failureTextOf, getInputFiles, getProject, baseVolumeUrl, getSites, joinedMaxVolumeUrl, removeInput, reportServiceProblem, saveSites, setHeights as storeHeights, setMaxVolumeSource,
  type InputFileInfo, type InputFilesReply, type MaxVolumeSource, type ModeInfo, type ProjectDetail, type SitesReply,
} from "../api_client/client";
import { NO_HEIGHTS, baseHeightOf, heightsOf, type Heights, type Site } from "../sites/site_geometry";
import { useProjectSession } from "../api_client/project_session";
import { hemisphereOfLatitude, seasonsOfLatitude, type Hemisphere } from "../settings_form/analysis_period";
import type { FormState, SettingsForm } from "../settings_form/form_state";
import { localOrigin, type Bounds3, type Point3 } from "../viewer/local_origin";
import { useInputGeometry, type InputGeometry, type MeshRole } from "../steps/input_meshes";
import { inputProblemText, type AddInputFiles, type InputRole, type RemoveInputFile } from "../common/InputBox";
import { analysisPeriodOf } from "../steps/sun_path_request";
import type { WeatherFileChange } from "../settings_form/weather_change_notice";

const NO_SHIFT: Point3 = [0, 0, 0];

export interface InputFilesContext {
  project: ProjectDetail;
  modes: ModeInfo[];
  /** The form the steps show, read when a weather file is added. */
  currentForm: () => FormState;
  /** The shared settings' form: a save of its unchanged settings brings the grid plan that follows a new maximum volume. */
  sharedForm: Pick<SettingsForm, "dispatch">;
  refreshStageStatus: () => void;
  /** Told whenever a role's meshes are loaded: the view frames the inputs. */
  onInputsLoaded: () => void;
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
  /** The part of the maximum volume below the base heights (none without one): the view draws it solid and the rest dotted. */
  baseVolume: InputGeometry;
  sites: SitesInput;
}

/** The sites of the project and what its maximum volume is made from (design/site-input.md). */
export interface SitesInput {
  /** Null until the service has said. */
  source: MaxVolumeSource | null;
  sites: Site[];
  /** Store the whole list; resolves to null once saved, or the service's reason it was refused (the sites shown go back). */
  save: (sites: Site[]) => Promise<string | null>;
  setSource: (source: MaxVolumeSource) => Promise<void>;
  /** The max height and base height of the sites (design/base-height.md). */
  heights: Heights;
  /** Store the heights; resolves to null once saved, or the service's reason it refused them (the heights shown go back). */
  setHeights: (heights: Heights) => Promise<string | null>;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** The service's reason the last change was refused, until the next change. */
  refusal: string | null;
}

const UNDO_DEPTH = 50;
const MAX_VOLUME_FILE = [{ name: "max_volume.ply", triangle_count: 0 }];
const BASE_VOLUME_FILE = [{ name: "base_volume.ply", triangle_count: 0 }];

export function useInputFiles(context: InputFilesContext): InputFiles {
  const { token, onServiceProblem } = useProjectSession();
  const { project, modes, currentForm, sharedForm, refreshStageStatus, onInputsLoaded } = context;
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

  const [source, setSourceState] = useState<MaxVolumeSource | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [heights, setHeightsState] = useState<Heights>(NO_HEIGHTS);
  const [undoStack, setUndoStack] = useState<Site[][]>([]);
  const [redoStack, setRedoStack] = useState<Site[][]>([]);
  const [refusal, setRefusal] = useState<string | null>(null);
  useEffect(() => {
    let stale = false;
    getSites(token, project.name).then((reply) => {
      if (stale) return;
      setSourceState(reply.source);
      setSites(reply.sites as Site[]);
      setHeightsState(heightsOf(reply.heights));
    }).catch((error) => {
      // Lost access is reported; another failure leaves the project on its mesh files, as before sites
      if (!stale && !reportServiceProblem(error, onServiceProblem)) setSourceState("mesh");
    });
    return () => {
      stale = true;
    };
  }, [token, project.name, onServiceProblem]);

  const origin = joinedBounds === null ? NO_SHIFT : localOrigin(joinedBounds);
  const fromSites = source === "sites";
  const maxVolume = useInputGeometry("max_volume", fromSites ? (joinedBounds === null ? [] : MAX_VOLUME_FILE) : files.max_volume, origin,
                                     inputRevisions.max_volume, onInputsLoaded, fromSites ? () => joinedMaxVolumeUrl(project.name) : undefined);
  const hasBase = source === "sites" ? sites.some((site) => baseHeightOf(site, heights) !== null)
    : source === "mesh" && (heights.base.value ?? 0) > 0 && files.max_volume.length > 0;     // 0 is no lower limit, as none is
  const baseVolume = useInputGeometry("max_volume", hasBase ? BASE_VOLUME_FILE : [], origin, inputRevisions.max_volume, () => {},
                                      () => baseVolumeUrl(project.name));
  const testSurfaces = useInputGeometry("test_surfaces", files.test_surfaces, origin, inputRevisions.test_surfaces, onInputsLoaded);
  const contextMesh = useInputGeometry("context", files.context, origin, inputRevisions.context, onInputsLoaded);
  const terrain = useInputGeometry("terrain", files.terrain, origin, inputRevisions.terrain, onInputsLoaded);

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
        if (reportServiceProblem(error, onServiceProblem)) {
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
      reportServiceProblem(error, onServiceProblem);
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

  const applySitesReply = (reply: SitesReply) => {
    setSourceState(reply.source);
    setSites(reply.sites as Site[]);
    setHeightsState(heightsOf(reply.heights));
    setJoinedBounds(reply.joined_bounds as Bounds3 | null);
    setInputRevisions((current) => ({ ...current, max_volume: current.max_volume + 1 }));
  };
  // A change of the sites: shown at once, then stored; a refusal brings back what was shown before
  const storeSites = async (next: Site[], previous: Site[]): Promise<string | null> => {
    setSites(next);
    setRefusal(null);
    try {
      applySitesReply(await followedInputChange(saveSites(token, project.name, next)));
      if (source === "sites") afterInputsChanged("max_volume");
      return null;
    } catch (error) {
      if (reportServiceProblem(error, onServiceProblem)) return null;
      setSites(previous);
      const reason = failureTextOf(error);
      setRefusal(reason);
      return reason;
    }
  };
  const saveSitesUndoable = async (next: Site[]) => {
    const previous = sites;
    const refused = await storeSites(next, previous);
    if (refused === null) {
      setUndoStack((stack) => [...stack.slice(-(UNDO_DEPTH - 1)), previous]);
      setRedoStack([]);
    }
    return refused;
  };
  const undo = () => {
    if (!undoStack.length) return;
    const previous = undoStack[undoStack.length - 1];
    const current = sites;
    setUndoStack((stack) => stack.slice(0, -1));
    setRedoStack((stack) => [...stack, current]);
    void storeSites(previous, current);
  };
  const redo = () => {
    if (!redoStack.length) return;
    const next = redoStack[redoStack.length - 1];
    const current = sites;
    setRedoStack((stack) => stack.slice(0, -1));
    setUndoStack((stack) => [...stack, current]);
    void storeSites(next, current);
  };
  const setSource = async (next: MaxVolumeSource) => {
    try {
      applySitesReply(await followedInputChange(setMaxVolumeSource(token, project.name, next)));
      afterInputsChanged("max_volume");
    } catch (error) {
      reportServiceProblem(error, onServiceProblem);
    }
  };

  const setHeights = async (next: Heights): Promise<string | null> => {
    const previous = heights;
    setHeightsState(next);
    try {
      applySitesReply(await followedInputChange(storeHeights(token, project.name, next)));
      afterInputsChanged("max_volume");
      return null;
    } catch (error) {
      if (reportServiceProblem(error, onServiceProblem)) return null;
      setHeightsState(previous);
      return failureTextOf(error);
    }
  };

  return {
    sites: { source, sites, save: saveSitesUndoable, setSource, heights, setHeights, undo, redo, canUndo: undoStack.length > 0, canRedo: redoStack.length > 0, refusal },
    files, joinedBounds, origin,
    weather: { location: weatherLocation, latitude: weatherLatitude, fileRevision: weatherFileRevision, fileChange: weatherFileChange,
               setFileChange: setWeatherFileChange },
    inputRevisions, addFiles, removeFile, storeTestSurfaceFiles, reloadRoles, followedInputChange, inputChangesUnderWay, waitForInputChanges,
    meshes: { max_volume: maxVolume, test_surfaces: testSurfaces, context: contextMesh, terrain }, baseVolume,
  };
}

// The inspection of the open project's input files (Inspect, inspect design sections 3, 5 and 6): the summary of each mesh file, the
// geometry of each test surface file with the surface of each triangle, the file the Files panel selects, flip mode and the arrows,
// and the turns staged per file until Save. The inspection is read, with the geometries of every test surface file, when Inspect
// opens and after each save or restore. Save sends one request per file with all its turns; the turns stay drawn until the file's
// new geometry is in, so the view does not show the old orientation in between. A refused request leaves the turns as they were and
// says why (problem). useInspectView gives the view what it draws, kept the same between renders that change none of it (the view
// draws the layer again whenever its files change).
import { useEffect, useMemo, useRef, useState } from "react";
import {
  failureTextOf, getInspection, getInspectionGeometry, restoreOriginal, serviceProblemOf, turnSurfaces, type InspectedFile, type InspectReply,
} from "../api_client/client";
import type { InspectLayerFile } from "../viewer/layers";
import { toLocal, type Point3 } from "../viewer/local_origin";
import type { InspectView } from "../viewer_overlays/ViewerPane";
import { decodeInspectGeometry, localCorners, localSurfaces, type InspectGeometry } from "./inspect_geometry_decoder";

export const TEST_SURFACES_ROLE = "test_surfaces";

/** A file of the inspection: its role and its name (a name may be used in two roles). */
interface FileKey {
  role: string;
  fileName: string;
}

export interface InspectionHook {
  /** The last inspection read; null until the first one is in. */
  reply: InspectReply | null;
  /** The geometry of each test surface file, by file name, in the order of the inspection. */
  geometries: ReadonlyMap<string, InspectGeometry>;
  /** The file selected in the Files panel; null when none is. */
  selected: InspectedFile | null;
  select: (file: InspectedFile | null) => void;
  /** Each new selection from the panel asks the view to frame the file: the number of those asks. */
  frameRequest: number;
  /** In flip mode a click on a surface of the selected test surface file turns it. */
  flipMode: boolean;
  setFlipMode: (on: boolean) => void;
  arrows: boolean;
  setArrows: (on: boolean) => void;
  /** The surfaces turned and not saved, by file name; a file without turns is not listed. */
  turned: ReadonlyMap<string, ReadonlySet<number>>;
  /** A click on a surface in the view: in flip mode on the selected file it turns the surface, otherwise it selects its file. */
  clickSurface: (fileName: string, surface: number) => void;
  toggleSurface: (fileName: string, surface: number) => void;
  /** Turns every surface of the file once more (a whole export the wrong way round). */
  flipAll: (fileName: string) => void;
  discard: (fileName: string) => void;
  discardAll: () => void;
  /** Writes the file's turns; resolves with why it could not, or null once written (or with nothing to write). */
  save: (fileName: string) => Promise<string | null>;
  /** Writes the turns of every file, one after another; resolves with the first reason one could not be written, or null. */
  saveAll: () => Promise<string | null>;
  /** Puts the file's kept original back; resolves with why it could not, or null. */
  restore: (fileName: string) => Promise<string | null>;
  /** Some file has turns not saved. */
  unsaved: boolean;
  /** A save or restore is under way: the panel's buttons that send one wait. */
  busy: boolean;
  /** Why the inspection could not be read, or the last save or restore failed; null otherwise. */
  problem: string | null;
}

interface InspectionState {
  reply: InspectReply | null;
  geometries: ReadonlyMap<string, InspectGeometry>;
  selectedKey: FileKey | null;
  frameRequest: number;
  flipMode: boolean;
  arrows: boolean;
  turned: ReadonlyMap<string, ReadonlySet<number>>;
  busy: boolean;
  problem: string | null;
}

const NO_GEOMETRIES: ReadonlyMap<string, InspectGeometry> = new Map();
const NO_TURNS: ReadonlyMap<string, ReadonlySet<number>> = new Map();

const isKeyOf = (key: FileKey | null, file: InspectedFile) => key !== null && key.role === file.role && key.fileName === file.file_name;

interface InspectionOptions {
  token: string;
  project: string;
  /** Inspect is shown: the inspection is read each time it becomes so. */
  active: boolean;
  /** A save or restore changed a stored file (the stage status and the stored files are asked for again). */
  onSaved: () => void;
  /** Told a failed request that lost the token or the engine (the app's overlay says it). */
  onServiceProblem?: (error: unknown) => void;
}

export function useInspection({ token, project, active, onSaved, onServiceProblem = () => {} }: InspectionOptions): InspectionHook {
  const [state, setState] = useState<InspectionState>({
    reply: null, geometries: NO_GEOMETRIES, selectedKey: null, frameRequest: 0, flipMode: false, arrows: false, turned: NO_TURNS, busy: false, problem: null,
  });
  // The latest state, read by calls that wait for a reply while another change arrives.
  const latest = useRef(state);
  const commit = (next: Partial<InspectionState>) => {
    latest.current = { ...latest.current, ...next };
    setState(latest.current);
  };
  // Only the last read asked for is shown: an earlier one that answers later has older files.
  const readsAskedFor = useRef(0);

  const fileOf = (key: FileKey | null) => latest.current.reply?.files.find((file) => isKeyOf(key, file)) ?? null;
  const testSurfaceFile = (fileName: string) => fileOf({ role: TEST_SURFACES_ROLE, fileName });
  const failed = (error: unknown) => {
    if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    return failureTextOf(error);
  };

  const refresh = async () => {
    const read = ++readsAskedFor.current;
    try {
      const reply = await getInspection(token, project);
      const readable = reply.files.filter((file) => file.role === TEST_SURFACES_ROLE && file.problem == null);
      const buffers = await Promise.all(readable.map((file) => getInspectionGeometry(token, project, file.file_name)));
      if (read !== readsAskedFor.current) return;
      const { selectedKey, flipMode, turned } = latest.current;
      const kept = reply.files.some((file) => isKeyOf(selectedKey, file));
      const names = new Set(readable.map((file) => file.file_name));
      commit({
        reply, problem: null,
        geometries: new Map(readable.map((file, index) => [file.file_name, decodeInspectGeometry(buffers[index])])),
        selectedKey: kept ? selectedKey : null, flipMode: kept && flipMode,
        turned: new Map([...turned].filter(([fileName]) => names.has(fileName))),
      });
    } catch (error) {
      if (read !== readsAskedFor.current) return;
      commit({ problem: failed(error) });
    }
  };

  useEffect(() => {
    if (active) void refresh();
    else if (latest.current.flipMode) commit({ flipMode: false });
  }, [active]);

  const setTurns = (fileName: string, surfaces: ReadonlySet<number>) => {
    const turned = new Map(latest.current.turned);
    if (surfaces.size === 0) turned.delete(fileName);
    else turned.set(fileName, surfaces);
    commit({ turned });
  };
  const toggled = (surfaces: ReadonlySet<number>, surface: number) => {
    const next = new Set(surfaces);
    if (!next.delete(surface)) next.add(surface);
    return next;
  };
  const toggleSurface = (fileName: string, surface: number) => {
    if (!testSurfaceFile(fileName)?.flippable) return;
    setTurns(fileName, toggled(latest.current.turned.get(fileName) ?? new Set(), surface));
  };
  const select = (file: InspectedFile | null, frame = true) => {
    const { selectedKey, flipMode, frameRequest } = latest.current;
    const same = file !== null && isKeyOf(selectedKey, file);
    commit({
      selectedKey: file === null ? null : { role: file.role, fileName: file.file_name },
      flipMode: same && flipMode,
      frameRequest: frame && file !== null ? frameRequest + 1 : frameRequest,
    });
  };

  /** Sends *request* for the file; once it is answered the inspection is read again, then the file's turns are dropped. */
  const change = async (fileName: string, request: () => Promise<InspectedFile>): Promise<string | null> => {
    commit({ busy: true, problem: null });
    try {
      await request();
    } catch (error) {
      const problem = failed(error);
      commit({ busy: false, problem });
      return problem;
    }
    onSaved();
    try {
      await refresh();
    } finally {
      setTurns(fileName, new Set());
      commit({ busy: false });
    }
    return null;
  };
  const save = (fileName: string) => {
    const surfaces = [...(latest.current.turned.get(fileName) ?? [])].sort((first, second) => first - second);
    if (surfaces.length === 0) return Promise.resolve(null);
    return change(fileName, () => turnSurfaces(token, project, fileName, surfaces));
  };

  const { reply, geometries, selectedKey, frameRequest, flipMode, arrows, turned, busy, problem } = state;
  return {
    reply, geometries, frameRequest, flipMode, arrows, turned, busy, problem,
    selected: reply?.files.find((file) => isKeyOf(selectedKey, file)) ?? null,
    select: (file) => select(file),
    setFlipMode: (on) => commit({ flipMode: on && (fileOf(latest.current.selectedKey)?.flippable ?? false) }),
    setArrows: (on) => commit({ arrows: on }),
    clickSurface: (fileName, surface) => {
      const { selectedKey: key, flipMode: flipping } = latest.current;
      if (flipping && key?.role === TEST_SURFACES_ROLE && key.fileName === fileName) toggleSurface(fileName, surface);
      else select(testSurfaceFile(fileName), false);
    },
    toggleSurface,
    flipAll: (fileName) => {
      const count = latest.current.geometries.get(fileName)?.header.surface_count ?? testSurfaceFile(fileName)?.surface_count ?? 0;
      if (!testSurfaceFile(fileName)?.flippable) return;
      let surfaces = latest.current.turned.get(fileName) ?? new Set<number>();
      for (let surface = 0; surface < count; surface++) surfaces = toggled(surfaces, surface);
      setTurns(fileName, surfaces);
    },
    discard: (fileName) => setTurns(fileName, new Set()),
    discardAll: () => commit({ turned: NO_TURNS }),
    save,
    saveAll: async () => {
      for (const fileName of [...latest.current.turned.keys()]) {
        const reason = await save(fileName);
        if (reason !== null) return reason;
      }
      return null;
    },
    restore: (fileName) => change(fileName, () => restoreOriginal(token, project, fileName)),
    unsaved: turned.size > 0,
  };
}

/**
 * What the view draws in Inspect: each test surface file in local coordinates with its turns, the selected one drawn full and the
 * others faint (none faint while no file is selected), and the selected file's bounds to frame. The files are the same array while
 * the geometries, the origin, the turns and the selection are, so the view does not draw the layer again for another change.
 */
export function useInspectView(inspection: InspectionHook, origin: Point3, active: boolean): InspectView | null {
  const originKey = origin.join(",");
  const local = useMemo(() => [...inspection.geometries].map(([fileName, geometry]) => ({
    fileName, corners: localCorners(geometry, origin), surfaceOfTriangle: geometry.surfaceOfTriangle, surfaces: localSurfaces(geometry, origin),
  })), [inspection.geometries, originKey]);
  const { selected } = inspection;
  const selectedName = selected === null ? null : selected.role === TEST_SURFACES_ROLE ? selected.file_name : "";
  const files = useMemo((): InspectLayerFile[] => local.map((file) => ({
    ...file, turned: inspection.turned.get(file.fileName) ?? new Set<number>(), selected: selectedName === null || file.fileName === selectedName,
  })), [local, inspection.turned, selectedName]);
  const bounds = selected?.bounds;
  // Made anew for each request only: a file selected by a click on the view (no request) leaves the camera where it is.
  const frame = useMemo(() => (bounds === undefined ? null
    : { min: toLocal(bounds[0], origin), max: toLocal(bounds[1], origin), request: inspection.frameRequest }), [inspection.frameRequest, originKey]);
  if (!active) return null;
  return { files, arrows: inspection.arrows, onSurfaceClick: inspection.clickSurface, frame };
}

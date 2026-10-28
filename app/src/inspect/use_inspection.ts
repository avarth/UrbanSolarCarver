// The inspection of the open project's input files (Inspect, inspect design sections 3, 5 and 6): the summary of each mesh file, the
// geometry of each test surface file with the surface of each triangle, the file the Files panel selects, flip mode and the arrows,
// and the turns staged per file until Save. The inspection is read, with the geometries of every test surface file, when Inspect
// opens and after each save or restore.
// Save sends one request per file with all its staged turns, which then leave the staged ones: they are being written, no longer
// turns not saved. They stay drawn until the file's new geometry is in, so the view does not show the old orientation in between,
// and a surface turned while they are written is staged on top of them. A second save of a file waits for the one under way, so no
// turn is sent twice. A refused request puts its turns back with those staged and says why (problem).
// Staged turns hold for the version of the file they were made on (InspectedFile.version, the digest of its bytes), which a save
// sends: a file read again as another version (replaced by hand) has its surfaces numbered anew, so its staged turns are dropped, and
// the panel says so. A save or restore the service refuses because the file changed in the project folder (409, isStoredFileChanged)
// drops the file's turns, says why and reads the inspection again; so does a change found by the stage status (reload). A save of the
// app's own carries the turns staged while it ran to the version it wrote, when that has the same triangles and surfaces.
// useInspectView gives the view what it draws, kept the same between renders that change none of it (the view draws the layer again
// whenever its files change).
import { useEffect, useMemo, useRef, useState } from "react";
import {
  failureTextOf, getInspection, getInspectionGeometry, isStoredFileChanged, restoreOriginal, serviceProblemOf, turnSurfaces, type InspectedFile,
  type InspectReply,
} from "../api_client/client";
import { messages } from "../messages";
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

type Turns = ReadonlyMap<string, ReadonlySet<number>>;

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
  turned: Turns;
  /** The surfaces the view draws turned: those staged, on top of those being written. */
  drawnTurned: Turns;
  /** A click on a surface in the view: in flip mode on the selected file it turns the surface, otherwise it selects its file. */
  clickSurface: (fileName: string, surface: number) => void;
  toggleSurface: (fileName: string, surface: number) => void;
  /** Turns every surface of the file once more (a whole export the wrong way round). */
  flipAll: (fileName: string) => void;
  discard: (fileName: string) => void;
  discardAll: () => void;
  /**
   * Writes the file's staged turns, after a save or restore of the file under way; resolves with why it could not, or null once
   * written (or with nothing to write).
   */
  save: (fileName: string) => Promise<string | null>;
  /** Writes the turns of every file, one after another; resolves with the first reason one could not be written, or null. */
  saveAll: () => Promise<string | null>;
  /** Puts the file's kept original back, dropping its staged turns; resolves with why it could not, or null. */
  restore: (fileName: string) => Promise<string | null>;
  /** Resolves once no save or restore is under way: with why the first that ended meanwhile was refused, or null. */
  waitForUnderWay: () => Promise<string | null>;
  /** Whether a save or restore is under way, and whether some file has turns staged and not sent, now (for a caller that waited). */
  underWayNow: () => boolean;
  unsavedNow: () => boolean;
  /** Reads the inspection again while Inspect is shown (a file changed in the project folder); nothing otherwise. */
  reload: () => void;
  /** Some file has turns staged and not sent. */
  unsaved: boolean;
  /** A save or restore is under way: the panel's buttons that send one wait. */
  busy: boolean;
  /** Why the inspection could not be read, the last save or restore failed, or staged turns were dropped; null otherwise. */
  problem: string | null;
}

interface InspectionState {
  reply: InspectReply | null;
  geometries: ReadonlyMap<string, InspectGeometry>;
  selectedKey: FileKey | null;
  frameRequest: number;
  flipMode: boolean;
  arrows: boolean;
  turned: Turns;
  /** The version of each file with staged turns that they were made on (InspectedFile.version). */
  stagedOn: ReadonlyMap<string, string>;
  /** The turns being written, by file (a restore under way: none); a file is listed while its request and the read after it go on. */
  sending: Turns;
  problem: string | null;
}

const NO_GEOMETRIES: ReadonlyMap<string, InspectGeometry> = new Map();
const NO_TURNS: Turns = new Map();

const isKeyOf = (key: FileKey | null, file: InspectedFile) => key !== null && key.role === file.role && key.fileName === file.file_name;

/** The surfaces of *surfaces* turned once more by each of *by*. */
function toggledBy(surfaces: ReadonlySet<number>, by: Iterable<number>): Set<number> {
  const next = new Set(surfaces);
  for (const surface of by) {
    if (!next.delete(surface)) next.add(surface);
  }
  return next;
}

/** *turns* with the file's surfaces replaced; a file of no surfaces is taken out. */
function withTurns(turns: Turns, fileName: string, surfaces: ReadonlySet<number> | null): Turns {
  const next = new Map(turns);
  if (surfaces === null || surfaces.size === 0) next.delete(fileName);
  else next.set(fileName, surfaces);
  return next;
}

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
    reply: null, geometries: NO_GEOMETRIES, selectedKey: null, frameRequest: 0, flipMode: false, arrows: false, turned: NO_TURNS,
    stagedOn: new Map(), sending: NO_TURNS, problem: null,
  });
  // The latest state, read by calls that wait for a reply while another change arrives.
  const latest = useRef(state);
  const commit = (next: Partial<InspectionState>) => {
    latest.current = { ...latest.current, ...next };
    setState(latest.current);
  };
  // Only the last read asked for is shown: an earlier one that answers later has older files.
  const readsAskedFor = useRef(0);
  // The save or restore under way of each file, which a later save of the file waits for.
  const underWay = useRef(new Map<string, Promise<string | null>>());
  const shown = useRef(active);
  shown.current = active;

  const fileOf = (key: FileKey | null) => latest.current.reply?.files.find((file) => isKeyOf(key, file)) ?? null;
  const testSurfaceFile = (fileName: string) => fileOf({ role: TEST_SURFACES_ROLE, fileName });
  const failed = (error: unknown) => {
    if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    return failureTextOf(error);
  };

  /** Reads the inspection; *also* is committed with it (in the same render), and on its own when the read fails or is outrun. */
  const refresh = async (also: () => Partial<InspectionState> = () => ({})) => {
    const read = ++readsAskedFor.current;
    try {
      const reply = await getInspection(token, project);
      const readable = reply.files.filter((file) => file.role === TEST_SURFACES_ROLE && file.problem == null);
      const buffers = await Promise.all(readable.map((file) => getInspectionGeometry(token, project, file.file_name)));
      if (read !== readsAskedFor.current) return commit(also());
      const { selectedKey, flipMode, turned, stagedOn } = latest.current;
      const kept = reply.files.some((file) => isKeyOf(selectedKey, file));
      const readableNow = new Map(readable.map((file) => [file.file_name, file]));
      // Turns of a file gone or changed are dropped; only a change is said (a file gone leaves its row, which says enough).
      const changed = [...turned.keys()].filter((fileName) => {
        const now = readableNow.get(fileName), before = stagedOn.get(fileName);
        return now !== undefined && before !== undefined && now.version !== before;
      });
      const keptTurns = [...turned].filter(([fileName]) => readableNow.has(fileName) && !changed.includes(fileName));
      commit({
        reply, problem: changed.length > 0 ? messages.stagedTurnsDropped : null,
        geometries: new Map(readable.map((file, index) => [file.file_name, decodeInspectGeometry(buffers[index])])),
        selectedKey: kept ? selectedKey : null, flipMode: kept && flipMode,
        turned: new Map(keptTurns), stagedOn: new Map([...stagedOn].filter(([fileName]) => keptTurns.some(([kept]) => kept === fileName))),
        ...also(),
      });
    } catch (error) {
      if (read !== readsAskedFor.current) return commit(also());
      commit({ problem: failed(error), ...also() });
    }
  };

  useEffect(() => {
    if (active) void refresh();
    else if (latest.current.flipMode) commit({ flipMode: false });
  }, [active]);

  /** The staged turns of the file become *surfaces*; the file's version is noted with its first turn and forgotten with its last. */
  const stagedTurns = (fileName: string, surfaces: ReadonlySet<number>): Partial<InspectionState> => {
    const stagedOn = new Map(latest.current.stagedOn);
    const file = testSurfaceFile(fileName);
    if (surfaces.size === 0) stagedOn.delete(fileName);
    else if (!stagedOn.has(fileName) && file !== null) stagedOn.set(fileName, file.version);
    return { turned: withTurns(latest.current.turned, fileName, surfaces), stagedOn };
  };
  const setTurns = (fileName: string, surfaces: ReadonlySet<number>) => commit(stagedTurns(fileName, surfaces));
  const toggleSurface = (fileName: string, surface: number) => {
    if (!testSurfaceFile(fileName)?.flippable) return;
    setTurns(fileName, toggledBy(latest.current.turned.get(fileName) ?? new Set(), [surface]));
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

  /** Waits for the save or restore of the file under way, if any; resolves with why it failed, or null. */
  const waitForFile = async (fileName: string): Promise<string | null> => {
    for (let running = underWay.current.get(fileName); running !== undefined; running = underWay.current.get(fileName)) {
      const reason = await running;
      if (reason !== null) return reason;
    }
    return null;
  };
  /**
   * Sends *request* for the file: *sent* (the turns it writes) leave the staged turns, which become *stagedNow*, and are drawn as
   * being written. Once it is answered the inspection is read again, and the file's new geometry comes in with *sent* no longer drawn
   * on top. A refusal puts *sent* back on top of the turns staged since; a refusal because the file changed in the project folder
   * drops the file's turns instead and reads the inspection again. *carriesTurns*: a save, whose reply is the version the turns
   * staged meanwhile now hold for, when it has the same triangles and surfaces as the file sent.
   */
  const change = (fileName: string, sent: ReadonlySet<number>, stagedNow: ReadonlySet<number>, request: () => Promise<InspectedFile>,
                  carriesTurns: boolean) => {
    const before = testSurfaceFile(fileName);
    commit({ ...stagedTurns(fileName, stagedNow), sending: new Map(latest.current.sending).set(fileName, sent), problem: null });
    const notSending = () => ({ sending: withTurns(latest.current.sending, fileName, null) });
    const running = (async (): Promise<string | null> => {
      let written: InspectedFile;
      try {
        written = await request();
      } catch (error) {
        const problem = failed(error);
        if (isStoredFileChanged(error)) {
          commit(stagedTurns(fileName, new Set()));
          await refresh(() => ({ ...notSending(), problem }));
        } else {
          commit({ ...stagedTurns(fileName, toggledBy(latest.current.turned.get(fileName) ?? new Set(), sent)), ...notSending(), problem });
        }
        return problem;
      }
      const stagedOn = latest.current.stagedOn.get(fileName);
      if (carriesTurns && before !== null && stagedOn === before.version && written.triangle_count === before.triangle_count
          && written.surface_count === before.surface_count) {
        commit({ stagedOn: new Map(latest.current.stagedOn).set(fileName, written.version) });
      }
      onSaved();
      await refresh(notSending);
      return null;
    })();
    underWay.current.set(fileName, running);
    void running.finally(() => {
      if (underWay.current.get(fileName) === running) underWay.current.delete(fileName);
    });
    return running;
  };
  const save = async (fileName: string): Promise<string | null> => {
    const reason = await waitForFile(fileName);
    if (reason !== null) return reason;
    const sent = latest.current.turned.get(fileName) ?? new Set<number>();
    if (sent.size === 0) return null;
    const surfaces = [...sent].sort((first, second) => first - second);
    const version = latest.current.stagedOn.get(fileName) ?? testSurfaceFile(fileName)?.version ?? "";
    return change(fileName, sent, new Set(), () => turnSurfaces(token, project, fileName, surfaces, version), true);
  };
  const waitForUnderWay = async (): Promise<string | null> => {
    const waited = new Set<Promise<string | null>>();
    let reason: string | null = null;
    for (let running = [...underWay.current.values()].filter((each) => !waited.has(each)); running.length > 0;
         running = [...underWay.current.values()].filter((each) => !waited.has(each))) {
      for (const each of running) waited.add(each);
      const reasons = await Promise.all(running);
      reason = reason ?? reasons.find((each) => each !== null) ?? null;
    }
    return reason;
  };

  const { reply, geometries, selectedKey, frameRequest, flipMode, arrows, turned, sending, problem } = state;
  const drawnTurned = useMemo(() => {
    if (sending.size === 0) return turned;
    const drawn = new Map(turned);
    for (const [fileName, surfaces] of sending) drawn.set(fileName, toggledBy(turned.get(fileName) ?? new Set(), surfaces));
    return drawn;
  }, [turned, sending]);
  return {
    reply, geometries, frameRequest, flipMode, arrows, turned, drawnTurned, problem,
    busy: sending.size > 0,
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
      setTurns(fileName, toggledBy(latest.current.turned.get(fileName) ?? new Set(), Array.from({ length: count }, (_, surface) => surface)));
    },
    discard: (fileName) => setTurns(fileName, new Set()),
    discardAll: () => commit({ turned: NO_TURNS, stagedOn: new Map() }),
    save,
    saveAll: async () => {
      for (const fileName of new Set([...underWay.current.keys(), ...latest.current.turned.keys()])) {
        const reason = await save(fileName);
        if (reason !== null) return reason;
      }
      return null;
    },
    restore: async (fileName) => {
      const reason = await waitForFile(fileName);
      if (reason !== null) return reason;
      const version = testSurfaceFile(fileName)?.version ?? "";
      return change(fileName, new Set(), new Set(), () => restoreOriginal(token, project, fileName, version), false);
    },
    waitForUnderWay,
    underWayNow: () => underWay.current.size > 0,
    unsavedNow: () => latest.current.turned.size > 0,
    reload: () => {
      if (shown.current) void refresh();
    },
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
    ...file, turned: inspection.drawnTurned.get(file.fileName) ?? new Set<number>(), selected: selectedName === null || file.fileName === selectedName,
  })), [local, inspection.drawnTurned, selectedName]);
  const bounds = selected?.bounds;
  // Made anew for each request only: a file selected by a click on the view (no request) leaves the camera where it is.
  const frame = useMemo(() => (bounds === undefined ? null
    : { min: toLocal(bounds[0], origin), max: toLocal(bounds[1], origin), request: inspection.frameRequest }), [inspection.frameRequest, originKey]);
  if (!active) return null;
  return { files, arrows: inspection.arrows, onSurfaceClick: inspection.clickSurface, frame };
}

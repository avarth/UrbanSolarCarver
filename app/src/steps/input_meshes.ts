// The input meshes the 3D view draws (UX 8.2): the files of the maximum volume, the test surfaces, the existing surroundings and
// the terrain, each role's files
// joined into one geometry in local coordinates, fetched again when the files, their contents or the local origin change.
// A file the service accepted (the engine reads it) that the view cannot parse is left out of the drawing and named in its
// input box (UX 11); the role's other files are still drawn.
import { useEffect, useEffectEvent, useState } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { inputFileUrl, type InputFileInfo } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import { messages } from "../messages";
import { loadMesh, MeshNotReadableError } from "../viewer/loaders";
import type { Bounds3, Point3 } from "../viewer/local_origin";
import type { InputRole } from "../common/InputBox";

export type MeshRole = Exclude<InputRole, "weather">;

function extensionOf(fileName: string): string {
  return fileName.slice(fileName.lastIndexOf(".") + 1);
}

/** The meshes of several files as one geometry (triangle soup, positions only, as the view draws them). */
function joinedGeometry(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  return mergeGeometries(parts.map((part) => (part.index ? part.toNonIndexed() : part))) ?? new THREE.BufferGeometry();
}

/** Geometries that may be missing, joined into one; the one alone when the other is missing, null when none is there. */
export function joinedOrNull(parts: readonly (THREE.BufferGeometry | null)[]): THREE.BufferGeometry | null {
  const present = parts.filter((part): part is THREE.BufferGeometry => part !== null);
  return present.length < 2 ? (present[0] ?? null) : joinedGeometry(present);
}

/** The meshes of the named files joined; a name without a mesh (not loaded, or unreadable) is left out, and null when none is left. */
export function joinedGeometryOf(byFile: Record<string, THREE.BufferGeometry>, names: readonly string[]): THREE.BufferGeometry | null {
  const parts = names.filter((name) => Object.hasOwn(byFile, name)).map((name) => byFile[name]);
  return parts.length > 0 ? joinedGeometry(parts) : null;
}

/** The bounds of the geometries together; null when there is none. */
export function boundsOf(geometries: (THREE.BufferGeometry | null)[]): Bounds3 | null {
  const box = new THREE.Box3();
  for (const geometry of geometries) {
    if (!geometry) continue;
    geometry.computeBoundingBox();
    box.union(geometry.boundingBox!);
  }
  return box.isEmpty() ? null : [box.min.toArray(), box.max.toArray()];
}

export interface InputGeometry {
  /** The files the view could read, joined; null while none is loaded. */
  geometry: THREE.BufferGeometry | null;
  /** The mesh of each file the view could read, by file name (the test surfaces are drawn by criterion). */
  byFile: Record<string, THREE.BufferGeometry>;
  /** One text per file the view cannot draw, naming the file, for its input box. */
  drawingProblems: string[];
}

const NOTHING_LOADED: InputGeometry = { geometry: null, byFile: {}, drawingProblems: [] };

/** The joined mesh of a role's files in local coordinates; reloaded when the files, their contents or the local origin change. *urlOf*
 *  gives the address of a file when it is not the role's stored file (the joined maximum volume of a project that uses its sites). */
export function useInputGeometry(role: MeshRole, files: InputFileInfo[], origin: Point3, revision: number, onLoaded: () => void,
                                 urlOf?: (fileName: string) => string): InputGeometry {
  const { token, project, onServiceProblem } = useProjectSession();
  const [loaded, setLoaded] = useState<InputGeometry>(NOTHING_LOADED);
  if (files.length === 0 && loaded !== NOTHING_LOADED) setLoaded(NOTHING_LOADED);
  // The files and the origin are read as they are when the key says to load again.
  const reloadKey = JSON.stringify([files.map((file) => file.name), origin, revision]);
  const load = useEffectEvent(() => {
    if (files.length === 0) return;
    let stale = false;
    Promise.allSettled(files.map((file) => loadMesh(urlOf ? urlOf(file.name) : inputFileUrl(project, role, file.name), token, extensionOf(file.name), origin)))
      .then((outcomes) => {
        if (stale) return;
        const byFile: Record<string, THREE.BufferGeometry> = {};
        const drawingProblems: string[] = [];
        let failedRequest: unknown = null;
        outcomes.forEach((outcome, index) => {
          if (outcome.status === "fulfilled") byFile[files[index].name] = outcome.value;
          else if (outcome.reason instanceof MeshNotReadableError) drawingProblems.push(messages.fileProblem(files[index].name, outcome.reason.message));
          else failedRequest ??= outcome.reason;
        });
        const parts = Object.values(byFile);
        setLoaded({ geometry: parts.length > 0 ? joinedGeometry(parts) : null, byFile, drawingProblems });
        if (parts.length > 0) onLoaded();
        // A failed request may mean a lost token or a stopped engine: the app tells which, and leaves a refusal of another kind
        if (failedRequest !== null) onServiceProblem(failedRequest);
      });
    return () => {
      stale = true;
    };
  });
  useEffect(() => load(), [reloadKey, project, role]);
  return loaded;
}

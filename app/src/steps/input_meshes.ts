// The input meshes the 3D view draws (UX 8.2): the files of the maximum volume and of the test surfaces, each role's files
// joined into one geometry in local coordinates, fetched again when the files, their contents or the local origin change.
// A file the service accepted (the engine reads it) that the view cannot parse is left out of the drawing and named in its
// input box (UX 11); the role's other files are still drawn.
import { useEffect, useState } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { inputFileUrl, type InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { loadMesh, MeshNotReadableError } from "../viewer/loaders";
import type { Bounds3, Point3 } from "../viewer/local_origin";
import type { InputRole } from "./InputsStep";

export type MeshRole = Exclude<InputRole, "weather">;

function extensionOf(fileName: string): string {
  return fileName.slice(fileName.lastIndexOf(".") + 1);
}

/** The meshes of several files as one geometry (triangle soup, positions only, as the view draws them). */
function joinedGeometry(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  return mergeGeometries(parts.map((part) => (part.index ? part.toNonIndexed() : part))) ?? new THREE.BufferGeometry();
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
  /** One text per file the view cannot draw, naming the file, for its input box. */
  drawingProblems: string[];
}

const NOTHING_LOADED: InputGeometry = { geometry: null, drawingProblems: [] };

/** The joined mesh of a role's files in local coordinates; reloaded when the files, their contents or the local origin change. */
export function useInputGeometry(token: string, project: string, role: MeshRole, files: InputFileInfo[], origin: Point3, revision: number,
                                 onLoaded: () => void, onServiceProblem: (error: unknown) => void): InputGeometry {
  const [loaded, setLoaded] = useState<InputGeometry>(NOTHING_LOADED);
  const reloadKey = JSON.stringify([files.map((file) => file.name), origin, revision]);
  useEffect(() => {
    if (files.length === 0) {
      setLoaded(NOTHING_LOADED);
      return;
    }
    let stale = false;
    Promise.allSettled(files.map((file) => loadMesh(inputFileUrl(project, role, file.name), token, extensionOf(file.name), origin)))
      .then((outcomes) => {
        if (stale) return;
        const parts: THREE.BufferGeometry[] = [];
        const drawingProblems: string[] = [];
        let failedRequest: unknown = null;
        outcomes.forEach((outcome, index) => {
          if (outcome.status === "fulfilled") parts.push(outcome.value);
          else if (outcome.reason instanceof MeshNotReadableError) drawingProblems.push(messages.fileProblem(files[index].name, outcome.reason.message));
          else failedRequest ??= outcome.reason;
        });
        setLoaded({ geometry: parts.length > 0 ? joinedGeometry(parts) : null, drawingProblems });
        if (parts.length > 0) onLoaded();
        // A failed request may mean a lost token or a stopped engine: the app tells which, and leaves a refusal of another kind
        if (failedRequest !== null) onServiceProblem(failedRequest);
      });
    return () => {
      stale = true;
    };
  }, [reloadKey]);
  return loaded;
}

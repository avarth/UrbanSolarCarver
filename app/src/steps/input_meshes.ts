// The input meshes the 3D view draws (UX 8.2): the files of the maximum volume and of the test surfaces, each role's files
// joined into one geometry in local coordinates, fetched again when the files, their contents or the local origin change.
import { useEffect, useState } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { ApiError, inputFileUrl, type InputFileInfo } from "../api_client/client";
import { loadMesh } from "../viewer/loaders";
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

/** The joined mesh of a role's files in local coordinates; reloaded when the files, their contents or the local origin change. */
export function useInputGeometry(token: string, project: string, role: MeshRole, files: InputFileInfo[], origin: Point3, revision: number,
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

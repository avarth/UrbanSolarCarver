// Meshes for the 3D view: input files and run results, fetched with the token header (a loader's own request cannot send it)
// and parsed with the three.js loaders. Every mesh is moved to the local origin (local_origin.ts). In the text formats the
// coordinates are shifted in the text, in float64, before the loader turns them into float32; binary files already hold float32
// (or are read into float32 by the loader) and are shifted after parsing.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { ApiError, TOKEN_HEADER } from "../api_client/client";
import { messages } from "../messages";
import type { Point3 } from "./local_origin";

export type MeshExtension = "ply" | "obj" | "stl" | "glb";

const NO_SHIFT: Point3 = [0, 0, 0];
const BINARY_STL_HEADER_BYTES = 84;
const BINARY_STL_TRIANGLE_BYTES = 50;

/**
 * The file was fetched, but the view cannot make a mesh of it: a type it does not draw, or content the three.js loaders cannot
 * parse (a truncated ASCII PLY, say). The message is the reason, from messages.ts. A failed request rejects with its own error.
 */
export class MeshNotReadableError extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = "MeshNotReadableError";
  }
}

async function fetchWithToken(url: string, token: string): Promise<ArrayBuffer> {
  const reply = await fetch(url, { headers: { [TOKEN_HEADER]: token } });
  if (!reply.ok) throw new ApiError(reply.status, await reply.text());
  return reply.arrayBuffer();
}

function shifted(value: string, by: number): string {
  return String(Number(value) - by);
}

/** The x, y, z numbers after a line keyword ("v" in OBJ, "vertex" in ASCII STL) shifted by the origin. */
function shiftKeywordLines(text: string, keyword: string, origin: Point3): string {
  const coordinates = new RegExp(`^(\\s*${keyword}\\s+)(\\S+)(\\s+)(\\S+)(\\s+)(\\S+)`, "gm");
  return text.replace(coordinates, (_line, start, x, gapAfterX, y, gapAfterY, z) =>
    `${start}${shifted(x, origin[0])}${gapAfterX}${shifted(y, origin[1])}${gapAfterY}${shifted(z, origin[2])}`);
}

interface PlyElement { name: string; count: number; properties: string[]; hasList: boolean }

/**
 * ASCII PLY with the x, y and z properties of its vertices shifted by the origin; null when its vertex lines cannot be read by
 * position.
 */
function shiftAsciiPly(text: string, origin: Point3): string | null {
  const lines = text.split(/\r?\n/);
  const headerEnd = lines.findIndex((line) => line.trim() === "end_header");
  const elements: PlyElement[] = [];
  for (const line of lines.slice(0, headerEnd)) {
    const words = line.trim().split(/\s+/);
    if (words[0] === "element") elements.push({ name: words[1], count: Number(words[2]), properties: [], hasList: false });
    else if (words[0] === "property" && elements.length) {
      const element = elements[elements.length - 1];
      if (words[1] === "list") element.hasList = true;
      element.properties.push(words[words.length - 1]);
    }
  }
  let lineIndex = headerEnd + 1;
  for (const element of elements) {
    if (element.name === "vertex") {
      const columns = ["x", "y", "z"].map((name) => element.properties.indexOf(name));
      if (element.hasList || columns.includes(-1)) return null;
      for (let vertex = 0; vertex < element.count; vertex++, lineIndex++) {
        const values = lines[lineIndex].trim().split(/\s+/);
        columns.forEach((column, axis) => { values[column] = shifted(values[column], origin[axis]); });
        lines[lineIndex] = values.join(" ");
      }
      return lines.join("\n");
    }
    lineIndex += element.count;     // one line per item in ASCII PLY
  }
  return null;
}

function shiftPositions(geometry: THREE.BufferGeometry, origin: Point3): void {
  const positions = geometry.getAttribute("position");
  for (let vertex = 0; vertex < positions.count; vertex++) {
    positions.setXYZ(vertex, positions.getX(vertex) - origin[0], positions.getY(vertex) - origin[1], positions.getZ(vertex) - origin[2]);
  }
  positions.needsUpdate = true;
}

/** A mesh file without triangles (the building massing writes an empty file when no storey fits). */
function emptyGeometry(): THREE.BufferGeometry {
  return new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([], 3));
}

/** Only the positions are kept: the view shades the meshes flat and colours them itself. */
function positionsOnly(geometry: THREE.BufferGeometry): THREE.BufferGeometry {
  const bare = new THREE.BufferGeometry();
  bare.setAttribute("position", geometry.getAttribute("position"));
  if (geometry.index) bare.setIndex(geometry.index);
  return bare;
}

/** The meshes of a loaded scene as one geometry, one group per mesh, the mesh names in userData.partNames. */
function joinedParts(root: THREE.Object3D): THREE.BufferGeometry {
  root.updateMatrixWorld(true);
  const parts: THREE.BufferGeometry[] = [];
  const partNames: string[] = [];
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const part = positionsOnly(object.geometry).applyMatrix4(object.matrixWorld);
    parts.push(part.index ? part.toNonIndexed() : part);
    partNames.push(object.name);
  });
  const joined = parts.length ? mergeGeometries(parts, true) : emptyGeometry();
  joined.userData.partNames = partNames;
  return joined;
}

function isAsciiPly(buffer: ArrayBuffer): boolean {
  const start = new TextDecoder().decode(new Uint8Array(buffer, 0, Math.min(buffer.byteLength, 512)));
  return /format\s+ascii/.test(start);
}

function isBinaryStl(buffer: ArrayBuffer): boolean {
  if (buffer.byteLength < BINARY_STL_HEADER_BYTES) return false;
  const triangleCount = new DataView(buffer).getUint32(80, true);
  return BINARY_STL_HEADER_BYTES + triangleCount * BINARY_STL_TRIANGLE_BYTES === buffer.byteLength;
}

/**
 * A mesh file of the service, fetched with the token, as one geometry in coordinates relative to *localOriginPoint*. A file the
 * view cannot make a mesh of rejects with MeshNotReadableError.
 */
export async function loadMesh(url: string, token: string, extension: MeshExtension | string, localOriginPoint: Point3 = NO_SHIFT): Promise<THREE.BufferGeometry> {
  const buffer = await fetchWithToken(url, token);
  try {
    return await parsedMesh(buffer, extension, localOriginPoint);
  } catch (error) {
    if (error instanceof MeshNotReadableError) throw error;
    // The loaders throw whatever their parsing meets (a TypeError on a missing line); for the view it means one thing
    throw new MeshNotReadableError(messages.meshCannotBeDrawn);
  }
}

async function parsedMesh(buffer: ArrayBuffer, extension: MeshExtension | string, localOriginPoint: Point3): Promise<THREE.BufferGeometry> {
  const text = () => new TextDecoder().decode(buffer);
  switch (extension.toLowerCase().replace(/^\./, "")) {
    case "obj":
      return joinedParts(new OBJLoader().parse(shiftKeywordLines(text(), "v", localOriginPoint)));
    case "stl": {
      if (!isBinaryStl(buffer)) return positionsOnly(new STLLoader().parse(shiftKeywordLines(text(), "vertex", localOriginPoint)));
      const geometry = positionsOnly(new STLLoader().parse(buffer));
      shiftPositions(geometry, localOriginPoint);
      return geometry;
    }
    case "ply": {
      const shiftedText = isAsciiPly(buffer) ? shiftAsciiPly(text(), localOriginPoint) : null;
      const geometry = positionsOnly(new PLYLoader().parse(shiftedText ?? buffer));
      if (shiftedText === null) shiftPositions(geometry, localOriginPoint);
      return geometry;
    }
    case "glb": {
      const gltf = await new GLTFLoader().parseAsync(buffer, "");
      const geometry = joinedParts(gltf.scene);
      shiftPositions(geometry, localOriginPoint);
      return geometry;
    }
    default:
      throw new MeshNotReadableError(messages.meshTypeCannotBeShown(extension));
  }
}

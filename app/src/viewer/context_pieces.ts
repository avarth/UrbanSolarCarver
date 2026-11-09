// The flat pieces of the surroundings as the view picks them (design/test-surfaces-on-context.md): the clicked triangle and the
// triangles reached from it across shared edges whose normal is within FLAT_ANGLE_DEG of its own (either way round: neighbours may be
// wound opposite) and whose corners lie within FLAT_DISTANCE_M of its plane. The service finds the same piece on the joined surroundings
// (picked_surfaces.py) and stores that; the view's is for drawing it while picking. Points are in the view's local coordinates.
import type * as THREE from "three";

export const FLAT_ANGLE_DEG = 1;
export const FLAT_DISTANCE_M = 0.01;
/** Corners closer than this are one vertex: the surroundings' files repeat vertices where their faces meet. */
const SAME_CORNER_M = 1e-4;

export type Triangle = [[number, number, number], [number, number, number], [number, number, number]];

interface Adjacency {
  triangles: Triangle[];
  normals: [number, number, number][];
  neighbours: number[][];
}

const adjacencies = new WeakMap<THREE.BufferGeometry, Adjacency>();

function adjacencyOf(geometry: THREE.BufferGeometry): Adjacency {
  const known = adjacencies.get(geometry);
  if (known !== undefined) return known;
  const position = geometry.getAttribute("position");
  const index = geometry.getIndex();
  const faceCount = index === null ? position.count / 3 : index.count / 3;
  const corner = (face: number, at: number) => (index === null ? face * 3 + at : index.getX(face * 3 + at));
  const ids = new Map<string, number>();
  const idOf = (vertex: number) => {
    const key = [position.getX(vertex), position.getY(vertex), position.getZ(vertex)].map((value) => Math.round(value / SAME_CORNER_M)).join(",");
    let id = ids.get(key);
    if (id === undefined) {
      id = ids.size;
      ids.set(key, id);
    }
    return id;
  };
  const triangles: Triangle[] = [];
  const normals: [number, number, number][] = [];
  const facesOfEdge = new Map<string, number[]>();
  for (let face = 0; face < faceCount; face += 1) {
    const vertices = [0, 1, 2].map((at) => corner(face, at));
    const points = vertices.map((vertex) => [position.getX(vertex), position.getY(vertex), position.getZ(vertex)] as [number, number, number]);
    triangles.push(points as Triangle);
    normals.push(normalOf(points as Triangle));
    const corners = vertices.map(idOf);
    for (let at = 0; at < 3; at += 1) {
      const a = corners[at], b = corners[(at + 1) % 3];
      const key = a < b ? `${a}-${b}` : `${b}-${a}`;
      const faces = facesOfEdge.get(key) ?? [];
      faces.push(face);
      facesOfEdge.set(key, faces);
    }
  }
  const neighbours: number[][] = triangles.map(() => []);
  for (const faces of facesOfEdge.values()) {
    for (const a of faces) for (const b of faces) if (a !== b) neighbours[a].push(b);
  }
  const adjacency = { triangles, normals, neighbours };
  adjacencies.set(geometry, adjacency);
  return adjacency;
}

function normalOf([a, b, c]: Triangle): [number, number, number] {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const n: [number, number, number] = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const length = Math.hypot(...n);
  return length > 0 ? [n[0] / length, n[1] / length, n[2] / length] : [0, 0, 0];
}

const dot = (a: readonly number[], b: readonly number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/** The faces of the flat piece of *seed* in *geometry*. */
export function flatPieceFaces(geometry: THREE.BufferGeometry, seed: number): number[] {
  const { triangles, normals, neighbours } = adjacencyOf(geometry);
  const seedNormal = normals[seed];
  const origin = triangles[seed][0];
  const cosLimit = Math.cos((FLAT_ANGLE_DEG * Math.PI) / 180);
  const eligible = (face: number) => Math.abs(dot(normals[face], seedNormal)) >= cosLimit
    && triangles[face].every((point) => Math.abs(dot([point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]], seedNormal)) <= FLAT_DISTANCE_M);
  const found = new Set([seed]);
  const queue = [seed];
  while (queue.length > 0) {
    const face = queue.shift()!;
    for (const other of neighbours[face]) {
      if (!found.has(other) && eligible(other)) {
        found.add(other);
        queue.push(other);
      }
    }
  }
  return [...found].sort((a, b) => a - b);
}

/** The triangles of *faces* in *geometry*, in local coordinates. */
export function trianglesOf(geometry: THREE.BufferGeometry, faces: readonly number[]): Triangle[] {
  const { triangles } = adjacencyOf(geometry);
  return faces.map((face) => triangles[face]);
}

/** The face of *geometry* closest to the local point *point* within *within* metres (a pick kept from before); null for none. */
export function faceAt(geometry: THREE.BufferGeometry, point: readonly number[], within = 0.05): number | null {
  const { triangles } = adjacencyOf(geometry);
  let best: number | null = null, bestDistance = within;
  triangles.forEach((triangle, face) => {
    const distance = distanceToTriangle(point, triangle);
    if (distance <= bestDistance) {
      best = face;
      bestDistance = distance;
    }
  });
  return best;
}

/** The distance from *p* to the triangle (closest point on it, after Ericson, Real-Time Collision Detection, 5.1.5). */
function distanceToTriangle(p: readonly number[], [a, b, c]: Triangle): number {
  const sub = (x: readonly number[], y: readonly number[]) => [x[0] - y[0], x[1] - y[1], x[2] - y[2]];
  const ab = sub(b, a), ac = sub(c, a), ap = sub(p, a);
  const d1 = dot(ab, ap), d2 = dot(ac, ap);
  const at = (q: readonly number[]) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
  const along = (s: readonly number[], d: readonly number[], t: number) => [s[0] + d[0] * t, s[1] + d[1] * t, s[2] + d[2] * t];
  if (d1 <= 0 && d2 <= 0) return at(a);
  const bp = sub(p, b), d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return at(b);
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return at(along(a, ab, d1 / (d1 - d3)));
  const cp = sub(p, c), d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return at(c);
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return at(along(a, ac, d2 / (d2 - d6)));
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) return at(along(b, sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6))));
  const denominator = 1 / (va + vb + vc);
  const v = vb * denominator, w = vc * denominator;
  return at([a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w]);
}

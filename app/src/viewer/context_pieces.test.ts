// The flat pieces of the surroundings the picker draws (design/test-surfaces-on-context.md, section 3): the clicked triangle and its
// neighbours across shared edges that lie in its plane, within 1° and 1 cm; and the face nearest a point kept from before.
import * as THREE from "three";
import { expect, test } from "vitest";
import { faceAt, flatPieceFaces, trianglesOf, type Triangle } from "./context_pieces";

/** A geometry of these triangles, each with its own three vertices (as the loaders give a file: corners repeated where faces meet). */
function soup(triangles: Triangle[]): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(triangles.flat(2), 3));
  return geometry;
}

const QUAD: Triangle[] = [[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]];

test("a quad of two triangles is one piece, from either triangle", () => {
  const geometry = soup(QUAD);
  expect(flatPieceFaces(geometry, 0)).toEqual([0, 1]);
  expect(flatPieceFaces(geometry, 1)).toEqual([0, 1]);
});

test("an indexed quad, whose triangles share their vertices, is one piece too", () => {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], 3));
  geometry.setIndex([0, 1, 2, 0, 2, 3]);
  expect(flatPieceFaces(geometry, 0)).toEqual([0, 1]);
  expect(trianglesOf(geometry, [1])).toEqual([[[0, 0, 0], [1, 1, 0], [0, 1, 0]]]);
});

test("the floor and the wall of a box corner are two pieces, though they share an edge", () => {
  const geometry = soup([
    ...QUAD,
    [[0, 0, 0], [0, 1, 0], [0, 1, 1]], [[0, 0, 0], [0, 1, 1], [0, 0, 1]],
  ]);
  expect(flatPieceFaces(geometry, 0)).toEqual([0, 1]);
  expect(flatPieceFaces(geometry, 1)).toEqual([0, 1]);
  expect(flatPieceFaces(geometry, 2)).toEqual([2, 3]);
  expect(flatPieceFaces(geometry, 3)).toEqual([2, 3]);
});

test("a neighbour wound the opposite way still joins the piece", () => {
  const geometry = soup([QUAD[0], [[0, 0, 0], [0, 1, 0], [1, 1, 0]]]);
  expect(flatPieceFaces(geometry, 0)).toEqual([0, 1]);
  expect(flatPieceFaces(geometry, 1)).toEqual([0, 1]);
});

test("a small neighbour tilted 2° stays out, one tilted 0.5° joins (both within 1 cm of the plane)", () => {
  // Triangles 10 cm across: the lifted corner is 3.5 mm or 0.9 mm off the plane, so the angle alone decides.
  const lifted = (degrees: number): Triangle[] => {
    const z = 0.1 * Math.tan((degrees * Math.PI) / 180);
    return [[[0, 0, 0], [0.1, 0, 0], [0.1, 0.1, 0]], [[0, 0, 0], [0.1, 0.1, 0], [0, 0.1, z]]];
  };
  expect(flatPieceFaces(soup(lifted(2)), 0)).toEqual([0]);
  expect(flatPieceFaces(soup(lifted(0.5)), 0)).toEqual([0, 1]);
});

test("a large neighbour tilted 0.5° stays out: its far corner is more than 1 cm off the clicked triangle's plane", () => {
  const z = 10 * Math.tan((0.5 * Math.PI) / 180);      // 8.7 cm
  const geometry = soup([[[0, 0, 0], [10, 0, 0], [10, 10, 0]], [[0, 0, 0], [10, 10, 0], [0, 10, z]]]);
  expect(flatPieceFaces(geometry, 0)).toEqual([0]);
});

test("corners less than 0.1 mm apart are one vertex; 1 mm apart they are not, and the triangles do not touch", () => {
  const nudged = (by: number): Triangle[] => [QUAD[0], [[by, 0, 0], [1 + by, 1, 0], [0, 1, 0]]];
  expect(flatPieceFaces(soup(nudged(0.00001)), 0)).toEqual([0, 1]);
  expect(flatPieceFaces(soup(nudged(0.001)), 0)).toEqual([0]);
});

test("faceAt finds the face under a point, or near it within 5 cm; farther, none", () => {
  const geometry = soup([...QUAD, [[5, 0, 0], [6, 0, 0], [6, 1, 0]]]);
  expect(faceAt(geometry, [0.8, 0.2, 0])).toBe(0);
  expect(faceAt(geometry, [0.2, 0.8, 0.03])).toBe(1);
  expect(faceAt(geometry, [5.9, 0.1, -0.04])).toBe(2);
  expect(faceAt(geometry, [3, 0.5, 0])).toBeNull();
  expect(faceAt(geometry, [0.2, 0.8, 0.2])).toBeNull();
  expect(faceAt(geometry, [0.2, 0.8, 0.2], 0.5)).toBe(1);
  // Beside a face, past its edge: the distance is to the edge
  expect(faceAt(geometry, [6.04, 0.5, 0])).toBe(2);
});

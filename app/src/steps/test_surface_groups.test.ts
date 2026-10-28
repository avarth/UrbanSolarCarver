import * as THREE from "three";
import { expect, test } from "vitest";
import type { CriterionEntry } from "../api_client/client";
import { testSurfaceGroupsOf } from "./test_surface_groups";

/** A mesh of *triangles* triangles. */
const meshOf = (triangles: number) => new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(9 * triangles), 3));
const BY_FILE = { "facades.obj": meshOf(1), "windows.obj": meshOf(2), "roofs.obj": meshOf(4) };
const NONE_HIDDEN: ReadonlySet<string> = new Set();

function entry(id: string, colour: string, files: string[], bypassed = false): CriterionEntry {
  return { id, name: `Criterion ${id}`, named_by_user: true, colour, bypassed, energy_weighted: false, test_surface_files: files, settings: {} };
}

const FACADES = entry("1", "#4477aa", ["facades.obj"]), WINDOWS = entry("2", "#ee6677", ["windows.obj"]), ROOFS = entry("3", "#228833", ["roofs.obj"]);
const verticesOf = (group: { geometry: THREE.BufferGeometry | null }) => group.geometry?.getAttribute("position").count ?? null;

test("each criterion's files are one group in its colour, in chain order, whichever criterion is selected", () => {
  const groups = testSurfaceGroupsOf([FACADES, WINDOWS], "2", NONE_HIDDEN, BY_FILE, null);
  expect(groups.map(({ id, name, colour, off, shown }) => ({ id, name, colour, off, shown }))).toEqual([
    { id: "1", name: "Criterion 1", colour: "#4477aa", off: false, shown: true },
    { id: "2", name: "Criterion 2", colour: "#ee6677", off: false, shown: true },
  ]);
  expect(groups.map(verticesOf)).toEqual([3, 6]);
});

test("a file several criteria list is drawn once: for the selected criterion, else for the first that lists it", () => {
  const criteria = [FACADES, entry("2", "#ee6677", ["windows.obj", "facades.obj"]), entry("3", "#228833", ["facades.obj", "roofs.obj"])];
  const drawn = (selectedId: string, hidden: string[] = []) => testSurfaceGroupsOf(criteria, selectedId, new Set(hidden), BY_FILE, null).map(verticesOf);
  expect(drawn("1")).toEqual([3, 6, 12]);          // facades.obj with criterion 1
  expect(drawn("2")).toEqual([null, 9, 12]);       // with criterion 2: windows.obj and facades.obj; criterion 1 has nothing of its own
  expect(drawn("3")).toEqual([null, 6, 15]);
  expect(drawn("2", ["2"])).toEqual([3, null, 12]);        // the selected criterion is hidden: the first of the others that lists it
  expect(drawn("3", ["1", "3"])).toEqual([null, 9, null]);
  expect(drawn("1", ["1", "2", "3"])).toEqual([null, null, null]);       // every owner hidden: not drawn
});

test("a hidden criterion stays in the list, with nothing drawn; a stored file no criterion lists is not drawn", () => {
  const groups = testSurfaceGroupsOf([FACADES, WINDOWS], "1", new Set(["2"]), { ...BY_FILE, "stray.obj": meshOf(8) }, null);
  expect(groups.map(({ id, shown }) => [id, shown])).toEqual([["1", true], ["2", false]]);
  expect(groups.map(verticesOf)).toEqual([3, null]);
});

test("a criterion that is switched off is marked, and its files are drawn as any other's", () => {
  const groups = testSurfaceGroupsOf([FACADES, entry("2", "#ee6677", ["windows.obj"], true)], "1", NONE_HIDDEN, BY_FILE, null);
  expect(groups.map(({ off }) => off)).toEqual([false, true]);
  expect(groups.map(verticesOf)).toEqual([3, 6]);
});

test("a file that is not loaded (unreadable, or not yet) is left out of its criterion's mesh", () => {
  const groups = testSurfaceGroupsOf([entry("1", "#4477aa", ["facades.obj", "missing.obj"]), entry("2", "#ee6677", ["missing.obj"])], "1", NONE_HIDDEN, BY_FILE, null);
  expect(groups.map(verticesOf)).toEqual([3, null]);
});

test("a project that lists no criteria draws all its stored files in one group without a colour", () => {
  const all = meshOf(7);
  const groups = testSurfaceGroupsOf([], null, NONE_HIDDEN, BY_FILE, all);
  expect(groups).toEqual([{ id: "", name: "", colour: null, off: false, shown: true, geometry: all }]);
  expect(testSurfaceGroupsOf([], null, NONE_HIDDEN, {}, null)).toEqual([{ id: "", name: "", colour: null, off: false, shown: true, geometry: null }]);
});

test("one criterion draws its own files in its colour", () => {
  const groups = testSurfaceGroupsOf([ROOFS], "3", NONE_HIDDEN, BY_FILE, null);
  expect(groups.map(({ colour }) => colour)).toEqual(["#228833"]);
  expect(groups.map(verticesOf)).toEqual([12]);
});

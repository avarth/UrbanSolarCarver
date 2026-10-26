// The test surfaces the 3D view draws, by criterion: each criterion's files joined into one mesh, in the criterion's colour.
import type * as THREE from "three";
import type { CriterionEntry } from "../api_client/client";
import type { TestSurfaceGroup } from "../viewer_overlays/ViewerPane";
import { joinedGeometryOf } from "./input_meshes";

/**
 * The criterion each drawn file belongs to, by file name. A file several criteria list belongs to the selected criterion when it
 * lists it and its toggle is on, else to the first criterion in chain order that lists it and whose toggle is on (*hidden*: the ids of
 * the criteria whose toggle is off); a file whose criteria are all hidden, and a stored file no criterion lists, has no owner.
 */
export function testSurfaceOwners(criteria: readonly CriterionEntry[], selectedId: string | null, hidden: ReadonlySet<string>): Map<string, string> {
  const shownCriteria = criteria.filter((criterion) => !hidden.has(criterion.id));
  const selected = shownCriteria.find((criterion) => criterion.id === selectedId);
  const owners = new Map<string, string>();
  for (const criterion of selected === undefined ? shownCriteria : [selected, ...shownCriteria]) {
    for (const file of criterion.test_surface_files ?? []) {
      if (!owners.has(file)) owners.set(file, criterion.id);
    }
  }
  return owners;
}

/**
 * One group per criterion, in chain order, holding the files it owns (see testSurfaceOwners). The groups of a project that lists no
 * criteria are one group of *allFiles*, without a colour.
 */
export function testSurfaceGroupsOf(criteria: readonly CriterionEntry[], selectedId: string | null, hidden: ReadonlySet<string>,
                                    byFile: Record<string, THREE.BufferGeometry>, allFiles: THREE.BufferGeometry | null): TestSurfaceGroup[] {
  if (criteria.length === 0) return [{ id: "", name: "", colour: null, off: false, shown: true, geometry: allFiles }];
  const owners = testSurfaceOwners(criteria, selectedId, hidden);
  return criteria.map((criterion) => {
    const files = (criterion.test_surface_files ?? []).filter((file) => owners.get(file) === criterion.id);
    return { id: criterion.id, name: criterion.name, colour: criterion.colour, off: criterion.bypassed, shown: !hidden.has(criterion.id),
             geometry: joinedGeometryOf(byFile, files) };
  });
}

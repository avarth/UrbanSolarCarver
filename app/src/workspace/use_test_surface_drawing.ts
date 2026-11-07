// What the 3D view draws of the criteria's test surfaces: their groups by criterion, and the layer menu's toggle of each.
import { useState } from "react";
import type { BufferGeometry } from "three";
import type { CriterionEntry } from "../api_client/client";
import type { InputGeometry } from "../steps/input_meshes";
import { testSurfaceGroupsOf, testSurfaceOwners } from "../steps/test_surface_groups";

export function useTestSurfaceDrawing(criteriaList: CriterionEntry[], selected: CriterionEntry | null, testSurfacesMesh: InputGeometry, testSurfaces: BufferGeometry | null) {
  // Each criterion's test surfaces are drawn in its colour; the layers menu has a toggle for each (kept here, so a change of criterion or
  // of step leaves it as it is; a new criterion starts with its toggle on).
  const [hiddenTestSurfaceCriteria, setHiddenTestSurfaceCriteria] = useState<ReadonlySet<string>>(new Set());
  const setTestSurfacesShown = (ids: readonly string[], shown: boolean) => setHiddenTestSurfaceCriteria((hidden) => {
    const next = new Set(hidden);
    for (const id of ids) {
      if (shown) next.delete(id);
      else next.add(id);
    }
    return next;
  });
  // A criterion gone takes its toggle with it.
  const hiddenOfListedCriteria = new Set([...hiddenTestSurfaceCriteria].filter((id) => criteriaList.some((entry) => entry.id === id)));
  if (hiddenOfListedCriteria.size !== hiddenTestSurfaceCriteria.size) setHiddenTestSurfaceCriteria(hiddenOfListedCriteria);
  // What the groups hold, not which criterion is selected: a selection that moves no file to another criterion draws nothing again.
  const testSurfaceDrawingKey = JSON.stringify([criteriaList.map((entry) => [entry.id, entry.name, entry.colour, entry.bypassed]),
                                                [...testSurfaceOwners(criteriaList, selected?.id ?? null, hiddenTestSurfaceCriteria)].sort(),
                                                [...hiddenTestSurfaceCriteria].sort()]);
  // The groups are kept until the key or the meshes change; a useMemo would make them again for each new list of the criteria.
  const newTestSurfaceDrawing = () => ({
    key: testSurfaceDrawingKey, byFile: testSurfacesMesh.byFile, allFiles: testSurfaces,
    groups: testSurfaceGroupsOf(criteriaList, selected?.id ?? null, hiddenTestSurfaceCriteria, testSurfacesMesh.byFile, testSurfaces),
  });
  const [testSurfaceDrawing, setTestSurfaceDrawing] = useState(newTestSurfaceDrawing);
  if (testSurfaceDrawing.key !== testSurfaceDrawingKey || testSurfaceDrawing.byFile !== testSurfacesMesh.byFile || testSurfaceDrawing.allFiles !== testSurfaces) {
    setTestSurfaceDrawing(newTestSurfaceDrawing());
  }
  return { testSurfaceGroups: testSurfaceDrawing.groups, setTestSurfacesShown };
}

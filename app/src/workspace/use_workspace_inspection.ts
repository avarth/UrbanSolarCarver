// Inspect as the workspace holds it: the inspection, whether a save or restore changed the surfaces in this visit, and what the app is
// told so it can ask before Inspect is left.
import { useEffect, useEffectEvent, useLayoutEffect, useRef, useState } from "react";
import type { InspectTurns } from "../inspect/UnsavedTurnsDialog";
import { useInspection } from "../inspect/use_inspection";

interface WorkspaceInspectionContext {
  inspecting: boolean;
  refreshStageStatus: () => void;
  reloadStoredFiles: () => Promise<unknown>;
  onUnsavedChange?: (unsaved: boolean) => void;
  onTurnsReady?: (turns: InspectTurns | null) => void;
}

export function useWorkspaceInspection({ inspecting, refreshStageStatus, reloadStoredFiles, onUnsavedChange, onTurnsReady }: WorkspaceInspectionContext) {
  // Inspect: the inspection of the input files, read when Inspect opens. A save or restore writes a stored test surface file, which
  // the stage status (the criteria and studies that list it go out of date) and the meshes Design draws follow.
  // A save or restore in this visit to Inspect: the panel then says which analyses it left out of date.
  const [surfacesChanged, setSurfacesChanged] = useState(false);
  if (surfacesChanged && !inspecting) setSurfacesChanged(false);
  const inspection = useInspection({
    active: inspecting,
    onSaved: () => {
      setSurfacesChanged(true);
      refreshStageStatus();
      void reloadStoredFiles();
    },
  });
  const latestInspection = useRef(inspection);
  useLayoutEffect(() => {
    latestInspection.current = inspection;
  });
  // Leaving Inspect asks while turns are not saved and while a save or restore is under way (its refusal is then shown, not lost).
  const inspectUnsavedOrUnderWay = inspection.unsaved || inspection.busy;
  const tellInspectUnsaved = useEffectEvent((unsaved: boolean) => onUnsavedChange?.(unsaved));
  useEffect(() => tellInspectUnsaved(inspectUnsavedOrUnderWay), [inspectUnsavedOrUnderWay]);
  const tellInspectTurns = useEffectEvent((turns: InspectTurns | null) => onTurnsReady?.(turns));
  useEffect(() => {
    tellInspectTurns({
      saveAll: () => latestInspection.current.saveAll(), discardAll: () => latestInspection.current.discardAll(),
      waitForUnderWay: () => latestInspection.current.waitForUnderWay(), underWay: () => latestInspection.current.underWayNow(),
      unsaved: () => latestInspection.current.unsavedNow(),
    });
    return () => {
      tellInspectTurns(null);
      tellInspectUnsaved(false);
    };
  }, []);
  return { inspection, surfacesChanged };
}

// What Inspect puts over the 3D view: the Geometries panel at the top left (FilesPanel). The view itself draws the orientation of the test
// surfaces (the inspect_surfaces layer, given by useInspectView); ProjectWorkspace gives both to ViewerPane. Nothing in Inspect runs
// the engine or changes a setting; Save and Restore original wait while a run of the project goes on.
import type { ReactNode } from "react";
import { messages } from "../messages";
import type { Point3 } from "../viewer/local_origin";
import { FilesPanel } from "./FilesPanel";
import type { InspectionHook } from "./use_inspection";
import "./inspect.css";

interface InspectViewProps {
  inspection: InspectionHook;
  origin: Point3;
  /** Why Save and Restore original cannot be pressed now (a run of the project); null when they can. */
  saveDisabledReason: string | null;
  /** The notice of input files changed in the project folder or missing from it, at the top of the Geometries panel. */
  notice?: ReactNode;
}

/** After a save or restore that made analyses out of date: says so, with the way back to Carve, where the analysis runs. */
export function AnalysisOutOfDateNotice({ criteria, onGoToCarve }: { criteria: number; onGoToCarve?: () => void }) {
  return (
    <div className="input-changes-notice" role="status">
      <p>{messages.analysisOutOfDateAfterSave(criteria)}</p>
      {onGoToCarve !== undefined && <button type="button" className="secondary-button" onClick={onGoToCarve}>{messages.goToCarve}</button>}
    </div>
  );
}

export function InspectView({ inspection, origin, saveDisabledReason, notice }: InspectViewProps) {
  return (
    <div className="inspect-view" data-covers-view-left>
      <FilesPanel inspection={inspection} origin={origin} saveDisabledReason={saveDisabledReason} notice={notice} />
    </div>
  );
}

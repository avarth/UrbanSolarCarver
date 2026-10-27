// What Inspect puts over the 3D view: the Files panel at the top left (FilesPanel). The view itself draws the orientation of the test
// surfaces (the inspect_surfaces layer, given by useInspectView); ProjectWorkspace gives both to ViewerPane. Nothing in Inspect runs
// the engine or changes a setting; Save and Restore original wait while a run of the project goes on.
import type { ReactNode } from "react";
import type { Point3 } from "../viewer/local_origin";
import { FilesPanel } from "./FilesPanel";
import type { InspectionHook } from "./use_inspection";
import "./inspect.css";

interface InspectViewProps {
  inspection: InspectionHook;
  origin: Point3;
  /** Why Save and Restore original cannot be pressed now (a run of the project); null when they can. */
  saveDisabledReason: string | null;
  /** The notice of input files changed in the project folder or missing from it, at the top of the Files panel. */
  notice?: ReactNode;
}

export function InspectView({ inspection, origin, saveDisabledReason, notice }: InspectViewProps) {
  return (
    <div className="inspect-view">
      <FilesPanel inspection={inspection} origin={origin} saveDisabledReason={saveDisabledReason} notice={notice} />
    </div>
  );
}

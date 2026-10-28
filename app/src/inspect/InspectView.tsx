// What Inspect puts over the 3D view: the Files panel at the top left (FilesPanel) and the Sun panel under it (SunPanel). The view itself draws the orientation of the test
// surfaces (the inspect_surfaces layer, given by useInspectView); ProjectWorkspace gives both to ViewerPane. Nothing in Inspect runs
// the engine or changes a setting; Save and Restore original wait while a run of the project goes on.
import type { ReactNode } from "react";
import type { Point3 } from "../viewer/local_origin";
import { FilesPanel } from "./FilesPanel";
import { SunPanel } from "./SunPanel";
import type { InspectionHook } from "./use_inspection";
import type { SunStudyHook } from "./use_sun_study";
import "./inspect.css";

interface InspectViewProps {
  inspection: InspectionHook;
  sunStudy: SunStudyHook;
  origin: Point3;
  /** Why Save and Restore original cannot be pressed now (a run of the project); null when they can. */
  saveDisabledReason: string | null;
  /** The notice of input files changed in the project folder or missing from it, at the top of the Files panel. */
  notice?: ReactNode;
}

export function InspectView({ inspection, sunStudy, origin, saveDisabledReason, notice }: InspectViewProps) {
  return (
    <div className="inspect-view">
      <FilesPanel inspection={inspection} origin={origin} saveDisabledReason={saveDisabledReason} notice={notice} />
      <SunPanel sunStudy={sunStudy} />
    </div>
  );
}

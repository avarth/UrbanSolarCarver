// The Site step (UX 5.2, spec 7.1; named Inputs until design/new-project-setup.md): the site's geometry, one box per input role with
// its files (the maximum volume, the existing surroundings and the terrain, which are optional), "Add files" (picker, or drop the
// files onto the box) and a remove button per file; under the boxes the size of all inputs together and the warning when it does not
// look like metres. The boxes are common/InputBox.tsx; then the project's test surfaces as surface sets (SurfaceSetsBox), which the
// criteria and studies choose among; the weather file is in the project settings (ProjectSettingsDialog).
// While a run of the project is active the service refuses uploads and removals, so both are disabled with the reason. Under the boxes,
// how many removed files the project folder keeps (inputs/removed/), with Show to open that folder.
import { useState, type ReactNode } from "react";
import type { InputFileInfo } from "../api_client/client";
import { InputBox, type AddInputFiles, type InputRole, type RemoveInputFile } from "../common/InputBox";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import type { Bounds3 } from "../viewer/local_origin";
import { sizeWarning } from "../viewer/size_check";
import { formatNumber, formattedNumber } from "../format_numbers";
import { plainModeName } from "../modes";
import "../theme/panels.css";

/** The roles of the Site step: the site's geometry (the test surfaces are each criterion's, the weather file is in Settings). */
export const INPUT_ROLES: readonly InputRole[] = ["max_volume", "context", "terrain"];
/**
 * "Carved by Daylight, then Sun hours. ..." for a project that was carved further with an earlier version of the app (its
 * record stays, spec 9); null for one that was not.
 */
export function carvedByNote(chain: readonly { mode: string }[]): string | null {
  return chain.length === 0 ? null : messages.carvedBy(chain.map((step) => plainModeName(step.mode)).join(", then "));
}

const NO_FILES: InputFileInfo[] = [];

/** "52 × 44 × 30 m": whole metres from 10 m up, finer below. */
export function inputsSizeText(bounds: Bounds3): string {
  const sides = [0, 1, 2].map((axis) => bounds[1][axis] - bounds[0][axis]);
  const sideText = (side: number) => (side >= 10 ? formatNumber(side) : formattedNumber(side));
  return messages.inputsSize(sideText(sides[0]), sideText(sides[1]), sideText(sides[2]));
}

interface InputsStepProps {
  /** The files of each role; a role left out has none. */
  files: Partial<Record<InputRole, InputFileInfo[]>>;
  /** The bounds of all input meshes together, null before any is shown. */
  inputsBounds: Bounds3 | null;
  onAddFiles: AddInputFiles;
  onRemoveFile: RemoveInputFile;
  disabledReason: string | null;
  /** Per mesh role, the files the 3D view cannot draw (one text each naming the file). */
  drawingProblems?: Partial<Record<InputRole, string[]>>;
  /** How carving further made the maximum volume; null for one the user added. */
  maxVolumeNote?: string | null;
  /** In place of the maximum volume's box: the choice between a maximum volume and a site, or the Site card (sites/SiteInput.tsx). */
  maxVolumeBox?: ReactNode;
  /** At the end of the maximum volume's box: the link to a site instead. */
  maxVolumeFooter?: ReactNode;
  /** After the terrain: the project's test surfaces as surface sets (SurfaceSetsBox). */
  testSurfacesBox?: ReactNode;
  /** The removed files kept under inputs/removed/ of the project folder, and opening that folder; absent: no line about them. */
  removedFiles?: { count: number; show: () => Promise<string | null> };
}

export function InputsStep({ files, inputsBounds, onAddFiles, onRemoveFile, disabledReason, drawingProblems = {},
                             maxVolumeNote = null, maxVolumeBox, maxVolumeFooter = null, testSurfacesBox = null, removedFiles }: InputsStepProps) {
  const warning = inputsBounds === null ? null : sizeWarning(inputsBounds);
  const [showProblem, setShowProblem] = useState<string | null>(null);
  return (
    <div className="inputs-step">
      {INPUT_ROLES.map((role) => (role === "max_volume" && maxVolumeBox !== undefined ? <div key={role}>{maxVolumeBox}</div> : (
        <InputBox key={role} role={role} files={files[role] ?? NO_FILES}
                  onAddFiles={onAddFiles} onRemoveFile={onRemoveFile} disabledReason={disabledReason} drawingProblems={drawingProblems[role]}
                  note={role === "max_volume" ? maxVolumeNote : null} footer={role === "max_volume" ? maxVolumeFooter : null} />
      )))}
      {testSurfacesBox}
      {removedFiles !== undefined && removedFiles.count > 0 && (
        <p className="inputs-removed">
          {messages.removedFilesKept(removedFiles.count)}{" "}
          <button type="button" className="link-button" onClick={() => { void removedFiles.show().then(setShowProblem); }}>{messages.showRemovedFiles}</button>
          {showProblem !== null && <span className="input-box-problem"><WarningIcon />{showProblem}</span>}
        </p>
      )}
      {inputsBounds !== null && (
        <div className="inputs-size">
          <div className="inputs-size-title">{messages.inputsSizeTitle}</div>
          <div>{inputsSizeText(inputsBounds)}</div>
          {warning !== null && <p className="inputs-size-warning"><WarningIcon />{warning}</p>}
        </div>
      )}
    </div>
  );
}

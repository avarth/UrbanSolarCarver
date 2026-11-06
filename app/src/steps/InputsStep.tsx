// The Inputs step (UX 5.2, spec 7.1): the site only, one box per input role with its files (the maximum volume, the existing
// surroundings and the terrain, which are optional, and the weather file), "Add files" (picker, or drop the files onto the box) and
// a remove button per file; under the boxes the size of all inputs together and the warning when it does not look like metres.
// The boxes are common/InputBox.tsx; the test surfaces belong to the criteria (ProtectsBox).
// While a run of the project is active the service refuses uploads and removals, so both are disabled with the reason.
import type { InputFileInfo } from "../api_client/client";
import { InputBox, type AddInputFiles, type InputRole, type RemoveInputFile } from "../common/InputBox";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import type { Bounds3 } from "../viewer/local_origin";
import { sizeWarning } from "../viewer/size_check";
import { formatNumber, formattedNumber } from "../format_numbers";
import { plainModeName } from "../modes";
import "../theme/panels.css";

/** The roles of the Inputs step: the site's (the test surfaces are each criterion's). */
export const INPUT_ROLES: readonly InputRole[] = ["max_volume", "context", "terrain", "weather"];
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
  weatherLocation: string | null;
  weatherHint: string;
  /** The bounds of all input meshes together, null before any is shown. */
  inputsBounds: Bounds3 | null;
  onAddFiles: AddInputFiles;
  onRemoveFile: RemoveInputFile;
  disabledReason: string | null;
  /** Per mesh role, the files the 3D view cannot draw (one text each naming the file). */
  drawingProblems?: Partial<Record<InputRole, string[]>>;
  /** How carving further made the maximum volume; null for one the user added. */
  maxVolumeNote?: string | null;
}

export function InputsStep({ files, weatherLocation, weatherHint, inputsBounds, onAddFiles, onRemoveFile, disabledReason, drawingProblems = {},
                             maxVolumeNote = null }: InputsStepProps) {
  const warning = inputsBounds === null ? null : sizeWarning(inputsBounds);
  return (
    <div className="inputs-step">
      {INPUT_ROLES.map((role) => (
        <InputBox key={role} role={role} files={files[role] ?? NO_FILES} weatherLocation={weatherLocation} weatherHint={weatherHint}
                  onAddFiles={onAddFiles} onRemoveFile={onRemoveFile} disabledReason={disabledReason} drawingProblems={drawingProblems[role]}
                  note={role === "max_volume" ? maxVolumeNote : null} />
      ))}
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

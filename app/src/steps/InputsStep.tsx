// The Inputs step (UX 5.2): one box per input role with its files (the existing surroundings and the terrain are optional), "Add files" (picker, or drop the files onto the box) and a
// remove button per file; under the boxes the size of all inputs together and the warning when it does not look like metres.
// While a run of the project is active the service refuses uploads and removals, so both are disabled with the reason.
import { useId, useRef, useState, type DragEvent } from "react";
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import type { Bounds3 } from "../viewer/local_origin";
import { sizeWarning } from "../viewer/size_check";
import { formatNumber, formattedNumber } from "./format_numbers";
import "./steps.css";

export type InputRole = "max_volume" | "test_surfaces" | "context" | "terrain" | "weather";
export const INPUT_ROLES: readonly InputRole[] = ["max_volume", "test_surfaces", "context", "terrain", "weather"];
/** The mesh roles a run can do without: no "Required" beside their titles. */
const OPTIONAL_MESH_ROLES: readonly InputRole[] = ["context", "terrain"];

const MESH_FILE_TYPES = ".ply,.obj,.stl,.glb";
const WEATHER_FILE_TYPE = ".epw";

/** Adds the files to the role; resolves with a message per file that could not be added (empty when all were). */
export type AddInputFiles = (role: InputRole, files: File[]) => Promise<string[]>;
/** Removes a file of the role; resolves with the reason it could not be removed, or null. */
export type RemoveInputFile = (role: InputRole, fileName: string) => Promise<string | null>;

interface InputBoxProps {
  role: InputRole;
  files: InputFileInfo[];
  weatherLocation: string | null;
  /** The weather box's line: which modes need the file. */
  weatherHint: string;
  onAddFiles: AddInputFiles;
  onRemoveFile: RemoveInputFile;
  /** Why files cannot be added or removed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The weather box under the mode tiles, where the chosen mode needs the file: not titled optional there. */
  weatherNeeded?: boolean;
  /** The files of the box that the 3D view cannot draw, one text each naming the file. */
  drawingProblems?: string[];
  /** A line under the files: for the maximum volume, how carving further made it (CarveFurther.tsx). */
  note?: string | null;
}

const TITLES: Record<InputRole, string> = {
  max_volume: messages.maxVolumeTitle,
  test_surfaces: messages.testSurfacesTitle,
  context: messages.contextTitle,
  terrain: messages.terrainTitle,
  weather: messages.weatherFileTitle,
};

const MESH_HINTS: Record<Exclude<InputRole, "weather">, string> = {
  max_volume: messages.maxVolumeHint,
  test_surfaces: messages.testSurfacesHint,
  context: messages.contextHint,
  terrain: messages.terrainHint,
};

function RemoveIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
    </svg>
  );
}

/** One input box: dashed and with its hint while empty, solid with one row per file once it has files. */
const NO_PROBLEMS: string[] = [];

export function InputBox({ role, files, weatherLocation, weatherHint, onAddFiles, onRemoveFile, disabledReason, weatherNeeded = false,
                           drawingProblems = NO_PROBLEMS, note = null }: InputBoxProps) {
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const isWeather = role === "weather";
  const filled = files.length > 0;
  const disabled = disabledReason !== null || busy;
  const hint = role === "weather" ? weatherHint : MESH_HINTS[role];
  const badge = isWeather ? messages.weatherFileExtension : OPTIONAL_MESH_ROLES.includes(role) ? null : messages.requiredInput;

  const add = async (chosen: File[]) => {
    const toAdd = isWeather ? chosen.slice(0, 1) : chosen;     // one weather file per project
    if (disabled || toAdd.length === 0) return;
    setBusy(true);
    setProblems([]);
    try {
      setProblems(await onAddFiles(role, toAdd));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (fileName: string) => {
    if (disabled) return;
    setBusy(true);
    setProblems([]);
    try {
      const problem = await onRemoveFile(role, fileName);
      if (problem !== null) setProblems([problem]);
    } finally {
      setBusy(false);
    }
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void add(Array.from(event.dataTransfer.files));
  };

  const addButton = (
    <button type="button" className="input-add" disabled={disabled} onClick={() => picker.current?.click()}>
      {isWeather && filled ? messages.replaceFile : messages.addFiles}
    </button>
  );
  const boxClass = ["input-box", filled ? "input-box-filled" : "input-box-empty", dragging && !disabled ? "input-box-drop-target" : ""].join(" ");
  return (
    <section className={boxClass} aria-labelledby={titleId}
             onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
             onDragLeave={() => setDragging(false)} onDrop={drop}>
      <input ref={picker} type="file" hidden multiple={!isWeather} accept={isWeather ? WEATHER_FILE_TYPE : MESH_FILE_TYPES}
             onChange={(event) => { void add(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
      <div className="input-box-title-row">
        <h3 id={titleId} className="input-box-title">{isWeather && weatherNeeded ? messages.weatherFileNeededTitle : TITLES[role]}</h3>
        {filled ? addButton : badge !== null && <span className="input-box-required">{badge}</span>}
      </div>
      {!filled && (
        <>
          <p className="input-box-hint">{hint}</p>
          <div className="input-box-actions">{addButton}<span className="input-box-drop-hint">{messages.orDropThemHere}</span></div>
        </>
      )}
      {filled && (
        <ul className="input-file-list">
          {files.map((file) => (
            <li key={file.name} className="input-file-row">
              <div>
                <div className="input-file-name">{file.name}</div>
                <div className="input-file-detail">{isWeather ? weatherLocation ?? "" : messages.triangleCount(file.triangle_count)}</div>
              </div>
              <button type="button" className="input-remove" aria-label={messages.removeFile(file.name)} title={messages.removeFile(file.name)}
                      disabled={disabled} onClick={() => void remove(file.name)}>
                <RemoveIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
      {filled && note !== null && <p className="input-box-hint">{note}</p>}
      {disabledReason !== null && <p className="input-box-reason">{disabledReason}</p>}
      {[...problems, ...drawingProblems].map((problem) => <p key={problem} className="input-box-problem"><WarningIcon />{problem}</p>)}
    </section>
  );
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

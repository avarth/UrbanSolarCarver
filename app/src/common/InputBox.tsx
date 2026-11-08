// One box of input files (UX 5.2): dashed with its hint while empty, one row per file with a remove button once it has files,
// "Add files" by the picker or by dropping files onto the box. The Inputs step draws one per role of the site, a criterion's
// and a study's test surfaces one each (ProtectsBox). While a run is active the service refuses uploads and removals, so both
// are disabled with the reason.
import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import { ApiError, failureTextOf, type InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import { Subheading } from "../settings_form/Subheading";
import "../theme/panels.css";

export type InputRole = "max_volume" | "test_surfaces" | "context" | "terrain" | "weather";
/** The mesh roles a run can do without: no "Required" beside their titles. */
const OPTIONAL_MESH_ROLES: readonly InputRole[] = ["context", "terrain"];

const MESH_FILE_TYPES = ".ply,.obj,.stl,.glb";
const WEATHER_FILE_TYPE = ".epw";

/** Why a request about an input file failed, in words for its box. */
export function inputProblemText(error: unknown, fileName: string): string {
  if (error instanceof ApiError && error.status === 409) return messages.runInProgress;
  const detail = failureTextOf(error);
  return detail.includes(fileName) ? detail : messages.fileProblem(fileName, detail);
}

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
  /** Absent: the box offers no adding (no button, no drop), only its files and their removal (a study's stored files). */
  onAddFiles?: AddInputFiles;
  onRemoveFile: RemoveInputFile;
  /** Why files cannot be added or removed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The weather box under the mode tiles, where the chosen mode needs the file: not titled optional there. */
  weatherNeeded?: boolean;
  /** The files of the box that the 3D view cannot draw, one text each naming the file. */
  drawingProblems?: string[];
  /** A line under the files: for the maximum volume, how carving further made it (carvedByNote). */
  note?: string | null;
  /** The box's title, hint and add button in place of the role's (a criterion's test surfaces: the hint of its mode). */
  title?: string;
  /** The box has no heading, its title names it for screen readers: a section around the box says it already (a criterion's Test surfaces). */
  titleHidden?: boolean;
  hint?: string;
  addLabel?: string;
  /** Whether the reason things are disabled is written here; false where another part says it (a criterion's Run analysis). */
  showsDisabledReason?: boolean;
  /** At the end of the box: the maximum volume's link to a site instead (sites/SiteInput.tsx). */
  footer?: ReactNode;
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
                           drawingProblems = NO_PROBLEMS, note = null, title, titleHidden = false, hint: hintGiven, addLabel,
                           showsDisabledReason = true, footer = null }: InputBoxProps) {
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const isWeather = role === "weather";
  const filled = files.length > 0;
  const disabled = disabledReason !== null || busy;
  const hint = hintGiven ?? (role === "weather" ? weatherHint : MESH_HINTS[role]);
  const badge = isWeather ? messages.weatherFileExtension : OPTIONAL_MESH_ROLES.includes(role) ? null : messages.requiredInput;

  const adds = onAddFiles !== undefined;
  const add = async (chosen: File[]) => {
    const toAdd = isWeather ? chosen.slice(0, 1) : chosen;     // one weather file per project
    if (disabled || toAdd.length === 0 || onAddFiles === undefined) return;
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

  const addButton = adds && (
    <button type="button" className="input-add" disabled={disabled} onClick={() => picker.current?.click()}>
      {isWeather && filled ? messages.replaceFile : addLabel ?? messages.addFiles}
    </button>
  );
  const shownTitle = title ?? (isWeather && weatherNeeded ? messages.weatherFileNeededTitle : TITLES[role]);
  const boxClass = ["input-box", filled ? "input-box-filled" : "input-box-empty", dragging && !disabled ? "input-box-drop-target" : ""].join(" ");
  const dropHandlers = adds ? {
    onDragOver: (event: DragEvent) => { event.preventDefault(); if (!disabled) setDragging(true); },
    onDragLeave: () => setDragging(false),
    onDrop: drop,
  } : {};
  return (
    <section className={boxClass} aria-labelledby={titleHidden ? undefined : titleId} aria-label={titleHidden ? shownTitle : undefined} {...dropHandlers}>
      {adds && (
        <input ref={picker} type="file" hidden multiple={!isWeather} accept={isWeather ? WEATHER_FILE_TYPE : MESH_FILE_TYPES}
               onChange={(event) => { void add(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
      )}
      <div className="input-box-title-row">
        {!titleHidden && <Subheading id={titleId} className="input-box-title">{shownTitle}</Subheading>}
        {filled ? addButton : badge !== null && <span className="input-box-required">{badge}</span>}
      </div>
      {!filled && (
        <>
          <p className="input-box-hint">{hint}</p>
          {adds && <div className="input-box-actions">{addButton}<span className="input-box-drop-hint">{messages.orDropThemHere}</span></div>}
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
      {disabledReason !== null && showsDisabledReason && <p className="input-box-reason">{disabledReason}</p>}
      {[...problems, ...drawingProblems].map((problem) => <p key={problem} className="input-box-problem"><WarningIcon />{problem}</p>)}
      {footer}
    </section>
  );
}

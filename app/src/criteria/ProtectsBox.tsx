// What a criterion protects (spec 7.2): the drop box of its test surfaces, titled "Test surfaces" as the Inputs box was (one
// criterion brings no new words) for screen readers only, as the panel's section around it has that title, with its files. While it has none the box offers to add test surfaces, with a hint of what its
// mode may protect (mode_tiles.json, protects_hint; hints only). With several criteria, the stored files the others use and this
// one does not follow under "Use a file from another criterion", each with a Use button (the file is stored once). A study's popover
// (Simulate) draws the box too: its files, to add to, and the project's stored files to use.
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { InputBox } from "../steps/InputsStep";
import { useDialogRequest } from "../steps/ProjectDialogs";
import { MODE_TILES } from "../steps/step_summaries";

interface ProtectsBoxProps {
  /** The criterion's test surface files, with their triangle counts. */
  files: InputFileInfo[];
  /** The criterion's mode, whose hint the empty box gives. */
  mode: string;
  /**
   * Adds the files to the criterion (or study); resolves with a message per file that could not be added (empty when all were).
   * Absent: the box offers no adding.
   */
  onAddFiles?: (files: File[]) => Promise<string[]>;
  /** The line of the empty box in place of the mode's hint. */
  hint?: string;
  /** The label of the add button in place of "Add test surfaces". */
  addLabel?: string;
  /** The title over the stored files to use, in place of "Use a file from another criterion". */
  otherFilesTitle?: string;
  /** Takes the file out of the criterion; resolves with the reason it could not, or null. */
  onRemoveFile: (fileName: string) => Promise<string | null>;
  /** Why files cannot be added or removed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The files the 3D view cannot draw, one text each naming the file. */
  drawingProblems?: string[];
  /** The stored files other criteria use and this one does not. */
  otherFiles?: string[];
  /** Lets the criterion use a stored file too; resolves with the reason it could not, or null. */
  onUseFile?: (fileName: string) => Promise<string | null>;
}

export function protectsHintOf(mode: string): string {
  return MODE_TILES.find((tile) => tile.engine_name === mode)?.protects_hint ?? messages.testSurfacesHint;
}

interface FilesOfOtherCriteriaProps {
  files: string[];
  onUseFile: (fileName: string) => Promise<string | null>;
  disabledReason: string | null;
  title: string;
}

function FilesOfOtherCriteria({ files, onUseFile, disabledReason, title }: FilesOfOtherCriteriaProps) {
  const { problem, busy, send } = useDialogRequest(() => {});
  const use = (fileName: string) => send(() => onUseFile(fileName));
  return (
    <div className="protects-reuse">
      <p className="protects-reuse-title">{title}</p>
      <ul className="protects-reuse-files">
        {files.map((name) => (
          <li key={name}>
            <span className="protects-reuse-name">{name}</span>
            <button type="button" className="secondary-button" aria-label={messages.useFileNamed(name)} disabled={busy || disabledReason !== null}
                    onClick={() => void use(name)}>
              {messages.useFile}
            </button>
          </li>
        ))}
      </ul>
      {problem !== null && <p className="input-box-problem" role="alert">{problem}</p>}
    </div>
  );
}

export function ProtectsBox({ files, mode, onAddFiles, onRemoveFile, disabledReason, drawingProblems, otherFiles = [], onUseFile, hint,
                              addLabel = messages.addTestSurfaces, otherFilesTitle = messages.useFileOfOtherCriterion }: ProtectsBoxProps) {
  return (
    <div className="protects">
      <InputBox role="test_surfaces" files={files} hint={hint ?? protectsHintOf(mode)} addLabel={addLabel} titleHidden
                weatherLocation={null} weatherHint="" onAddFiles={onAddFiles === undefined ? undefined : (_role, chosen) => onAddFiles(chosen)}
                onRemoveFile={(_role, fileName) => onRemoveFile(fileName)} disabledReason={disabledReason} drawingProblems={drawingProblems}
                showsDisabledReason={false} />
      {otherFiles.length > 0 && onUseFile !== undefined && (
        <FilesOfOtherCriteria files={otherFiles} onUseFile={onUseFile} disabledReason={disabledReason} title={otherFilesTitle} />
      )}
    </div>
  );
}

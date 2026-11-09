// What a criterion protects (spec 7.2): the drop box of its test surfaces, titled "Test surfaces" as the Inputs box was (one
// criterion brings no new words) for screen readers only, as the panel's section around it has that title, with its files. While it has none the box offers to add test surfaces, with a hint of what its
// mode may protect (mode_tiles.json, protects_hint; hints only). With several criteria, the stored files the others use and this
// one does not follow under "Use a file from another criterion", each with a Use button (the file is stored once). A study's popover
// (Simulate) draws the box too: its files, to add to, and the project's stored files to use.
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { InputBox } from "./InputBox";
import { useState, type FormEvent } from "react";
import { ActionMenu } from "./ActionMenu";
import { DialogButtons, DialogFrame, useDialogRequest } from "./dialogs";
import { MODE_TILES } from "../modes";

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
  /** Opens picking on the surroundings for this criterion (design/test-surfaces-on-context.md); absent without surroundings. */
  onPickFromSurroundings?: () => void;
  /** Shows a surface set by another name; resolves with the reason it could not, or null. */
  onRenameSet?: (fileName: string, name: string) => Promise<string | null>;
  /** Opens picking on the set's picks (Edit picks). */
  onEditPicks?: (fileName: string) => void;
  /** The name each stored file is shown by (its surface set's), for the files of other criteria. */
  setNames?: Readonly<Record<string, string>>;
}

export function protectsHintOf(mode: string): string {
  return `${MODE_TILES.find((tile) => tile.engine_name === mode)?.protects_hint ?? messages.testSurfacesHint} ${messages.flatPanelsHint}`;
}

interface FilesOfOtherCriteriaProps {
  files: string[];
  onUseFile: (fileName: string) => Promise<string | null>;
  disabledReason: string | null;
  title: string;
}

function FilesOfOtherCriteria({ files, onUseFile, disabledReason, title, setNames = {} }: FilesOfOtherCriteriaProps & { setNames?: Readonly<Record<string, string>> }) {
  const { problem, busy, send } = useDialogRequest(() => {});
  const use = (fileName: string) => send(() => onUseFile(fileName));
  return (
    <div className="protects-reuse">
      <p className="protects-reuse-title">{title}</p>
      <ul className="protects-reuse-files">
        {files.map((name) => (
          <li key={name}>
            <span className="protects-reuse-name">{setNames[name] ?? name}</span>
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
                              addLabel = messages.addTestSurfaces, otherFilesTitle = messages.useFileOfOtherCriterion, onPickFromSurroundings,
                              onRenameSet, onEditPicks, setNames }: ProtectsBoxProps) {
  const [renaming, setRenaming] = useState<InputFileInfo | null>(null);
  const pickButton = onPickFromSurroundings === undefined ? null : (
    <button type="button" className="input-add" disabled={disabledReason !== null} onClick={onPickFromSurroundings}>{messages.pickFromSurroundings}</button>
  );
  const fileMenu = onRenameSet === undefined ? undefined : (file: InputFileInfo) => (
    <ActionMenu label={messages.surfaceSetActions(file.shown_name ?? file.name)} symbol={<span aria-hidden="true">⋯</span>}
                onChoose={(key) => {
                  if (key === "rename") setRenaming(file);
                  else if (key === "edit_picks") onEditPicks?.(file.name);
                }}
                items={[
                  { key: "rename", label: messages.renameSurfaceSet, disabledReason },
                  ...(file.picked === true && onEditPicks !== undefined ? [{ key: "edit_picks", label: messages.editPicks, disabledReason }] : []),
                ]} />
  );
  return (
    <div className="protects">
      <InputBox role="test_surfaces" files={files} hint={hint ?? protectsHintOf(mode)} addLabel={addLabel} titleHidden
                weatherLocation={null} weatherHint="" onAddFiles={onAddFiles === undefined ? undefined : (_role, chosen) => onAddFiles(chosen)}
                onRemoveFile={(_role, fileName) => onRemoveFile(fileName)} disabledReason={disabledReason} drawingProblems={drawingProblems}
                showsDisabledReason={false} extraAction={pickButton} fileMenu={fileMenu} />
      {otherFiles.length > 0 && onUseFile !== undefined && (
        <FilesOfOtherCriteria files={otherFiles} onUseFile={onUseFile} disabledReason={disabledReason} title={otherFilesTitle} setNames={setNames} />
      )}
      {renaming !== null && onRenameSet !== undefined && (
        <RenameSetDialog file={renaming} onRename={(name) => onRenameSet(renaming.name, name)} onClose={() => setRenaming(null)} />
      )}
    </div>
  );
}

/** Asks for a surface set's new name; the request's refusal is shown under the field. */
function RenameSetDialog({ file, onRename, onClose }: { file: InputFileInfo; onRename: (name: string) => Promise<string | null>; onClose: () => void }) {
  const shown = file.shown_name ?? file.name;
  const [name, setName] = useState(shown);
  const { problem, busy, send } = useDialogRequest(onClose);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void send(() => onRename(name));
  };
  return (
    <DialogFrame title={messages.renameSurfaceSetTitle(shown)} busy={busy} onClose={onClose}>
      <form className="project-dialog-form" onSubmit={submit}>
        <input type="text" className="setting-number project-dialog-field" aria-label={messages.surfaceSetName} value={name} maxLength={80}
               data-autofocus onChange={(event) => setName(event.target.value)} />
        {problem !== null && <p className="input-box-problem" role="alert">{problem}</p>}
        <DialogButtons confirmLabel={messages.renameSurfaceSet} confirmDisabled={!name.trim() || name.trim() === shown} busy={busy} onCancel={onClose} />
      </form>
    </DialogFrame>
  );
}

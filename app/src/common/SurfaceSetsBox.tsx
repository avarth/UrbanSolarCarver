// The project's test surfaces as surface sets (design/test-surfaces-on-context.md): the Test surfaces box of the Site step lists every
// set, uploaded or picked on the surroundings, with the criteria and studies that use it. Add files uploads sets, From surroundings
// opens picking in the view; a set's menu renames it and, for a picked set, edits its picks. A set in use cannot be removed: it is
// switched off in its criteria and studies first (user, 2026-11-09). A criterion chooses among the sets with SurfaceSetSwitches.
import { useState, type FormEvent } from "react";
import type { InputFileInfo } from "../api_client/client";
import { listedWithAnd, messages } from "../messages";
import { MODE_TILES } from "../modes";
import { ActionMenu } from "./ActionMenu";
import { DialogButtons, DialogFrame, useDialogRequest } from "./dialogs";
import { InputBox, type AddInputFiles, type RemoveInputFile } from "./InputBox";

/** What a mode's test surfaces may be (mode_tiles.json, protects_hint), with the note on flat panels. */
export function protectsHintOf(mode: string): string {
  return `${MODE_TILES.find((tile) => tile.engine_name === mode)?.protects_hint ?? messages.testSurfacesHint} ${messages.flatPanelsHint}`;
}

interface SurfaceSetsBoxProps {
  /** The project's surface sets (its stored test surface files). */
  files: InputFileInfo[];
  onAddFiles: AddInputFiles;
  onRemoveFile: RemoveInputFile;
  /** Why sets cannot be added, picked or removed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The sets the 3D view cannot draw, one text each naming the file. */
  drawingProblems?: string[];
  /** Opens picking on the surroundings; absent without surroundings. */
  onPickFromSurroundings?: () => void;
  /** Shows a set by another name; resolves with the reason it could not, or null. */
  onRenameSet: (fileName: string, name: string) => Promise<string | null>;
  /** Opens picking on a picked set's picks (Edit picks). */
  onEditPicks: (fileName: string) => void;
}

export function SurfaceSetsBox({ files, onAddFiles, onRemoveFile, disabledReason, drawingProblems, onPickFromSurroundings, onRenameSet,
                                 onEditPicks }: SurfaceSetsBoxProps) {
  const [renaming, setRenaming] = useState<InputFileInfo | null>(null);
  const pickButton = onPickFromSurroundings === undefined ? null : (
    <button type="button" className="input-add" disabled={disabledReason !== null} onClick={onPickFromSurroundings}>{messages.pickFromSurroundings}</button>
  );
  const fileMenu = (file: InputFileInfo) => (
    <ActionMenu label={messages.surfaceSetActions(file.shown_name ?? file.name)} symbol={<span aria-hidden="true">⋯</span>}
                onChoose={(key) => {
                  if (key === "rename") setRenaming(file);
                  else if (key === "edit_picks") onEditPicks(file.name);
                }}
                items={[
                  { key: "rename", label: messages.renameSurfaceSet, disabledReason },
                  ...(file.picked === true && onPickFromSurroundings !== undefined ? [{ key: "edit_picks", label: messages.editPicks, disabledReason }] : []),
                ]} />
  );
  return (
    <>
      <InputBox role="test_surfaces" files={files} hint={messages.surfaceSetsHint} onAddFiles={onAddFiles} onRemoveFile={onRemoveFile}
                disabledReason={disabledReason} drawingProblems={drawingProblems} extraAction={pickButton} fileMenu={fileMenu}
                removeRefusal={(file) => ((file.used_by ?? []).length > 0 ? messages.surfaceSetInUse(listed(file.used_by ?? [])) : null)} />
      {renaming !== null && (
        <RenameSetDialog file={renaming} onRename={(name) => onRenameSet(renaming.name, name)} onClose={() => setRenaming(null)} />
      )}
    </>
  );
}

/** "A", "A and B", "A, B and C". */
export function listed(names: readonly string[]): string {
  return listedWithAnd([...names]);
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

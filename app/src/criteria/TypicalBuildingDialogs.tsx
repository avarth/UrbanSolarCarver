// The dialogs of the typical building's library (TypicalBuildingSheet): Save as new and Rename, which ask a name and refuse an empty
// one with the service's words before sending it, and Delete, which says what goes and waits for a confirmation. They are the
// project dialogs' frame (ProjectDialogs.tsx): modal, Escape or Cancel closes them, and a refusal of the service (a name in use, a
// name too long) is shown in its words with the dialog left open.
import { useId, useState, type FormEvent } from "react";
import { messages } from "../messages";
import { DialogButtons, DialogFrame, ProblemLine, useDialogRequest } from "../steps/ProjectDialogs";

interface LibraryNameDialogProps {
  title: string;
  /** The name the field starts with: the entry's own for Rename, empty for Save as new. */
  name: string;
  confirmLabel: string;
  /** Resolves with the service's reason when it refused the name, or null once saved. */
  onSave: (name: string) => Promise<string | null>;
  onClose: () => void;
}

export function LibraryNameDialog({ title, name, confirmLabel, onSave, onClose }: LibraryNameDialogProps) {
  const [newName, setNewName] = useState(name);
  const { problem, setProblem, busy, send } = useDialogRequest(onClose);
  const fieldId = useId();
  // The name as the service stores it: without the white space around it.
  const storedName = newName.trim();
  const unchanged = name !== "" && storedName === name;
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (busy || unchanged) return;
    if (storedName === "") return setProblem(messages.libraryEntryNeedsName);
    void send(() => onSave(storedName));
  };
  return (
    <DialogFrame title={title} busy={busy} onClose={onClose}>
      <form className="project-dialog-form" onSubmit={save}>
        <label htmlFor={fieldId}>{messages.libraryEntryName}</label>
        <input id={fieldId} className="setting-number project-dialog-field" value={newName} aria-invalid={problem !== null || undefined}
               onChange={(event) => { setNewName(event.target.value); setProblem(null); }} />
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={confirmLabel} confirmDisabled={unchanged} busy={busy} onCancel={onClose} />
      </form>
    </DialogFrame>
  );
}

interface DeleteLibraryEntryDialogProps {
  name: string;
  /** Resolves with the service's reason when it refused, or null once deleted. */
  onDelete: () => Promise<string | null>;
  onClose: () => void;
}

export function DeleteLibraryEntryDialog({ name, onDelete, onClose }: DeleteLibraryEntryDialogProps) {
  const { problem, busy, send } = useDialogRequest(onClose);
  const explanationId = useId();
  const remove = (event: FormEvent) => {
    event.preventDefault();
    if (!busy) void send(onDelete);
  };
  return (
    <DialogFrame title={messages.deleteLibraryEntryTitle} busy={busy} onClose={onClose} describedBy={explanationId}>
      <form className="project-dialog-form" onSubmit={remove}>
        <p id={explanationId}>{messages.deleteLibraryEntryExplanation(name)}</p>
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={messages.delete} confirmDisabled={false} busy={busy} onCancel={onClose} cancelHasFocus />
      </form>
    </DialogFrame>
  );
}

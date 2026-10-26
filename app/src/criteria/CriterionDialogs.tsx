// The dialogs of a criterion card's menu (spec 7.2): Rename, which refuses an empty name with the service's words before sending it,
// and Delete, which says what goes and waits for a confirmation. They are the project dialogs' frame (ProjectDialogs.tsx): modal,
// Escape or Cancel closes them, and a refusal of the service is shown in its words with the dialog left open.
import { useId, useState, type FormEvent } from "react";
import { messages } from "../messages";
import { DialogButtons, DialogFrame, ProblemLine, useDialogRequest } from "../steps/ProjectDialogs";

interface RenameCriterionDialogProps {
  name: string;
  /** Resolves with the service's reason when it refused the name, or null once renamed. */
  onRename: (newName: string) => Promise<string | null>;
  onClose: () => void;
}

export function RenameCriterionDialog({ name, onRename, onClose }: RenameCriterionDialogProps) {
  const [newName, setNewName] = useState(name);
  const { problem, setProblem, busy, send } = useDialogRequest(onClose);
  const fieldId = useId();
  // The name as the service stores it: without the white space around it (Python's strip).
  const storedName = newName.trim();
  const unchanged = storedName === name;
  const rename = (event: FormEvent) => {
    event.preventDefault();
    if (busy || unchanged) return;
    if (storedName === "") return setProblem(messages.criterionNeedsName);
    void send(() => onRename(storedName));
  };
  return (
    <DialogFrame title={messages.renameCriterionTitle(name)} busy={busy} onClose={onClose}>
      <form className="project-dialog-form" onSubmit={rename}>
        <label htmlFor={fieldId}>{messages.newCriterionNameLabel}</label>
        <input id={fieldId} className="setting-number project-dialog-field" value={newName} aria-invalid={problem !== null || undefined}
               onChange={(event) => { setNewName(event.target.value); setProblem(null); }} />
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={messages.renameCriterion} confirmDisabled={unchanged} busy={busy} onCancel={onClose} />
      </form>
    </DialogFrame>
  );
}

interface DeleteCriterionDialogProps {
  name: string;
  /** Resolves with the service's reason when it refused, or null once deleted. */
  onDelete: () => Promise<string | null>;
  onClose: () => void;
}

export function DeleteCriterionDialog({ name, onDelete, onClose }: DeleteCriterionDialogProps) {
  const { problem, busy, send } = useDialogRequest(onClose);
  const explanationId = useId();
  const remove = (event: FormEvent) => {
    event.preventDefault();
    if (!busy) void send(onDelete);
  };
  return (
    <DialogFrame title={messages.deleteCriterionTitle} busy={busy} onClose={onClose} describedBy={explanationId}>
      <form className="project-dialog-form" onSubmit={remove}>
        <p id={explanationId}>{messages.deleteCriterionExplanation(name)}</p>
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={messages.deleteCriterion} confirmDisabled={false} busy={busy} onCancel={onClose} cancelHasFocus />
      </form>
    </DialogFrame>
  );
}

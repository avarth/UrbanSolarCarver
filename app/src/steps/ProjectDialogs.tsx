// The dialogs of the project menu (R2 7.2): Rename, checked by the project-name rule before it is sent; Delete, which names the
// project and its folder and waits for the project name to be typed; Reset to the example, after a confirmation; and the reason
// Open folder failed. Each is modal: the focus moves into it and stays there with Tab, and Escape or Cancel closes it (not while
// its request is out). A refusal of the service is shown in the dialog in the service's words, and the dialog stays open.
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { messages } from "../messages";
import "./steps.css";

// The project-name rule of the service (local_web_service/project_names.py), so a name it would refuse is not sent.
const PROJECT_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$/;
const WINDOWS_DEVICE_NAME_PATTERN = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i;
const PROJECT_NAME_MAXIMUM_LENGTH = 64;

/** The name as the service stores it: without the spaces around it. */
export function withoutSurroundingSpaces(name: string): string {
  return name.replace(/^ +| +$/g, "");
}

/** Why the service would refuse *name* as a project name, or null when it follows the rule. */
export function projectNameProblem(name: string): string | null {
  const storedName = withoutSurroundingSpaces(name);
  if (!PROJECT_NAME_PATTERN.test(storedName)) return messages.projectNameInvalid;
  if (WINDOWS_DEVICE_NAME_PATTERN.test(storedName)) return messages.projectNameIsWindowsDeviceName(storedName);
  return null;
}

/** Whether two names are one project: project folders ignore letter case, as on Windows. */
export function sameProjectName(firstName: string, secondName: string): boolean {
  return firstName.toLowerCase() === secondName.toLowerCase();
}

/** The folder of a project: the projects folder (as the service gives it, with its own separator) and the project name. */
export function projectFolderPath(projectsFolder: string, projectName: string): string {
  const separator = projectsFolder.includes("\\") ? "\\" : "/";
  return projectsFolder.endsWith(separator) ? `${projectsFolder}${projectName}` : `${projectsFolder}${separator}${projectName}`;
}

/**
 * The controls of a dialog that take the focus, in the order of the page. Every element is walked: jsdom returns the matches
 * of a selector list ("button, input") grouped by selector, not in document order.
 */
function focusableControls(dialog: HTMLElement): HTMLElement[] {
  return [...dialog.querySelectorAll<HTMLElement>("*")].filter((element): element is HTMLButtonElement | HTMLInputElement =>
    (element instanceof HTMLButtonElement || element instanceof HTMLInputElement) && !element.disabled);
}

interface DialogFrameProps {
  title: string;
  /** While the dialog's request is out, Escape does not close it. */
  busy: boolean;
  onClose: () => void;
  /** The ids of the text that explains the dialog, read out with its title. */
  describedBy?: string;
  children: ReactNode;
}

/** A modal dialog: the element marked data-autofocus (else the first control) takes the focus, which Tab keeps inside. */
function DialogFrame({ title, busy, onClose, describedBy, children }: DialogFrameProps) {
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    const first = dialog.current!.querySelector<HTMLElement>("[data-autofocus]") ?? focusableControls(dialog.current!)[0];
    first?.focus();
    if (first instanceof HTMLInputElement) first.select();
  }, []);

  const keepFocusInside = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!busy) onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableControls(dialog.current!);
    if (focusable.length === 0) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="project-dialog-backdrop">
      <div ref={dialog} className="project-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}
           aria-describedby={describedBy} onKeyDown={keepFocusInside}>
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

function DialogButtons({ confirmLabel, confirmDisabled, busy, onCancel, cancelHasFocus = false }: {
  confirmLabel: string;
  confirmDisabled: boolean;
  busy: boolean;
  onCancel: () => void;
  /** For a confirmation without a field: the focus starts on Cancel, so Enter does not confirm by mistake. */
  cancelHasFocus?: boolean;
}) {
  return (
    <div className="project-dialog-buttons">
      <button type="button" className="secondary-button" disabled={busy} onClick={onCancel} data-autofocus={cancelHasFocus || undefined}>
        {messages.cancel}
      </button>
      <button type="submit" className="primary-button" disabled={confirmDisabled || busy}>{confirmLabel}</button>
    </div>
  );
}

/** The request of a dialog: *send* resolves with the service's reason when it refused, or null once done, which closes the dialog. */
function useDialogRequest(onClose: () => void) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (request: () => Promise<string | null>) => {
    setBusy(true);
    const reason = await request();
    setBusy(false);
    if (reason === null) onClose();
    else setProblem(reason);
  };
  return { problem, setProblem, busy, send };
}

function ProblemLine({ problem }: { problem: string | null }) {
  return problem === null ? null : <p className="setting-error" role="alert">{problem}</p>;
}

interface RenameProjectDialogProps {
  projectName: string;
  onRename: (newName: string) => Promise<string | null>;
  onClose: () => void;
}

export function RenameProjectDialog({ projectName, onRename, onClose }: RenameProjectDialogProps) {
  const [newName, setNewName] = useState(projectName);
  const { problem, setProblem, busy, send } = useDialogRequest(onClose);
  const fieldId = useId();
  const hintId = useId();
  const unchanged = withoutSurroundingSpaces(newName) === projectName;
  const rename = (event: FormEvent) => {
    event.preventDefault();
    if (busy || unchanged) return;
    const nameProblem = projectNameProblem(newName);
    if (nameProblem !== null) return setProblem(nameProblem);
    void send(() => onRename(withoutSurroundingSpaces(newName)));
  };
  return (
    <DialogFrame title={messages.renameProjectTitle(projectName)} busy={busy} onClose={onClose}>
      <form className="project-dialog-form" onSubmit={rename}>
        <label htmlFor={fieldId}>{messages.newProjectNameLabel}</label>
        <input id={fieldId} className="setting-number project-dialog-field" value={newName} maxLength={PROJECT_NAME_MAXIMUM_LENGTH}
               aria-describedby={hintId} aria-invalid={problem !== null || undefined}
               onChange={(event) => { setNewName(event.target.value); setProblem(null); }} />
        <p id={hintId} className="start-hint">{messages.projectNameHint}</p>
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={messages.renameProject} confirmDisabled={!newName.trim() || unchanged} busy={busy} onCancel={onClose} />
      </form>
    </DialogFrame>
  );
}

interface DeleteProjectDialogProps {
  projectName: string;
  /** Null while the projects folder is not known yet: the dialog then names the project only. */
  projectFolderPath: string | null;
  onDelete: (confirmName: string) => Promise<string | null>;
  onClose: () => void;
}

export function DeleteProjectDialog({ projectName, projectFolderPath, onDelete, onClose }: DeleteProjectDialogProps) {
  const [typedName, setTypedName] = useState("");
  const { problem, setProblem, busy, send } = useDialogRequest(onClose);
  const fieldId = useId();
  const explanationId = useId();
  const folderId = useId();
  const nameMatches = typedName === projectName;      // as the service checks it: the name exactly as it is written
  const remove = (event: FormEvent) => {
    event.preventDefault();
    if (busy || !nameMatches) return;
    void send(() => onDelete(typedName));
  };
  return (
    <DialogFrame title={messages.deleteProjectTitle(projectName)} busy={busy} onClose={onClose}
                 describedBy={projectFolderPath !== null ? `${explanationId} ${folderId}` : explanationId}>
      <form className="project-dialog-form" onSubmit={remove}>
        <p id={explanationId}>{messages.deleteProjectExplanation(projectName)}</p>
        {projectFolderPath !== null && <p id={folderId}>{messages.projectFolderIs}<span className="project-dialog-path">{projectFolderPath}</span></p>}
        <label htmlFor={fieldId}>{messages.typeProjectNameToConfirm(projectName)}</label>
        <input id={fieldId} className="setting-number project-dialog-field" value={typedName} autoComplete="off" spellCheck={false}
               aria-invalid={problem !== null || undefined} onChange={(event) => { setTypedName(event.target.value); setProblem(null); }} />
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={messages.deleteProjectButton} confirmDisabled={!nameMatches} busy={busy} onCancel={onClose} />
      </form>
    </DialogFrame>
  );
}

interface ResetProjectDialogProps {
  projectName: string;
  exampleTitle: string;
  onReset: () => Promise<string | null>;
  onClose: () => void;
}

export function ResetProjectDialog({ projectName, exampleTitle, onReset, onClose }: ResetProjectDialogProps) {
  const { problem, busy, send } = useDialogRequest(onClose);
  const explanationId = useId();
  const reset = (event: FormEvent) => {
    event.preventDefault();
    if (!busy) void send(onReset);
  };
  return (
    <DialogFrame title={messages.resetProjectTitle(projectName)} busy={busy} onClose={onClose} describedBy={explanationId}>
      <form className="project-dialog-form" onSubmit={reset}>
        <p id={explanationId}>{messages.resetProjectExplanation(projectName, exampleTitle)}</p>
        <ProblemLine problem={problem} />
        <DialogButtons confirmLabel={messages.resetProjectButton} confirmDisabled={false} busy={busy} onCancel={onClose} cancelHasFocus />
      </form>
    </DialogFrame>
  );
}

export function ProjectProblemDialog({ title, problem, onClose }: { title: string; problem: string; onClose: () => void }) {
  const problemId = useId();
  return (
    <DialogFrame title={title} busy={false} onClose={onClose} describedBy={problemId}>
      <p id={problemId} className="setting-error">{problem}</p>
      <div className="project-dialog-buttons">
        <button type="button" className="secondary-button" onClick={onClose}>{messages.closePanel}</button>
      </div>
    </DialogFrame>
  );
}

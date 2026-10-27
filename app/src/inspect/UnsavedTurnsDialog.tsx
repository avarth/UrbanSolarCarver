// Leaving Inspect with turns not saved (inspect design, section 6): the app asks to save or discard them first, or to stay. The
// workspace says whether Inspect holds turns not saved (onInspectUnsavedChange) and hands the app what saves or drops them
// (onInspectTurnsReady); useLeavingInspect puts these together for the page's switch, and its dialog waits for the answer. Save writes
// every file with turns, one request each, and leaves once all are written; a refusal keeps the dialog open with its reason.
import { useRef, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { DialogFrame, ProblemLine } from "../steps/ProjectDialogs";
import type { WorkspaceMode } from "../steps/WorkspaceModeSwitch";

/** What the open workspace gives the app for its turns not saved. */
export interface InspectTurns {
  /** Saves the turns of every file; resolves with why one could not be saved, or null once all are. */
  saveAll: () => Promise<string | null>;
  /** Drops every turn not saved. */
  discardAll: () => void;
}

interface UnsavedTurnsDialogProps {
  /** Why Save cannot be pressed now (a run of the project); null when it can. */
  saveDisabledReason: string | null;
  onStay: () => void;
  onDiscard: () => void;
  /** Resolves with why the turns could not be saved, or null once they are. */
  onSave: () => Promise<string | null>;
}

export function UnsavedTurnsDialog({ saveDisabledReason, onStay, onDiscard, onSave }: UnsavedTurnsDialogProps) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setProblem(null);
    const reason = await onSave();
    setBusy(false);
    setProblem(reason);
  };
  return (
    <DialogFrame title={messages.saveTurnsBeforeLeaving} busy={busy} onClose={onStay}>
      {saveDisabledReason !== null && <p>{saveDisabledReason}</p>}
      <ProblemLine problem={problem} />
      <div className="project-dialog-buttons">
        <button type="button" className="secondary-button" disabled={busy} onClick={onStay} data-autofocus>{messages.stayInInspect}</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={onDiscard}>{messages.discardTurns}</button>
        <button type="button" className="primary-button" disabled={busy || saveDisabledReason !== null} onClick={() => void save()}>
          {messages.saveTurns}
        </button>
      </div>
    </DialogFrame>
  );
}

export interface LeavingInspect {
  /** Does *then* (a change of mode, closing the project), once the turns not saved are saved or dropped; at once when there are none. */
  leave: (then: () => void) => void;
  /** The dialog while it waits for an answer; null otherwise. */
  dialog: ReactNode;
  /** For the workspace's onInspectUnsavedChange and onInspectTurnsReady. */
  onUnsavedChange: (unsaved: boolean) => void;
  onTurnsReady: (turns: InspectTurns | null) => void;
}

/** *mode*: the workspace's mode now. *saveDisabledReason*: why Save cannot be pressed now (a run of the open project), or null. */
export function useLeavingInspect(mode: WorkspaceMode, saveDisabledReason: string | null): LeavingInspect {
  const [unsaved, setUnsaved] = useState(false);
  const turns = useRef<InspectTurns | null>(null);
  const [waiting, setWaiting] = useState<{ then: () => void } | null>(null);
  const finish = () => {
    const then = waiting?.then;
    setWaiting(null);
    then?.();
  };
  const dialog = waiting === null ? null : (
    <UnsavedTurnsDialog saveDisabledReason={saveDisabledReason} onStay={() => setWaiting(null)}
                        onDiscard={() => {
                          turns.current?.discardAll();
                          finish();
                        }}
                        onSave={async () => {
                          const reason = (await turns.current?.saveAll()) ?? null;
                          if (reason === null) finish();
                          return reason;
                        }} />
  );
  return {
    leave: (then) => {
      if (mode === "inspect" && unsaved && turns.current !== null) setWaiting({ then });
      else then();
    },
    dialog,
    onUnsavedChange: setUnsaved,
    onTurnsReady: (ready) => { turns.current = ready; },
  };
}

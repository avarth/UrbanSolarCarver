// Leaving Inspect with turns not saved, or while a save or restore is under way (inspect design, section 6): the app asks to save or
// discard the turns first, or to stay. The workspace says whether Inspect holds turns not saved or has a save under way
// (onInspectUnsavedChange) and hands the app what saves, drops and waits for them (onInspectTurnsReady); useLeavingInspect puts these
// together for the page's switch, and its dialog waits for the answer. Save writes every file with turns, one request each, after the
// save under way, and leaves once all are written; Discard drops the turns staged and leaves once the save under way is written. A
// save under way when the dialog opens is said; once it is written with nothing left to save, the dialog leaves by itself. Any refusal,
// that of the save under way included, keeps the dialog open with its reason, so no failed save goes unseen in another workspace.
import { useRef, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { DialogFrame, ProblemLine } from "../steps/ProjectDialogs";
import type { WorkspaceMode } from "../steps/WorkspaceModeSwitch";

/** What the open workspace gives the app for its turns not saved and its saves under way. */
export interface InspectTurns {
  /** Saves the turns of every file, after the saves under way; resolves with why one could not be saved, or null once all are. */
  saveAll: () => Promise<string | null>;
  /** Drops every turn not saved. */
  discardAll: () => void;
  /** Resolves once no save or restore is under way: with why one that ended meanwhile was refused, or null. */
  waitForUnderWay: () => Promise<string | null>;
  /** A save or restore is under way now. */
  underWay: () => boolean;
  /** Some file has turns staged and not sent now. */
  unsaved: () => boolean;
}

interface UnsavedTurnsDialogProps {
  /** Why Save cannot be pressed now (a run of the project); null when it can. */
  saveDisabledReason: string | null;
  /** A save or restore of Inspect is under way: the dialog says so. */
  saveUnderWay: boolean;
  /** An answer is being carried out: the buttons wait. */
  busy: boolean;
  /** Why the last save could not be made (the dialog's own, or the one under way when it opened); null otherwise. */
  problem: string | null;
  onStay: () => void;
  onDiscard: () => void;
  onSave: () => void;
}

export function UnsavedTurnsDialog({ saveDisabledReason, saveUnderWay, busy, problem, onStay, onDiscard, onSave }: UnsavedTurnsDialogProps) {
  return (
    <DialogFrame title={messages.saveTurnsBeforeLeaving} busy={busy} onClose={onStay}>
      {saveUnderWay && <p>{messages.inspectSaveUnderWay}</p>}
      {saveDisabledReason !== null && <p>{saveDisabledReason}</p>}
      <ProblemLine problem={problem} />
      <div className="project-dialog-buttons">
        <button type="button" className="secondary-button" disabled={busy} onClick={onStay} data-autofocus>{messages.stayInInspect}</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={onDiscard}>{messages.discardTurns}</button>
        <button type="button" className="primary-button" disabled={busy || saveDisabledReason !== null} onClick={onSave}>
          {messages.saveTurns}
        </button>
      </div>
    </DialogFrame>
  );
}

export interface LeavingInspect {
  /** Does *then* (a change of mode, closing the project), once the turns not saved are saved or dropped and the save under way is
   * written; at once when there are none. */
  leave: (then: () => void) => void;
  /** The dialog while it waits for an answer; null otherwise. */
  dialog: ReactNode;
  /** For the workspace's onInspectUnsavedChange (turns not saved, or a save under way) and onInspectTurnsReady. */
  onUnsavedChange: (unsaved: boolean) => void;
  onTurnsReady: (turns: InspectTurns | null) => void;
}

interface Waiting {
  then: () => void;
  /** A save or restore was under way when the dialog opened, and has not ended yet. */
  saveUnderWay: boolean;
  /** The dialog is carrying out Save or Discard. */
  busy: boolean;
  problem: string | null;
}

/** *mode*: the workspace's mode now. *saveDisabledReason*: why Save cannot be pressed now (a run of the open project), or null. */
export function useLeavingInspect(mode: WorkspaceMode, saveDisabledReason: string | null): LeavingInspect {
  const [unsaved, setUnsaved] = useState(false);
  const turns = useRef<InspectTurns | null>(null);
  const [waiting, setWaitingState] = useState<Waiting | null>(null);
  // The dialog as it is now, read by the answers that wait (each opening is another object, so an answer to an earlier one is dropped).
  const current = useRef<Waiting | null>(null);
  const setWaiting = (next: Waiting | null) => {
    current.current = next;
    setWaitingState(next);
  };
  const update = (opened: Waiting, change: Partial<Waiting>) => {
    if (current.current !== opened) return;
    const next = { ...opened, ...change };
    current.current = next;
    setWaitingState(next);
    return next;
  };
  const finish = () => {
    const then = current.current?.then;
    setWaiting(null);
    then?.();
  };
  /** Carries out an answer: *act* resolves with why it could not, or null, after which the dialog leaves. */
  const answer = async (act: () => Promise<string | null>) => {
    const opened = current.current;
    if (opened === null) return;
    const busy = update(opened, { busy: true, problem: null })!;
    const reason = await act();
    if (current.current !== busy) return;
    if (reason === null) finish();
    else update(busy, { busy: false, saveUnderWay: false, problem: reason });
  };
  /** The save under way when the dialog opened: its refusal is shown; once written with nothing left to save, the dialog leaves. */
  const watchUnderWay = async (opened: Waiting) => {
    const reason = (await turns.current?.waitForUnderWay()) ?? null;
    const now = current.current;
    if (now === null || now.then !== opened.then || now.busy) return;
    if (reason !== null) update(now, { saveUnderWay: false, problem: reason });
    else if (turns.current?.unsaved()) update(now, { saveUnderWay: false });
    else finish();
  };
  const dialog = waiting === null ? null : (
    <UnsavedTurnsDialog saveDisabledReason={saveDisabledReason} saveUnderWay={waiting.saveUnderWay} busy={waiting.busy} problem={waiting.problem}
                        onStay={() => setWaiting(null)}
                        onDiscard={() => void answer(async () => {
                          turns.current?.discardAll();
                          return (await turns.current?.waitForUnderWay()) ?? null;
                        })}
                        onSave={() => void answer(async () => (await turns.current?.saveAll()) ?? null)} />
  );
  return {
    leave: (then) => {
      const ready = turns.current;
      if (mode !== "inspect" || !unsaved || ready === null) {
        then();
        return;
      }
      const opened: Waiting = { then, saveUnderWay: ready.underWay(), busy: false, problem: null };
      setWaiting(opened);
      if (opened.saveUnderWay) void watchUnderWay(opened);
    },
    dialog,
    onUnsavedChange: setUnsaved,
    onTurnsReady: (ready) => { turns.current = ready; },
  };
}

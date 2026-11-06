// What every dialog of the app shares: the modal frame (the focus moves in and stays there with Tab, Escape or Cancel closes
// it, not while its request is out), the Cancel and confirm buttons, the request that keeps the dialog open with the
// service's words when it is refused, and the line that says them. The project menu's dialogs (workspace/ProjectDialogs.tsx),
// the criterion dialogs and the typical building's window (a wide frame with a × and the title in focus) are built on it.
import { useEffect, useEffectEvent, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { messages } from "../messages";
import "../theme/panels.css";

/**
 * The controls of a dialog that take the focus, in the order of the page. Every element is walked: jsdom returns the matches
 * of a selector list ("button, input") grouped by selector, not in document order.
 */
function focusableControls(dialog: HTMLElement): HTMLElement[] {
  return [...dialog.querySelectorAll<HTMLElement>("*")].filter((element) => {
    if (element instanceof HTMLAnchorElement) return element.hasAttribute("href");
    return (element instanceof HTMLButtonElement || element instanceof HTMLInputElement || element instanceof HTMLSelectElement
            || element instanceof HTMLTextAreaElement) && !element.disabled;
  });
}

export interface DialogFrameProps {
  title: string;
  /** While the dialog's request is out, Escape does not close it. */
  busy: boolean;
  onClose: () => void;
  /** The ids of the text that explains the dialog, read out with its title. */
  describedBy?: string;
  /** A window for a larger piece of work (the typical building): wider, and as tall as the browser window lets it be. */
  wide?: boolean;
  /** The name of an × button in the title row that calls *onClose*; without it the dialog has no ×. */
  closeLabel?: string;
  /** The title (not the first control) takes the focus when the dialog opens, so a long window is read from its top. */
  titleTakesFocus?: boolean;
  children: ReactNode;
}

/**
 * A modal dialog: the element marked data-autofocus (else the first control) takes the focus, which Tab keeps inside. Escape inside a
 * dialog open within another closes only the inner one.
 */
export function DialogFrame({ title, busy, onClose, describedBy, wide = false, closeLabel, titleTakesFocus = false, children }: DialogFrameProps) {
  const dialog = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const titleId = useId();

  // The focus moves in once, when the dialog opens.
  const takeFocus = useEffectEvent(() => {
    if (titleTakesFocus) {
      heading.current?.focus();
      return;
    }
    const first = dialog.current!.querySelector<HTMLElement>("[data-autofocus]") ?? focusableControls(dialog.current!)[0];
    first?.focus();
    if (first instanceof HTMLInputElement) first.select();
  });
  useEffect(() => takeFocus(), []);

  const keepFocusInside = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      if (!busy) onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableControls(dialog.current!);
    if (focusable.length === 0) return;
    // Tab is settled here: a dialog open within another keeps it to itself.
    event.stopPropagation();
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === heading.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const titleElement = <h2 id={titleId} ref={heading} tabIndex={titleTakesFocus ? -1 : undefined}>{title}</h2>;
  return (
    <div className="project-dialog-backdrop">
      <div ref={dialog} className={wide ? "project-dialog project-dialog-wide" : "project-dialog"} role="dialog" aria-modal="true"
           aria-labelledby={titleId} aria-describedby={describedBy} onKeyDown={keepFocusInside}>
        {closeLabel === undefined ? titleElement : (
          <div className="project-dialog-title-row">
            {titleElement}
            <button type="button" className="project-dialog-close" aria-label={closeLabel} title={closeLabel} onClick={onClose}>
              <span aria-hidden="true">×</span>
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

export function DialogButtons({ confirmLabel, confirmDisabled, busy, onCancel, cancelHasFocus = false }: {
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

/**
 * The request of a dialog (or of a part that sends one request at a time: Add criterion, Use a file): *send*'s request resolves with
 * the service's reason when it refused, which is shown, or null once done, which closes the dialog.
 */
export function useDialogRequest(onClose: () => void) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (request: () => Promise<string | null>) => {
    setBusy(true);
    setProblem(null);
    const reason = await request();
    setBusy(false);
    if (reason === null) onClose();
    else setProblem(reason);
  };
  return { problem, setProblem, busy, send };
}

export function ProblemLine({ problem }: { problem: string | null }) {
  return problem === null ? null : <p className="setting-error" role="alert">{problem}</p>;
}

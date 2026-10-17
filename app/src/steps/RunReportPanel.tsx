// The run report (run_report.md) in a panel over the 3D view (UX 5.6), as preformatted text in milestone 1; a report that cannot
// be read says so. It closes with its Close button or Escape, and gives the focus back to what opened it.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { getRunFileText, serviceProblemOf } from "../api_client/client";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import "./steps.css";

export const RUN_REPORT_PATH = "run_report.md";

interface RunReportPanelProps {
  token: string;
  project: string;
  onClose: () => void;
  onServiceProblem: (error: unknown) => void;
}

export function RunReportPanel({ token, project, onClose, onServiceProblem }: RunReportPanelProps) {
  const [report, setReport] = useState<string | null>(null);
  const [unreadable, setUnreadable] = useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const openedFrom = useRef<Element | null>(document.activeElement);

  useEffect(() => {
    closeButton.current?.focus();
    let stale = false;
    getRunFileText(token, project, RUN_REPORT_PATH).then((text) => { if (!stale) setReport(text); }).catch((error) => {
      if (stale) return;
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      setUnreadable(true);
    });
    return () => {
      stale = true;
      (openedFrom.current as HTMLElement | null)?.focus?.();
    };
  }, []);

  const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key === "Escape") onClose();
  };
  return (
    <section className="run-report-panel" role="dialog" aria-label={messages.runReportTitle} onKeyDown={closeOnEscape}>
      <header className="run-report-header">
        <h2>{messages.runReportTitle}</h2>
        <button ref={closeButton} type="button" className="secondary-button" onClick={onClose}>{messages.closePanel}</button>
      </header>
      {unreadable ? <p className="setting-error run-report-problem"><WarningIcon /><span>{messages.runReportUnreadable}</span></p>
        : <pre className="run-report-text">{report}</pre>}
    </section>
  );
}

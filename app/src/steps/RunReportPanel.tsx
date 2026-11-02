// The run report (run_report.md) in a panel over the 3D view (UX 5.6), as preformatted text in milestone 1; a report that cannot
// be read says so. It closes with its Close button or Escape, and gives the focus back to what opened it.
import { useEffect, useEffectEvent, useRef, useState, type KeyboardEvent } from "react";
import { getRunFileText, reportServiceProblem } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import "../theme/panels.css";

export const RUN_REPORT_PATH = "run_report.md";

interface RunReportPanelProps {
  onClose: () => void;
}

export function RunReportPanel({ onClose }: RunReportPanelProps) {
  const { token, project, onServiceProblem } = useProjectSession();
  const [report, setReport] = useState<string | null>(null);
  const [unreadable, setUnreadable] = useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const openedFrom = useRef<Element | null>(document.activeElement);

  useEffect(() => {
    closeButton.current?.focus();
    const giveFocusBackTo = openedFrom.current as HTMLElement | null;
    return () => giveFocusBackTo?.focus?.();
  }, []);

  const reportProblem = useEffectEvent((error: unknown) => onServiceProblem(error));
  useEffect(() => {
    let stale = false;
    getRunFileText(token, project, RUN_REPORT_PATH).then((text) => { if (!stale) setReport(text); }).catch((error) => {
      if (stale) return;
      reportServiceProblem(error, reportProblem);
      setUnreadable(true);
    });
    return () => {
      stale = true;
    };
  }, [token, project]);

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

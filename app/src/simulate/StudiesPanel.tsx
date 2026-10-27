// The studies panel of Simulate (simulate design, section 3): small, floating over the top left of the 3D view, collapsible to an
// icon button. One row per study: its colour swatch, its name and a line (its test surface files while its result is current, else
// "Out of date", "Not run yet" or why it cannot run). A press on a row selects the study for the view; its settings button opens the
// popover beside the panel. Under the rows, Add study (AddStudyMenu) and, once there is a study, Run with its progress. While a run
// of the project goes on the service refuses changes, so Add study waits, with the reason Run says.
import { useId, useRef, useState, type ReactNode } from "react";
import type { CriterionEntry, MetricInfo, StudySource, StudyWithState } from "../api_client/client";
import { messages } from "../messages";
import { RunAnalysisButton } from "../steps/SettingsStep";
import { AddStudyMenu } from "./AddStudyMenu";
import "./simulate.css";

export interface StudiesPanelProps {
  studies: StudyWithState[];
  /** The study shown in the view; null when none is. */
  selectedId: string | null;
  /** The criteria, which Add study offers as shortcuts. */
  criteria: CriterionEntry[];
  metrics: MetricInfo[];
  /** Why Run cannot start now; null when it can. */
  runDisabledReason: string | null;
  /** Why the studies cannot be changed now (a run of the project); null when they can. */
  editDisabledReason: string | null;
  /** The study whose settings are open beside the panel; null when none is. */
  popoverStudyId: string | null;
  /** The id of the popover, which the settings button of its study names. */
  popoverId?: string;
  onSelect: (id: string) => void;
  /** The settings button of a study was pressed: its popover opens, or closes when it is open. */
  onToggleSettings: (id: string) => void;
  /** Adds a study; resolves with the reason it could not, or null. */
  onAdd: (source: StudySource) => Promise<string | null>;
  onRun: () => void;
  /** The progress and outcome of the simulation, under Run. */
  runFeedback?: ReactNode;
  /** The settings popover of popoverStudyId. */
  popover?: ReactNode;
  /** Why the studies could not be read; null when they were. */
  loadProblem?: string | null;
}

/** The line under a study's name. */
export function studyLine(study: StudyWithState): string {
  switch (study.state) {
    case "current": return (study.entry.test_surface_files ?? []).join(", ");
    case "out_of_date": return messages.outOfDateSummary;
    case "not_run": return messages.notRunYet;
    case "refused": return study.reason ?? "";
  }
}

function StudiesIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M2 4h14M2 9h14M2 14h9" strokeLinecap="round" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M2 4h7M13 4h1M2 12h1M7 12h7" strokeLinecap="round" />
      <circle cx="11" cy="4" r="2" />
      <circle cx="5" cy="12" r="2" />
    </svg>
  );
}

export function StudiesPanel(props: StudiesPanelProps) {
  const { studies, selectedId, editDisabledReason, runDisabledReason, popoverStudyId } = props;
  const [open, setOpen] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const [addProblem, setAddProblem] = useState<string | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const bodyId = useId();
  const titleId = useId();
  const menuId = useId();
  const reasonId = useId();
  const hasRun = studies.length > 0;
  // Add study waits only while a run of the project goes on, when Run waits for the same reason: it is said once.
  const reason = (hasRun ? runDisabledReason : null) ?? editDisabledReason;

  const add = async (source: StudySource) => {
    setMenuOpen(false);
    setAddProblem(null);
    setAddProblem(await props.onAdd(source));
  };

  return (
    <section className={`studies-panel ${open ? "studies-panel-open" : "studies-panel-collapsed"}`} aria-labelledby={open ? titleId : undefined}
             aria-label={open ? undefined : messages.studiesTitle}>
      <div className="studies-panel-header">
        <button type="button" className="studies-panel-toggle" aria-label={messages.studiesTitle} aria-expanded={open} aria-controls={open ? bodyId : undefined}
                title={messages.studiesTitle} onClick={() => setOpen((shown) => !shown)}>
          <StudiesIcon />
        </button>
        {open && <h2 id={titleId} className="studies-panel-title">{messages.studiesTitle}</h2>}
      </div>
      {open && (
        <div id={bodyId} className="studies-panel-body">
          {props.loadProblem != null && <p className="studies-panel-problem" role="alert">{props.loadProblem}</p>}
          {hasRun && (
            <ul className="study-list">
              {studies.map((study) => {
                const { id, name, colour } = study.entry;
                const settingsOpen = popoverStudyId === id;
                return (
                  <li key={id} className="study-row" aria-current={selectedId === id || undefined} data-study-id={id}>
                    <button type="button" className="study-row-select" onClick={() => props.onSelect(id)}>
                      <span className="study-row-swatch" style={{ background: colour }} aria-hidden="true" />
                      <span className="study-row-text">
                        <span className="study-row-name">{name}</span>
                        <span className={`study-row-line study-row-line-${study.state}`} title={studyLine(study)}>{studyLine(study)}</span>
                      </span>
                    </button>
                    <button type="button" className="study-row-settings" aria-label={messages.studySettingsOf(name)} title={messages.studySettingsOf(name)}
                            aria-expanded={settingsOpen} aria-controls={settingsOpen ? props.popoverId : undefined} onClick={() => props.onToggleSettings(id)}>
                      <SettingsIcon />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="studies-panel-actions">
            <button ref={addButton} type="button" className="secondary-button study-add" aria-haspopup="menu" aria-expanded={menuOpen}
                    aria-controls={menuOpen ? menuId : undefined} disabled={editDisabledReason !== null}
                    aria-describedby={editDisabledReason !== null ? reasonId : undefined} onClick={() => setMenuOpen((shown) => !shown)}>
              {messages.addStudy}
            </button>
            {menuOpen && (
              <AddStudyMenu id={menuId} anchor={addButton} criteria={props.criteria} metrics={props.metrics} onChoose={(source) => void add(source)}
                            onClose={() => setMenuOpen(false)} />
            )}
            {hasRun && <RunAnalysisButton blocker={runDisabledReason} label={messages.runStudies} onRunAnalysis={props.onRun} sharedReasonId={reasonId} />}
          </div>
          {reason !== null && <p id={reasonId} className="run-button-reason">{reason}</p>}
          {addProblem !== null && <p className="studies-panel-problem" role="alert">{addProblem}</p>}
          {props.runFeedback}
        </div>
      )}
      {open && props.popover}
    </section>
  );
}

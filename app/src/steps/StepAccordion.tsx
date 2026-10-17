// The step list of the left panel (UX 4, 4.1): one step open at a time, every row with its state mark, its title and, while
// closed, its one-line summary. Steps never lock: a step that cannot be used yet says why when opened. The summary of a step
// with a setting to fix stays visible while it is open. The open step's run button is pinned under the list.
import { useId, type ReactNode } from "react";
import type { StepMark, StepName } from "./step_summaries";
import "./steps.css";

export interface AccordionStep {
  name: StepName;
  title: string;
  summary: string;
  mark: StepMark;
  /** Why the step cannot be used yet, shown in place of its content; null when it can. */
  notUsableYet: string | null;
  content: ReactNode;
}

interface StepAccordionProps {
  steps: AccordionStep[];
  openStep: StepName | null;
  onOpenStep: (step: StepName | null) => void;
  /** The open step's run button and its disabled reason. */
  pinnedAction: ReactNode;
}

function TickIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2.5 6.2 5 8.5l4.5-5" />
    </svg>
  );
}

function StepMarkSign({ mark, open }: { mark: StepMark; open: boolean }) {
  if (mark === "done") return <span className="step-mark step-mark-done" aria-hidden="true"><TickIcon /></span>;
  if (mark === "error") return <span className="step-mark step-mark-error" aria-hidden="true">!</span>;
  return <span className={open ? "step-mark step-mark-open" : "step-mark"} aria-hidden="true" />;
}

function StepRow({ step, open, onToggle }: { step: AccordionStep; open: boolean; onToggle: () => void }) {
  const contentId = useId();
  const showSummary = !open || step.mark === "error";
  return (
    <li className={open ? "step step-open" : "step"}>
      <h2 className="step-heading">
        <button type="button" className="step-header" aria-expanded={open} aria-controls={open ? contentId : undefined} onClick={onToggle}>
          <StepMarkSign mark={step.mark} open={open} />
          <span className="step-header-text">
            <span className="step-title">{step.title}</span>
            {showSummary && <span className={step.mark === "error" ? "step-summary step-summary-error" : "step-summary"}>{step.summary}</span>}
          </span>
        </button>
      </h2>
      {open && (
        <div id={contentId} className="step-content">
          {step.notUsableYet !== null ? <p className="step-not-usable">{step.notUsableYet}</p> : step.content}
        </div>
      )}
    </li>
  );
}

export function StepAccordion({ steps, openStep, onOpenStep, pinnedAction }: StepAccordionProps) {
  return (
    <div className="step-panel">
      <ol className="step-list">
        {steps.map((step) => (
          <StepRow key={step.name} step={step} open={step.name === openStep} onToggle={() => onOpenStep(step.name === openStep ? null : step.name)} />
        ))}
      </ol>
      {pinnedAction && <div className="step-pinned-action">{pinnedAction}</div>}
    </div>
  );
}

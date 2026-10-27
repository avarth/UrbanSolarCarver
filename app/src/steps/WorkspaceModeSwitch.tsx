// The Design / Simulate / Inspect switch of the top bar: Design is the pipeline (the steps beside the 3D view), Simulate and Inspect give the view the whole
// window (the studies; the orientation of the test surfaces). A group of toggle buttons, the pressed one is the mode in use.
import { messages } from "../messages";

export type WorkspaceMode = "design" | "simulate" | "inspect";

const MODES: WorkspaceMode[] = ["design", "simulate", "inspect"];

export function WorkspaceModeSwitch({ mode, onChange }: { mode: WorkspaceMode; onChange: (mode: WorkspaceMode) => void }) {
  return (
    <div className="segmented-switch workspace-mode-switch" role="group" aria-label={messages.workspaceModeLabel}>
      {MODES.map((choice) => (
        <button key={choice} type="button" aria-pressed={mode === choice} onClick={() => onChange(choice)}>{messages.workspaceModes[choice]}</button>
      ))}
    </div>
  );
}

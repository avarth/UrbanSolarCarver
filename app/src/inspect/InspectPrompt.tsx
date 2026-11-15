// The prompt to check face directions in Inspect (user 2026-11-15, vault features/inspect-prompt-first-geometry): under the test
// surfaces box once the project's first test surface file is imported. A test surface is read from one side, so one that faces
// the wrong way is barely protected. Open Inspect opens Inspect with the file selected; Not now closes it. Either answer is kept in
// the project (project.json inspect_prompt_answered), so it is shown once per project. Drawn and picked sets do not bring it.
import { messages } from "../messages";

interface InspectPromptProps {
  /** The file just imported, as the box names it. */
  fileName: string;
  onOpenInspect: () => void;
  onNotNow: () => void;
}

export function InspectPrompt({ fileName, onOpenInspect, onNotNow }: InspectPromptProps) {
  return (
    <div className="weather-change-notice inspect-prompt" role="status">
      <p>{messages.inspectPromptText(fileName)}</p>
      <div className="weather-change-notice-buttons">
        <button type="button" className="secondary-button" onClick={onOpenInspect}>{messages.inspectPromptOpen}</button>
        <button type="button" className="secondary-button" onClick={onNotNow}>{messages.inspectPromptNotNow}</button>
      </div>
    </div>
  );
}

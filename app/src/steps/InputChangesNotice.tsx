// Input files changed in the project folder from outside the app, or missing from it, as the stage status lists them: a notice
// over Design's steps and in Simulate's studies panel. The changed ones go once the user dismisses them; a missing one stays until
// the file is back or removed.
import type { InputFileChange } from "../api_client/client";
import { listedWithAnd, messages } from "../messages";
import "./steps.css";

interface InputChangesNoticeProps {
  changes: readonly InputFileChange[];
  onDismiss: () => void;
}

export function InputChangesNotice({ changes, onDismiss }: InputChangesNoticeProps) {
  const filesIn = (state: InputFileChange["state"]) => listedWithAnd(changes.filter((change) => change.state === state)
    .map((change) => messages.inputFileInRole(change.file_name, change.role)));
  const changed = filesIn("changed"), missing = filesIn("missing");
  if (changed === "" && missing === "") return null;
  return (
    <div className="input-changes-notice" role="status">
      {changed !== "" && <p>{messages.inputFilesChangedInFolder(changed)}</p>}
      {missing !== "" && <p>{messages.inputFilesMissingFromFolder(missing)}</p>}
      {changed !== "" && (
        <button type="button" className="secondary-button" onClick={onDismiss}>{messages.dismissInputChanges}</button>
      )}
    </div>
  );
}

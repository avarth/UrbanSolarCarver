// The window of an outline import (design/site-import.md, section 7): what the file holds before anything is added. The closed
// polylines found, each with its area and rise; what was left out; a warning when the outlines lie far from the other inputs in plan;
// Place on terrain, on by default while the project has terrain; and Import n sites, which adds them as one undoable change.
import { useId, useState, type FormEvent } from "react";
import type { OutlinesReply } from "../api_client/client";
import { DialogButtons, DialogFrame } from "../common/dialogs";
import { formattedNumber, groupedDigits } from "../format_numbers";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";

interface ImportSitesDialogProps {
  found: OutlinesReply;
  /** The name each outline will be added with (its own, or the next "Site n"), so the list says what Import adds. */
  names: string[];
  hasTerrain: boolean;
  busy: boolean;
  onImport: (placeOnTerrain: boolean) => void;
  onCancel: () => void;
}

export function ImportSitesDialog({ found, names, hasTerrain, busy, onImport, onCancel }: ImportSitesDialogProps) {
  const [onTerrain, setOnTerrain] = useState(hasTerrain);
  const textId = useId();
  const count = found.outlines.length;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onImport(hasTerrain && onTerrain);
  };
  return (
    <DialogFrame title={messages.importSitesTitle(found.file)} busy={busy} onClose={onCancel} describedBy={textId}>
      <form className="project-dialog-form import-sites" onSubmit={submit}>
        <p id={textId}>{messages.importSitesFound(count, found.unit)}</p>
        <ul className="import-sites-list">
          {found.outlines.map((outline, index) => (
            <li key={index}>
              <span>{names[index] ?? outline.name}</span>
              <span className="import-sites-detail">{messages.importSiteLine(groupedDigits(Math.round(outline.area)), formattedNumber(outline.rise))}</span>
            </li>
          ))}
        </ul>
        {found.left_out.length > 0 && (
          <div className="import-sites-left-out">
            <p>{messages.importLeftOut}</p>
            <ul>{found.left_out.map((text) => <li key={text}>{text}</li>)}</ul>
          </div>
        )}
        {found.distance_from_inputs != null && (
          <p className="input-box-problem"><WarningIcon />{messages.importFarFromInputs(formattedNumber(found.distance_from_inputs / 1000))}</p>
        )}
        {hasTerrain && (
          <label className="import-sites-terrain">
            <input type="checkbox" checked={onTerrain} disabled={busy} onChange={(event) => setOnTerrain(event.target.checked)} />
            <span>{messages.placeOnTerrain}<small>{messages.placeOnTerrainHint}</small></span>
          </label>
        )}
        <DialogButtons confirmLabel={messages.importSitesButton(count)} confirmDisabled={count === 0} busy={busy} onCancel={onCancel} />
      </form>
    </DialogFrame>
  );
}

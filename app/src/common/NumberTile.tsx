// A key number on chrome (UX 5.6), as the carving rule and the Envelope and massing step show them.
import { SettingTooltip } from "../settings_form/SettingTooltip";
import "../steps/steps.css";

/**
 * A key number on chrome (UX 5.6): its label, with an "i" that says what it counts when *help* is given, then the value; the
 * unit may wrap under the value in a narrow tile.
 */
export function NumberTile({ label, value, unit, help }: { label: string; value: string; unit?: string; help?: string }) {
  return (
    <div className="number-tile">
      <span className="number-tile-label">{label}{help !== undefined && <> <SettingTooltip settingLabel={label} help={help} /></>}</span>
      <span className="number-tile-value">{value}{unit && <> <span className="number-tile-unit">{unit}</span></>}</span>
    </div>
  );
}

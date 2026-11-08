// The Heights group of the project settings window (design/base-height.md): the base height, below which nothing is carved, and the
// max height of the sites. Each has a switch, Global (its value here) or Per site (set in each site's row of the Site
// card). A project with a mesh maximum volume has only the base height, one level above the mesh's lowest point. Each change is
// stored at once; a change the service refuses (a site whose max height would not be above its base) goes back, with the reason.
import { useId, useState } from "react";
import { messages } from "../messages";
import { formattedNumber } from "../format_numbers";
import { Subheading } from "../settings_form/Subheading";
import { WarningIcon } from "../settings_form/SettingField";
import type { HeightSetting, Heights } from "./site_geometry";
import "./sites.css";

interface HeightsSettingsProps {
  /** Whether the maximum volume is made from sites; with a mesh only the base height is shown. */
  fromSites: boolean;
  heights: Heights;
  /** The max height a switch to Global starts from when there is none yet (the first site's). */
  startingMax: number;
  onChange: (heights: Heights) => Promise<string | null>;
  disabledReason: string | null;
}

export function HeightsSettings({ fromSites, heights, startingMax, onChange, disabledReason }: HeightsSettingsProps) {
  const titleId = useId();
  const [problem, setProblem] = useState<string | null>(null);
  const change = (next: Heights) => {
    setProblem(null);
    void onChange(next).then((reason) => setProblem(reason));
  };
  return (
    <section className="setting-group heights-settings" aria-labelledby={titleId}>
      <Subheading id={titleId} className="setting-group-title">{messages.heightsGroup}</Subheading>
      <HeightRow name="base_height" label={messages.baseHeight} setting={heights.base} withSwitch={fromSites} optional
                 disabledReason={disabledReason} onProblem={setProblem} onChange={(base) => change({ ...heights, base })} />
      {fromSites && (
        <HeightRow name="max_height" label={messages.maxHeight} setting={heights.max} withSwitch optional={false} startingValue={startingMax}
                   disabledReason={disabledReason} onProblem={setProblem} onChange={(max) => change({ ...heights, max })} />
      )}
      <p className="heights-help">{fromSites ? messages.heightsHelp : messages.meshBaseHelp}</p>
      {problem !== null && <p className="input-box-problem" role="alert"><WarningIcon />{problem}</p>}
      {disabledReason !== null && <p className="input-box-reason">{disabledReason}</p>}
    </section>
  );
}

interface HeightRowProps {
  /** The name the row is found by when the window opens on it (data-setting). */
  name: string;
  label: string;
  setting: HeightSetting;
  withSwitch: boolean;
  /** Whether the value may be empty (the base height: no lower limit). */
  optional: boolean;
  /** The value a switch to Global takes when there is none (the max height needs one). */
  startingValue?: number;
  disabledReason: string | null;
  onProblem: (problem: string | null) => void;
  onChange: (setting: HeightSetting) => void;
}

function HeightRow({ name, label, setting, withSwitch, optional, startingValue, disabledReason, onProblem, onChange }: HeightRowProps) {
  const fieldId = useId();
  const shown = typeof setting.value === "number" ? formattedNumber(setting.value) : "";
  const [text, setText] = useState(shown);
  const [lastShown, setLastShown] = useState(shown);
  if (lastShown !== shown) {
    setLastShown(shown);
    setText(shown);
  }
  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === shown) return;
    if (trimmed === "") {
      if (optional) onChange({ ...setting, value: null });
      else onProblem(messages.heightNeedsValue);
      return;
    }
    const value = Number(trimmed.replace(",", "."));
    if (!Number.isFinite(value) || value < 0 || (value === 0 && !optional)) {
      onProblem(messages.heightNotPositive);
      return;
    }
    onChange({ ...setting, value });
  };
  const disabled = disabledReason !== null;
  return (
    <div className="height-row" data-setting={name} data-input-id={fieldId}>
      <span className="height-row-label">{label}</span>
      {withSwitch && (
        <span className="segmented-switch" role="group" aria-label={label}>
          <button type="button" aria-pressed={setting.for_all_sites} disabled={disabled}
                  onClick={() => !setting.for_all_sites && onChange({ for_all_sites: true, value: setting.value ?? startingValue ?? null })}>
            {messages.forAllSites}
          </button>
          <button type="button" aria-pressed={!setting.for_all_sites} disabled={disabled}
                  onClick={() => setting.for_all_sites && onChange({ ...setting, for_all_sites: false })}>
            {messages.perSite}
          </button>
        </span>
      )}
      {(!withSwitch || setting.for_all_sites) && (
        <label className="height-row-value">
          <input id={fieldId} type="text" inputMode="decimal" value={text} aria-label={label} disabled={disabled}
                 placeholder={optional ? messages.siteNoBase : undefined}
                 onChange={(event) => setText(event.target.value)} onBlur={commit}
                 onKeyDown={(event) => { if (event.key === "Enter") commit(); }} />
          <span>m</span>
        </label>
      )}
    </div>
  );
}

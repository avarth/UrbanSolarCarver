// The maximum volume input of Carve › Inputs when it is chosen between a maximum volume and a site (design/site-input.md): the two
// tiles before either has content, the Site card (a row per site with its name, height, area and elevations, Draw site), and the
// link that switches the input, which asks first when the input has content. The sites themselves are drawn and edited in the view
// (SiteEditor.tsx).
import { useId, useState, type FormEvent } from "react";
import { ActionMenu } from "../common/ActionMenu";
import { DialogButtons, DialogFrame } from "../common/dialogs";
import { messages } from "../messages";
import { Subheading } from "../settings_form/Subheading";
import { WarningIcon } from "../settings_form/SettingField";
import { formattedNumber } from "../format_numbers";
import { baseHeightOf, maxHeightOf, outlinePoints, planArea, siteProblems, siteRise, type Heights, type Site } from "./site_geometry";
import type { SiteTool } from "./SiteEditor";
import "./sites.css";

interface InputChoiceProps {
  onChooseMaxVolume: () => void;
  onChooseSite: () => void;
  disabledReason: string | null;
}

/** The two inputs a project can start from, before either has content. */
export function InputChoice({ onChooseMaxVolume, onChooseSite, disabledReason }: InputChoiceProps) {
  const titleId = useId();
  return (
    <section className="input-box input-choice" aria-labelledby={titleId}>
      <Subheading id={titleId} className="input-box-title">{messages.inputChoiceTitle}</Subheading>
      <div className="input-choice-tiles">
        <button type="button" className="input-choice-tile" disabled={disabledReason !== null} onClick={onChooseMaxVolume}>
          <strong>{messages.inputChoiceMaxVolume}</strong>
          <span>{messages.inputChoiceMaxVolumeLine}</span>
        </button>
        <button type="button" className="input-choice-tile" disabled={disabledReason !== null} onClick={onChooseSite}>
          <strong>{messages.inputChoiceSite}</strong>
          <span>{messages.inputChoiceSiteLine}</span>
        </button>
      </div>
      {disabledReason !== null && <p className="input-box-reason">{disabledReason}</p>}
    </section>
  );
}

interface SwitchInputLinkProps {
  toSite: boolean;
  /** Whether the input left has content: the switch then asks first. */
  asks: boolean;
  onSwitch: () => void;
  disabledReason: string | null;
}

/** "Use a site instead" / "Use a maximum volume instead", with its question when the input left has content. */
export function SwitchInputLink({ toSite, asks, onSwitch, disabledReason }: SwitchInputLinkProps) {
  const [asking, setAsking] = useState(false);
  const textId = useId();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setAsking(false);
    onSwitch();
  };
  return (
    <>
      <button type="button" className="link-button input-switch-link" disabled={disabledReason !== null}
              onClick={() => (asks ? setAsking(true) : onSwitch())}>
        {toSite ? messages.useSiteInstead : messages.useMaxVolumeInstead}
      </button>
      {asking && (
        <DialogFrame title={messages.switchInputTitle(toSite)} busy={false} onClose={() => setAsking(false)} describedBy={textId}>
          <form onSubmit={submit}>
            <p id={textId}>{messages.switchInputText(toSite)}</p>
            <DialogButtons confirmLabel={messages.switchInput} confirmDisabled={false} busy={false} onCancel={() => setAsking(false)} cancelHasFocus />
          </form>
        </DialogFrame>
      )}
    </>
  );
}

interface SiteBoxProps {
  sites: Site[];
  /** The max and base heights: a height for all sites is shown read-only, and a click opens Settings on it. */
  heights: Heights;
  onOpenSettings: (settingName: "max_height" | "base_height") => void;
  tool: SiteTool | null;
  onDraw: () => void;
  onEdit: (index: number) => void;
  onChangeSite: (index: number, site: Site) => Promise<string | null>;
  onDeleteSite: (index: number) => void;
  onSwitch: () => void;
  /** The service's reason the last change was refused. */
  refusal: string | null;
  disabledReason: string | null;
}

/** The Site card: one row per site, Draw site, and the link back to a maximum volume. */
export function SiteBox({ sites, heights, onOpenSettings, tool, onDraw, onEdit, onChangeSite, onDeleteSite, onSwitch, refusal, disabledReason }: SiteBoxProps) {
  const titleId = useId();
  const [renaming, setRenaming] = useState<number | null>(null);
  return (
    <section className="input-box input-box-filled" aria-labelledby={titleId}>
      <div className="input-box-title-row">
        <Subheading id={titleId} className="input-box-title">{messages.siteTitle}</Subheading>
        <span className="input-box-required">{messages.requiredInput}</span>
      </div>
      {sites.length === 0 ? <p className="input-box-hint">{messages.siteEmptyHint}</p> : (
        <ul className="site-list">
          {sites.map((site, index) => (
            <SiteRow key={`${index}-${site.name}`} site={site} heights={heights} onOpenSettings={onOpenSettings}
                     editing={tool?.kind === "edit" && tool.index === index} renaming={renaming === index}
                     disabledReason={disabledReason} onRenamed={(name) => {
                       setRenaming(null);
                       if (name && name !== site.name) void onChangeSite(index, { ...site, name });
                     }}
                     onHeight={(height) => onChangeSite(index, { ...site, height })}
                     onBase={(base) => onChangeSite(index, { ...site, base_height: base })}
                     onChoose={(key) => {
                       if (key === "rename") setRenaming(index);
                       else if (key === "edit") onEdit(index);
                       else if (key === "delete") onDeleteSite(index);
                     }} />
          ))}
        </ul>
      )}
      <div className="site-card-actions">
        <button type="button" className="input-add" disabled={disabledReason !== null || tool?.kind === "draw"} onClick={onDraw}>{messages.drawSite}</button>
      </div>
      {refusal !== null && <p className="input-box-problem" role="alert"><WarningIcon />{refusal}</p>}
      {disabledReason !== null && <p className="input-box-reason">{disabledReason}</p>}
      <SwitchInputLink toSite={false} asks={sites.length > 0} onSwitch={onSwitch} disabledReason={disabledReason} />
    </section>
  );
}

interface SiteRowProps {
  site: Site;
  heights: Heights;
  onOpenSettings: (settingName: "max_height" | "base_height") => void;
  editing: boolean;
  renaming: boolean;
  disabledReason: string | null;
  onRenamed: (name: string) => void;
  onHeight: (height: number) => Promise<string | null>;
  onBase: (base: number | null) => Promise<string | null>;
  onChoose: (key: string) => void;
}

function SiteRow({ site, heights, onOpenSettings, editing, renaming, disabledReason, onRenamed, onHeight, onBase, onChoose }: SiteRowProps) {
  const points = outlinePoints(site.points);
  const [typedProblems, setTypedProblems] = useState<string[]>([]);
  // A typed height is checked as the site would be with it; a problem keeps it unsaved and is shown in the row
  const check = (changed: Site) => {
    const problems = siteProblems(changed, heights);
    setTypedProblems(problems);
    return problems.length === 0;
  };
  const problems = siteProblems(site, heights);
  const disabled = disabledReason !== null;
  return (
    <li className={`site-row${editing ? " site-row-editing" : ""}`}>
      <span className="site-row-name">
        {renaming ? (
          <input type="text" defaultValue={site.name} aria-label={messages.siteNameOf(site.name)} autoFocus maxLength={80}
                 onBlur={(event) => onRenamed(event.target.value.trim())}
                 onKeyDown={(event) => {
                   if (event.key === "Enter") onRenamed(event.currentTarget.value.trim());
                   else if (event.key === "Escape") onRenamed(site.name);
                 }} />
        ) : site.name}
      </span>
      <ActionMenu label={messages.siteActions(site.name)} symbol={<span aria-hidden="true">⋯</span>} onChoose={onChoose}
                  items={[
                    { key: "rename", label: messages.renameSite, disabledReason },
                    { key: "edit", label: messages.editSite, disabledReason },
                    { key: "delete", label: messages.deleteSite, disabledReason },
                  ]} />
      <span className="site-row-heights">
        {heights.base.for_all_sites ? (
          <SetInSettings label={messages.siteBase} value={baseHeightOf(site, heights)} onOpen={() => onOpenSettings("base_height")} />
        ) : (
          <HeightField label={messages.siteBase} ariaLabel={messages.siteBaseOf(site.name)} value={site.base_height ?? null} optional
                       invalid={typedProblems.length > 0} disabled={disabled}
                       onCommit={(base) => {
                         if (base === undefined) setTypedProblems([messages.heightNotPositive]);
                         else if (check({ ...site, base_height: base })) void onBase(base);
                       }} />
        )}
        {heights.max.for_all_sites ? (
          <SetInSettings label={messages.siteHeight} value={maxHeightOf(site, heights)} onOpen={() => onOpenSettings("max_height")} />
        ) : (
          <HeightField label={messages.siteHeight} ariaLabel={messages.siteHeightOf(site.name)} value={site.height} optional={false}
                       invalid={typedProblems.length > 0} disabled={disabled}
                       onCommit={(height) => {
                         if (height === null || height === undefined) setTypedProblems([messages.siteHeightNotPositive]);
                         else if (check({ ...site, height })) void onHeight(height);
                       }} />
        )}
      </span>
      <span className="site-row-details">{messages.siteArea(planArea(points))} · {messages.siteElevations(siteRise(points))}</span>
      {(typedProblems.length > 0 ? typedProblems : problems).map((problem) => <span key={problem} className="site-row-problem">{problem}</span>)}
    </li>
  );
}

/** A height set for all sites in Settings: its value, read-only, and a click that opens Settings on it. */
function SetInSettings({ label, value, onOpen }: { label: string; value: number | null; onOpen: () => void }) {
  const valueText = value === null ? messages.siteNoBase : `${formattedNumber(value)}\u00a0m`;
  return (
    <span className="site-row-height">
      <span>{label}</span>
      <button type="button" className="link-button site-row-set-in-settings" title={messages.heightSetInSettingsHint} onClick={onOpen}>
        {messages.heightSetInSettings(valueText)}
      </button>
    </span>
  );
}

interface HeightFieldProps {
  label: string;
  ariaLabel: string;
  value: number | null;
  /** Whether it may be left empty (the base height: no lower limit). Empty commits null, a typed value that is no positive number
   * undefined. */
  optional: boolean;
  invalid: boolean;
  disabled: boolean;
  onCommit: (value: number | null | undefined) => void;
}

/** A site's own height, typed; committed on Enter or when the field is left, when it changed. */
function HeightField({ label, ariaLabel, value, optional, invalid, disabled, onCommit }: HeightFieldProps) {
  const shown = value === null ? "" : formattedNumber(value);
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
      onCommit(null);
      return;
    }
    const typed = Number(trimmed.replace(",", "."));
    onCommit(Number.isFinite(typed) && typed > 0 ? typed : undefined);
  };
  return (
    <label className="site-row-height">
      <span>{label}</span>
      <input type="text" inputMode="decimal" value={text} aria-label={ariaLabel} aria-invalid={invalid} disabled={disabled}
             placeholder={optional ? messages.siteNoBase : undefined}
             onChange={(event) => setText(event.target.value)} onBlur={commit}
             onKeyDown={(event) => { if (event.key === "Enter") commit(); }} />
      <span>m</span>
    </label>
  );
}

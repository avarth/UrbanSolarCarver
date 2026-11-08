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
import { outlinePoints, planArea, siteProblems, siteRise, type Site } from "./site_geometry";
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
export function SiteBox({ sites, tool, onDraw, onEdit, onChangeSite, onDeleteSite, onSwitch, refusal, disabledReason }: SiteBoxProps) {
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
            <SiteRow key={`${index}-${site.name}`} site={site} editing={tool?.kind === "edit" && tool.index === index} renaming={renaming === index}
                     disabledReason={disabledReason} onRenamed={(name) => {
                       setRenaming(null);
                       if (name && name !== site.name) void onChangeSite(index, { ...site, name });
                     }}
                     onHeight={(height) => onChangeSite(index, { ...site, height })}
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
  editing: boolean;
  renaming: boolean;
  disabledReason: string | null;
  onRenamed: (name: string) => void;
  onHeight: (height: number) => Promise<string | null>;
  onChoose: (key: string) => void;
}

function SiteRow({ site, editing, renaming, disabledReason, onRenamed, onHeight, onChoose }: SiteRowProps) {
  const points = outlinePoints(site.points);
  const [heightText, setHeightText] = useState(formattedNumber(site.height));
  const [shownHeight, setShownHeight] = useState(site.height);
  if (shownHeight !== site.height) {
    setShownHeight(site.height);
    setHeightText(formattedNumber(site.height));
  }
  const typedHeight = Number(heightText.replace(",", "."));
  const heightProblems = Number.isFinite(typedHeight) ? siteProblems({ ...site, height: typedHeight }) : [messages.siteHeightNotPositive];
  const commitHeight = () => {
    if (!Number.isFinite(typedHeight) || typedHeight === site.height) return;
    if (heightProblems.length) return;
    void onHeight(typedHeight);
  };
  const problems = siteProblems(site);
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
      <label className="site-row-height">
        <span>{messages.siteHeight}</span>
        <input type="text" inputMode="decimal" value={heightText} aria-label={messages.siteHeightOf(site.name)} aria-invalid={heightProblems.length > 0}
               disabled={disabledReason !== null} onChange={(event) => setHeightText(event.target.value)} onBlur={commitHeight}
               onKeyDown={(event) => { if (event.key === "Enter") commitHeight(); }} />
        <span>m</span>
      </label>
      <ActionMenu label={messages.siteActions(site.name)} symbol={<span aria-hidden="true">⋯</span>} onChoose={onChoose}
                  items={[
                    { key: "rename", label: messages.renameSite, disabledReason },
                    { key: "edit", label: messages.editSite, disabledReason },
                    { key: "delete", label: messages.deleteSite, disabledReason },
                  ]} />
      <span className="site-row-details">{messages.siteArea(planArea(points))} · {messages.siteElevations(siteRise(points))}</span>
      {(heightProblems.length > 0 ? heightProblems : problems).map((problem) => <span key={problem} className="site-row-problem">{problem}</span>)}
    </li>
  );
}

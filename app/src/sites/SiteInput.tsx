// The maximum volume input of Carve › Inputs when it is chosen between a maximum volume and a site (design/site-input.md): the two
// tiles before either has content, the Site card (a row per site with its name, height, area and elevations, Draw site), and the
// link that switches the input, which asks first when the input has content. The sites themselves are drawn and edited in the view
// (SiteEditor.tsx).
import { useId, useRef, useState, type CSSProperties, type DragEvent, type FormEvent } from "react";
import { ActionMenu } from "../common/ActionMenu";
import { DialogButtons, DialogFrame } from "../common/dialogs";
import { messages } from "../messages";
import { Subheading } from "../settings_form/Subheading";
import { WarningIcon } from "../settings_form/SettingField";
import { formattedNumber } from "../format_numbers";
import { differsFromOriginal, outlinePoints, planArea, siteProblems, siteRise, type Heights, type Site } from "./site_geometry";
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
  /** The max and base heights: a height set per site is a column of the table (a height for all sites is in Settings). */
  heights: Heights;
  tool: SiteTool | null;
  onDraw: () => void;
  onEdit: (index: number) => void;
  onChangeSite: (index: number, site: Site) => Promise<string | null>;
  onDeleteSite: (index: number) => void;
  onSwitch: () => void;
  /** A DXF or OBJ file chosen with Import or dropped on the box (design/site-import.md). */
  onImport: (file: File) => void;
  /** Place on terrain and Restore original, from a site's menu. */
  onPlaceOnTerrain: (index: number) => void;
  onRestoreOriginal: (index: number) => void;
  /** Whether the project has terrain: Place on terrain needs it. */
  hasTerrain: boolean;
  /** The service's reason the last change was refused. */
  refusal: string | null;
  /** What the last import or Place on terrain said ("2 vertices have no terrain under them ..."), or why an import failed. */
  note?: { text: string; warning: boolean } | null;
  disabledReason: string | null;
}

/** The Sites card: Draw site at the right of its title, a line for the heights set for all sites, a table of the sites (a line each:
 * name, the heights set per site, the menu), and at its foot the link back to a maximum volume. */
export function SiteBox({ sites, heights, tool, onDraw, onEdit, onChangeSite, onDeleteSite, onSwitch, onImport, onPlaceOnTerrain,
                          onRestoreOriginal, hasTerrain, refusal, note = null, disabledReason }: SiteBoxProps) {
  const titleId = useId();
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const outlineFileOf = (files: FileList | null) => Array.from(files ?? []).find((file) => /\.(dxf|obj)$/i.test(file.name));
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const file = outlineFileOf(event.dataTransfer.files);
    if (file && disabledReason === null) onImport(file);
  };
  const [renaming, setRenaming] = useState<number | null>(null);
  const perSite = { base: !heights.base.for_all_sites, max: !heights.max.for_all_sites };
  const columns = Number(perSite.base) + Number(perSite.max);
  return (
    <section className={`input-box input-box-filled${dragging && disabledReason === null ? " input-box-drop-target" : ""}`} aria-labelledby={titleId}
             onDragOver={(event) => { event.preventDefault(); if (disabledReason === null) setDragging(true); }}
             onDragLeave={() => setDragging(false)} onDrop={drop}>
      <input ref={picker} type="file" hidden accept=".dxf,.obj"
             onChange={(event) => { const file = outlineFileOf(event.target.files); event.target.value = ""; if (file) onImport(file); }} />
      <div className="input-box-title-row">
        <Subheading id={titleId} className="input-box-title">{messages.siteTitle}</Subheading>
        <span className="site-box-actions">
          <button type="button" className="input-add" disabled={disabledReason !== null || tool?.kind === "draw"} onClick={onDraw}>{messages.drawSite}</button>
          <button type="button" className="input-add" disabled={disabledReason !== null} onClick={() => picker.current?.click()}>{messages.importSites}</button>
        </span>
      </div>
      <p className="input-box-hint">{messages.siteHint}</p>
      {sites.length === 0 ? <><p className="input-box-hint">{messages.siteEmptyHint}</p><p className="input-box-drop-hint">{messages.siteDropHint}</p></> : (
        <div className="site-table" style={{ "--site-table-columns": tableColumns(columns) } as CSSProperties}>
          {columns > 0 && (
            <div className="site-table-head" aria-hidden="true">
              <span />
              {perSite.base && <span>{messages.baseHeight}<small>m</small></span>}
              {perSite.max && <span>{messages.maxHeight}<small>m</small></span>}
              <span />
            </div>
          )}
          <ul className="site-list">
            {sites.map((site, index) => (
              <SiteRow key={`${index}-${site.name}`} site={site} heights={heights} perSite={perSite}
                       editing={tool?.kind === "edit" && tool.index === index} renaming={renaming === index}
                       disabledReason={disabledReason} onRenamed={(name) => {
                         setRenaming(null);
                         if (name && name !== site.name) void onChangeSite(index, { ...site, name });
                       }}
                       onHeight={(height) => onChangeSite(index, { ...site, height })}
                       onBase={(base) => onChangeSite(index, { ...site, base_height: base })}
                       hasTerrain={hasTerrain}
                       onChoose={(key) => {
                         if (key === "rename") setRenaming(index);
                         else if (key === "edit") onEdit(index);
                         else if (key === "place_on_terrain") onPlaceOnTerrain(index);
                         else if (key === "restore_original") onRestoreOriginal(index);
                         else if (key === "delete") onDeleteSite(index);
                       }} />
            ))}
          </ul>
        </div>
      )}
      {refusal !== null && <p className="input-box-problem" role="alert"><WarningIcon />{refusal}</p>}
      {note !== null && (note.warning ? <p className="input-box-problem" role="alert"><WarningIcon />{note.text}</p>
        : <p className="input-box-hint" role="status">{note.text}</p>)}
      {disabledReason !== null && <p className="input-box-reason">{disabledReason}</p>}
      <SwitchInputLink toSite={false} asks={sites.length > 0} onSwitch={onSwitch} disabledReason={disabledReason} />
    </section>
  );
}

/** The grid columns of the table: the name, one per height set per site, the menu. */
function tableColumns(heightColumns: number): string {
  return ["minmax(0, 1fr)", ...Array.from({ length: heightColumns }, () => "5.4em"), "1.8em"].join(" ");
}

interface SiteRowProps {
  site: Site;
  heights: Heights;
  /** Which heights are each site's own, and so have a column. */
  perSite: { base: boolean; max: boolean };
  editing: boolean;
  renaming: boolean;
  disabledReason: string | null;
  onRenamed: (name: string) => void;
  onHeight: (height: number) => Promise<string | null>;
  onBase: (base: number | null) => Promise<string | null>;
  onChoose: (key: string) => void;
  hasTerrain: boolean;
}

/** One line per site; its area and elevations are in the name's tooltip, and under the name while the site is edited. */
function SiteRow({ site, heights, perSite, editing, renaming, disabledReason, onRenamed, onHeight, onBase, onChoose, hasTerrain }: SiteRowProps) {
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
  const details = `${messages.siteArea(planArea(points))} · ${messages.siteElevations(siteRise(points))}`;
  return (
    <li className={`site-row${editing ? " site-row-editing" : ""}`}>
      <span className="site-row-name" title={`${site.name}: ${details}. ${messages.doubleClickToRename}`}
            onDoubleClick={() => { if (!renaming && !disabled) onChoose("rename"); }}>
        {renaming ? (
          <input type="text" defaultValue={site.name} aria-label={messages.siteNameOf(site.name)} autoFocus maxLength={80}
                 onBlur={(event) => onRenamed(event.target.value.trim())}
                 onKeyDown={(event) => {
                   if (event.key === "Enter") onRenamed(event.currentTarget.value.trim());
                   else if (event.key === "Escape") onRenamed(site.name);
                 }} />
        ) : site.name}
      </span>
      {perSite.base && (
        <HeightField ariaLabel={messages.siteBaseOf(site.name)} value={site.base_height ?? null} optional
                     invalid={typedProblems.length > 0} disabled={disabled}
                     onCommit={(base) => {
                       if (base === undefined) setTypedProblems([messages.heightNotPositive]);
                       else if (check({ ...site, base_height: base })) void onBase(base);
                     }} />
      )}
      {perSite.max && (
        <HeightField ariaLabel={messages.siteHeightOf(site.name)} value={site.height} optional={false}
                     invalid={typedProblems.length > 0} disabled={disabled}
                     onCommit={(height) => {
                       if (height === null || height === undefined) setTypedProblems([messages.siteHeightNotPositive]);
                       else if (check({ ...site, height })) void onHeight(height);
                     }} />
      )}
      <ActionMenu label={messages.siteActions(site.name)} symbol={<span aria-hidden="true">⋯</span>} onChoose={onChoose}
                  items={[
                    { key: "rename", label: messages.renameSite, disabledReason },
                    { key: "edit", label: messages.editSite, disabledReason },
                    { key: "place_on_terrain", label: messages.placeOnTerrain, disabledReason: hasTerrain ? disabledReason : messages.placeOnTerrainNeedsTerrain },
                    ...(differsFromOriginal(site) ? [{ key: "restore_original", label: messages.restoreOriginal, disabledReason }] : []),
                    { key: "delete", label: messages.deleteSite, disabledReason },
                  ]} />
      {editing && <span className="site-row-details">{details}</span>}
      {(typedProblems.length > 0 ? typedProblems : problems).map((problem) => <span key={problem} className="site-row-problem">{problem}</span>)}
    </li>
  );
}

interface HeightFieldProps {
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
function HeightField({ ariaLabel, value, optional, invalid, disabled, onCommit }: HeightFieldProps) {
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
    onCommit(Number.isFinite(typed) && (typed > 0 || (optional && typed === 0)) ? typed : undefined);
  };
  return (
    <input type="text" inputMode="decimal" className="site-row-height" value={text} aria-label={ariaLabel} aria-invalid={invalid} disabled={disabled}
           placeholder={optional ? messages.siteNoBase : undefined}
           onChange={(event) => setText(event.target.value)} onBlur={commit}
           onKeyDown={(event) => { if (event.key === "Enter") commit(); }} />
  );
}

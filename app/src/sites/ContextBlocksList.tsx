// The drawn context blocks in the Context box (design/context-blocks.md), laid out as the Sites table: a row each with its name
// (renamed by a double click), its height typed in a column (Enter or leaving the field stores it), and a menu of Edit (its outline
// in the 3D view, with the site editor), Draw hole, Place on terrain where there is a terrain, and Remove. The block being edited is
// marked and scrolled into view; past five rows the rows scroll. A change the service refuses puts the row back as it was; the
// reason is shown under the rows, and Undo under them takes back the last change (a block removed by mistake).
import { useEffect, useRef, useState } from "react";
import { ActionMenu } from "../common/ActionMenu";
import { formattedNumber } from "../format_numbers";
import { messages } from "../messages";
import { useFiveRows } from "./five_rows";
import type { Site } from "./site_geometry";
import "./sites.css";

export interface ContextBlocksListProps {
  blocks: Site[];
  disabledReason: string | null;
  hasTerrain: boolean;
  /** The block whose height field takes the focus (one just drawn); null: none. */
  focusHeightOf: number | null;
  /** The service's reason the last change was refused, or null. */
  refusal: string | null;
  /** The block being edited in the view (or drawn a hole of); null: none. */
  editing: number | null;
  onEdit: (index: number) => void;
  onDrawHole: (index: number) => void;
  /** Stores a changed block; resolves to null once saved, or the reason it was refused. */
  onChange: (index: number, block: Site) => Promise<string | null>;
  onRemove: (index: number) => void;
  onPlaceOnTerrain: (index: number) => void;
  /** The last change of the blocks can be taken back (a removal by mistake); Undo shows under the rows while it can. */
  canUndo: boolean;
  onUndo: () => void;
}

export function ContextBlocksList({ blocks, disabledReason, hasTerrain, focusHeightOf, refusal, editing, onEdit, onDrawHole, onChange, onRemove,
                                    onPlaceOnTerrain, canUndo, onUndo }: ContextBlocksListProps) {
  const list = useFiveRows();
  if (blocks.length === 0 && refusal === null && !canUndo) return null;
  return (
    <div className="context-blocks">
      {blocks.length > 0 && (
        <div className="site-table context-blocks-table">
          <div className="site-table-head" aria-hidden="true">
            <span>{messages.drawnBlocks}</span>
            <span>{messages.blockHeight}<small>m</small></span>
            <span />
          </div>
          <ul ref={list} className="site-list">
            {blocks.map((block, index) => (
              // keyed by its values too: a block changed or put back by a refusal shows its stored name and height afresh
              <BlockRow key={`${index}:${block.name}:${block.height}`} block={block} disabledReason={disabledReason} hasTerrain={hasTerrain}
                        focusHeight={focusHeightOf === index} editing={editing === index}
                        onChange={(changed) => onChange(index, changed)}
                        onChoose={(key) => {
                          if (key === "edit") onEdit(index);
                          else if (key === "draw_hole") onDrawHole(index);
                          else if (key === "place_on_terrain") onPlaceOnTerrain(index);
                          else if (key === "remove") onRemove(index);
                        }} />
            ))}
          </ul>
        </div>
      )}
      {refusal !== null && <p className="input-box-problem" role="alert">{refusal}</p>}
      {canUndo && (
        <p className="context-blocks-undo">
          <button type="button" className="link-button" disabled={disabledReason !== null} onClick={onUndo}>{messages.undoBlockChange}</button>
        </p>
      )}
    </div>
  );
}

interface BlockRowProps {
  block: Site;
  disabledReason: string | null;
  hasTerrain: boolean;
  focusHeight: boolean;
  editing: boolean;
  onChange: (block: Site) => Promise<string | null>;
  onChoose: (key: string) => void;
}

function BlockRow({ block, disabledReason, hasTerrain, focusHeight, editing, onChange, onChoose }: BlockRowProps) {
  const disabled = disabledReason !== null;
  const [renaming, setRenaming] = useState(false);
  const [height, setHeight] = useState(formattedNumber(block.height));
  const row = useRef<HTMLLIElement>(null);
  const heightField = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusHeight) heightField.current?.focus();
  }, [focusHeight]);
  useEffect(() => {
    if (editing) row.current?.scrollIntoView?.({ block: "nearest" });
  }, [editing]);
  const store = async (changed: Site) => {
    if (await onChange(changed) !== null) setHeight(formattedNumber(block.height));     // refused: the row goes back to the block as it is
  };
  const renamed = (name: string) => {
    setRenaming(false);
    if (name !== "" && name !== block.name) void store({ ...block, name });
  };
  const commitHeight = () => {
    const value = Number(height.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) return setHeight(formattedNumber(block.height));
    if (value !== block.height) void store({ ...block, height: value });
  };
  return (
    <li ref={row} className={`site-row context-block-row${editing ? " site-row-editing" : ""}`}>
      <span className="site-row-name" title={`${block.name}. ${messages.doubleClickToRename}`}
            onDoubleClick={() => { if (!renaming && !disabled) setRenaming(true); }}>
        {renaming ? (
          <input type="text" defaultValue={block.name} aria-label={messages.blockNameLabel} autoFocus maxLength={80}
                 onBlur={(event) => renamed(event.target.value.trim())}
                 onKeyDown={(event) => {
                   if (event.key === "Enter") renamed(event.currentTarget.value.trim());
                   else if (event.key === "Escape") renamed(block.name);
                 }} />
        ) : block.name}
      </span>
      <input ref={heightField} type="text" className="site-row-height" aria-label={messages.blockHeightLabel(block.name)} inputMode="decimal"
             value={height} disabled={disabled} onChange={(event) => setHeight(event.target.value)} onBlur={commitHeight}
             onKeyDown={(event) => { if (event.key === "Enter") commitHeight(); }} />
      <ActionMenu label={messages.blockActions(block.name)} symbol={<span aria-hidden="true">⋯</span>} onChoose={onChoose}
                  items={[
                    { key: "edit", label: messages.editBlock, disabledReason },
                    { key: "draw_hole", label: messages.drawHole, disabledReason },
                    ...(hasTerrain ? [{ key: "place_on_terrain", label: messages.placeBlockOnTerrain, disabledReason }] : []),
                    { key: "remove", label: messages.removeBlockShort, disabledReason },
                  ]} />
    </li>
  );
}

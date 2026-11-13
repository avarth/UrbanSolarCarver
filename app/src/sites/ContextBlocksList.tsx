// The drawn context blocks in the Context box (design/context-blocks.md): one row each, with its name and height typed in place
// (Enter or leaving the field stores them), Edit (its outline in the 3D view, with the site editor), Place on terrain where there is
// a terrain, and Remove. A change the service refuses puts the row back as it was; the reason is shown under the rows.
import { useEffect, useRef, useState } from "react";
import { formattedNumber } from "../format_numbers";
import { messages } from "../messages";
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
  onEdit: (index: number) => void;
  /** Stores a changed block; resolves to null once saved, or the reason it was refused. */
  onChange: (index: number, block: Site) => Promise<string | null>;
  onRemove: (index: number) => void;
  onPlaceOnTerrain: (index: number) => void;
  /** The last change of the blocks can be taken back (a removal by mistake); Undo shows under the rows while it can. */
  canUndo: boolean;
  onUndo: () => void;
}

export function ContextBlocksList({ blocks, disabledReason, hasTerrain, focusHeightOf, refusal, onEdit, onChange, onRemove, onPlaceOnTerrain,
                                    canUndo, onUndo }: ContextBlocksListProps) {
  if (blocks.length === 0 && refusal === null && !canUndo) return null;
  return (
    <div className="context-blocks">
      {blocks.map((block, index) => (
        // keyed by its values too: a block changed or put back by a refusal shows its stored name and height afresh
        <BlockRow key={`${index}:${block.name}:${block.height}`} block={block} disabled={disabledReason !== null} hasTerrain={hasTerrain} focusHeight={focusHeightOf === index}
                  onEdit={() => onEdit(index)} onChange={(changed) => onChange(index, changed)} onRemove={() => onRemove(index)}
                  onPlaceOnTerrain={() => onPlaceOnTerrain(index)} />
      ))}
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
  disabled: boolean;
  hasTerrain: boolean;
  focusHeight: boolean;
  onEdit: () => void;
  onChange: (block: Site) => Promise<string | null>;
  onRemove: () => void;
  onPlaceOnTerrain: () => void;
}

function BlockRow({ block, disabled, hasTerrain, focusHeight, onEdit, onChange, onRemove, onPlaceOnTerrain }: BlockRowProps) {
  const [name, setName] = useState(block.name);
  const [height, setHeight] = useState(formattedNumber(block.height));
  const heightField = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusHeight) heightField.current?.focus();
  }, [focusHeight]);
  const store = async (changed: Site) => {
    if (await onChange(changed) !== null) {     // refused: the row goes back to the block as it is
      setName(block.name);
      setHeight(formattedNumber(block.height));
    }
  };
  const commitName = () => {
    const trimmed = name.trim();
    if (trimmed === "" ) return setName(block.name);
    if (trimmed !== block.name) void store({ ...block, name: trimmed });
  };
  const commitHeight = () => {
    const value = Number(height.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) return setHeight(formattedNumber(block.height));
    if (value !== block.height) void store({ ...block, height: value });
  };
  const onEnter = (commit: () => void) => (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") commit();
  };
  return (
    <div className="context-block-row">
      <input className="context-block-name" aria-label={messages.blockNameLabel} value={name} disabled={disabled} maxLength={80}
             onChange={(event) => setName(event.target.value)} onBlur={commitName} onKeyDown={onEnter(commitName)} />
      <input ref={heightField} className="context-block-height" aria-label={messages.blockHeightLabel(block.name)} inputMode="decimal"
             value={height} disabled={disabled} onChange={(event) => setHeight(event.target.value)} onBlur={commitHeight} onKeyDown={onEnter(commitHeight)} />
      <span className="context-block-unit" aria-hidden="true">m</span>
      <span className="context-block-actions">
        <button type="button" className="link-button" disabled={disabled} onClick={onEdit}>{messages.editBlock}</button>
        {hasTerrain && <button type="button" className="link-button" disabled={disabled} onClick={onPlaceOnTerrain}>{messages.placeBlockOnTerrain}</button>}
        <button type="button" className="link-button" disabled={disabled} onClick={onRemove} aria-label={messages.removeBlock(block.name)}>{messages.removeBlockShort}</button>
      </span>
    </div>
  );
}

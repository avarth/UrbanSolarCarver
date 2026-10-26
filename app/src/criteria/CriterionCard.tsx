// One criterion's card in the list of several (spec 7.2): a drag handle (the arrow keys on it move the card one place), the colour
// swatch of the criterion in the 3D view, its name, its mode's symbol and one line (its result while current, else its status), a
// bypass switch and a menu with Rename, Duplicate and Delete. A press on the card selects it. The list (CriterionList) does the
// dragging and the requests.
import { useId, type DragEvent, type KeyboardEvent } from "react";
import type { CriterionEntry } from "../api_client/client";
import { messages } from "../messages";
import { ActionMenu } from "../steps/ActionMenu";
import { ModeTileSymbol } from "../steps/ModeTileSymbols";
import { MODE_TILES } from "../steps/step_summaries";
import "../steps/steps.css";

export type CriterionMenuItem = "rename" | "duplicate" | "delete";

export interface CriterionCardProps {
  entry: CriterionEntry;
  /** Its result while current, else the words of its status. */
  line: string;
  selected: boolean;
  /** Why Delete waits (the only criterion); null when it can be chosen. */
  deleteDisabledReason: string | null;
  /** Why the card cannot be changed now (a run is in progress); null when it can. */
  disabledReason: string | null;
  onSelect: () => void;
  /** Moves the card one place up (-1) or down (1). */
  onMove: (step: -1 | 1) => void;
  onSetBypassed: (on: boolean) => void;
  onChoose: (item: CriterionMenuItem) => void;
  /** The drag of the card by its handle, and drops of another card onto it. */
  onDragStart?: (event: DragEvent) => void;
  onDragEnd?: () => void;
  onDragOver?: (event: DragEvent) => void;
  onDragLeave?: (event: DragEvent) => void;
  onDrop?: (event: DragEvent) => void;
  /** A card is dragged over this one, where it would go if dropped. */
  dropTarget?: boolean;
}

const MOVES: Record<string, -1 | 1> = { ArrowUp: -1, ArrowDown: 1 };

function GripIcon() {
  return (
    <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor" aria-hidden="true">
      {[3, 8, 13].flatMap((y) => [<circle key={`l${y}`} cx="2.5" cy={y} r="1.4" />, <circle key={`r${y}`} cx="7.5" cy={y} r="1.4" />])}
    </svg>
  );
}

export function CriterionCard(props: CriterionCardProps) {
  const { entry, selected, disabledReason } = props;
  const disabled = disabledReason !== null;
  const hintId = useId();
  const mode = String(entry.settings?.mode ?? "");
  const symbol = MODE_TILES.find((tile) => tile.engine_name === mode)?.symbol;
  const moveWithKeys = (event: KeyboardEvent) => {
    const step = MOVES[event.key];
    if (step === undefined || disabled) return;
    event.preventDefault();
    props.onMove(step);
  };
  const classes = ["criterion-card", selected && "criterion-card-selected", entry.bypassed && "criterion-card-bypassed", props.dropTarget && "criterion-card-drop-target"];
  return (
    <li className={classes.filter(Boolean).join(" ")} aria-current={selected || undefined} data-criterion-id={entry.id}
        onDragOver={props.onDragOver} onDragLeave={props.onDragLeave} onDrop={props.onDrop}>
      <span className="criterion-card-handle" role="button" tabIndex={0} draggable={!disabled} aria-disabled={disabled || undefined}
            aria-label={messages.moveCriterion(entry.name)} aria-describedby={hintId} title={messages.moveCriterionHint} onKeyDown={moveWithKeys}
            onDragStart={props.onDragStart} onDragEnd={props.onDragEnd}>
        <GripIcon />
        <span id={hintId} className="visually-hidden">{messages.moveCriterionHint}</span>
      </span>
      <button type="button" className="criterion-card-select" onClick={props.onSelect}>
        <span className="criterion-card-swatch" style={{ background: entry.colour }} aria-hidden="true" />
        <span className="criterion-card-text">
          <span className="criterion-card-name">{entry.name}</span>
          <span className="criterion-card-line">{props.line}</span>
        </span>
        {symbol !== undefined && <ModeTileSymbol symbol={symbol} />}
      </button>
      <input type="checkbox" role="switch" className="setting-switch criterion-card-bypass" checked={entry.bypassed} disabled={disabled}
             aria-label={messages.bypassCriterion(entry.name)} onChange={(event) => props.onSetBypassed(event.target.checked)} />
      <ActionMenu label={messages.criterionMenuOf(entry.name)} symbol={<span aria-hidden="true">{messages.projectMenuSymbol}</span>}
                  buttonClassName="criterion-card-menu-button" onChoose={(key) => props.onChoose(key as CriterionMenuItem)}
                  items={[
                    { key: "rename", label: messages.renameCriterion, disabledReason },
                    { key: "duplicate", label: messages.duplicateCriterion, disabledReason },
                    { key: "delete", label: messages.deleteCriterion, disabledReason: disabledReason ?? props.deleteDisabledReason },
                  ]} />
    </li>
  );
}

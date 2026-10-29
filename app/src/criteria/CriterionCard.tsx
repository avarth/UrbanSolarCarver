// One criterion's card in the list (spec 7.2): a drag handle when the list has several cards (the arrow keys on it move the card
// one place), the colour swatch of the criterion in the 3D view, its name (whole, up to two lines), its mode's symbol, a
// chevron that says the card opens, a switch that is on while the chain uses the criterion, and a menu with Rename, Duplicate
// and Delete; under them, at the card's full width, one line (its result while current, else its status). A press on the card
// selects it. The list (CriterionList) does the dragging and the requests.
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
  /** The list has several cards: the card has a drag handle. */
  reorderable: boolean;
  /** A run is working on this criterion's stages: the card is marked busy. */
  running?: boolean;
  /** Why Delete waits (the only criterion); null when it can be chosen. */
  deleteDisabledReason: string | null;
  /** Why the card cannot be changed now (a run is in progress); null when it can. */
  disabledReason: string | null;
  onSelect: () => void;
  /** Moves the card one place up (-1) or down (1). */
  onMove: (step: -1 | 1) => void;
  /** The switch was turned: *on* true skips the criterion in the chain (the switch was turned off). */
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
  const lineId = useId();
  const mode = String(entry.settings?.mode ?? "");
  const symbol = MODE_TILES.find((tile) => tile.engine_name === mode)?.symbol;
  const moveWithKeys = (event: KeyboardEvent) => {
    const step = MOVES[event.key];
    if (step === undefined || disabled) return;
    event.preventDefault();
    props.onMove(step);
  };
  const classes = ["criterion-card", props.reorderable && "criterion-card-reorderable", selected && "criterion-card-selected", entry.bypassed && "criterion-card-bypassed", props.dropTarget && "criterion-card-drop-target",
                   props.running && "criterion-card-running"];
  return (
    <li className={classes.filter(Boolean).join(" ")} aria-current={selected || undefined} aria-busy={props.running || undefined} data-criterion-id={entry.id}
        onDragOver={props.onDragOver} onDragLeave={props.onDragLeave} onDrop={props.onDrop}>
      {props.reorderable && (
        <span className="criterion-card-handle" role="button" tabIndex={0} draggable={!disabled} aria-disabled={disabled || undefined}
              aria-label={messages.moveCriterion(entry.name)} aria-describedby={hintId} title={messages.moveCriterionHint} onKeyDown={moveWithKeys}
              onDragStart={props.onDragStart} onDragEnd={props.onDragEnd}>
          <GripIcon />
          <span id={hintId} className="visually-hidden">{messages.moveCriterionHint}</span>
        </span>
      )}
      <button type="button" className="criterion-card-select" aria-describedby={lineId} onClick={props.onSelect}>
        <span className="criterion-card-swatch" style={{ background: entry.colour }} aria-hidden="true" />
        <span className="criterion-card-name">{entry.name}</span>
        {symbol !== undefined && <ModeTileSymbol symbol={symbol} />}
        <span className="criterion-card-chevron" aria-hidden="true">›</span>
      </button>
      <input type="checkbox" role="switch" className="setting-switch criterion-card-switch" checked={!entry.bypassed} disabled={disabled}
             aria-label={messages.criterionSwitchLabel(entry.name)} onChange={(event) => props.onSetBypassed(!event.target.checked)} />
      <ActionMenu label={messages.criterionMenuOf(entry.name)} symbol={<span aria-hidden="true">{messages.projectMenuSymbol}</span>}
                  buttonClassName="criterion-card-menu-button" onChoose={(key) => props.onChoose(key as CriterionMenuItem)}
                  items={[
                    { key: "rename", label: messages.renameCriterion, disabledReason },
                    { key: "duplicate", label: messages.duplicateCriterion, disabledReason },
                    { key: "delete", label: messages.deleteCriterion, disabledReason: disabledReason ?? props.deleteDisabledReason },
                  ]} />
      <span id={lineId} className="criterion-card-line" onClick={props.onSelect}>{props.line}</span>
    </li>
  );
}

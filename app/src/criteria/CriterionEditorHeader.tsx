// The header of the editor of one criterion (spec 7.2), in three rows that stay at the top of the step while the sections scroll under
// them. Row 1: All criteria (back to the list) and, with several criteria, where this one stands in carving order with the buttons to
// the criterion before and after; at the first and the last criterion the button that leads nowhere waits (aria-disabled, so it keeps
// the focus a press gave it), and after a move a polite live region says the criterion's name and position. Row 2: the criterion's
// colour, mode symbol, the switch that is on while the chain uses it and the menu with Rename, Duplicate and Delete, as on its card;
// under them, across the header, its name (whole on up to two lines, the whole name its title; the step gives it the focus when a
// card, Add or Duplicate opens the editor). Row 3: its result or status line, cut with an ellipsis when it is long; the whole line is
// its title. The step (CriteriaStep) does the requests.
import { useEffect, useRef, useState } from "react";
import type { CriterionEntry } from "../api_client/client";
import { messages } from "../messages";
import { ActionMenu } from "../steps/ActionMenu";
import { ModeTileSymbol } from "../steps/ModeTileSymbols";
import { MODE_TILES } from "../steps/step_summaries";
import type { CriterionMenuItem } from "./CriterionCard";
import "../steps/steps.css";

export interface CriterionEditorHeaderProps {
  /** The criterion the editor shows: its colour, name, mode, and whether the chain uses it. */
  entry: CriterionEntry;
  /** Its result while current, else the words of its status. */
  line: string;
  /** Where the criterion stands in carving order, from 1. */
  position: number;
  /** How many criteria the project has; with one there is no position and no previous or next. */
  count: number;
  /** Back to the list of the criteria. */
  onShowList: () => void;
  /** Open the criterion before this one in carving order; not called at the first. */
  onPrevious: () => void;
  /** Open the criterion after this one in carving order; not called at the last. */
  onNext: () => void;
  /** Why the criterion cannot be changed now (a run is in progress); null when it can. */
  disabledReason: string | null;
  /** Why Delete waits (the only criterion); null when it can be chosen. */
  deleteDisabledReason: string | null;
  /** The switch was turned: *on* true means the chain skips the criterion (the switch was turned off), false that it uses it again. */
  onSetBypassed: (on: boolean) => void;
  /** An item of the menu was chosen: Rename, Duplicate or Delete. */
  onChoose: (item: CriterionMenuItem) => void;
}

function Chevron({ direction }: { direction: "left" | "up" | "down" }) {
  const points = { left: "10,3 5,8 10,13", up: "3,10 8,5 13,10", down: "3,6 8,11 13,6" }[direction];
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points={points} />
    </svg>
  );
}

export function CriterionEditorHeader(props: CriterionEditorHeaderProps) {
  const { entry, position, count, disabledReason } = props;
  const mode = String(entry.settings?.mode ?? "");
  const symbol = MODE_TILES.find((tile) => tile.engine_name === mode)?.symbol;
  const classes = ["criterion-editor-header", entry.bypassed && "criterion-editor-header-bypassed"];
  // What the live region says: the criterion previous or next opened, once it is shown (empty until then).
  const moved = useRef(false);
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    setSaid(messages.criterionShownAt(entry.name, messages.criterionPosition(position, count)));
  }, [entry.id]);
  const isFirst = position <= 1, isLast = position >= count;
  const move = (waits: boolean, open: () => void) => {
    if (waits) return;
    moved.current = true;
    open();
  };
  return (
    <div className={classes.filter(Boolean).join(" ")} data-criterion-id={entry.id}>
      <div className="criterion-editor-row">
        <button type="button" className="link-button criterion-editor-back" onClick={props.onShowList}>
          <Chevron direction="left" />
          {messages.allCriteria}
        </button>
        {count > 1 && (
          <span className="criterion-editor-neighbours">
            <span className="criterion-editor-position">{messages.criterionPosition(position, count)}</span>
            <button type="button" className="criterion-editor-step" aria-label={messages.previousCriterion} aria-disabled={isFirst || undefined}
                    onClick={() => move(isFirst, props.onPrevious)}>
              <Chevron direction="up" />
            </button>
            <button type="button" className="criterion-editor-step" aria-label={messages.nextCriterion} aria-disabled={isLast || undefined}
                    onClick={() => move(isLast, props.onNext)}>
              <Chevron direction="down" />
            </button>
          </span>
        )}
        <span className="visually-hidden" role="status">{said}</span>
      </div>
      <div className="criterion-editor-identity">
        <span className="criterion-card-swatch" style={{ background: entry.colour }} aria-hidden="true" />
        {symbol !== undefined && <ModeTileSymbol symbol={symbol} />}
        <input type="checkbox" role="switch" className="setting-switch criterion-card-switch" checked={!entry.bypassed} disabled={disabledReason !== null}
               aria-label={messages.criterionSwitchLabel(entry.name)} onChange={(event) => props.onSetBypassed(!event.target.checked)} />
        <ActionMenu label={messages.criterionMenuOf(entry.name)} symbol={<span aria-hidden="true">{messages.projectMenuSymbol}</span>}
                    buttonClassName="criterion-card-menu-button" onChoose={(key) => props.onChoose(key as CriterionMenuItem)}
                    items={[
                      { key: "rename", label: messages.renameCriterion, disabledReason },
                      { key: "duplicate", label: messages.duplicateCriterion, disabledReason },
                      { key: "delete", label: messages.deleteCriterion, disabledReason: disabledReason ?? props.deleteDisabledReason },
                    ]} />
        <h3 className="criterion-editor-name" tabIndex={-1} title={entry.name}>{entry.name}</h3>
      </div>
      <p className="criterion-editor-line" title={props.line}>{props.line}</p>
    </div>
  );
}

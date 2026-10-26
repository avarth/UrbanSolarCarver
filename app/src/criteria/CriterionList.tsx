// The criteria of a project with several (spec 7.2): their cards in carving order, the selected one marked, then Add criterion,
// which opens the mode tiles. A card moves by dragging its handle onto another card, or with the arrow keys on its handle; its
// menu renames (in a dialog), duplicates, or deletes (after a confirmation; never the only criterion). A change the service
// refuses is said under the cards. AddCriterion is also the one-criterion step's quiet "Add another criterion" (CriteriaStep).
import { useEffect, useRef, useState, type DragEvent } from "react";
import type { CriterionEntry } from "../api_client/client";
import { messages } from "../messages";
import { ModeStep } from "../steps/ModeStep";
import { CriterionCard, type CriterionMenuItem } from "./CriterionCard";
import { DeleteCriterionDialog, RenameCriterionDialog } from "./CriterionDialogs";
import { orderAfterDropping, orderAfterMoving } from "./criteria_state";
import "../steps/steps.css";

/** The requests of the list; each resolves with the reason it was refused, or null once done. */
export interface CriterionListProps {
  criteria: CriterionEntry[];
  selectedId: string;
  /** A card's line: its result while current, else its status. */
  lineOf: (criterion: CriterionEntry) => string;
  /** Why the criteria cannot be changed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  onSelect: (id: string) => void;
  onReorder: (ids: string[]) => Promise<string | null>;
  onSetBypassed: (id: string, on: boolean) => Promise<string | null>;
  onRename: (id: string, name: string) => Promise<string | null>;
  onDuplicate: (id: string) => Promise<string | null>;
  onDelete: (id: string) => Promise<string | null>;
  /** Adds a criterion of the mode at the end (it is then selected). */
  onAdd: (mode: string) => Promise<string | null>;
}

type OpenDialog = { kind: "rename" | "delete"; criterion: CriterionEntry };

interface AddCriterionProps {
  /** "Add criterion" under the cards, "Add another criterion" at the end of a one-criterion step. */
  label: string;
  onAdd: (mode: string) => Promise<string | null>;
  disabledReason: string | null;
}

/** A link that opens the mode tiles; choosing one adds a criterion of that mode, and the tiles close once it is added. */
export function AddCriterion({ label, onAdd, disabledReason }: AddCriterionProps) {
  const [choosing, setChoosing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const add = async (mode: string) => {
    setBusy(true);
    setProblem(null);
    const reason = await onAdd(mode);
    setBusy(false);
    if (reason === null) setChoosing(false);
    else setProblem(reason);
  };
  if (!choosing) {
    return (
      <div className="add-criterion">
        <button type="button" className="link-button" disabled={disabledReason !== null} onClick={() => setChoosing(true)}>{label}</button>
      </div>
    );
  }
  return (
    <div className="add-criterion add-criterion-open">
      <p className="add-criterion-title">{messages.newCriterionModeTitle}</p>
      <ModeStep mode="" onChoose={(mode) => void add(mode)} disabledReason={busy ? "" : disabledReason} weatherDropZone={null}
                showsNote={false} showsDisabledReason={false} />
      {problem !== null && <p className="setting-error" role="alert">{problem}</p>}
      <button type="button" className="link-button" disabled={busy} onClick={() => { setChoosing(false); setProblem(null); }}>{messages.cancel}</button>
    </div>
  );
}

export function CriterionList(props: CriterionListProps) {
  const { criteria, selectedId, disabledReason } = props;
  const [dialog, setDialog] = useState<OpenDialog | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);
  // The card moved with the keyboard and the order asked for: its handle takes the focus back once the cards are in that order
  // (moving the card in the page loses the focus).
  const [keyboardMove, setKeyboardMove] = useState<{ id: string; order: string } | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const ids = criteria.map((criterion) => criterion.id);
  const cardElement = (id: string | undefined) =>
    [...(list.current?.querySelectorAll<HTMLElement>(".criterion-card") ?? [])].find((card) => card.dataset.criterionId === id);

  useEffect(() => {
    if (keyboardMove === null || keyboardMove.order !== ids.join(",")) return;
    cardElement(keyboardMove.id)?.querySelector<HTMLElement>(".criterion-card-handle")?.focus();
    setKeyboardMove(null);
  }, [ids.join(",")]);

  /** Sends a change; resolves with whether it was done, the refusal said under the cards. */
  const request = async (change: Promise<string | null>): Promise<boolean> => {
    setProblem(null);
    const reason = await change;
    if (reason !== null) setProblem(reason);
    return reason === null;
  };
  const reorder = async (order: string[] | null) => order !== null && request(props.onReorder(order));
  const moveWithKeys = (id: string, step: -1 | 1) => {
    const order = orderAfterMoving(ids, id, step);
    if (order === null) return;
    setKeyboardMove({ id, order: order.join(",") });
    void reorder(order).then((done) => { if (!done) setKeyboardMove(null); });
  };
  const choose = (criterion: CriterionEntry, item: CriterionMenuItem) => {
    if (item === "duplicate") void request(props.onDuplicate(criterion.id));
    else setDialog({ kind: item, criterion });
  };
  const closeDialog = () => {
    const criterionId = dialog?.criterion.id;
    setDialog(null);
    cardElement(criterionId)?.querySelector<HTMLElement>(".action-menu-button")?.focus();
  };

  const dragHandlers = (criterion: CriterionEntry) => ({
    onDragStart: (event: DragEvent) => {
      setDraggedId(criterion.id);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", criterion.id);
        const card = (event.currentTarget as HTMLElement).closest("li");
        if (card) event.dataTransfer.setDragImage(card, 16, 16);
      }
    },
    onDragEnd: () => {
      setDraggedId(null);
      setDropTargetId(null);
    },
    onDragOver: (event: DragEvent) => {
      if (draggedId === null) return;
      event.preventDefault();                 // a card may be dropped here
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      setDropTargetId(criterion.id);
    },
    onDrop: (event: DragEvent) => {
      if (draggedId === null) return;
      event.preventDefault();
      void reorder(orderAfterDropping(ids, draggedId, criterion.id));
      setDraggedId(null);
      setDropTargetId(null);
    },
  });

  return (
    <div className="criteria-list-block">
      <ol ref={list} className="criterion-list" aria-label={messages.criteriaListLabel}>
        {criteria.map((criterion) => (
          <CriterionCard key={criterion.id} entry={criterion} line={props.lineOf(criterion)} selected={criterion.id === selectedId}
                         deleteDisabledReason={criteria.length === 1 ? messages.onlyCriterionStays : null} disabledReason={disabledReason}
                         onSelect={() => props.onSelect(criterion.id)}
                         onMove={(step) => moveWithKeys(criterion.id, step)}
                         onSetBypassed={(on) => void request(props.onSetBypassed(criterion.id, on))} onChoose={(item) => choose(criterion, item)}
                         dropTarget={dropTargetId === criterion.id && draggedId !== criterion.id} {...dragHandlers(criterion)} />
        ))}
      </ol>
      {problem !== null && <p className="setting-error criterion-list-problem" role="alert">{problem}</p>}
      <AddCriterion label={messages.addCriterion} onAdd={props.onAdd} disabledReason={disabledReason} />
      {dialog?.kind === "rename" && (
        <RenameCriterionDialog name={dialog.criterion.name} onRename={(name) => props.onRename(dialog.criterion.id, name)} onClose={closeDialog} />
      )}
      {dialog?.kind === "delete" && (
        <DeleteCriterionDialog name={dialog.criterion.name} onDelete={() => props.onDelete(dialog.criterion.id)} onClose={closeDialog} />
      )}
    </div>
  );
}

// The Criteria step (spec 7.1, 7.2): the list of the criteria or the editor of one, never both. The list is the cards (CriterionList,
// with Add criterion under the last one) and, with two or more criteria, what the chain kept (one line); a press on a card opens its
// editor. The editor is the header of the criterion (CriterionEditorHeader: back to the list, its neighbours, name, switch and menu,
// its line) over its panel. While a criterion just opened waits for its settings the panel says so (or why they could not be read)
// instead of showing another criterion's; a run refused because it protects nothing is said over its panel. Add and Duplicate open the
// editor of the criterion they make, with the focus on its name; a Delete returns to the list with the focus on the card selected then.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { CriterionEditorHeader } from "./CriterionEditorHeader";
import { CriterionList, useCriterionDialogs, type CriterionListProps } from "./CriterionList";
import type { SelectionLoad } from "./use_criterion_selection";
import "../steps/steps.css";

/** What the step shows: the cards of all the criteria, or the editor of the selected one. */
export type CriteriaShows = "list" | "editor";

interface CriteriaStepProps {
  /** The panel of the selected criterion. */
  panel: ReactNode;
  /** The criteria and their requests. */
  list: CriterionListProps;
  /** Whether the step shows the list or the editor of the selected criterion. */
  shows: CriteriaShows;
  /** The step asks to show the list or the editor (a card pressed, a criterion added or duplicated, the criterion deleted, All criteria). */
  onShowsChange: (shows: CriteriaShows) => void;
  /** Whether the selected criterion's settings are in; absent: they are. */
  load?: SelectionLoad;
  /** What keeps a run from starting that is the selected criterion's to fix (it protects nothing), said over its panel; absent: none. */
  panelProblem?: string | null;
  /** What the chain kept (chainSummaryLine), under the cards, of two or more criteria; absent or null: no line. */
  chainLine?: string | null;
}

export function CriteriaStep({ panel, list, shows, onShowsChange, load = { state: "ready" }, panelProblem = null, chainLine = null }: CriteriaStepProps) {
  const step = useRef<HTMLDivElement>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  // The refusal of a change made from the editor's header, said under it (the list says its own under the cards).
  const [headerProblem, setHeaderProblem] = useState<string | null>(null);
  const selectedIndex = list.criteria.findIndex((criterion) => criterion.id === list.selectedId);
  const selected = list.criteria[selectedIndex];
  const selectedName = selected?.name ?? "";

  // After a delete the focus goes to the card selected then, once the list shows it.
  useEffect(() => {
    if (focusRequest === 0 || shows !== "list") return;
    step.current?.querySelector<HTMLElement>('.criterion-card[aria-current="true"] .criterion-card-select')?.focus();
  }, [focusRequest, shows, list.selectedId]);
  // The editor opened, or another criterion in it: the focus goes to the criterion's name.
  useEffect(() => {
    if (shows === "editor") step.current?.querySelector<HTMLElement>(".criterion-editor-name")?.focus();
  }, [shows, list.selectedId]);
  useEffect(() => { setHeaderProblem(null); }, [list.selectedId, shows]);

  const shownList: CriterionListProps = {
    ...list,
    onSelect: (id) => { list.onSelect(id); onShowsChange("editor"); },
    onDelete: async (id) => {
      const reason = await list.onDelete(id);
      if (reason === null) { onShowsChange("list"); setFocusRequest((count) => count + 1); }
      return reason;
    },
    onDuplicate: async (id) => {
      const reason = await list.onDuplicate(id);
      if (reason === null) onShowsChange("editor");
      return reason;
    },
    onAdd: async (mode) => {
      const reason = await list.onAdd(mode);
      if (reason === null) onShowsChange("editor");
      return reason;
    },
  };
  const { open: openDialog, dialogs } = useCriterionDialogs(shownList);
  const sayRefusal = async (change: Promise<string | null>) => setHeaderProblem(await change);

  const panelFrame = (
    <div className="criterion-panel-frame" tabIndex={-1} role="group" aria-label={selectedName || undefined}>
      {load.state === "ready" ? <>{panelProblem !== null && <p className="setting-error criterion-panel-problem" role="alert">{panelProblem}</p>}{panel}</>
        : load.state === "loading" ? <p className="step-reason criterion-panel-waits" role="status">{messages.loadingCriterion(selectedName)}</p>
        : <p className="setting-error criterion-panel-waits" role="alert">{load.problem}</p>}
    </div>
  );
  return (
    <div ref={step} className="criteria-step">
      {shows === "list" ? (
        <>
          <CriterionList {...shownList} />
          {chainLine !== null && <p className="chain-summary">{chainLine}</p>}
        </>
      ) : (
        <>
          {selected !== undefined && (
            <CriterionEditorHeader entry={selected} line={list.lineOf(selected)} position={selectedIndex + 1} count={list.criteria.length}
                                   onShowList={() => onShowsChange("list")}
                                   onPrevious={() => list.onSelect(list.criteria[selectedIndex - 1].id)}
                                   onNext={() => list.onSelect(list.criteria[selectedIndex + 1].id)}
                                   disabledReason={list.disabledReason} deleteDisabledReason={list.criteria.length === 1 ? messages.onlyCriterionStays : null}
                                   onSetBypassed={(on) => void sayRefusal(list.onSetBypassed(selected.id, on))}
                                   onChoose={(item) => (item === "duplicate" ? void sayRefusal(shownList.onDuplicate(selected.id)) : openDialog(item, selected))} />
          )}
          {headerProblem !== null && <p className="setting-error criterion-editor-problem" role="alert">{headerProblem}</p>}
          {panelFrame}
        </>
      )}
      {dialogs}
    </div>
  );
}

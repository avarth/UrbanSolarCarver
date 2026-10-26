// The selected criterion and the requests of its cards (CriterionList), for the workspace. Selecting another card (a press, or the
// selection moving as the selected one is deleted or bypassed, or a new one added or duplicated) first saves a change still waiting
// to the criterion it was made in, then asks for the new one's settings (GET criteria/{id}/settings) and starts the criterion form
// again from them; the shared form follows its mode. Until they are in, the panel waits (SelectionLoad); a refusal is said there.
// A run refused for a criterion selects it the same way (showCriterion) and marks its fields once its settings are shown.
// Each change of the criteria dates thresholding (order, bypass) or adds stages, so the stage status is asked for again.
import { useEffect, useRef, useState } from "react";
import { failureTextOf, getCriterionSettings, serviceProblemOf } from "../api_client/client";
import type { FormStart, SettingsForm } from "../settings_form/form_state";
import { selectionAfterRemoving } from "./criteria_state";
import type { CriterionListProps } from "./CriterionList";
import type { CriteriaHook } from "./use_criteria";

/** Whether the panel can show the selected criterion: its settings are in, are being asked for, or the request was refused. */
export type SelectionLoad = { state: "ready" } | { state: "loading" } | { state: "failed"; problem: string };

export type CriterionRequests = Pick<CriterionListProps, "onSelect" | "onReorder" | "onSetBypassed" | "onRename" | "onDuplicate" | "onDelete" | "onAdd">;

interface CriterionSelectionSource {
  token: string;
  project: string;
  criteria: CriteriaHook;
  /** The criterion whose settings the criterion form holds (the workspace's state: the form's send reads it), and its setter. */
  shownCriterionId: string;
  setShownCriterionId: (id: string) => void;
  criterionForm: SettingsForm;
  sharedForm: SettingsForm;
  /** The criterion form's start from a criterion's settings as GET criteria/{id}/settings gives them (the shared ones with them). */
  criterionStartOf: (settings: Record<string, unknown>) => FormStart;
  refreshStageStatus: () => void;
  /** After a criterion is deleted: the stored test surface files are asked for again, as the files only it used are gone. */
  afterDelete?: () => Promise<void>;
  onServiceProblem: (error: unknown) => void;
}

export interface CriterionSelection {
  load: SelectionLoad;
  requests: CriterionRequests;
  /**
   * Selects the card *id*, as a press does, and calls *then* once its settings are shown in the panel (at once when they are
   * already): a run refused for that criterion marks its fields then. A press on another card meanwhile drops *then*.
   */
  showCriterion: (id: string, then?: () => void) => void;
}

export function useCriterionSelection(source: CriterionSelectionSource): CriterionSelection {
  const { token, project, criteria, shownCriterionId, criterionForm, onServiceProblem } = source;
  const [failure, setFailure] = useState<{ id: string; problem: string } | null>(null);
  const [attempt, setAttempt] = useState(0);         // a press on a card whose settings were refused asks again
  const selectionRequest = useRef(0);
  const whenShown = useRef<{ id: string; then: () => void } | null>(null);
  const wanted = criteria.selectedId;
  const load: SelectionLoad = failure !== null && failure.id === wanted ? { state: "failed", problem: failure.problem }
    : wanted !== "" && wanted !== shownCriterionId ? { state: "loading" } : { state: "ready" };

  // Before another criterion is selected or the selected one goes, a change still waiting is saved to the criterion it was made in
  // (the form reads its send, which names the shown criterion, when the save goes out).
  const saveTheShownCriterion = () => void criterionForm.flushSave();

  useEffect(() => {
    const request = ++selectionRequest.current;       // a reply for a card selected before is not used
    if (whenShown.current !== null && whenShown.current.id !== wanted) whenShown.current = null;
    if (wanted === "" || wanted === shownCriterionId) return;
    saveTheShownCriterion();
    setFailure(null);                                 // a refusal of an earlier request is not said while this one is out
    getCriterionSettings(token, project, wanted).then((reply) => {
      if (request !== selectionRequest.current) return;
      // The restart sends a change still waiting with the send of the render before, the shown criterion's.
      criterionForm.restart(source.criterionStartOf(reply.settings));
      source.sharedForm.dispatch({ type: "mode_followed", mode: criterionForm.currentForm().mode });
      source.setShownCriterionId(wanted);
      setFailure(null);
    }).catch((error) => {
      if (request !== selectionRequest.current) return;
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      setFailure({ id: wanted, problem: failureTextOf(error) });
    });
  }, [wanted, attempt]);

  useEffect(() => {
    const waiting = whenShown.current;
    if (waiting === null || waiting.id !== shownCriterionId || wanted !== shownCriterionId) return;
    whenShown.current = null;
    waiting.then();
  }, [shownCriterionId, wanted]);

  const change = async (request: () => Promise<unknown>): Promise<string | null> => {
    try {
      await request();
      source.refreshStageStatus();
      return null;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return failureTextOf(error);
    }
  };

  const select = (id: string) => {
    saveTheShownCriterion();
    if (id === wanted && failure?.id === id) {
      setFailure(null);
      setAttempt((count) => count + 1);
    }
    criteria.select(id);
  };
  const showCriterion = (id: string, then?: () => void) => {
    if (id === wanted && id === shownCriterionId) {
      then?.();
      return;
    }
    whenShown.current = then === undefined ? null : { id, then };
    select(id);
  };

  const requests: CriterionRequests = {
    onSelect: select,
    onReorder: (ids) => change(() => criteria.reorder(ids)),
    // Bypassing the selected criterion selects the next card (else the previous one), as deleting it does: from the selection when
    // the reply is in, which a press may have changed meanwhile.
    onSetBypassed: (id, on) => {
      if (on && id === wanted) saveTheShownCriterion();
      return change(async () => {
        await criteria.setBypassed(id, on);
        const now = criteria.current();
        if (on) criteria.select(selectionAfterRemoving(now.criteria, id, now.selectedId));
      });
    },
    onRename: (id, name) => change(() => criteria.rename(id, name)),
    onDuplicate: (id) => {
      saveTheShownCriterion();
      return change(() => criteria.duplicate(id));
    },
    onDelete: (id) => {
      saveTheShownCriterion();
      return change(async () => {
        await criteria.remove(id);
        await source.afterDelete?.();
      });
    },
    onAdd: (mode) => {
      saveTheShownCriterion();
      return change(() => criteria.add(mode));
    },
  };
  return { load, requests, showCriterion };
}

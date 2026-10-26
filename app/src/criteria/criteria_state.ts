// What the criteria list needs to know about its cards, with no React: which criteria are on, the status of a card, its result
// line, where the selection goes when a card is removed, the order after a card is moved, and the files of the other criteria.
import type { CriterionCarvingSummary, CriterionEntry } from "../api_client/client";
import { messages } from "../messages";
import { formatNumber, formatPercent } from "../steps/format_numbers";
import type { StageRunState } from "../steps/run_state";
import type { StageState } from "../steps/step_summaries";

export type CardStatus =
  | { kind: "current" | "out_of_date" | "running" | "bypassed" | "no_test_surfaces" | "not_run" }
  | { kind: "updates_from"; from: string };

/** The stages of each criterion that is on, by criterion id (a bypassed criterion is not in it). */
export type StagesByCriterion = Record<string, Record<"preprocessing" | "thresholding", StageState>>;

/**
 * The stages of each criterion as the service gives them (ProjectDetail.criterion_status, StageStatusReply.criteria: a dict of
 * dicts the generated types leave open), with a stage it does not name as missing; empty without them.
 */
export function stagesByCriterionOf(status: Record<string, Record<string, StageState>> | undefined): StagesByCriterion {
  return Object.fromEntries(Object.entries(status ?? {}).map(([id, stages]) => [id, {
    preprocessing: stages.preprocessing ?? "missing", thresholding: stages.thresholding ?? "missing",
  }]));
}

/** The criteria that are on, in chain order. */
export function activeCriteria(criteria: CriterionEntry[]): CriterionEntry[] {
  return criteria.filter((criterion) => !criterion.bypassed);
}

/**
 * What a card says about its criterion. Bypassed, running and without test surfaces come first. Then, from its stages: current;
 * not run yet when either stage is missing; out of date when its preprocessing is, or when its thresholding is and every earlier
 * criterion that is on is current; "updates from" the first earlier criterion that is on and not current when its thresholding
 * is out of date only because that one will change the voxels it decides among (out of date while an earlier one protects
 * nothing, since no run starts then). During a run, *stagesByCriterion* are those stagesDuringRun gives.
 */
export function criterionStatus(entry: CriterionEntry, criteria: CriterionEntry[], stagesByCriterion: StagesByCriterion, runningId: string | null): CardStatus {
  if (entry.bypassed) return { kind: "bypassed" };
  if (runningId === entry.id) return { kind: "running" };
  if ((entry.test_surface_files ?? []).length === 0) return { kind: "no_test_surfaces" };
  const stages = stagesByCriterion[entry.id];
  if (stages === undefined || stages.preprocessing === "missing" || stages.thresholding === "missing") return { kind: "not_run" };
  if (stages.preprocessing === "out_of_date") return { kind: "out_of_date" };
  if (stages.thresholding === "current") return { kind: "current" };
  const active = activeCriteria(criteria);
  const earlier = active.slice(0, active.findIndex((criterion) => criterion.id === entry.id));
  const earlierNotCurrent = earlier.find((criterion) => !isCurrent(stagesByCriterion[criterion.id]));
  // "Updates from" names only a criterion a run brings up to date first: while an earlier one protects nothing, the run is refused.
  const runRefused = earlier.some((criterion) => (criterion.test_surface_files ?? []).length === 0);
  return earlierNotCurrent === undefined || runRefused ? { kind: "out_of_date" } : { kind: "updates_from", from: earlierNotCurrent.name };
}

function isCurrent(stages: StagesByCriterion[string] | undefined): boolean {
  return stages !== undefined && stages.preprocessing === "current" && stages.thresholding === "current";
}

/**
 * The stages of each criterion while a run goes on (*progress*: the state of each criterion's stages in it, run_state's
 * criterionProgressOf): a stage the run has done is current, one it has still to do is out of date (the status read before the
 * run may call it current), a missing one stays missing until done. The cards read their status from these.
 */
export function stagesDuringRun(stagesByCriterion: StagesByCriterion, progress: Record<string, Record<string, StageRunState>>): StagesByCriterion {
  const during: StagesByCriterion = { ...stagesByCriterion };
  for (const [id, stages] of Object.entries(progress)) {
    const ofCriterion = { ...(during[id] ?? { preprocessing: "missing", thresholding: "missing" }) };
    for (const stage of ["preprocessing", "thresholding"] as const) {
      const runState = stages[stage];
      if (runState === "done") ofCriterion[stage] = "current";
      else if (runState !== undefined && ofCriterion[stage] === "current") ofCriterion[stage] = "out_of_date";
    }
    during[id] = ofCriterion;
  }
  return during;
}

/** The words of a card's status; null for a current criterion, whose card shows its result line instead. */
export function cardStatusText(status: CardStatus): string | null {
  switch (status.kind) {
    case "current":
      return null;
    case "out_of_date":
      return messages.criterionOutOfDate;
    case "updates_from":
      return messages.criterionUpdatesFrom(status.from);
    case "running":
      return messages.criterionRunning;
    case "bypassed":
      return messages.criterionBypassed;
    case "no_test_surfaces":
      return messages.criterionNeedsTestSurfaces;
    case "not_run":
      return messages.criterionNotRunYet;
  }
}

/**
 * "70 % of the score carved, 18 400 m³ removed" for a weighted mode (it reports the obstruction fraction it carved), "39 % of the
 * volume carved, ..." for the others; null while the criterion has no numbers.
 */
export function cardResultLine(summary: CriterionCarvingSummary): string | null {
  const carving = summary.carving;
  if (carving === null) return null;
  const isWeighted = carving.obstruction_fraction_carved !== null;
  const percentText = formatPercent(isWeighted ? carving.obstruction_fraction_carved! * 100 : 100 - carving.retention_pct);
  if (summary.volume_removed_m3 === null || summary.volume_removed_m3 === undefined) {
    return isWeighted ? messages.criterionScoreCarved(percentText) : messages.criterionVolumeCarved(percentText);
  }
  const volumeText = formatNumber(summary.volume_removed_m3, "m³");
  return isWeighted ? messages.criterionResultOfScore(percentText, volumeText) : messages.criterionResultOfVolume(percentText, volumeText);
}

/**
 * The selection once *removedId* is removed from *criteria* (the list before the removal): unchanged unless the removed card is the
 * selected one, then the card after it, else the one before it. With no other card the selection stays as it is.
 */
export function selectionAfterRemoving(criteria: CriterionEntry[], removedId: string, selectedId: string): string {
  if (removedId !== selectedId) return selectedId;
  const position = criteria.findIndex((criterion) => criterion.id === removedId);
  const neighbour = criteria[position + 1] ?? criteria[position - 1];
  return neighbour === undefined ? selectedId : neighbour.id;
}

/** A card's line: its result while current (empty until the run summary is in), else the words of its status. */
export function cardLineOf(status: CardStatus, summary: CriterionCarvingSummary | undefined): string {
  return cardStatusText(status) ?? (summary === undefined ? null : cardResultLine(summary)) ?? "";
}

/** The order once the card *id* moves one place up (-1) or down (1); null when it is at that end already. */
export function orderAfterMoving(ids: readonly string[], id: string, step: -1 | 1): string[] | null {
  const position = ids.indexOf(id);
  const target = position + step;
  if (position < 0 || target < 0 || target >= ids.length) return null;
  const order = [...ids];
  [order[position], order[target]] = [order[target], order[position]];
  return order;
}

/** The order once the card *draggedId* is dropped on *targetId*: it takes that card's place; null when nothing moves. */
export function orderAfterDropping(ids: readonly string[], draggedId: string, targetId: string): string[] | null {
  const from = ids.indexOf(draggedId), to = ids.indexOf(targetId);
  if (from < 0 || to < 0 || from === to) return null;
  const order = ids.filter((id) => id !== draggedId);
  order.splice(to, 0, draggedId);
  return order;
}

/** The test surface files the other criteria use and *id* does not, each once, in the order of the cards. */
export function filesOfOtherCriteria(criteria: CriterionEntry[], id: string): string[] {
  const own = new Set(criteria.find((criterion) => criterion.id === id)?.test_surface_files ?? []);
  const others = criteria.filter((criterion) => criterion.id !== id).flatMap((criterion) => criterion.test_surface_files ?? []);
  return [...new Set(others)].filter((name) => !own.has(name));
}

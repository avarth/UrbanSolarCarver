// What the criteria list needs to know about its cards, with no React: which criteria are on, the status of a card, its result
// line, and where the selection goes when a card is removed.
import type { CriterionCarvingSummary, CriterionEntry } from "../api_client/client";
import { messages } from "../messages";
import { formatNumber, formatPercent } from "../steps/format_numbers";
import type { StageState } from "../steps/step_summaries";

export type CardStatus =
  | { kind: "current" | "out_of_date" | "running" | "bypassed" | "no_test_surfaces" | "not_run" }
  | { kind: "updates_from"; from: string };

/** The stages of each criterion that is on, by criterion id (a bypassed criterion is not in it). */
export type StagesByCriterion = Record<string, Record<"preprocessing" | "thresholding", StageState>>;

/** The criteria that are on, in chain order. */
export function activeCriteria(criteria: CriterionEntry[]): CriterionEntry[] {
  return criteria.filter((criterion) => !criterion.bypassed);
}

/**
 * What a card says about its criterion. Bypassed, running and without test surfaces come first. Then, from its stages: current;
 * not run yet when either stage is missing; out of date when its preprocessing is, or when its thresholding is and every earlier
 * criterion that is on is current; "updates from" the first earlier criterion that is on and not current when its thresholding
 * is out of date only because that one will change the voxels it decides among.
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
  const earlierNotCurrent = active.slice(0, active.findIndex((criterion) => criterion.id === entry.id)).find((earlier) => !isCurrent(stagesByCriterion[earlier.id]));
  return earlierNotCurrent === undefined ? { kind: "out_of_date" } : { kind: "updates_from", from: earlierNotCurrent.name };
}

function isCurrent(stages: StagesByCriterion[string] | undefined): boolean {
  return stages !== undefined && stages.preprocessing === "current" && stages.thresholding === "current";
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
  const whatIsCarved = isWeighted ? "score" : "volume";
  if (summary.volume_removed_m3 === null || summary.volume_removed_m3 === undefined) return messages.criterionPercentOnly(percentText, whatIsCarved);
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

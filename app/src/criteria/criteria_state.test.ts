import { expect, test } from "vitest";
import type { CriterionCarvingSummary, CriterionEntry } from "../api_client/client";
import type { StageState } from "../steps/step_summaries";
import { activeCriteria, cardResultLine, cardStatusText, criterionStatus, selectionAfterRemoving } from "./criteria_state";

function entry(id: string, overrides: Partial<CriterionEntry> = {}): CriterionEntry {
  return { id, name: `Criterion ${id}`, named_by_user: false, colour: "#336699", bypassed: false, test_surface_files: ["roofs.obj"], settings: {}, ...overrides };
}

type Stages = Record<"preprocessing" | "thresholding", StageState>;
const CURRENT: Stages = { preprocessing: "current", thresholding: "current" };
const THRESHOLD_OUT_OF_DATE: Stages = { preprocessing: "current", thresholding: "out_of_date" };
const ALL_OUT_OF_DATE: Stages = { preprocessing: "out_of_date", thresholding: "out_of_date" };
const NOTHING: Stages = { preprocessing: "missing", thresholding: "missing" };

test("active criteria leave out the bypassed ones, in order", () => {
  const criteria = [entry("1"), entry("2", { bypassed: true }), entry("3")];
  expect(activeCriteria(criteria).map((criterion) => criterion.id)).toEqual(["1", "3"]);
});

test("a criterion whose stages are current is current", () => {
  const criteria = [entry("1"), entry("2")];
  expect(criterionStatus(criteria[1], criteria, { "1": CURRENT, "2": CURRENT }, null)).toEqual({ kind: "current" });
});

test("a bypassed criterion is bypassed, whatever else holds", () => {
  const criteria = [entry("1", { bypassed: true, test_surface_files: [] })];
  expect(criterionStatus(criteria[0], criteria, {}, "1")).toEqual({ kind: "bypassed" });
});

test("the criterion the run is working on is running", () => {
  const criteria = [entry("1"), entry("2")];
  const stages = { "1": CURRENT, "2": THRESHOLD_OUT_OF_DATE };
  expect(criterionStatus(criteria[1], criteria, stages, "2")).toEqual({ kind: "running" });
  expect(criterionStatus(criteria[0], criteria, stages, "2")).toEqual({ kind: "current" });
});

test("a criterion with no test surfaces asks for them", () => {
  const criteria = [entry("1", { test_surface_files: [] })];
  expect(criterionStatus(criteria[0], criteria, { "1": NOTHING }, null)).toEqual({ kind: "no_test_surfaces" });
});

test("a criterion without results is not run yet", () => {
  const criteria = [entry("1")];
  expect(criterionStatus(criteria[0], criteria, { "1": NOTHING }, null)).toEqual({ kind: "not_run" });
  expect(criterionStatus(criteria[0], criteria, { "1": { preprocessing: "current", thresholding: "missing" } }, null)).toEqual({ kind: "not_run" });
  expect(criterionStatus(criteria[0], criteria, {}, null)).toEqual({ kind: "not_run" });
});

test("a criterion whose own analysis is out of date is out of date", () => {
  const criteria = [entry("1"), entry("2")];
  const stages = { "1": ALL_OUT_OF_DATE, "2": ALL_OUT_OF_DATE };
  expect(criterionStatus(criteria[0], criteria, stages, null)).toEqual({ kind: "out_of_date" });
  expect(criterionStatus(criteria[1], criteria, stages, null)).toEqual({ kind: "out_of_date" });
});

test("a criterion with only its thresholding out of date and nothing earlier out of date is out of date", () => {
  const criteria = [entry("1"), entry("2")];
  expect(criterionStatus(criteria[1], criteria, { "1": CURRENT, "2": THRESHOLD_OUT_OF_DATE }, null)).toEqual({ kind: "out_of_date" });
  expect(criterionStatus(criteria[0], criteria, { "1": THRESHOLD_OUT_OF_DATE, "2": THRESHOLD_OUT_OF_DATE }, null)).toEqual({ kind: "out_of_date" });
});

test("a criterion that waits for an earlier one updates from the first earlier one that is not current", () => {
  const criteria = [entry("1"), entry("2", { name: "Daylight" }), entry("3")];
  const stages = { "1": CURRENT, "2": THRESHOLD_OUT_OF_DATE, "3": THRESHOLD_OUT_OF_DATE };
  expect(criterionStatus(criteria[2], criteria, stages, null)).toEqual({ kind: "updates_from", from: "Daylight" });
  const bothEarlier = { ...stages, "1": THRESHOLD_OUT_OF_DATE };
  expect(criterionStatus(criteria[2], criteria, bothEarlier, null)).toEqual({ kind: "updates_from", from: "Criterion 1" });
});

test("a bypassed criterion is skipped when looking back for the earlier one", () => {
  const criteria = [entry("1"), entry("2", { bypassed: true }), entry("3")];
  const stages = { "1": CURRENT, "3": THRESHOLD_OUT_OF_DATE };      // a bypassed criterion is absent from the stages
  expect(criterionStatus(criteria[2], criteria, stages, null)).toEqual({ kind: "out_of_date" });
});

test("the words of each status; a current criterion has none because its result line is shown", () => {
  expect(cardStatusText({ kind: "current" })).toBeNull();
  expect(cardStatusText({ kind: "out_of_date" })).toBe("Out of date");
  expect(cardStatusText({ kind: "updates_from", from: "Daylight" })).toBe("Updates from Daylight");
  expect(cardStatusText({ kind: "running" })).toBe("Running");
  expect(cardStatusText({ kind: "bypassed" })).toBe("Bypassed");
  expect(cardStatusText({ kind: "no_test_surfaces" })).toBe("Add test surfaces");
  expect(cardStatusText({ kind: "not_run" })).toBe("Not run yet");
});

const CARVING = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: null,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 0,
};

function summary(carving: CriterionCarvingSummary["carving"], volumeRemoved: number | null): CriterionCarvingSummary {
  return { id: "1", name: "Criterion 1", colour: "#336699", mode: "daylight", carving, voxels_at_start: 1000, volume_kept_m3: 5000, volume_removed_m3: volumeRemoved };
}

test("the result line of a weighted mode gives the share of the score carved", () => {
  const weighted = summary({ ...CARVING, obstruction_fraction_carved: 0.7 }, 18400);
  expect(cardResultLine(weighted)).toBe("70 % of the score carved, 18 400 m³ removed");
});

test("the result line of an unweighted mode gives the share of the volume carved", () => {
  expect(cardResultLine(summary(CARVING, 1250.4))).toBe("39 % of the volume carved, 1 250 m³ removed");
});

test("a criterion without numbers has no result line", () => {
  expect(cardResultLine(summary(null, null))).toBeNull();
});

test("the selection stays unless the selected card is removed, then moves to the next card, else the previous one", () => {
  const criteria = [entry("1"), entry("2"), entry("3")];
  expect(selectionAfterRemoving(criteria, "2", "2")).toBe("3");
  expect(selectionAfterRemoving(criteria, "1", "1")).toBe("2");
  expect(selectionAfterRemoving(criteria, "3", "3")).toBe("2");
  expect(selectionAfterRemoving(criteria, "1", "3")).toBe("3");
  expect(selectionAfterRemoving([entry("1")], "1", "1")).toBe("1");
});

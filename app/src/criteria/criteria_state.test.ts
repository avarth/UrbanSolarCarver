import { expect, test } from "vitest";
import type { CriterionCarvingSummary, CriterionEntry } from "../api_client/client";
import type { StageState } from "../steps/step_summaries";
import {
  activeCriteria, cardLineOf, cardResultLine, cardStatusText, criterionStatus, filesOfOtherCriteria, orderAfterDropping, orderAfterMoving, selectionAfterRemoving,
  stagesByCriterionOf, stagesDuringRun,
} from "./criteria_state";

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

test("updates from names only a criterion a run brings up to date first: not while an earlier one protects nothing", () => {
  const criteria = [entry("1", { name: "Facades", test_surface_files: [] }), entry("2", { name: "Daylight" }), entry("3")];
  const stages = { "1": NOTHING, "2": CURRENT, "3": THRESHOLD_OUT_OF_DATE };
  expect(criterionStatus(criteria[2], criteria, stages, null)).toEqual({ kind: "out_of_date" });
  // Never run but with test surfaces, it does run first.
  const withSurfaces = [{ ...criteria[0], test_surface_files: ["facades.obj"] }, criteria[1], criteria[2]];
  expect(criterionStatus(withSurfaces[2], withSurfaces, stages, null)).toEqual({ kind: "updates_from", from: "Facades" });
});

test("during a run a criterion's stages are current once the run has done them and out of date while it still has to", () => {
  const stages = { "1": CURRENT, "2": CURRENT, "3": NOTHING };
  const progress = { 1: { thresholding: "done" as const }, 2: { thresholding: "running" as const }, 3: { preprocessing: "waiting" as const, thresholding: "waiting" as const } };
  expect(stagesDuringRun(stages, progress)).toEqual({ "1": CURRENT, "2": THRESHOLD_OUT_OF_DATE, "3": NOTHING });
  expect(stagesDuringRun({ "1": THRESHOLD_OUT_OF_DATE }, { 1: { thresholding: "done" } })).toEqual({ "1": CURRENT });
  expect(stagesDuringRun({}, { 4: { preprocessing: "done", thresholding: "running" } })).toEqual({ "4": { preprocessing: "current", thresholding: "missing" } });
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

test("without the removed volume the result line gives the share alone", () => {
  expect(cardResultLine(summary({ ...CARVING, obstruction_fraction_carved: 0.7 }, null))).toBe("70 % of the score carved");
  expect(cardResultLine(summary(CARVING, null))).toBe("39 % of the volume carved");
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

test("the stages of each criterion as the service gives them, a stage it does not name read as missing", () => {
  expect(stagesByCriterionOf({ 1: { preprocessing: "current", thresholding: "out_of_date", exporting: "current" }, 2: { preprocessing: "current" } }))
    .toEqual({ 1: THRESHOLD_OUT_OF_DATE, 2: { preprocessing: "current", thresholding: "missing" } });
  expect(stagesByCriterionOf(undefined)).toEqual({});
});

test("reordering with the keyboard moves a card one place, and not past either end", () => {
  expect(orderAfterMoving(["1", "2", "3"], "2", -1)).toEqual(["2", "1", "3"]);
  expect(orderAfterMoving(["1", "2", "3"], "2", 1)).toEqual(["1", "3", "2"]);
  expect(orderAfterMoving(["1", "2", "3"], "1", -1)).toBeNull();
  expect(orderAfterMoving(["1", "2", "3"], "3", 1)).toBeNull();
});

test("a card dropped on another takes its place, the cards between moving one place", () => {
  expect(orderAfterDropping(["1", "2", "3"], "1", "3")).toEqual(["2", "3", "1"]);
  expect(orderAfterDropping(["1", "2", "3"], "3", "1")).toEqual(["3", "1", "2"]);
  expect(orderAfterDropping(["1", "2", "3"], "2", "2")).toBeNull();
  expect(orderAfterDropping(["1", "2", "3"], "4", "2")).toBeNull();
});

test("the files of other criteria are those they use and this one does not, each once", () => {
  const criteria = [entry("1", { test_surface_files: ["roofs.obj"] }), entry("2", { test_surface_files: ["windows.obj", "roofs.obj"] }),
                    entry("3", { test_surface_files: ["windows.obj", "courtyard.obj"] })];
  expect(filesOfOtherCriteria(criteria, "1")).toEqual(["windows.obj", "courtyard.obj"]);
  expect(filesOfOtherCriteria(criteria, "2")).toEqual(["courtyard.obj"]);
  expect(filesOfOtherCriteria([entry("1")], "1")).toEqual([]);
});

test("a card's line is its result while current, else its status", () => {
  expect(cardLineOf({ kind: "current" }, summary(CARVING, 1250.4))).toBe(cardResultLine(summary(CARVING, 1250.4)));
  expect(cardLineOf({ kind: "current" }, undefined)).toBe("");
  expect(cardLineOf({ kind: "bypassed" }, summary(CARVING, 1250.4))).toBe("Bypassed");
  expect(cardLineOf({ kind: "updates_from", from: "Daylight on windows" }, undefined)).toBe("Updates from Daylight on windows");
});

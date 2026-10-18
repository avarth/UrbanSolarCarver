import { expect, test } from "vitest";
import { initialRunState, runProgressShare, runReducer, stageDisplayName } from "./run_state";

test("run events build per-stage progress, issues and the final state", () => {
  let s = initialRunState(["preprocessing", "thresholding"]);
  s = runReducer(s, { type: "stage_progress", stage: "preprocessing", done: 3, total: 10 });
  s = runReducer(s, { type: "issue", stage: "preprocessing", code: "W1", message: "m" });
  s = runReducer(s, { type: "run_failed", error_type: "InputError", message: "broken", field_errors: [] });
  expect(s.stages.preprocessing).toMatchObject({ done: 3, total: 10 });
  expect(s.issues).toHaveLength(1);
  expect(s.final).toBe("failed");
  expect(s.failure).toMatchObject({ error_type: "InputError", message: "broken" });
});

test("a stage runs from its first progress and is done when a later stage starts or the run finishes", () => {
  let s = initialRunState(["preprocessing", "thresholding"], 1000);
  expect(s.stages.preprocessing.state).toBe("running");
  expect(s.stages.thresholding.state).toBe("waiting");
  s = runReducer(s, { type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  expect(s.stages.preprocessing.state).toBe("done");
  expect(s.stages.thresholding.state).toBe("running");
  expect(s.final).toBeNull();
  s = runReducer(s, { type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] }, 7400);
  expect(s.stages.thresholding.state).toBe("done");
  expect(s.final).toBe("finished");
  expect(s.endedAt! - s.startedAt).toBe(6400);
});

test("a cancelled run leaves the unfinished stages as they were; a lost connection ends the run as lost", () => {
  let s = initialRunState(["preprocessing", "thresholding"]);
  s = runReducer(s, { type: "run_cancelled" });
  expect(s.final).toBe("cancelled");
  expect(s.stages.preprocessing.state).toBe("running");
  const lost = runReducer(initialRunState(["thresholding"]), { type: "connection_lost", code: 1006, reason: "" });
  expect(lost.final).toBe("connection_lost");
  expect(lost.lostConnectionCode).toBe(1006);
});

test("events after the last one change nothing", () => {
  const finished = runReducer(initialRunState(["thresholding"]), { type: "run_finished", stages: ["thresholding"], files: [] });
  expect(runReducer(finished, { type: "connection_lost", code: 1006, reason: "" })).toBe(finished);
});

test("the progress bar counts finished stages and the batch fraction of the running one", () => {
  let s = initialRunState(["preprocessing", "thresholding"]);
  expect(runProgressShare(s)).toBe(0);
  s = runReducer(s, { type: "stage_progress", stage: "preprocessing", done: 5, total: 10 });
  expect(runProgressShare(s)).toBeCloseTo(0.25);
  s = runReducer(s, { type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  expect(runProgressShare(s)).toBeCloseTo(0.5);
});

test("stages are named in plain words", () => {
  expect(["preprocessing", "thresholding", "exporting", "massing"].map(stageDisplayName))
    .toEqual(["Sun analysis", "Carving", "Envelope mesh", "Building massing"]);
});

test("an issue raised before any stage began (stage null, as the service sends it) is kept with the run's warnings", () => {
  let s = initialRunState(["preprocessing"]);
  s = runReducer(s, { type: "issue", stage: null, code: "UNUSED_SETTING", message: "epw_path is not used by this mode" });
  expect(s.issues).toEqual([{ stage: null, code: "UNUSED_SETTING", message: "epw_path is not used by this mode" }]);
  expect(s.stages.preprocessing.state).toBe("running");
});

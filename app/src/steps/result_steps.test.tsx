import { afterEach, expect, test, vi } from "vitest";
import * as THREE from "three";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { dimmedLayersOf, isStageDimmed, missingLayersOf } from "./result_steps";
import { resultsOfStages, useResultsFollowingRun, type RunResults } from "./run_results";
import { initialRunState, runReducer, type RunRecord, type RunState } from "./run_state";
import type { PipelineStage, StageState } from "./step_summaries";

const ALL_CURRENT: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
const NO_RESULTS: RunResults = { summary: null, scorePoints: null, skyDome: null, envelope: null, massing: null, platesFile: null };

function record(state: RunState, serial = 1): RunRecord {
  return { serial, project: "p", origin: "build", runId: `r${serial}`, state, refusal: null };
}

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

test("a stage of the run under way is dimmed until the run has done it; other stages follow their status", () => {
  let state = initialRunState(["exporting", "massing"]);
  state = runReducer(state, { type: "stage_progress", stage: "massing", done: 0, total: 1 });
  const stages: Record<PipelineStage, StageState> = { ...ALL_CURRENT, thresholding: "out_of_date", exporting: "missing", massing: "missing" };
  expect(isStageDimmed("exporting", record(state), stages)).toBe(false);       // done in this run, though its status still says missing
  expect(isStageDimmed("massing", record(state), stages)).toBe(true);
  expect(isStageDimmed("thresholding", record(state), stages)).toBe(true);     // not in the run: its status
  expect(dimmedLayersOf(record(state), stages)).toEqual(["kept_voxels", "carved_voxels", "building_massing"]);
  expect(dimmedLayersOf(null, ALL_CURRENT)).toEqual([]);
  const ended = runReducer(state, { type: "run_finished", stages: ["exporting", "massing"], files: [] });
  expect(isStageDimmed("massing", record(ended), { ...stages, massing: "current" })).toBe(false);
});

test("a run that stopped early lists the layers its stages left without data; a finished run lists none", () => {
  const cancelled = runReducer(initialRunState(["preprocessing", "thresholding"]), { type: "run_cancelled" });
  const scorePointsWithoutMask = { kept: null } as unknown as ScorePoints;
  const withoutCarving: RunResults = { ...NO_RESULTS, scorePoints: scorePointsWithoutMask };
  expect(missingLayersOf(record(cancelled), withoutCarving, false)).toEqual(["kept_voxels", "carved_voxels"]);
  expect(missingLayersOf(record(cancelled), withoutCarving, true)).toEqual(["sky_dome", "kept_voxels", "carved_voxels"]);
  const failedBuild = runReducer(initialRunState(["exporting", "massing"]), { type: "run_failed", error_type: "E", message: "m", field_errors: [] });
  expect(missingLayersOf(record(failedBuild), { ...NO_RESULTS, envelope: new THREE.BufferGeometry() }, false)).toEqual(["building_massing"]);
  const finished = runReducer(initialRunState(["exporting"]), { type: "run_finished", stages: ["exporting"], files: [] });
  expect(missingLayersOf(record(finished), NO_RESULTS, false)).toEqual([]);
  expect(missingLayersOf(null, NO_RESULTS, false)).toEqual([]);
});

test("each stage names the results it writes; the score points follow the carving, not the analysis", () => {
  expect(resultsOfStages(["preprocessing"])).toEqual(["skyDome"]);
  expect(resultsOfStages(["thresholding", "exporting", "massing"])).toEqual(["summary", "scorePoints", "envelope", "massing", "platesFile"]);
});

function followedRun(initial: RunRecord | null) {
  const reload = vi.fn(), onRunEnded = vi.fn();
  function Follower({ current }: { current: RunRecord | null }) {
    useResultsFollowingRun(current, reload, onRunEnded);
    return null;
  }
  rendered = renderForTest(<Follower current={initial} />);
  return { reload, onRunEnded, show: (next: RunRecord | null) => rendered!.rerender(<Follower current={next} />) };
}

test("results are fetched again stage by stage as a run does them, the rest at its end, and the end is reported once", () => {
  const { reload, onRunEnded, show } = followedRun(null);
  let state = initialRunState(["preprocessing", "thresholding"]);
  show(record(state));
  expect(reload).not.toHaveBeenCalled();
  state = runReducer(state, { type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  show(record(state));
  expect(reload.mock.calls).toEqual([[["preprocessing"]]]);
  state = runReducer(state, { type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  show(record(state));
  expect(reload.mock.calls).toEqual([[["preprocessing"]], [["thresholding"]]]);
  expect(onRunEnded).toHaveBeenCalledOnce();
  show(record(state));
  expect(onRunEnded).toHaveBeenCalledOnce();
});

test("a cancelled run fetches again what its unfinished stages removed", () => {
  const { reload, onRunEnded, show } = followedRun(null);
  show(record(runReducer(initialRunState(["preprocessing", "thresholding"]), { type: "run_cancelled" })));
  expect(reload.mock.calls).toEqual([[["preprocessing", "thresholding"]]]);
  expect(onRunEnded).toHaveBeenCalledOnce();
});

test("a run that had ended before the project opened is not followed again; the next run is", () => {
  const ended = record(runReducer(initialRunState(["thresholding"]), { type: "run_finished", stages: ["thresholding"], files: [] }));
  const { reload, onRunEnded, show } = followedRun(ended);
  expect(reload).not.toHaveBeenCalled();
  expect(onRunEnded).not.toHaveBeenCalled();
  show(record(runReducer(initialRunState(["exporting"]), { type: "run_finished", stages: ["exporting"], files: [] }), 2));
  expect(reload.mock.calls).toEqual([[["exporting"]]]);
  expect(onRunEnded).toHaveBeenCalledOnce();
});

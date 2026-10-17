import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo, RunSummary } from "../api_client/client";
import { initialFormState, type FormState } from "../settings_form/form_state";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { CarvingStep, readAutoUpdate, type CarvingStepProps } from "./CarvingStep";
import { EnvelopeAndMassingStep, storeyRows, type PlatesFile } from "./EnvelopeAndMassingStep";
import { exportDownloads } from "./ExportStep";
import { RunProgress } from "./RunProgress";
import { initialRunState, runReducer, type RunLoop, type RunRecord } from "./run_state";
import { ScoreHistogram } from "./ScoreHistogram";

const SCHEMA = {
  properties: {
    mode: { default: "time-based", type: "string" },
    voxel_size: { default: 1.0, type: "number" },
    carve_fraction: { default: 0.7, type: "number" },
    threshold: { anyOf: [{ $ref: "#/$defs/ThresholdSpec" }, { type: "null" }], default: null },
    carve_above: { default: true, type: "boolean" },
    carve_above_min_consecutive: { default: 1, type: "integer" },
    max_slope_deg: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
    score_smoothing: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
    apply_smoothing: { default: true, type: "boolean" },
    ground_floor_height: { default: 5.0, type: "number" },
    floor_height: { default: 3.0, type: "number" },
    min_plate_dimension: { default: 3.0, type: "number" },
  },
};
const mode = (name: string, scoreKind: ModeInfo["score_kind"]): ModeInfo =>
  ({ name, description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: scoreKind, weight_unit: "", starting_values: {} });
const MODES = [mode("time-based", "violation_count"), mode("daylight", "weighted_sum"), mode("tilted_plane", "violation_count")];

function formFor(modeName: string, settings: Record<string, unknown> = {}): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: modeName, ...settings }, gridPlan: null });
}

const CARVING: NonNullable<RunSummary["carving"]> = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: 0.42,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 312,
};

const SCORE_POINTS: ScorePoints = {
  header: { origin: [0, 0, 0], shape: [2, 2, 2], voxel_size: 2, scores_kind: "violation_count", weight_unit: "m²·h", score_min: 0, score_max: 9.6,
            occupied_count: 4, point_count: 4, thinning_step: 1, has_mask: true, has_compared_scores: true },
  indices: Uint32Array.from([0, 1, 2, 3]),
  scores: Float32Array.from([0, 1, 5, 9.6]),
  kept: Uint8Array.from([1, 1, 0, 0]),
  comparedScores: Float32Array.from([0, 1, 5, 9.6]),
};

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  window.localStorage.clear();
});

function carvingProps(overrides: Partial<CarvingStepProps> = {}): CarvingStepProps {
  return {
    form: formFor("time-based", { threshold: { method: "cutoff", value: 1.5 } }), isWeightedMode: false, summary: CARVING, scorePoints: SCORE_POINTS,
    analysisOutOfDate: false, carvingDimmed: false, autoUpdate: true, onAutoUpdateChange: vi.fn(), thresholdDisabledReason: null,
    settingsDisabledReason: null, runBlocker: null, onChange: vi.fn(), onThresholdCommit: vi.fn(), onCarvingSettingCommit: vi.fn(),
    onUpdateCarving: vi.fn(), onRunAnalysis: vi.fn(), lastAnalysisSeconds: 6.4, carvingFeedback: null, analysisFeedback: null, ...overrides,
  };
}

function typeInto(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

test("Sun at set hours: Shadow tolerated with its slider ends, the histogram, the tiles two per row", () => {
  rendered = renderForTest(<CarvingStep {...carvingProps()} />);
  const text = rendered.container.textContent!;
  expect(rendered.container.querySelector(".threshold-control label")!.textContent).toBe("Shadow tolerated");
  expect(rendered.container.querySelector(".threshold-slider-ends")!.textContent).toBe("09.6, the highest score");
  expect(text).toContain("More carving settings");
  expect(text).toContain("Update when I change the threshold");
  expect(text).not.toContain("Update carving");
  expect(text).toContain("Scores of the voxels");
  expect([...rendered.container.querySelectorAll(".number-tile")].map((tile) => tile.textContent))
    .toEqual(["Volume kept61 %", "Volume carved39 %", "Kept volume4 880 m³", "Last analysis took6.4 s"]);
});

test("with auto-update on the threshold runs when the user leaves the field; off, it changes the form and Update carving runs", () => {
  const onThresholdCommit = vi.fn(), onChange = vi.fn(), onUpdateCarving = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ onThresholdCommit, onChange })} />);
  const field = rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  typeInto(field, "2.5");
  expect(onThresholdCommit).not.toHaveBeenCalled();
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(onThresholdCommit).toHaveBeenCalledExactlyOnceWith(2.5);
  expect(onChange).not.toHaveBeenCalled();
  rendered.unmount();

  rendered = renderForTest(<CarvingStep {...carvingProps({ autoUpdate: false, onChange, onUpdateCarving })} />);
  typeInto(rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!, "3");
  expect(onChange).toHaveBeenCalledWith({ threshold: { method: "cutoff", value: 3 } });
  click([...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Update carving")!);
  expect(onUpdateCarving).toHaveBeenCalledOnce();
});

test("a weighted mode shows Carve amount in % and Obstruction removed; the angle rule says it has no threshold and no histogram", () => {
  rendered = renderForTest(<CarvingStep {...carvingProps({ form: formFor("daylight"), isWeightedMode: true })} />);
  expect(rendered.container.querySelector(".threshold-control label")!.textContent).toBe("Carve amount");
  expect(rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!.value).toBe("70");
  expect(rendered.container.textContent).toContain("Obstruction removed42 %");
  rendered.unmount();
  rendered = renderForTest(<CarvingStep {...carvingProps({ form: formFor("tilted_plane") })} />);
  expect(rendered.container.textContent).toContain("The angle rule has no threshold: everything above the planes is removed. Change the angle in Settings.");
  expect(rendered.container.querySelector(".score-histogram")).toBeNull();
  expect(rendered.container.textContent).toContain("Update carving");
});

test("an analysis out of date dims the carving, disables its controls and offers Run analysis", () => {
  const onRunAnalysis = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ analysisOutOfDate: true, onRunAnalysis })} />);
  expect(rendered.container.textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  expect(rendered.container.querySelector(".carving-content-dimmed")).not.toBeNull();
  expect(rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!.disabled).toBe(true);
  expect(rendered.container.querySelector<HTMLInputElement>(".switch-row input")!.disabled).toBe(true);
  click([...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Run analysis")!);
  expect(onRunAnalysis).toHaveBeenCalledOnce();
});

test("auto-update is on unless switched off for the project on this computer", () => {
  expect(readAutoUpdate("p")).toBe(true);
  window.localStorage.setItem("usc.autoUpdate.p", "off");
  expect(readAutoUpdate("p")).toBe(false);
  expect(readAutoUpdate("other")).toBe(true);
});

test("the histogram: title, Log and Linear, the cutoff label, the key, the axis title, the slope-limit note and the readout", () => {
  rendered = renderForTest(<ScoreHistogram comparedScores={SCORE_POINTS.comparedScores!} kept={SCORE_POINTS.kept!} cutoff={1.5} isShadowTolerated
                                           slopeLimitVoxelsRemoved={312} />);
  const text = rendered.container.textContent!;
  expect(rendered.container.querySelector("h3")!.textContent).toBe("Scores of the voxels");
  expect([...rendered.container.querySelectorAll(".segmented-switch button")].map((button) => [button.textContent, button.getAttribute("aria-pressed")]))
    .toEqual([["Log", "true"], ["Linear", "false"]]);
  expect(rendered.container.querySelector(".histogram-cutoff-label")!.textContent).toBe("1.5");
  expect(text).toContain("Shadow tolerated at which a voxel is carved, m²·h");
  expect(text).toContain("KeptCarved");
  expect(text).toContain("The slope limit removed 312 voxels below the cutoff.");
  const chart = rendered.container.querySelector("svg")!;
  act(() => chart.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })));
  expect(rendered.container.querySelector(".score-histogram-readout")!.textContent).toBe("0 to 0.24 m²·h1 kept, 0 carved");
  click(rendered.container.querySelectorAll(".segmented-switch button")[1]);
  expect(rendered.container.querySelectorAll(".segmented-switch button")[1].getAttribute("aria-pressed")).toBe("true");
});

const PLATES: PlatesFile = {
  plates: [
    { floor: 0, z_bottom: 0, z_top: 5, area_m2: 400 }, { floor: 0, z_bottom: 0, z_top: 5, area_m2: 100 },
    { floor: 1, z_bottom: 5, z_top: 8, area_m2: 380 },
  ],
  floor_area_m2_per_floor: [500, 380],
  total_floor_area_m2: 880,
};

test("the storeys of plates.json, one row each from the ground up", () => {
  expect(storeyRows(PLATES)).toEqual([{ floorIndex: 0, bottom: 0, top: 5, area: 500 }, { floorIndex: 1, bottom: 5, top: 8, area: 380 }]);
});

test("Envelope and massing: three tiles, the per-storey table with a total, greyed and labelled when out of date", () => {
  const massing = { floor_area_m2_per_storey: [500, 380], total_floor_area_m2: 880, storeys_built: 2, envelope_volume_m3: 4200 };
  rendered = renderForTest(<EnvelopeAndMassingStep form={formFor("time-based")} onChange={vi.fn()} disabledReason={null} massing={massing}
                                                   platesFile={PLATES} outOfDate hasRunReport onOpenRunReport={vi.fn()} />);
  expect([...rendered.container.querySelectorAll(".number-tile")].map((tile) => tile.textContent))
    .toEqual(["Gross floor area880 m²", "Storeys2", "Envelope volume4 200 m³"]);
  const table = rendered.container.querySelector("table")!;
  expect(table.querySelector("caption")!.textContent).toBe("Floor area per storey");
  expect([...table.querySelectorAll("tr")].map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
    ["Storey", "Bottom, m", "Top, m", "Area, m²"], ["1, ground", "0.0", "5.0", "500"], ["2", "5.0", "8.0", "380"], ["Total", "", "", "880"],
  ]);
  expect(rendered.container.querySelector(".envelope-results-out-of-date")).not.toBeNull();
  expect(rendered.container.textContent).toContain("Out of date for the current carving");
  expect(rendered.container.textContent).toContain("Open the run report");
});

test("the Export downloads in the format chosen, out-of-date files labelled", () => {
  const downloads = exportDownloads({ project: "my project", meshFormat: "glb", envelopeOutOfDate: true, massingOutOfDate: false });
  expect(downloads.map((download) => [download.label, download.fileName, download.outOfDate])).toEqual([
    ["Carved envelope (GLB)", "my project envelope.glb", true],
    ["Building massing (OBJ)", "my project massing.obj", false],
    ["Building massing data (JSON)", "my project massing.json", false],
    ["Settings (config.yaml)", "config.yaml", false],
    ["Whole project (zip)", "my project.zip", false],
  ]);
  expect(downloads[0].address).toBe("/api/projects/my%20project/run/files/exporting/export.glb");
  expect(downloads[3].address).toBe("/api/projects/my%20project/config.yaml");
});

function runs(record: RunRecord | null, upToDate: RunLoop["upToDate"] = null) {
  return { current: record, upToDate, cancel: vi.fn() };
}

test("under the button that started it: the stages with their states, the batches, the elapsed time and Cancel", () => {
  let state = initialRunState(["preprocessing", "thresholding"]);
  state = runReducer(state, { type: "stage_progress", stage: "preprocessing", done: 3, total: 10 });
  const loop = runs({ serial: 1, project: "p", origin: "settings_run_analysis", runId: "r", state, refusal: null });
  rendered = renderForTest(<RunProgress runs={loop} project="p" origin="settings_run_analysis" mode="time-based" onGoToSetting={vi.fn()} />);
  expect([...rendered.container.querySelectorAll(".run-stage")].map((row) => row.textContent)).toEqual(["Sun analysis3 of 10 batches", "Carvingwaiting"]);
  expect(rendered.container.textContent).toMatch(/Elapsed \d+\.\d s/);
  click([...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Cancel")!);
  expect(loop.cancel).toHaveBeenCalledOnce();
  rendered.unmount();
  rendered = renderForTest(<RunProgress runs={loop} project="p" origin="build" mode="time-based" onGoToSetting={vi.fn()} />);
  expect(rendered.container.textContent).toBe("");
});

test("a failed run: the message, a link to the setting it names, and the Details fold with the type and the engine's message", () => {
  const state = runReducer(initialRunState(["preprocessing"]), {
    type: "run_failed", error_type: "ConfigError", message: "invalid", field_errors: [{ field: "voxel_size", message: "too small" }],
  });
  const onGoToSetting = vi.fn();
  rendered = renderForTest(<RunProgress runs={runs({ serial: 1, project: "p", origin: "build", runId: "r", state, refusal: null })} project="p"
                                        origin="build" mode="time-based" onGoToSetting={onGoToSetting} />);
  expect(rendered.container.textContent).toContain("The run stopped on an error.");
  click([...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Go to voxel size")!);
  expect(onGoToSetting).toHaveBeenCalledWith("voxel_size");
  expect(rendered.container.querySelector("summary")!.textContent).toBe("Details");
  expect(rendered.container.querySelector("details")!.textContent).toContain("Error type: ConfigError");
});

test("Cancelled, a stage chain error, the warnings of a run and Results are up to date", () => {
  const cancelled = runReducer(runReducer(initialRunState(["preprocessing"]), { type: "issue", stage: "preprocessing", code: "w", message: "1 panel skipped" }),
    { type: "run_cancelled" });
  rendered = renderForTest(<RunProgress runs={runs({ serial: 1, project: "p", origin: "build", runId: "r", state: cancelled, refusal: null })} project="p"
                                        origin="build" mode="time-based" onGoToSetting={vi.fn()} />);
  expect(rendered.container.textContent).toBe("Cancelled.Warnings1 panel skipped");
  rendered.unmount();
  const chain = runReducer(initialRunState(["exporting"]), { type: "run_failed", error_type: "StageChainError", message: "x", field_errors: [] });
  rendered = renderForTest(<RunProgress runs={runs({ serial: 2, project: "p", origin: "build", runId: "r", state: chain, refusal: null })} project="p"
                                        origin="build" mode="time-based" onGoToSetting={vi.fn()} />);
  expect(rendered.container.textContent).toBe("Results are out of date; run the analysis again");
  rendered.unmount();
  rendered = renderForTest(<RunProgress runs={runs(null, { project: "p", origin: "build" })} project="p" origin="build" mode="time-based"
                                        onGoToSetting={vi.fn()} />);
  expect(rendered.container.textContent).toBe("Results are up to date");
});

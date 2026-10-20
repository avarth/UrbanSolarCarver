import { act, useMemo, useReducer } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo, RunSummary } from "../api_client/client";
import { formReducer, initialFormState, type FormState } from "../settings_form/form_state";
import { addStyleSheetForTest, click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { CarvingStep, readAutoUpdate, type CarvingStepProps } from "./CarvingStep";
import { EnvelopeAndMassingStep, storeyRows, type EnvelopeAndMassingStepProps, type PlatesFile } from "./EnvelopeAndMassingStep";
import { exportDownloads } from "./ExportStep";
import { RunProgress } from "./RunProgress";
import { RunReportPanel } from "./RunReportPanel";
import { initialRunState, runReducer, type RunLoop, type RunRecord } from "./run_state";
import { ScoreHistogram } from "./ScoreHistogram";
import { createThresholdUpdateQueue } from "./threshold_queue";

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
  ({ name, description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: scoreKind, weight_unit: "", score_unit: "", starting_values: {} });
const MODES = [mode("time-based", "violation_count"), mode("daylight", "weighted_sum"), mode("tilted_plane", "violation_count")];

function formFor(modeName: string, settings: Record<string, unknown> = {}): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: modeName, ...settings }, gridPlan: null });
}

const CARVING: NonNullable<RunSummary["carving"]> = {
  threshold_value: 1.5, voxels_occupied: 1000, voxels_kept: 610, voxels_removed: 390, retention_pct: 61, obstruction_fraction_carved: 0.42,
  carve_above_extra_voxels_removed: 0, slope_limit_extra_voxels_removed: 312,
};

const SCORE_POINTS: ScorePoints = {
  header: { origin: [0, 0, 0], shape: [2, 2, 2], voxel_size: 2, mode: "time-based", scores_kind: "violation_count", weight_unit: "m²·h", score_unit: "m²·h", score_min: 0, score_max: 9.6, compared_score_max: 9.6,
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

test("Solar time-based: Shadow tolerated with its slider ends, the histogram, the tiles two per row", () => {
  rendered = renderForTest(<CarvingStep {...carvingProps()} />);
  const text = rendered.container.textContent!;
  expect(rendered.container.querySelector(".threshold-control label")!.textContent).toBe("Shadow tolerated");
  expect(rendered.container.querySelector(".threshold-slider-ends")!.textContent).toBe("09.6\u00a0m²·h, the highest score");
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
  expect(onThresholdCommit).toHaveBeenCalledExactlyOnceWith({ threshold: { method: "cutoff", value: 2.5 } });
  expect(onChange).not.toHaveBeenCalled();
  rendered.unmount();

  rendered = renderForTest(<CarvingStep {...carvingProps({ autoUpdate: false, onChange, onUpdateCarving })} />);
  typeInto(rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!, "3");
  expect(onChange).toHaveBeenCalledWith({ threshold: { method: "cutoff", value: 3 } });
  click([...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Update carving")!);
  expect(onUpdateCarving).toHaveBeenCalledOnce();
});

test("a threshold typed back to the stored value while another value waits behind a run replaces that value", async () => {
  // The control and the queue as result_steps joins them: the queue applies a value to the form, then runs it until told to end.
  const appliedValues: number[] = [];
  const endRuns: (() => void)[] = [];
  function CarvingWithQueue() {
    const [form, dispatch] = useReducer(formReducer, carvingProps().form);
    const queue = useMemo(() => createThresholdUpdateQueue<Record<string, unknown>>((values) => {
      appliedValues.push((values.threshold as { value: number }).value);
      dispatch({ type: "values_changed", values });
      return new Promise<boolean>((resolve) => { endRuns.push(() => resolve(true)); });
    }, vi.fn()), []);
    return <CarvingStep {...carvingProps({ form, onThresholdCommit: (values) => queue.submit(values) })} />;
  }
  rendered = renderForTest(<CarvingWithQueue />);
  const field = () => rendered!.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  const typeAndLeave = (text: string) => {
    typeInto(field(), text);
    act(() => field().dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  };
  typeAndLeave("1");                  // run A, for 1: the form holds 1
  typeAndLeave("2");                  // waits behind A
  typeAndLeave("1");                  // back to the stored value: 1 waits instead of 2
  expect(field().value).toBe("1");
  await act(async () => { endRuns.shift()!(); await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(appliedValues).toEqual([1, 1]);
  expect(field().value).toBe("1");
});

test("leaving the threshold field at the stored number submits nothing after the form got that number another way", () => {
  const onThresholdCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ onThresholdCommit })} />);
  const field = () => rendered!.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  const typeAndLeave = (text: string) => {
    typeInto(field(), text);
    act(() => field().dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  };
  typeAndLeave("2");
  expect(onThresholdCommit.mock.calls).toEqual([[{ threshold: { method: "cutoff", value: 2 } }]]);
  // The form now holds 3, set without this control's run (an edit with auto-update off, another carving setting's run).
  rendered.rerender(<CarvingStep {...carvingProps({ onThresholdCommit, form: formFor("time-based", { threshold: { method: "cutoff", value: 3 } }) })} />);
  typeAndLeave("3");
  expect(onThresholdCommit.mock.calls).toEqual([[{ threshold: { method: "cutoff", value: 2 } }]]);
  expect(field().value).toBe("3");
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
  rendered = renderForTest(<ScoreHistogram comparedScores={SCORE_POINTS.comparedScores!} kept={SCORE_POINTS.kept!} cutoff={1.5} carvingCutoff={1.5}
                                           cutoffIsPreview={false} axisTitle="Shade a voxel casts, m²·h" unit="m²·h"
                                           cutoffValueText={(cutoff) => String(cutoff)} slopeLimitVoxelsRemoved={312} />);
  const text = rendered.container.textContent!;
  expect(rendered.container.querySelector("h3")!.textContent).toBe("Scores of the voxels");
  expect([...rendered.container.querySelectorAll(".segmented-switch button")].map((button) => [button.textContent, button.getAttribute("aria-pressed")]))
    .toEqual([["Log", "true"], ["Linear", "false"]]);
  expect(rendered.container.querySelector(".histogram-cutoff-label")!.textContent).toBe("1.5");
  expect(text).toContain("Shade a voxel casts, m²·h");
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

test("the storeys of plates.json, one row each from the ground up, heights from the bottom of storey 1", () => {
  expect(storeyRows(PLATES)).toEqual([{ floorIndex: 0, bottom: 0, top: 5, area: 500 }, { floorIndex: 1, bottom: 5, top: 8, area: 380 }]);
  const belowZero = { ...PLATES, plates: PLATES.plates.map((plate) => ({ ...plate, z_bottom: plate.z_bottom - 0.5, z_top: plate.z_top - 0.5 })) };
  expect(storeyRows(belowZero).map((row) => [row.bottom, row.top])).toEqual([[0, 5], [5, 8]]);
});

const MASSING = { export_mesh_file: "plates.ply", floor_area_m2_per_storey: [500, 380], total_floor_area_m2: 880, storeys_built: 2 };
const ENVELOPE = { mesh_file: "export.ply", envelope_volume_m3: 4150 };

function envelopeAndMassingProps(overrides: Partial<EnvelopeAndMassingStepProps> = {}): EnvelopeAndMassingStepProps {
  return {
    form: formFor("time-based"), onChange: vi.fn(), disabledReason: null, envelope: ENVELOPE, envelopeOutOfDate: false,
    envelopeButton: <button type="button">Build envelope</button>, massing: MASSING, platesFile: PLATES, massingOutOfDate: false,
    massingButton: <button type="button">Build massing</button>, buildFeedback: null, hasRunReport: true, onOpenRunReport: vi.fn(), ...overrides,
  };
}

/** The part of the step whose heading is *title*: its settings, its button and its results. */
function partOf(container: Element, title: string): Element {
  return [...container.querySelectorAll(".build-part")].find((part) => part.querySelector(".setting-group-title")!.textContent === title)!;
}

test("Envelope and massing: two parts, each with its settings, its button and its results; the run report link at the bottom (R2 5)", () => {
  rendered = renderForTest(<EnvelopeAndMassingStep {...envelopeAndMassingProps()} />);
  const envelope = partOf(rendered.container, "Envelope"), massing = partOf(rendered.container, "Building massing");
  expect(envelope.querySelector('[data-setting="apply_smoothing"]')).not.toBeNull();
  expect(envelope.querySelector('[data-setting="ground_floor_height"]')).toBeNull();
  expect(massing.querySelector('[data-setting="min_plate_dimension"]')).not.toBeNull();
  expect([...rendered.container.querySelectorAll('[data-setting="min_plate_dimension"] label')].map((label) => label.textContent)).toEqual(["Grid module"]);
  expect([...envelope.querySelectorAll("button")].map((button) => button.textContent)).toContain("Build envelope");
  expect([...massing.querySelectorAll("button")].map((button) => button.textContent)).toContain("Build massing");
  expect([...envelope.querySelectorAll(".number-tile")].map((tile) => tile.textContent)).toEqual(["Envelope volume i4 150 m³"]);     // " i": the tile's "i"
  expect([...massing.querySelectorAll(".number-tile")].map((tile) => tile.textContent)).toEqual(["Gross floor area880 m²", "Storeys2"]);
  const table = massing.querySelector("table")!;
  expect(table.querySelector("caption")!.textContent).toBe("Floor area per storey");
  expect([...table.querySelectorAll("tr")].map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
    ["Storey", "Bottom, m", "Top, m", "Area, m²"], ["1, ground", "0.0", "5.0", "500"], ["2", "5.0", "8.0", "380"], ["Total", "", "", "880"],
  ]);
  expect(rendered.container.querySelector(".envelope-results-out-of-date")).toBeNull();
  // What the envelope volume counts is said in the tile's "i".
  click(envelope.querySelector<HTMLButtonElement>('[aria-label="About envelope volume"]')!);
  expect(document.querySelector('[role="tooltip"]')!.textContent).toBe(
    "Counted on the kept voxels the envelope mesh was built from, after small pieces were dropped, not on the smoothed surface.");
  const lastChild = rendered.container.querySelector(".envelope-step")!.lastElementChild!;
  expect(lastChild.textContent).toBe("Open the run report");
});

test("each part is greyed and labelled out of date on its own; a part not built shows no results", () => {
  rendered = renderForTest(<EnvelopeAndMassingStep {...envelopeAndMassingProps({ massingOutOfDate: true })} />);
  expect(partOf(rendered.container, "Envelope").querySelector(".envelope-results-out-of-date")).toBeNull();
  expect(partOf(rendered.container, "Building massing").querySelector(".envelope-results-out-of-date")!.textContent).toContain("Out of date for the current settings");
  rendered.unmount();
  rendered = renderForTest(<EnvelopeAndMassingStep {...envelopeAndMassingProps({ envelopeOutOfDate: true, massing: null, platesFile: null })} />);
  expect(partOf(rendered.container, "Envelope").querySelector(".envelope-results-out-of-date")).not.toBeNull();
  expect(partOf(rendered.container, "Building massing").querySelector(".envelope-results")).toBeNull();
  expect(partOf(rendered.container, "Building massing").textContent).toContain("Build massing");
});

/** The elements that hold text of their own (HTML or SVG) inside *root*. */
function textBearingElementsIn(root: Element): Element[] {
  return [root, ...root.querySelectorAll("*")].filter((element) =>
    [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent!.trim() !== ""));
}

/** The opacities below 1 from *element* up to *root*: what fades the element's text. */
function fadingOpacitiesOf(element: Element, root: Element): string[] {
  const opacities: string[] = [];
  for (let current: Element | null = element; current !== null; current = current === root ? null : current.parentElement) {
    const opacity = getComputedStyle(current).opacity;
    if (opacity !== "" && Number(opacity) < 1) opacities.push(`${current.tagName.toLowerCase()}.${current.getAttribute("class")}: ${opacity}`);
  }
  return opacities;
}

test("dimmed and greyed results keep their text at full opacity in the muted colour, and fade only the bars and swatches (UX 5.5, 5.6, 12)", () => {
  const removeStyleSheet = addStyleSheetForTest("src/steps/steps.css");
  try {
    rendered = renderForTest(<CarvingStep {...carvingProps({ carvingDimmed: true })} />);
    const carvingResults = rendered.container.querySelector(".carving-content-dimmed")!;
    act(() => carvingResults.querySelector("svg")!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })));
    expect(carvingResults.querySelector(".score-histogram-readout")).not.toBeNull();
    const carvingTexts = textBearingElementsIn(carvingResults);
    expect(carvingTexts.map((element) => element.textContent)).toEqual(expect.arrayContaining(["Scores of the voxels", "Volume kept", "61 %", "Kept", "1.5"]));
    expect(carvingTexts.flatMap((element) => fadingOpacitiesOf(element, carvingResults))).toEqual([]);
    expect(getComputedStyle(carvingResults).color).toBe("var(--colour-muted)");
    expect(Number(getComputedStyle(carvingResults.querySelector(".histogram-bar")!).opacity)).toBeLessThan(1);
    expect(Number(getComputedStyle(carvingResults.querySelector(".histogram-swatch")!).opacity)).toBeLessThan(1);
    rendered.unmount();

    rendered = renderForTest(<EnvelopeAndMassingStep {...envelopeAndMassingProps({ massingOutOfDate: true })} />);
    const massingResults = rendered.container.querySelector(".envelope-results-out-of-date")!;
    const massingTexts = textBearingElementsIn(massingResults);
    expect(massingTexts.map((element) => element.textContent)).toEqual(expect.arrayContaining(["Gross floor area", "Floor area per storey", "1, ground", "880"]));
    expect(massingTexts.flatMap((element) => fadingOpacitiesOf(element, massingResults))).toEqual([]);
    for (const greyed of massingResults.querySelectorAll(".number-tiles, .storey-table")) expect(getComputedStyle(greyed).color).toBe("var(--colour-muted)");
    expect(Number(getComputedStyle(massingResults.querySelector(".storey-swatch")!).opacity)).toBeLessThan(1);
  } finally {
    removeStyleSheet();
  }
});

test("the Export downloads in the format chosen, out-of-date files labelled", () => {
  const downloads = exportDownloads({ project: "my project", meshFormat: "glb", envelopeFile: "export.glb", envelope: "out_of_date",
                                      massingFile: "plates.glb", massing: "current" });
  expect(downloads.map((download) => [download.label, download.fileName, download.outOfDate, download.note])).toEqual([
    ["Carved envelope (GLB)", "my project envelope.glb", true, undefined],
    ["Building massing (GLB)", "my project massing.glb", false, undefined],
    ["Building massing data (JSON)", "my project massing.json", false, undefined],
    ["Settings (config.yaml)", "config.yaml", false, undefined],
    ["Whole project (zip)", "my project.zip", false, undefined],
  ]);
  expect(downloads[0].address).toBe("/api/projects/my%20project/run/files/exporting/export.glb");
  expect(downloads[1].address).toBe("/api/projects/my%20project/run/files/massing/plates.glb");
  expect(downloads[3].address).toBe("/api/projects/my%20project/config.yaml");
});

test("Export offers each file once its stage exists: the envelope without the massing, the massing without the envelope (R2 5)", () => {
  const labelsWith = (envelope: "current" | "missing", massing: "current" | "missing") =>
    exportDownloads({ project: "p", meshFormat: "ply", envelopeFile: "export.ply", envelope, massingFile: "plates.ply", massing }).map((download) => download.label);
  expect(labelsWith("current", "missing")).toEqual(["Carved envelope (PLY)", "Settings (config.yaml)", "Whole project (zip)"]);
  expect(labelsWith("missing", "current")).toEqual(["Building massing (PLY)", "Building massing data (JSON)", "Settings (config.yaml)", "Whole project (zip)"]);
});

test("Export offers the massing file that was built, under its own format, when the format chosen since was not built yet", () => {
  // PLY was chosen after the massing was built as OBJ: the OBJ on disk is what can be downloaded until the next massing build.
  const [massing] = exportDownloads({ project: "p", meshFormat: "ply", envelopeFile: null, envelope: "missing", massingFile: "plates.obj", massing: "out_of_date" });
  expect([massing.label, massing.address, massing.fileName, massing.outOfDate, massing.note])
    .toEqual(["Building massing (OBJ)", "/api/projects/p/run/files/massing/plates.obj", "p massing.obj", true, "Built as OBJ; the next massing build writes PLY."]);
  // Until the run summary names the file, the massing data is offered without the mesh.
  expect(exportDownloads({ project: "p", meshFormat: "ply", envelopeFile: null, envelope: "missing", massingFile: null, massing: "current" }).map((download) => download.label))
    .toEqual(["Building massing data (JSON)", "Settings (config.yaml)", "Whole project (zip)"]);
});

test("Export offers the envelope file that was built, under its own format, when the format chosen since was not built yet", () => {
  // OBJ was chosen while Carving was locked: stored, not built; the PLY on disk is what can be downloaded.
  const [envelope] = exportDownloads({ project: "p", meshFormat: "obj", envelopeFile: "export.ply", envelope: "out_of_date", massingFile: null, massing: "missing" });
  expect([envelope.label, envelope.address, envelope.fileName, envelope.outOfDate, envelope.note])
    .toEqual(["Carved envelope (PLY)", "/api/projects/p/run/files/exporting/export.ply", "p envelope.ply", true, "Built as PLY; the next envelope build writes OBJ."]);
  expect(exportDownloads({ project: "p", meshFormat: "ply", envelopeFile: "export.ply", envelope: "current", massingFile: null, massing: "missing" })[0].note).toBeUndefined();
  // Until the run summary names the file, no envelope file is offered.
  expect(exportDownloads({ project: "p", meshFormat: "ply", envelopeFile: null, envelope: "current", massingFile: null, massing: "missing" }).map((download) => download.label))
    .toEqual(["Settings (config.yaml)", "Whole project (zip)"]);
});

function runs(record: RunRecord | null, notice: RunLoop["notice"] = null) {
  return { current: record, notice, cancel: vi.fn() };
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
  rendered = renderForTest(<RunProgress runs={runs(null, { project: "p", origin: "build", message: "Results are up to date" })} project="p"
                                        origin="build" mode="time-based" onGoToSetting={vi.fn()} />);
  expect(rendered.container.textContent).toBe("Results are up to date");
});

function unfoldCarvingSettings(container: HTMLElement) {
  click([...container.querySelectorAll("button")].find((button) => button.textContent === "More carving settings")!);
}

test("with auto-update on, a carving number field runs once the user leaves it, with the whole number; a switch runs at once", () => {
  const onChange = vi.fn(), onCarvingSettingCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ onChange, onCarvingSettingCommit })} />);
  unfoldCarvingSettings(rendered.container);
  const field = rendered.container.querySelector<HTMLInputElement>('[data-setting="carve_above_min_consecutive"] input')!;
  typeInto(field, "4");
  typeInto(field, "45");
  expect(onChange.mock.calls).toEqual([[{ carve_above_min_consecutive: 4 }], [{ carve_above_min_consecutive: 45 }]]);
  expect(onCarvingSettingCommit).not.toHaveBeenCalled();
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(onCarvingSettingCommit).toHaveBeenCalledOnce();
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(onCarvingSettingCommit).toHaveBeenCalledOnce();            // nothing changed since: no second run
  typeInto(field, "3");
  act(() => field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
  expect(onCarvingSettingCommit).toHaveBeenCalledTimes(2);
  click(rendered.container.querySelector<HTMLInputElement>('[data-setting="carve_above"] input')!);
  expect(onChange).toHaveBeenLastCalledWith({ carve_above: false });
  expect(onCarvingSettingCommit).toHaveBeenCalledTimes(3);
});

test("with auto-update on, a carving slider changes the form while dragged and runs once it is let go, or after a key moved it", () => {
  const onChange = vi.fn(), onCarvingSettingCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ onChange, onCarvingSettingCommit })} />);
  unfoldCarvingSettings(rendered.container);
  const slider = rendered.container.querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="range"]')!;
  typeInto(slider, "60");
  typeInto(slider, "55");
  expect(onChange.mock.calls).toEqual([[{ max_slope_deg: 60 }], [{ max_slope_deg: 55 }]]);
  expect(onCarvingSettingCommit).not.toHaveBeenCalled();
  act(() => slider.dispatchEvent(new Event("pointerup", { bubbles: true })));
  expect(onCarvingSettingCommit).toHaveBeenCalledOnce();
  typeInto(slider, "56");
  act(() => slider.dispatchEvent(new KeyboardEvent("keyup", { key: "ArrowRight", bubbles: true })));
  expect(onCarvingSettingCommit).toHaveBeenCalledTimes(2);
  act(() => slider.dispatchEvent(new KeyboardEvent("keyup", { key: "Tab", bubbles: true })));
  expect(onCarvingSettingCommit).toHaveBeenCalledTimes(2);       // no slider key, nothing moved
});

test("with auto-update off, carving settings only change the form", () => {
  const onChange = vi.fn(), onCarvingSettingCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ autoUpdate: false, onChange, onCarvingSettingCommit })} />);
  unfoldCarvingSettings(rendered.container);
  const field = rendered.container.querySelector<HTMLInputElement>('[data-setting="carve_above_min_consecutive"] input')!;
  typeInto(field, "2");
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(onChange).toHaveBeenCalledWith({ carve_above_min_consecutive: 2 });
  expect(onCarvingSettingCommit).not.toHaveBeenCalled();
});

test("disabled carving controls say why, outside the dimmed carving: the run in progress over the controls, the run blocker under Update carving", () => {
  // The carving is dimmed while its run is under way, which is when these reasons show: dimmed, their text would fall below AA (UX 12).
  rendered = renderForTest(<CarvingStep {...carvingProps({ autoUpdate: false, carvingDimmed: true, thresholdDisabledReason: "A run is in progress",
                                                           settingsDisabledReason: "A run is in progress", runBlocker: "A run is in progress" })} />);
  expect(rendered.container.querySelector(".carving-content-dimmed")).not.toBeNull();
  expect([...rendered.container.querySelectorAll(".carving-step > .step-reason")].map((reason) => reason.textContent)).toEqual(["A run is in progress"]);
  const update = [...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Update carving")!;
  expect(update.hasAttribute("disabled")).toBe(true);
  const updateReason = document.getElementById(update.getAttribute("aria-describedby")!)!;
  expect(updateReason.textContent).toBe("A run is in progress");
  expect(updateReason.closest(".carving-content-dimmed")).toBeNull();
  expect(rendered.container.querySelectorAll(".carving-content-dimmed .step-reason, .carving-content-dimmed .run-button-reason")).toHaveLength(0);
  rendered.unmount();
  rendered = renderForTest(<CarvingStep {...carvingProps({ autoUpdate: false, runBlocker: "Waiting for the GPU to be ready" })} />);
  expect(rendered.container.querySelector(".carving-step > .step-reason")).toBeNull();
  expect(rendered.container.querySelector(".update-carving .run-button-reason")!.textContent).toBe("Waiting for the GPU to be ready");
  rendered.unmount();

  // The angle rule's message, in place of the threshold control, is not dimmed either.
  rendered = renderForTest(<CarvingStep {...carvingProps({ form: formFor("tilted_plane"), carvingDimmed: true })} />);
  expect(rendered.container.querySelector(".carving-content-dimmed")).not.toBeNull();
  const angleRuleMessage = [...rendered.container.querySelectorAll(".step-reason")].find((reason) => reason.textContent!.startsWith("The angle rule has no threshold"))!;
  expect(angleRuleMessage.closest(".carving-content-dimmed")).toBeNull();
  expect(angleRuleMessage.parentElement).toBe(rendered.container.querySelector(".carving-step > .carving-content"));    // where the threshold control would be
  rendered.unmount();

  // Nor are the messages of carving settings a failed run found invalid, each still under its field.
  const formWithErrors = formReducer(carvingProps().form, { type: "save_rejected", reply: { grid_plan: null, field_errors: [
    { field: "threshold", message: "Input should be greater than or equal to 0" },
    { field: "carve_above_min_consecutive", message: "Input should be greater than or equal to 1" }] } });
  rendered = renderForTest(<CarvingStep {...carvingProps({ form: formWithErrors, carvingDimmed: true })} />);
  expect(rendered.container.querySelector(".carving-content-dimmed")).not.toBeNull();
  const fieldErrors = [...rendered.container.querySelectorAll(".setting-error")];
  expect(fieldErrors.map((error) => error.closest(".setting-field")!.getAttribute("data-setting"))).toEqual(["threshold", "carve_above_min_consecutive"]);
  expect(rendered.container.querySelectorAll(".carving-content-dimmed .setting-error, .carving-content-dimmed .step-reason")).toHaveLength(0);
});

/** The score points of SCORE_POINTS as a Daylight analysis gives them: m² of hidden sky. */
const DAYLIGHT_POINTS: ScorePoints = { ...SCORE_POINTS, header: { ...SCORE_POINTS.header, mode: "daylight", scores_kind: "weighted_sum", score_unit: "m²" } };

function weightedCarvingProps(settings: Record<string, unknown>, overrides: Partial<CarvingStepProps> = {}): CarvingStepProps {
  return carvingProps({ form: formFor("daylight", settings), isWeightedMode: true, scorePoints: DAYLIGHT_POINTS, ...overrides });
}

const ruleChoices = (container: HTMLElement) => [...container.querySelectorAll<HTMLInputElement>(".carving-rule-options input")];
const cutoffHandle = (container: HTMLElement) => container.querySelector<HTMLElement>(".histogram-cutoff-handle")!;
const pressHandleKey = (container: HTMLElement, key: string) => act(() => {
  cutoffHandle(container).dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
});
const releaseHandleKey = (container: HTMLElement, key: string) => act(() => {
  cutoffHandle(container).dispatchEvent(new KeyboardEvent("keyup", { key, bubbles: true }));
});

test("a weighted mode: the carving rule at the top, the control of the rule under it, and the histogram in every rule", () => {
  for (const [threshold, controlLabel] of [[null, "Carve amount"], [{ method: "headtail" }, null], [{ method: "cutoff", value: 4 }, "Score cutoff"]] as const) {
    rendered = renderForTest(<CarvingStep {...weightedCarvingProps(threshold === null ? {} : { threshold })} />);
    const container = rendered.container;
    expect(container.querySelector(".carving-rule-choice .setting-label")!.textContent).toBe("Carving rule");
    expect(ruleChoices(container).map((choice) => [choice.parentElement!.textContent, choice.checked]))
      .toEqual([["Carve amount", threshold === null], ["Automatic split", threshold?.method === "headtail"], ["Score cutoff", threshold?.method === "cutoff"]]);
    expect(container.querySelector(".threshold-control label")?.textContent ?? null).toBe(controlLabel);
    expect(container.querySelector(".score-histogram")).not.toBeNull();
    expect(container.querySelector(".score-histogram-axis-title")!.textContent).toBe("Overcast sky a voxel hides, m²");
    // The rule is no longer in the fold, and the histogram comes before it.
    expect(container.querySelector('.carving-settings [data-setting="threshold"]')).toBeNull();
    expect(container.querySelector(".score-histogram")!.compareDocumentPosition(container.querySelector(".carving-settings")!))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    rendered.unmount();
  }
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "headtail" } })} />);
  expect(rendered.container.textContent).toContain("Cut at 1.5 m², found from the spread of the scores. Drag the line on the histogram to set a cutoff of your own.");
  rendered.unmount();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "cutoff", value: 4 } })} />);
  expect(rendered.container.querySelector(".threshold-control .setting-unit")!.textContent).toBe("m²");
  expect(rendered.container.querySelector(".threshold-slider-ends")!.textContent).toBe("09.6 m², the highest score");
  rendered.unmount();
  // The slider ends at the highest score the cutoff is compared with (after Remove everything above a cut), where a higher
  // cutoff would carve nothing more; the raw score of a voxel may be higher.
  const comparedLower: ScorePoints = { ...DAYLIGHT_POINTS, header: { ...DAYLIGHT_POINTS.header, compared_score_max: 7.5 },
                                       comparedScores: Float32Array.from([0, 1, 5, 7.5]) };
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "cutoff", value: 4 } }, { scorePoints: comparedLower })} />);
  expect(rendered.container.querySelector(".threshold-slider-ends")!.textContent).toBe("07.5 m², the highest score");
  rendered.unmount();
  // Without compared scores (no carving on this analysis yet) it ends at the highest raw score.
  const withoutCompared: ScorePoints = { ...DAYLIGHT_POINTS, header: { ...DAYLIGHT_POINTS.header, compared_score_max: null } };
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "cutoff", value: 4 } }, { scorePoints: withoutCompared })} />);
  expect(rendered.container.querySelector(".threshold-slider-ends")!.textContent).toBe("09.6 m², the highest score");
});

test("choosing a rule keeps the cut on the histogram: Score cutoff and Carve amount start from it; the rules without a carve amount unset it", () => {
  const onThresholdCommit = vi.fn(), onChange = vi.fn();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({}, { onThresholdCommit })} />);
  click(ruleChoices(rendered.container)[2]);
  expect(onThresholdCommit).toHaveBeenLastCalledWith({ threshold: { method: "cutoff", value: 1.5 }, carve_fraction: null });
  rendered.unmount();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "cutoff", value: 4 } }, { autoUpdate: false, onChange })} />);
  click(ruleChoices(rendered.container)[1]);
  expect(onChange).toHaveBeenLastCalledWith({ threshold: { method: "headtail" }, carve_fraction: null });
  // The cut at 1.5 carves the points scoring 5 and 9.6: 14.6 of 15.6, a carve amount of 93.6 %.
  click(ruleChoices(rendered.container)[0]);
  expect(onChange).toHaveBeenLastCalledWith({ threshold: null, carve_fraction: 0.936 });
});

test("under Carve amount, moving the cutoff line previews what it keeps, shows the amount it stands for, and sets that amount when let go", () => {
  // The points score 0, 1, 5 and 9.6 (15.6 in all); the cut is at 1.5. Page Up moves it a tenth of the range, to 2.46: the points
  // 5 and 9.6 go, 14.6 of 15.6 (93.6 %), and two of the four points stay.
  const onThresholdCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({}, { onThresholdCommit })} />);
  const container = rendered.container;
  expect(cutoffHandle(container).getAttribute("role")).toBe("slider");
  expect(cutoffHandle(container).getAttribute("aria-valuetext")).toBe("1.5 m², keeps about 50 % of the volume");
  expect(container.querySelector(".score-histogram-preview-note")).toBeNull();
  pressHandleKey(container, "PageUp");
  expect(container.querySelector(".histogram-cutoff-label")!.textContent).toBe("2.46");
  expect(container.querySelector(".score-histogram-preview-note")!.textContent)
    .toBe("Preview: carve amount 94 %, a cut at 2.46 m², keeps about 50 % of the volume, before the slope limit.");
  expect(container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!.value).toBe("93.6");
  expect(onThresholdCommit).not.toHaveBeenCalled();
  releaseHandleKey(container, "PageUp");
  expect(onThresholdCommit).toHaveBeenCalledExactlyOnceWith({ carve_fraction: 0.936 });
  // Until the carving it started comes back, the line stays where it was let go.
  expect(container.querySelector(".histogram-cutoff-label")!.textContent).toBe("2.46");
});

test("under Score cutoff and in Solar time-based the line sets the cutoff; under Automatic split it switches to Score cutoff, and says so", () => {
  const onThresholdCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "cutoff", value: 1.5 } }, { onThresholdCommit })} />);
  pressHandleKey(rendered.container, "PageUp");
  expect(rendered.container.querySelector(".score-histogram-preview-note")!.textContent)
    .toBe("Preview: a cut at 2.46 m² keeps about 50 % of the volume, before the slope limit.");
  releaseHandleKey(rendered.container, "PageUp");
  expect(onThresholdCommit).toHaveBeenLastCalledWith({ threshold: { method: "cutoff", value: 2.46 }, carve_fraction: null });
  rendered.unmount();

  const props = weightedCarvingProps({ threshold: { method: "headtail" } }, { onThresholdCommit });
  rendered = renderForTest(<CarvingStep {...props} />);
  pressHandleKey(rendered.container, "End");
  releaseHandleKey(rendered.container, "End");
  expect(onThresholdCommit).toHaveBeenLastCalledWith({ threshold: { method: "cutoff", value: 9.6 }, carve_fraction: null });
  rendered.rerender(<CarvingStep {...props} form={formFor("daylight", { threshold: { method: "cutoff", value: 9.6 } })} />);
  expect(rendered.container.textContent).toContain("Dragging the line switched the carving rule from Automatic split to Score cutoff.");
  rendered.unmount();

  rendered = renderForTest(<CarvingStep {...carvingProps({ onThresholdCommit })} />);         // Solar time-based, cut at 1.5 m²·h
  pressHandleKey(rendered.container, "ArrowRight");
  releaseHandleKey(rendered.container, "ArrowRight");
  expect(onThresholdCommit).toHaveBeenLastCalledWith({ threshold: { method: "cutoff", value: 1.6 }, carve_fraction: null });
  expect(rendered.container.querySelector(".score-histogram-axis-title")!.textContent).toBe("Shade a voxel casts, m²·h");
});

test("the line follows the pointer while it is dragged and is set when the pointer lets go", () => {
  const onThresholdCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({ threshold: { method: "cutoff", value: 1.5 } }, { onThresholdCommit })} />);
  const handle = cutoffHandle(rendered.container);
  // The chart is 300 px wide, as its view box: the plot runs from 50 to 292 px, scores 0 to 9.6.
  vi.spyOn(handle.parentElement!, "getBoundingClientRect").mockReturnValue(DOMRect.fromRect({ x: 0, y: 0, width: 300, height: 170 }));
  const pointer = (type: string, clientX: number) => act(() => {
    handle.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX }) as PointerEvent);
  });
  pointer("pointerdown", 70);
  pointer("pointermove", 171);         // halfway: 4.8
  expect(rendered.container.querySelector(".histogram-cutoff-label")!.textContent).toBe("4.8");
  expect(onThresholdCommit).not.toHaveBeenCalled();
  pointer("pointerup", 171);
  expect(onThresholdCommit).toHaveBeenCalledExactlyOnceWith({ threshold: { method: "cutoff", value: 4.8 }, carve_fraction: null });
});

test("with auto-update off, a cutoff let go changes the form and stays on the histogram as a preview until Update carving runs it", () => {
  const onChange = vi.fn(), onThresholdCommit = vi.fn();
  const props = weightedCarvingProps({}, { autoUpdate: false, onChange, onThresholdCommit });
  rendered = renderForTest(<CarvingStep {...props} />);
  pressHandleKey(rendered.container, "PageUp");
  releaseHandleKey(rendered.container, "PageUp");
  expect(onChange).toHaveBeenCalledExactlyOnceWith({ carve_fraction: 0.936 });
  expect(onThresholdCommit).not.toHaveBeenCalled();
  // The form holds the new amount, not stored yet: the line is where that amount cuts, a preview.
  const changed = formReducer(props.form, { type: "values_changed", values: { carve_fraction: 0.936 } });
  rendered.rerender(<CarvingStep {...props} form={changed} />);
  expect(rendered.container.querySelector(".score-histogram-preview")).not.toBeNull();
  expect(rendered.container.querySelector(".score-histogram-preview-note")!.textContent).toContain("carve amount 94 %");
});

test("the line follows the Carve amount slider before it is let go, as a preview", () => {
  // 95 % of the 15.6 is 14.8: the cut falls at the point scoring 1, which keeps two of the four points.
  const onThresholdCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({}, { onThresholdCommit })} />);
  typeInto(rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=range]")!, "95");
  expect(onThresholdCommit).not.toHaveBeenCalled();
  expect(rendered.container.querySelector(".histogram-cutoff-label")!.textContent).toBe("1");
  expect(rendered.container.querySelector(".score-histogram-preview-note")!.textContent)
    .toBe("Preview: carve amount 95 %, a cut at 1 m², keeps about 50 % of the volume, before the slope limit.");
});

test("the cutoff line cannot be moved while the threshold cannot be changed", () => {
  const onThresholdCommit = vi.fn();
  rendered = renderForTest(<CarvingStep {...weightedCarvingProps({}, { onThresholdCommit, thresholdDisabledReason: "A run is in progress" })} />);
  expect(cutoffHandle(rendered.container).getAttribute("aria-disabled")).toBe("true");
  expect(ruleChoices(rendered.container).every((choice) => choice.disabled)).toBe(true);
  pressHandleKey(rendered.container, "PageUp");
  releaseHandleKey(rendered.container, "PageUp");
  expect(onThresholdCommit).not.toHaveBeenCalled();
  expect(rendered.container.querySelector(".histogram-cutoff-label")!.textContent).toBe("1.5");
});

test("Volume carved is 100 minus Volume kept as shown, so the two add up to 100", () => {
  rendered = renderForTest(<CarvingStep {...carvingProps({ summary: { ...CARVING, retention_pct: 60.5 } })} />);
  const tiles = [...rendered.container.querySelectorAll(".number-tile")].map((tile) => tile.textContent);
  expect(tiles.slice(0, 2)).toEqual(["Volume kept61 %", "Volume carved39 %"]);
});

test("a run report that cannot be read says so instead of an empty panel", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "There is no result file" }), { status: 404 })));
  rendered = renderForTest(<RunReportPanel token="t" project="p" onClose={vi.fn()} onServiceProblem={vi.fn()} />);
  await act(async () => {});
  expect(rendered.container.querySelector(".run-report-problem")!.textContent)
    .toBe("The run report could not be read. Build the envelope or the massing again to write it.");
  expect(rendered.container.querySelector("pre")).toBeNull();
  vi.unstubAllGlobals();
});

/** Types *text* one character at a time, as a keyboard does: each keystroke is an input event with the text so far. */
function typeKeys(input: HTMLInputElement, text: string) {
  typeInto(input, "");
  for (let length = 1; length <= text.length; length++) typeInto(input, text.slice(0, length));
}

test("Carve amount typed past 100 keystroke by keystroke keeps the stored amount and runs nothing on leave", () => {
  const onThresholdCommit = vi.fn(), onChange = vi.fn();
  rendered = renderForTest(<CarvingStep {...carvingProps({ form: formFor("daylight"), isWeightedMode: true, onThresholdCommit, onChange })} />);
  const field = rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!;
  typeKeys(field, "150");
  expect(rendered.container.querySelector(".threshold-control .setting-error")!.textContent).toBe("Use 0 to 100.");
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(onThresholdCommit).not.toHaveBeenCalled();
  expect(field.value).toBe("70");
  expect(onChange).not.toHaveBeenCalled();
});

test("while the analysis is out of date, only a carving setting with an error stays editable, and its change runs nothing", () => {
  const onCarvingSettingCommit = vi.fn(), onChange = vi.fn();
  let form = formFor("daylight");
  form = formReducer(form, { type: "save_rejected", reply: { field_errors: [{ field: "max_slope_deg", message: "Input should be greater than 0" }], grid_plan: null } });
  rendered = renderForTest(<CarvingStep {...carvingProps({ form, isWeightedMode: true, analysisOutOfDate: true, onCarvingSettingCommit, onChange })} />);
  const slope = rendered.container.querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="number"]')!;
  expect(slope.disabled).toBe(false);
  expect(rendered.container.querySelector<HTMLInputElement>('[data-setting="carve_above"] input')!.disabled).toBe(true);
  expect(rendered.container.querySelector<HTMLInputElement>(".threshold-control input[type=number]")!.disabled).toBe(true);
  // A slider is locked with its number field, and stays editable with it when it holds the error.
  expect(rendered.container.querySelector<HTMLInputElement>('[data-setting="score_smoothing"] input[type="range"]')!.disabled).toBe(true);
  expect(rendered.container.querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="range"]')!.disabled).toBe(false);
  typeKeys(slope, "45");
  act(() => slope.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(onChange).toHaveBeenLastCalledWith({ max_slope_deg: 45 });
  expect(onCarvingSettingCommit).not.toHaveBeenCalled();
});

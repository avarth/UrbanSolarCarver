// The one-line summary and the state mark of each step row (UX 4.1), from what the app knows of the open project.
import { messages } from "../messages";
import { formatNumber, formatPercent, formattedNumber, withUnit } from "./format_numbers";
import modeTiles from "./mode_tiles.json";

/** The steps (spec 7.1): the site's inputs, the shared settings, the criteria, then the envelope and massing and the downloads. */
export type StepName = "inputs" | "site_and_grid" | "criteria" | "envelope_and_massing" | "export";
export type PipelineStage = "preprocessing" | "thresholding" | "exporting" | "massing";
export type StageState = "current" | "out_of_date" | "missing";
export type StepMark = "done" | "error" | "none";

/** The steps in the order of the accordion. */
export const STEP_NAMES: readonly StepName[] = ["inputs", "site_and_grid", "criteria", "envelope_and_massing", "export"];

export interface ModeTile {
  engine_name: string;
  plain_name: string;
  one_line: string;
  tooltip: string;
  needs: string;
  /** What a criterion of the mode may protect, under the drop box of its test surfaces while it has none (7.2: hints only). */
  protects_hint: string;
  symbol: string;
}

export const MODE_TILES: readonly ModeTile[] = modeTiles;

export function plainModeName(engineName: string): string {
  return MODE_TILES.find((tile) => tile.engine_name === engineName)?.plain_name ?? engineName;
}

export interface AnalysisPeriod {
  startMonth: number;
  startDay: number;
  startHour: number;
  endMonth: number;
  endDay: number;
  endHour: number;
}

export interface ProjectViewState {
  maxVolumeFiles: number;
  hasWeatherFile: boolean;
  /** The files of the optional existing surroundings and terrain; absent: none. */
  contextFiles?: number;
  terrainFiles?: number;
  /** The mode of the criterion. */
  mode: string;
  northDegrees: number;
  voxelSize: number;
  /** Settings whose last save was refused, by the step that shows them (messages that name no setting count where they are shown). */
  settingsToFix: Partial<Record<StepName, number>>;
  stages: Record<PipelineStage, StageState>;
  /** From the run summary of the last carving; null before one. */
  keptPercent: number | null;
  totalFloorArea: number | null;
  storeys: number | null;
}

function inputsSummary(state: ProjectViewState): string {
  if (state.maxVolumeFiles === 0) return messages.maxVolumeMissing;
  return messages.inputsSummary(state.maxVolumeFiles, state.hasWeatherFile, state.contextFiles ?? 0, (state.terrainFiles ?? 0) > 0);
}

const settingsToFixIn = (step: StepName, state: ProjectViewState) => state.settingsToFix[step] ?? 0;

/** "North 10°, 0.5 m voxels" */
function siteAndGridSummary(state: ProjectViewState): string {
  return messages.siteAndGridSummary(formattedNumber(state.northDegrees), messages.voxelsOfSize(withUnit(formattedNumber(state.voxelSize), "m")));
}

function carvingSummary(state: ProjectViewState): string {
  const carving = state.stages.thresholding;
  if (carving === "out_of_date") return messages.outOfDateSummary;     // with or without the summary of that carving
  if (carving === "missing" || state.keptPercent === null) return messages.notRunYet;
  return messages.keptShare(formatPercent(state.keptPercent));
}

/** One criterion: its mode and its carving, "Solar usefulness, 56 % kept", "Daylight, Out of date". */
function criteriaSummary(state: ProjectViewState): string {
  return messages.criterionSummary(plainModeName(state.mode), carvingSummary(state));
}

/**
 * What exists of the two parts, each built on its own (R2 5): "Envelope built, massing not built"; "Not built yet" or "Out of
 * date" when both are; the floor area and storeys of the massing when both are built and current (UX 4.1).
 */
function envelopeAndMassingSummary(state: ProjectViewState): string {
  const { exporting, massing } = state.stages;
  if (exporting === "missing" && massing === "missing") return messages.notBuiltYet;
  if (exporting === "out_of_date" && massing === "out_of_date") return messages.outOfDateSummary;
  if (exporting === "current" && massing === "current" && state.totalFloorArea !== null && state.storeys !== null) {
    return messages.massingSummary(formatNumber(state.totalFloorArea, "m²"), messages.storeyCount(state.storeys));
  }
  return messages.envelopeAndMassingParts(messages.envelopePartStates[exporting], messages.massingPartStates[massing]);
}

/**
 * "Ready" once both parts are built, or the part that is (Export offers each file once its stage exists); "Out of date" while a
 * part that is built is out of date, as its files are then marked.
 */
function exportSummary(state: ProjectViewState): string {
  const { exporting, massing } = state.stages;
  if (exporting === "out_of_date" || massing === "out_of_date") return messages.outOfDateSummary;
  const hasEnvelope = exporting !== "missing", hasMassing = massing !== "missing";
  if (hasEnvelope && hasMassing) return messages.exportReady;
  if (hasEnvelope) return messages.envelopeReady;
  return hasMassing ? messages.massingReady : messages.notBuiltYet;
}

/** The summary of a step's row: "1 volume, weather", "North 0°, 1 m voxels", "Solar time-based, 61 % kept" ... */
export function stepSummary(step: StepName, state: ProjectViewState): string {
  if (settingsToFixIn(step, state) > 0) return messages.settingsToFix(settingsToFixIn(step, state));
  switch (step) {
    case "inputs":
      return inputsSummary(state);
    case "site_and_grid":
      return siteAndGridSummary(state);
    case "criteria":
      return criteriaSummary(state);
    case "envelope_and_massing":
      return envelopeAndMassingSummary(state);
    case "export":
      return exportSummary(state);
  }
}

/** A tick when the step is done, "!" when it has a setting to fix, an empty ring otherwise. */
export function stepMark(step: StepName, state: ProjectViewState): StepMark {
  const { preprocessing, thresholding, exporting, massing } = state.stages;
  if (settingsToFixIn(step, state) > 0) return "error";
  switch (step) {
    case "inputs":
      return state.maxVolumeFiles > 0 ? "done" : "none";
    case "site_and_grid":
      return preprocessing === "current" ? "done" : "none";
    case "criteria":
      return thresholding === "current" ? "done" : "none";
    case "envelope_and_massing":
    case "export":
      return exporting === "current" && massing === "current" ? "done" : "none";
  }
}

/**
 * Why an open step cannot be used yet, or null when it can (UX 4.1: steps are never locked, they explain). Criteria always can:
 * it holds the mode and Run analysis, and says itself that the carving waits for an analysis.
 */
export function stepNotUsableYet(step: StepName, state: ProjectViewState): string | null {
  switch (step) {
    case "envelope_and_massing":
      return state.stages.thresholding === "missing" ? messages.envelopeNeedsAnalysis : null;
    case "export":
      return state.stages.exporting === "missing" && state.stages.massing === "missing" ? messages.exportNeedsBuild : null;
    default:
      return null;
  }
}

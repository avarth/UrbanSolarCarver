// The one-line summary and the state mark of each step row (UX 4.1), from what the app knows of the open project.
import { messages } from "../messages";
import type { StepName as SettingsFormStepName } from "../settings_form/presentation";
import { formatNumber, formatPercent, formattedNumber, withUnit } from "./format_numbers";
import modeTiles from "./mode_tiles.json";

export type StepName = "inputs" | "mode" | SettingsFormStepName;
export type PipelineStage = "preprocessing" | "thresholding" | "exporting" | "massing";
export type StageState = "current" | "out_of_date" | "missing";
export type StepMark = "done" | "error" | "none";

/** The steps in the order of the accordion. */
export const STEP_NAMES: readonly StepName[] = ["inputs", "mode", "settings", "carving", "envelope_and_massing", "export"];

export interface ModeTile {
  engine_name: string;
  plain_name: string;
  one_line: string;
  tooltip: string;
  needs: string;
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
  testSurfaceFiles: number;
  hasWeatherFile: boolean;
  mode: string;
  /** The period the analysis reads; null for a mode that reads none, or while a part of it is unset. */
  analysisPeriod: AnalysisPeriod | null;
  voxelSize: number;
  /** Settings whose last save was refused, by the step that shows them (messages that name no setting count in Settings). */
  settingsToFix: Partial<Record<StepName, number>>;
  stages: Record<PipelineStage, StageState>;
  /** From the run summary of the last carving; null before one. */
  keptPercent: number | null;
  totalFloorArea: number | null;
  storeys: number | null;
}

function inputsSummary(state: ProjectViewState): string {
  const hasMaxVolume = state.maxVolumeFiles > 0, hasTestSurfaces = state.testSurfaceFiles > 0;
  if (!hasMaxVolume && !hasTestSurfaces) return messages.maxVolumeAndTestSurfacesMissing;
  if (!hasMaxVolume) return messages.maxVolumeMissing;
  if (!hasTestSurfaces) return messages.testSurfacesMissing;
  return messages.inputsSummary(state.maxVolumeFiles, state.testSurfaceFiles, state.hasWeatherFile);
}

const settingsToFixIn = (step: StepName, state: ProjectViewState) => state.settingsToFix[step] ?? 0;

function settingsSummary(state: ProjectViewState): string {
  if (settingsToFixIn("settings", state) > 0) return messages.settingsToFix(settingsToFixIn("settings", state));
  const voxels = messages.voxelsOfSize(withUnit(formattedNumber(state.voxelSize), "m"));
  const period = state.analysisPeriod;
  if (period === null) return voxels;
  return messages.settingsSummary(
    messages.periodSummary(period.startMonth, period.startDay, period.startHour, period.endMonth, period.endDay, period.endHour), voxels);
}

function carvingSummary(state: ProjectViewState): string {
  const carving = state.stages.thresholding;
  if (carving === "out_of_date") return messages.outOfDateSummary;     // with or without the summary of that carving
  if (carving === "missing" || state.keptPercent === null) return messages.notRunYet;
  return messages.keptShare(formatPercent(state.keptPercent));
}

function envelopeAndMassingSummary(state: ProjectViewState): string {
  const { exporting, massing } = state.stages;
  if (exporting === "out_of_date" || massing === "out_of_date") return messages.outOfDateSummary;
  if (massing === "current" && state.totalFloorArea !== null && state.storeys !== null) {
    return messages.massingSummary(formatNumber(state.totalFloorArea, "m²"), messages.storeyCount(state.storeys));
  }
  return messages.notBuiltYet;
}

/** The summary of a step's row: "1 volume, 2 test surfaces, weather", "Solar time-based", "21 Dec, 10 to 14 h; 1 m voxels" ... */
export function stepSummary(step: StepName, state: ProjectViewState): string {
  if (step !== "settings" && settingsToFixIn(step, state) > 0) return messages.settingsToFix(settingsToFixIn(step, state));
  switch (step) {
    case "inputs":
      return inputsSummary(state);
    case "mode":
      return plainModeName(state.mode);
    case "settings":
      return settingsSummary(state);
    case "carving":
      return carvingSummary(state);
    case "envelope_and_massing":
      return envelopeAndMassingSummary(state);
    case "export":
      return state.stages.exporting !== "missing" && state.stages.massing !== "missing" ? messages.exportReady : messages.buildEnvelopeFirst;
  }
}

/** A tick when the step is done, "!" when it has a setting to fix, an empty ring otherwise. */
export function stepMark(step: StepName, state: ProjectViewState): StepMark {
  const { preprocessing, thresholding, exporting, massing } = state.stages;
  if (settingsToFixIn(step, state) > 0) return "error";
  switch (step) {
    case "inputs":
      return state.maxVolumeFiles > 0 && state.testSurfaceFiles > 0 ? "done" : "none";
    case "mode":
      return "done";      // a project always has a mode, a new one Solar time-based
    case "settings":
      return preprocessing === "current" ? "done" : "none";
    case "carving":
      return thresholding === "current" ? "done" : "none";
    case "envelope_and_massing":
    case "export":
      return exporting === "current" && massing === "current" ? "done" : "none";
  }
}

/** Why an open step cannot be used yet, or null when it can (UX 4.1: steps are never locked, they explain). */
export function stepNotUsableYet(step: StepName, state: ProjectViewState): string | null {
  switch (step) {
    case "carving":
      return state.stages.thresholding === "missing" ? messages.carvingNeedsAnalysis : null;
    case "envelope_and_massing":
      return state.stages.thresholding === "missing" ? messages.envelopeNeedsAnalysis : null;
    case "export":
      return state.stages.exporting === "missing" || state.stages.massing === "missing" ? messages.exportNeedsBuild : null;
    default:
      return null;
  }
}

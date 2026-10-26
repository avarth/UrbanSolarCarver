// The interface texts of UX spec sections 4, 5, 6.1, 7, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here. A unit follows its number after a no-break space (\u00a0), as in format_numbers.ts.
import { formattedNumber, groupedDigits, withUnit } from "./steps/format_numbers";

const MONTH_ABBREVIATIONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// What the sky patch weights of each weighted mode measure, for the sky dome legend (UX 8.2), with their unit: the energy from a
// patch per square metre facing it (Solar energy, Solar usefulness), or the patch's share of its sky (Daylight, Night cooling).
const SKY_PATCH_WEIGHT_OF_MODE: Record<string, string> = {
  irradiance: "Solar energy from each sky patch, kWh/m²",
  benefit: "Useful solar heat from each sky patch, kWh/m²",
  daylight: "Share of the overcast sky in each patch",
  radiative_cooling: "Share of the night sky cooling in each patch",
};

// What the score of a voxel measures in each mode, for the histogram axis and the kept voxels legend (UX 5.5, 8.1). The unit is
// the engine's (mode_registry score_unit, in the score points): m²·h, kWh, or m² of fully hidden sky.
const SCORE_OF_MODE: Record<string, string> = {
  "time-based": "Shade a voxel casts",
  irradiance: "Solar energy a voxel blocks",
  benefit: "Useful solar heat a voxel blocks",
  daylight: "Overcast sky a voxel hides",
  radiative_cooling: "Night sky cooling a voxel hides",
};

/** The dates of a period: "21 Dec", "21 to 22 Dec" (one month written once), "1 Oct to 30 Apr", "22 Dec to 21 Dec". */
function periodDatesInWords(startMonth: number, startDay: number, endMonth: number, endDay: number): string {
  const endDate = `${endDay} ${MONTH_ABBREVIATIONS[endMonth - 1]}`;
  if (startMonth === endMonth && startDay === endDay) return endDate;
  return startMonth === endMonth && startDay < endDay ? `${startDay} to ${endDate}` : `${startDay} ${MONTH_ABBREVIATIONS[startMonth - 1]} to ${endDate}`;
}

/** "12-21" (month and day) as "21 Dec". */
export function dayAndMonth(monthDay: string): string {
  const [month, day] = monthDay.split("-").map(Number);
  return `${day} ${MONTH_ABBREVIATIONS[month - 1]}`;
}

/** A moment in this computer's time zone as "17 Oct 2026, 09:05". */
export function dateAndTime(moment: Date): string {
  const twoDigits = (value: number) => String(value).padStart(2, "0");
  return `${moment.getDate()} ${MONTH_ABBREVIATIONS[moment.getMonth()]} ${moment.getFullYear()}, ${twoDigits(moment.getHours())}:${twoDigits(moment.getMinutes())}`;
}

/** ["10", "12", "14"] as "10, 12 and 14". */
export function listedWithAnd(items: string[]): string {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** A text in which a command is shown as code. */
export type MessagePart = string | { code: string };

export function plainText(parts: MessagePart[]): string {
  return parts.map((part) => (typeof part === "string" ? part : part.code)).join("");
}

export const messages = {
  // Top bar and start screen (4, 5.1)
  productName: "UrbanSolarCarver",
  versionLine: (version: string) => `Version ${version}`,
  projectsLink: "Projects",
  newProject: "New project",
  projectNameLabel: "Project name",
  projectNameHint: "Up to 64 letters, numbers, spaces, hyphens or underscores.",
  createProject: "Create project",
  openProject: "Open a project",
  noProjectsYet: "No projects yet.",
  tryExample: "Try an example",

  // The projects folder and the menu of a project (R2 7.1, 7.2). The service's own reasons for a refusal are shown as it gives them.
  projectsFolderIs: "Projects folder: ",
  changeFolder: "Change folder",
  folderPickerOpen: "Choose a folder in the window that opened on this computer. It may be behind the browser.",
  folderPickerUnavailableWay: [" To use another folder, start USC with ", { code: "usc ui --projects-folder <folder>" }, "."] as MessagePart[],
  folderGivenOnCommandLine: ["This folder was given with ", { code: "--projects-folder" }, ". To change it here, start ", { code: "usc ui" },
    " without it."] as MessagePart[],
  folderChangesOnceRunEnds: "The projects folder can be changed once the run has ended.",
  projectMenuOf: (projectName: string) => `Actions for ${projectName}`,
  projectMenuSymbol: "⋯",      // the menu button beside a project of the start screen
  projectMenuCaret: "▾",       // after the project name in the top bar
  openProjectFolder: "Open folder",
  renameProject: "Rename",
  deleteProject: "Delete",
  resetProjectToExample: "Reset to the example",
  projectChangesWaitForRun: "A run of this project is in progress. Rename, delete and reset wait until it has ended.",
  cancel: "Cancel",
  openFolderFailedTitle: "The folder could not be opened",
  renameProjectTitle: (projectName: string) => `Rename ${projectName}`,
  newProjectNameLabel: "New name",
  projectNameInvalid: "Use up to 64 letters, numbers, spaces, hyphens or underscores, starting with a letter or number.",
  projectNameIsWindowsDeviceName: (projectName: string) => `Windows does not allow '${projectName}' as a folder name. Choose another name.`,
  deleteProjectTitle: (projectName: string) => `Delete ${projectName}`,
  deleteProjectExplanation: (projectName: string) =>
    `The project ${projectName} and everything in its folder go to the recycle bin or trash, where you can restore them.`,
  projectFolderIs: "Folder: ",
  typeProjectNameToConfirm: (projectName: string) => `Type ${projectName} to confirm`,
  deleteProjectButton: "Delete project",
  resetProjectTitle: (projectName: string) => `Reset ${projectName} to the example`,
  resetProjectExplanation: (projectName: string, exampleTitle: string) =>
    `The inputs, settings and results of ${projectName} are replaced with a fresh copy of the example ${exampleTitle}. ` +
    "The current ones go to the recycle bin or trash. The project keeps its name.",
  resetProjectButton: "Reset project",
  settingsNotSavedSoNotRenamed: "The last change to the settings was not saved, so the project was not renamed. Save the settings again, then rename it.",
  requestDidNotReachEngine: "The request did not reach the USC engine. Check that it is still running, then try again.",
  requestRefusedWithoutReason: (status: number) => `The USC engine refused the request and gave no reason (status ${status}). Try again.`,

  // The steps and their summary lines (4.1)
  stepTitles: {
    inputs: "Inputs",
    site_and_grid: "Site and grid",
    criteria: "Criteria",
    envelope_and_massing: "Envelope and massing",
    export: "Export",
  },
  // The site's files (the test surfaces belong to the criteria): "1 volume, 2 surroundings files, terrain, weather".
  inputsSummary: (volumeCount: number, hasWeatherFile: boolean, contextCount = 0, hasTerrain = false) =>
    `${volumeCount} ${volumeCount === 1 ? "volume" : "volumes"}` +
    (contextCount > 0 ? `, ${contextCount} ${contextCount === 1 ? "surroundings file" : "surroundings files"}` : "") +
    (hasTerrain ? ", terrain" : "") +
    (hasWeatherFile === true ? ", weather" : ""),
  maxVolumeMissing: "Maximum volume missing",
  // Site and grid: "North 10°, 0.5 m voxels"
  siteAndGridSummary: (northText: string, voxelsText: string) => `North ${northText}°, ${voxelsText}`,
  // Criteria with one criterion: its mode and its carving, "Solar usefulness, 56 % kept"
  criterionSummary: (modeName: string, carvingText: string) => `${modeName}, ${carvingText}`,
  // The analysis period in words (R2 4.3), in the step summary and in the period's tooltip: "21 Dec, 10 to 14 h", "21 to 22 Dec,
  // 22 to 2 h" (one month written once), "1 Oct to 30 Apr, 0 to 23 h", "22 Dec to 21 Dec, 10 to 14 h" (across the new year within
  // one month). One date with hours across midnight is what the engine runs: every night of the year.
  periodSummary: (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number) => {
    const hours = `${startHour} to ${endHour}\u00a0h`;
    const oneDate = startMonth === endMonth && startDay === endDay;
    if (oneDate && startHour > endHour) return `Every day, ${hours}`;
    return `${periodDatesInWords(startMonth, startDay, endMonth, endDay)}, ${hours}`;
  },
  voxelsOfSize: (voxelSizeText: string) => `${voxelSizeText} voxels`,
  keptShare: (percentText: string) => `${percentText} kept`,
  notRunYet: "Not run yet",
  outOfDateSummary: "Out of date",
  // A criterion's card (7.2): the result line of one that is current, else its status
  criterionResultOfScore: (percentText: string, volumeText: string) => `${percentText} of the score carved, ${volumeText} removed`,
  criterionResultOfVolume: (percentText: string, volumeText: string) => `${percentText} of the volume carved, ${volumeText} removed`,
  criterionScoreCarved: (percentText: string) => `${percentText} of the score carved`,
  criterionVolumeCarved: (percentText: string) => `${percentText} of the volume carved`,
  // Under the cards of two or more criteria (7.2): what the chain kept of the maximum volume; the volume alone without the share.
  chainKept: (volumeText: string, percentText: string) => `Kept ${volumeText}, ${percentText} of the maximum volume`,
  chainKeptVolume: (volumeText: string) => `Kept ${volumeText}`,
  criterionOutOfDate: "Out of date",
  criterionUpdatesFrom: (criterionName: string) => `Updates from ${criterionName}`,
  criterionRunning: "Running",
  criterionOff: "Off",
  allCriteriaOff: "All off",
  criterionNeedsTestSurfaces: "Add test surfaces",
  criterionNotRunYet: "Not run yet",
  // Criteria with several criteria: the ones that are on in order, each with the share it kept, "Daylight on windows 70 %, then
  // Solar usefulness 80 %"
  criterionKeptInChain: (criterionName: string, percentText: string) => `${criterionName} ${percentText}`,
  criteriaThen: (earlierText: string, laterText: string) => `${earlierText}, then ${laterText}`,
  // The cards of the criteria (7.2), their menu and dialogs
  criteriaListLabel: "Criteria in carving order",
  addCriterion: "Add criterion",
  newCriterionModeTitle: "Mode of the new criterion",
  addingCriterion: "Adding the criterion",
  // The panel of a card just selected, until its settings are in
  loadingCriterion: (criterionName: string) => `Loading the settings of ${criterionName}`,
  // A run refused because a criterion that is on protects nothing: said in that criterion's panel (7.3)
  addTestSurfacesTo: (criterionName: string) => `Add test surfaces to ${criterionName}.`,
  // A run's stage of one criterion, with several criteria (7.3): "Daylight on windows: Carving"
  criterionStage: (criterionName: string, stageName: string) => `${criterionName}: ${stageName}`,
  moveCriterion: (criterionName: string) => `Move ${criterionName}`,
  moveCriterionHint: "Drag to reorder, or press the up and down arrow keys",
  criterionSwitchLabel: (criterionName: string) => `Use ${criterionName}`,
  criterionMenuOf: (criterionName: string) => `Actions for ${criterionName}`,
  renameCriterion: "Rename",
  duplicateCriterion: "Duplicate",
  deleteCriterion: "Delete",
  onlyCriterionStays: "A project needs at least one criterion.",
  renameCriterionTitle: (criterionName: string) => `Rename ${criterionName}`,
  newCriterionNameLabel: "New name",
  criterionNeedsName: "A criterion needs a name.",      // the service's words for an empty name
  deleteCriterionTitle: "Delete criterion",
  deleteCriterionExplanation: (criterionName: string) =>
    `Delete ${criterionName}? Its settings and results go; test surface files no other criterion uses go to the recycle bin.`,
  massingSummary: (floorAreaText: string, storeysText: string) => `${floorAreaText}, ${storeysText}`,
  notBuiltYet: "Not built yet",
  // What exists of the two parts of Envelope and massing (R2 5): "Envelope built, massing not built".
  envelopePartStates: { current: "Envelope built", out_of_date: "Envelope out of date", missing: "Envelope not built" },
  massingPartStates: { current: "massing built", out_of_date: "massing out of date", missing: "massing not built" },
  envelopeAndMassingParts: (envelopeText: string, massingText: string) => `${envelopeText}, ${massingText}`,
  exportReady: "Ready",
  envelopeReady: "Envelope ready",
  massingReady: "Massing ready",
  carvingNeedsAnalysis: "Run the analysis to see the carving",
  envelopeNeedsAnalysis: "Run the analysis in Criteria before building the envelope and massing",
  exportNeedsBuild: "Build the envelope or the massing to export them",

  // Inputs (5.2)
  maxVolumeTitle: "Maximum volume",
  testSurfacesTitle: "Test surfaces",
  contextTitle: "Existing surroundings (optional)",
  terrainTitle: "Terrain (optional)",
  weatherFileTitle: "Weather file (optional)",
  weatherFileNeededTitle: "Weather file",
  requiredInput: "Required",
  weatherFileExtension: ".epw",
  maxVolumeHint: "The largest building you would allow, as one or more closed meshes.",
  testSurfacesHint: "The surfaces whose sun or sky the carving protects, such as neighbouring facades.",
  contextHint: "Buildings and large trees that stay. They block sun and sky, and nothing is built in their place.",
  terrainHint: "The ground. It blocks sun and sky; the site stays buildable above it.",
  weatherNeededFor: (modeNames: string) => `Needed for ${modeNames}.`,
  orDropThemHere: "or drop them here",
  replaceFile: "Replace",
  removeFile: (fileName: string) => `Remove ${fileName}`,
  triangleCount: (count: number) => `${groupedDigits(count)} ${count === 1 ? "triangle" : "triangles"}`,
  fileProblem: (fileName: string, reason: string) => `${fileName}: ${reason}`,
  // A file the service accepted (the engine reads it) that the 3D view cannot draw, said in its box as fileProblem(name, reason)
  meshCannotBeDrawn: "The 3D view cannot read this file, so it is not drawn. Runs still use it.",
  meshTypeCannotBeShown: (extension: string) => `Meshes of type '${extension}' cannot be shown.`,
  // A criterion's test surfaces (7.2): the add button of its drop box, titled testSurfacesTitle; its hint for the mode is in
  // steps/mode_tiles.json (protects_hint).
  addTestSurfaces: "Add test surfaces",
  // Under the box with several criteria: the stored files the other criteria use, each with a button that adds it to this one.
  useFileOfOtherCriterion: "Use a file from another criterion",
  useFile: "Use",
  useFileNamed: (fileName: string) => `Use ${fileName}`,
  inputsSizeTitle: "Size of all inputs together",
  inputsSize: (sideX: string, sideY: string, sideZ: string) => `${sideX} × ${sideY} × ${sideZ}\u00a0m`,

  // Mode (5.3). The names, lines and tooltips of the six modes are in steps/mode_tiles.json.
  modeGroupLabel: "Mode",
  modeFillsStartingValues: "Choosing a mode fills its starting values in the settings below.",
  // After a mode change that set values the user had set back to the new mode's own (the new mode refuses them).
  valuesResetForMode: (listedLabels: string, count: number, modeName: string) => (count === 1
    ? `${listedLabels} is back to its default: ${modeName} cannot use the value you had set.`
    : `${listedLabels} are back to their defaults: ${modeName} cannot use the values you had set.`),
  engineName: (engineName: string): MessagePart[] => ["Engine name: ", { code: String(engineName) }],
  // A tile's description for a screen reader: the text of its tooltip after the name, which the tile itself says.
  modeTileDescription: (oneLine: string, description: string, needs: string, engineName: string) =>
    `${oneLine}. ${description} ${needs} Engine name: ${engineName}`,
  // Under the tiles while Night cooling is the chosen mode (R2 3: the tile itself shows the symbol and the name only).
  radiativeCoolingIsExperimental: (plainName: string) => `${plainName} is experimental and assumes horizontal test surfaces.`,

  // Run buttons (5.4, 6.4). The reasons a run button waits, and those a carving change or a build waits for, fill the same slots:
  // a reason of one sentence has no final period, one of two sentences ends each with one.
  runAnalysis: "Run analysis",
  runInProgress: "A run is in progress",
  addMaxVolumeToRun: "Add a maximum volume to run the analysis",
  addTestSurfacesToRun: "Add test surfaces to run the analysis",
  addMaxVolumeAndTestSurfacesToRun: "Add a maximum volume and test surfaces to run the analysis",
  // Another criterion that is on protects nothing (7.2: the run refuses to start until every one protects something)
  addTestSurfacesOfCriterionToRun: (criterionName: string) => `Add test surfaces to ${criterionName} to run the analysis`,
  // Every criterion is off (the service's words for the refusal)
  turnOnCriterionToRun: "Turn on a criterion to run",
  fixSettingsToRun: "Fix the settings above to run the analysis",
  fixSettingsInStepToRun: (stepTitle: string) => `Fix the settings in ${stepTitle} to run the analysis`,

  // Warm-up and device status (5.1, 6.1, 11)
  gpuPreparing: "Preparing the GPU",
  gpuWarmUpHint: "You can open a project and add files now. The run buttons wait until the GPU is ready.",
  gpuReady: "GPU ready",
  gpuReadyWithDevice: (deviceName: string) => `GPU ready: ${deviceName}`,
  cpuMode: "CPU mode",
  gpuNotAvailable: "GPU not available",
  noCudaGpuFound: "No CUDA-enabled GPU found. USC runs on the CPU, which is slower.",
  cpuModeChosenAtLaunch: "CPU mode, chosen at launch.",      // usc ui --device cpu on a computer that has a CUDA device
  runButtonWaitsForGpu: "Waiting for the GPU to be ready",

  // Empty, error and warning states (11)
  noInputsYet: "Add a maximum volume to start",
  addFiles: "Add files",
  orTryAnExample: "or try an example",
  weatherFileNeeded: "Add a weather file to run this mode",
  // A criterion that is on, not the one shown, has a mode that needs a weather file (Site and grid names the shown one too)
  weatherFileNeededFor: (criterionName: string) => `Add a weather file to run ${criterionName}`,
  fixSettingToRun: (settingLabel: string) => `Fix the ${String(settingLabel).toLowerCase()} to run the analysis`,
  fixSettingInStepToRun: (settingLabel: string, stepTitle: string) => `Fix the ${String(settingLabel).toLowerCase()} in ${stepTitle} to run the analysis`,
  settingsToFix: (count: number) => `${count} ${count === 1 ? "setting" : "settings"} to fix`,
  gridOverBudget: (voxelsPerSide: number, totalVoxels: number, budgetVoxels: number, smallestVoxelSize: number) => ({
    description: `This grid would have ${groupedDigits(voxelsPerSide)} voxels per side, ${groupedDigits(totalVoxels)} in total. ` +
      `The analysis can handle up to ${groupedDigits(budgetVoxels)}.`,
    advice: `Use ${smallestVoxelSize}\u00a0m or more.`,   // shown in bold
  }),
  details: "Details",
  resultsOutOfDate: "Results are out of date; run the analysis again",
  runCancelled: "Cancelled.",
  engineStopped: ["The USC engine stopped. Start it again with ", { code: "usc ui" }, ", then reload this page."] as MessagePart[],
  accessLost: ["This page has lost its access to the engine. Open it again from the link that ", { code: "usc ui" }, " printed."] as MessagePart[],
  resultsUpToDate: "Results are up to date",
  settingsNotSaved: "The last change to the settings was not saved.",
  runOfProjectElsewhere: "A run of this project is in progress, perhaps in another tab.",
  saveAgainAfterThatRun: "Save again once it has ended.",
  saveAgainOrRun: "Save again, or start a run: it saves the settings first.",
  saveAgain: "Save again",
  modelMoreThan10Km: "This model is more than 10\u00a0km across. Is it in meters?",
  modelLessThan1M: "This model is less than 1\u00a0m across. Is it in meters?",

  // Units written after the numbers of the run steps (UX 5.5 to 5.7, 9)
  units: { shadeHours: "m²·h", percent: "%", squareMetres: "m²", cubicMetres: "m³", seconds: "s" },

  // Runs and their progress (6.2 to 6.4, 11)
  runProgress: "Run progress",
  // The stamp at the top of the 3D view while a dimmed result is shown (UX 6.3).
  viewerStampOutOfDate: "Out of date",
  viewerStampOutOfDateNote: "The dimmed results do not match the settings.",
  viewerStampUpdating: "Updating",
  viewerStampUpdatingNote: "The dimmed results are being replaced.",
  stageStates: { waiting: "waiting", running: "running", done: "done" },
  rayBatches: (done: number, total: number) => `${groupedDigits(done)} of ${groupedDigits(total)} batches`,
  elapsedTime: (secondsText: string) => `Elapsed ${secondsText}`,
  cancelRun: "Cancel",
  runFailed: "The run stopped on an error.",
  errorType: (errorType: string) => `Error type: ${errorType}`,
  goToSetting: (settingLabel: string) => `Go to ${String(settingLabel).toLowerCase()}`,
  // A run refused for the settings of a criterion other than the one shown (several criteria)
  runFailedForCriterion: (criterionName: string) => `The run stopped on an error in the settings of ${criterionName}.`,
  goToSettingOf: (settingLabel: string, criterionName: string) => `Go to ${String(settingLabel).toLowerCase()} of ${criterionName}`,
  runConnectionLost: "The connection to the engine was lost during the run.",
  runReportUnreadable: "The run report could not be read. Build the envelope or the massing again to write it.",
  warningsTitle: "Warnings",
  warningCount: (count: number) => `${count} ${count === 1 ? "warning" : "warnings"}`,
  summaryWithWarnings: (summary: string, warningsText: string) => `${summary}, ${warningsText}`,

  // Carving (5.5)
  angleRuleHasNoThreshold: "The angle rule has no threshold: everything above the planes is removed. Change the angle above.",
  analysisOutOfDate: "Settings changed since the analysis. Run the analysis again to update the carving.",
  sliderLowestEnd: "0",
  sliderHighestScore: (highestText: string) => `${highestText}, the highest score`,
  updateWhenThresholdChanges: "Update when I change the threshold",
  updateCarving: "Update carving",
  buildEnvelopeAndMassing: "Build envelope and massing",
  // Why the build buttons wait while Carving is locked: a build would run the analysis first (M10). With several criteria they name
  // the criterion whose analysis is missing or out of date instead (carvingWaitsForAnalysisOf, addTestSurfacesFirst).
  buildWaitsForAnalysis: "Settings changed since the analysis. Run the analysis again before building.",
  // The same for the build pinned in Criteria, which shows before the first analysis and while a carving is not current.
  buildWaitsForFirstAnalysis: "Run the analysis before building",
  buildWaitsForCarving: "Update the carving before building",
  // Why a carving change of the selected criterion runs nothing while another criterion's analysis is out of date: the carving
  // run would trace that criterion first, which only Run analysis starts (M10). The same while that criterion protects nothing.
  carvingWaitsForAnalysisOf: (criterionName: string) => `Run the analysis for ${criterionName} first`,
  addTestSurfacesFirst: (criterionName: string) => `Add test surfaces to ${criterionName} first`,
  // The panel of a criterion that is off, in place of its carving rule
  criterionOffNote: "Off: the chain skips this criterion",
  // The folded sections of a criterion's panel, each saying in one line what it holds while it is closed
  panelSectionTitles: { test_surfaces: "Test surfaces", mode: "Mode", settings: "Settings", carving: "Carving rule" },
  noTestSurfacesYet: "None yet",
  twoFileNames: (firstName: string, secondName: string) => `${firstName}, ${secondName}`,
  fileCount: (count: number) => `${count} ${count === 1 ? "file" : "files"}`,
  startingValues: "Starting values",
  settingsChanged: (count: number) => `${count} ${count === 1 ? "setting" : "settings"} changed`,
  carveAmountSummary: (percentText: string) => `Carve ${percentText}`,
  cutoffSummary: (cutoffText: string) => `Cutoff ${cutoffText}`,
  angleRuleSummary: "Everything above the planes",
  histogramTitle: "Scores of the voxels",
  histogramScaleLabel: "Scale of the counts",
  logScale: "Log",
  linearScale: "Linear",
  // The histogram axis and the kept voxels legend: "Solar energy a voxel blocks, kWh".
  scoreOfModeWithUnit: (mode: string | null, unit: string) => {
    const score = mode !== null && Object.hasOwn(SCORE_OF_MODE, mode) ? SCORE_OF_MODE[mode] : "Score of a voxel";
    return unit ? `${score}, ${unit}` : score;
  },
  histogramKept: "Kept",
  histogramCarved: "Carved",
  histogramBinRange: (lowerText: string, upperText: string, unit: string) => `${lowerText} to ${upperText}${unit ? ` ${unit}` : ""}`,
  histogramBinCounts: (kept: number, carved: number) => `${groupedDigits(kept)} kept, ${groupedDigits(carved)} carved`,
  histogramDescription: (voxelCount: number, cutoffText: string) =>
    `Histogram of the scores of ${groupedDigits(voxelCount)} voxels, cutoff at ${cutoffText}. Use the arrow keys to read each bar.`,
  // The handle of the cutoff line on the histogram (a slider for the keyboard), and what it says of its value.
  cutoffHandle: "Cutoff",
  cutoffHandleValue: (cutoffText: string, keptText: string) => `${cutoffText}, keeps about ${keptText} of the volume`,
  // Under the histogram while the line shows a cutoff not run yet: dragged, or set in the form since the carving shown.
  cutoffPreview: (cutoffText: string, keptText: string) =>
    `Preview: a cut at ${cutoffText} keeps about ${keptText} of the volume, before the slope limit.`,
  cutoffPreviewWithCarveAmount: (carveAmountText: string, cutoffText: string, keptText: string) =>
    `Preview: carve amount ${carveAmountText}, a cut at ${cutoffText}, keeps about ${keptText} of the volume, before the slope limit.`,
  slopeLimitNote: (count: number) => `The slope limit removed ${groupedDigits(count)} voxels below the cutoff.`,
  volumeKept: "Volume kept",
  volumeCarved: "Volume carved",
  keptVolume: "Kept volume",
  obstructionRemoved: "Obstruction removed",
  lastAnalysisTook: "Last analysis took",

  // Envelope and massing (5.6; R2 5: two parts, each built on its own)
  buildEnvelope: "Build envelope",
  buildMassing: "Build massing",
  grossFloorArea: "Gross floor area",
  storeys: "Storeys",
  envelopeVolume: "Envelope volume",
  envelopeVolumeHelp: "Counted on the kept voxels the envelope mesh was built from, after small pieces were dropped, not on the smoothed surface.",
  floorAreaPerStorey: "Floor area per storey",
  storeyColumns: { storey: "Storey", bottom: "Bottom, m", top: "Top, m", area: "Area, m²" },
  storeyRowLabel: (storeyNumber: number) => (storeyNumber === 1 ? "1, ground" : String(storeyNumber)),
  totalRow: "Total",
  // Under a part built from a carving or from settings of its own that changed since (R2 5).
  outOfDateForSettings: "Out of date for the current settings",
  openRunReport: "Open the run report",
  runReportTitle: "Run report",
  closePanel: "Close",

  // Export (5.7)
  envelopeMeshDownload: (formatName: string) => `Carved envelope (${formatName})`,
  // Beside the envelope file when the format chosen since was stored without a build (Carving was locked).
  envelopeBuiltInOtherFormat: (builtFormatName: string, chosenFormatName: string) =>
    `Built as ${builtFormatName}; the next envelope build writes ${chosenFormatName}.`,
  massingMeshDownload: (formatName: string) => `Building massing (${formatName})`,
  // Beside the massing file when the format chosen since was stored without a build (Carving was locked).
  massingBuiltInOtherFormat: (builtFormatName: string, chosenFormatName: string) =>
    `Built as ${builtFormatName}; the next massing build writes ${chosenFormatName}.`,
  massingJsonDownload: "Building massing data (JSON)",
  settingsDownload: "Settings (config.yaml)",
  projectZipDownload: "Whole project (zip)",
  outOfDateFile: "Out of date",

  // Under the maximum volume file once the project has carved further: the plain mode names in the order they carved it, joined by ", then ".
  carvedBy: (modesInOrder: string) => `Carved by ${modesInOrder}. The earlier maximum volumes are kept in the ` +
    "project folder, in inputs/earlier_max_volumes.",

  // Settings form (5.4 to 5.7, 7). The labels, units and help texts of the settings are in settings_form/setting_presentation.json.
  moreSettingsOfGroup: {
    "When": "More sun settings",
    "Mode specific": "More mode settings",
    "Detail": "More detail settings",
    "How much to carve": "More carving settings",
    "Envelope": "More envelope settings",
    "Building massing": "More massing settings",
  },
  // The fold of a group that shows no essential setting where it is drawn (a criterion's Detail: the rays per sky patch only).
  foldedGroupTitles: {
    "Detail": "Detail settings",
  },
  aboutSetting: (settingLabel: string) => `About ${String(settingLabel).toLowerCase()}`,
  configNameAndDefault: (configName: string, defaultText: string): MessagePart[] =>
    ["Config name: ", { code: String(configName) }, `, default ${defaultText}`],
  analysisPeriodConfigNames: "start_month ... end_hour",
  gridSize: (voxelsPerSide: number, totalVoxels: number) => `${groupedDigits(voxelsPerSide)} voxels per side, ${groupedDigits(totalVoxels)} in total`,
  // The grid line while the voxel size shown was refused: the grid is the one of the voxel size last saved.
  gridSizeAtSavedVoxelSize: (voxelSizeText: string, voxelsPerSide: number, totalVoxels: number) =>
    `Grid at the saved voxel size of ${voxelSizeText}: ${groupedDigits(voxelsPerSide)} voxels per side, ${groupedDigits(totalVoxels)} in total`,
  // Under Voxel size when a voxel size below the sample spacing lowered it (R2 4.4).
  // Under Voxel size: the sample spacing the engine uses on the test surfaces, half the voxel size (resolve_grid_step).
  testSurfacesSampledEvery: (sampleSpacing: number) => `Test surfaces sampled every ${withUnit(formattedNumber(sampleSpacing), "m")}`,
  // Errors of the whole config, said under the settings they name (UX 11); the engine's own words are for the YAML.
  dayNotInMonth: (dayName: string, day: number, monthName: string, daysInMonth: number) =>
    `${monthName} has ${daysInMonth} days, so the ${String(dayName).toLowerCase()} cannot be ${day}.`,
  periodIncomplete: (modeName: string) => `${modeName} needs the whole analysis period: every day, month and hour.`,
  settingProblem: (settingLabel: string, message: string) => `${settingLabel}: ${message}`,
  automatic: "automatic",
  // An empty slider, to a screen reader: automatic, and the number the engine uses for it ("automatic, 75 °").
  automaticValue: (valueText: string) => `automatic, ${valueText}`,
  // What an empty setting does in the open mode, in its tooltip (UX 7): the engine's automatic value there.
  emptyMeansInMode: (valueText: string, modeName: string) => `Left empty, it is ${valueText} in ${modeName}.`,
  // A number refused in its field (UX 11): what to use instead. An exclusive bound is not allowed itself ("above 0").
  useNumberInRange: (lower: { value: number; exclusive: boolean } | null, upper: { value: number; exclusive: boolean } | null) => {
    if (lower !== null && upper !== null) {
      if (lower.exclusive) return `Use a number above ${lower.value}${upper.exclusive ? ` and below ${upper.value}` : `, up to ${upper.value}`}.`;
      return upper.exclusive ? `Use ${lower.value} or more, below ${upper.value}.` : `Use ${lower.value} to ${upper.value}.`;
    }
    if (lower !== null) return lower.exclusive ? `Use a number above ${lower.value}.` : `Use ${lower.value} or more.`;
    return upper!.exclusive ? `Use a number below ${upper!.value}.` : `Use ${upper!.value} or less.`;
  },
  useWholeNumber: "Use a whole number.",
  switchedOn: "on",
  switchedOff: "off",
  monthNames: MONTH_NAMES,
  // The six period settings by name, for the engine's messages about them (engine_errors.ts).
  periodFieldNames: {
    start_day: "Start day", start_month: "Start month", start_hour: "Start hour",
    end_day: "End day", end_month: "End month", end_hour: "End hour",
  },
  // The analysis period control (R2 4.3): the month marks of the year strip, its four handles, what they say to a screen reader
  // and what their bubbles show ("21 Dec", "10 h"), the presets, and the notes under the strips.
  monthInitials: MONTH_ABBREVIATIONS.map((abbreviation) => abbreviation[0]),
  periodHandleNames: { start_date: "Start date", end_date: "End date", start_hour: "Start hour", end_hour: "End hour" },
  periodDateSpoken: (month: number, day: number) => `${day} ${MONTH_NAMES[month - 1]}`,
  periodHourSpoken: (hour: number) => `${hour}\u00a0h`,
  periodDateOnBubble: (month: number, day: number) => `${day} ${MONTH_ABBREVIATIONS[month - 1]}`,
  periodPresets: "Presets",
  // The cold period of the weather file (round 2, section 8), a preset of Solar usefulness: the longest run of days whose
  // month-around mean temperature is below the balance temperature minus the dead band.
  coldPeriodPreset: "Cold period from the weather file",
  coldPeriodNeedsWeatherFile: "Add a weather file to find its cold period.",
  coldPeriodFinding: "Finding the cold period of the weather file.",
  coldPeriodFound: (startDay: number, startMonth: number, endDay: number, endMonth: number, baseText: string) =>
    `Cold period of the weather file, where the mean of the month around each day is below ${baseText}: ` +
    `${startDay} ${MONTH_ABBREVIATIONS[startMonth - 1]} to ${endDay} ${MONTH_ABBREVIATIONS[endMonth - 1]}.`,
  coldPeriodNone: (baseText: string) => `No month-long stretch of the weather file has a mean below ${baseText} (balance temperature minus dead band).`,
  coldPeriodFailed: (reason: string) => `The cold period cannot be found. ${reason}`,
  temperatureText: (degrees: number) => `${Number(degrees.toFixed(1))} °C`,
  periodPresetNames: { winter_solstice: "21 December", summer_solstice: "21 June", heating_season: "Heating season, October to April", whole_year: "Whole year" },
  // The heating season preset where the weather file is in the southern hemisphere.
  southernHeatingSeasonPresetName: "Heating season, April to October",
  // The notice of a weather file added or replaced in this session (steps/weather_change_notice.ts), over the criterion's settings in Criteria.
  periodDates: (startMonth: number, startDay: number, endMonth: number, endDay: number) => periodDatesInWords(startMonth, startDay, endMonth, endDay),
  weatherChangeColdPeriod: (location: string | null, coldPeriodDatesText: string, periodDatesText: string) =>
    `The new weather file${location === null ? "" : ` (${location})`} has its cold period from ${coldPeriodDatesText}; ` +
    `the analysis period is ${periodDatesText}.`,
  useColdPeriodButton: "Use the cold period",
  weatherChangeOtherHemisphere: (location: string | null, hemisphere: "northern" | "southern", shiftedPeriodText: string) =>
    `The new weather file${location === null ? "" : ` (${location})`} is in the ${hemisphere} hemisphere: winter there is ${hemisphere === "southern" ? "June to August" : "December to February"}. ` +
    `Shift the analysis period by six months, to ${shiftedPeriodText}?`,
  shiftBySixMonthsButton: "Shift by six months",
  keepAnalysisPeriodButton: "Keep",
  keepAnalysisPeriodName: "Keep the analysis period",
  periodNotSet: "Not set yet",
  // Under the strips, for a period stored as one date with hours across midnight: "Every day, 22 to 2 h: ...".
  periodRunsEveryDay: (periodWords: string) =>
    `${periodWords}: the hours cross midnight on one date, which the engine runs on every day of the year. The next change makes it one night.`,
  oneAngle: "One angle",
  oneAnglePerDirection: "One per direction",
  compassDirections: ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
  angleTowards: (direction: string) => `Plane angle for test surfaces facing ${direction}`,
  sunStepsOption: (stepsPerHour: number) =>
    stepsPerHour === 1 ? "1 per hour" : stepsPerHour === 60 ? "60 per hour (every minute)" : `${stepsPerHour} per hour (every ${60 / stepsPerHour} minutes)`,
  meshFormatNames: { ply: "PLY", obj: "OBJ", stl: "STL", glb: "GLB" },
  floorStackingChoices: { supported: "Supported", free: "Free" },
  timeBasisChoices: { standard: "Standard time", daylight_saving: "Daylight saving time", solar: "Solar time" },
  raysPerPatchChoices: { "1": "1, at the patch centre", "4": "4, spread over the patch", "9": "9, spread over the patch", "16": "16, spread over the patch" },
  carvingRuleChoices: { carve_fraction: "Manual", headtail: "Automatic" },
  // Under the carving rule Automatic, which has no setting: the cut of the last carving.
  automaticCut: (cutoffText: string) =>
    `Cut at ${cutoffText}, found from the spread of the scores. Dragging the line on the histogram switches to Manual.`,
  automaticBeforeCarving: "The cut is found from the spread of the scores when the carving runs.",
  ruleSwitchedToManual: "Dragging the line switched the carving rule from Automatic to Manual.",
  // The balance temperature strip: the names of its two handles, the two ends of the dead band.
  balanceLowerEnd: "Counts below",
  balanceUpperEnd: "Too warm above",

  // The 3D view (8)
  layerNames: {
    max_volume: "Maximum volume",
    test_surfaces: "Test surfaces",
    context: "Existing surroundings",
    terrain: "Terrain",
    kept_voxels: "Kept voxels, coloured by score",
    carved_voxels: "Carved voxels",
    carved_by_criterion: "Carved voxels, by criterion",
    sun_path: "Sun path",
    sky_dome: "Sky dome",
    envelope: "Carved envelope",
    building_massing: "Building massing",
  },
  carvedByCriterionMissing: "Shows once every criterion that is on has run.",
  noResultForStage: "No result for this stage: the last run stopped before it",
  viewerNeedsWebGl: "The 3D view cannot start because this browser cannot use WebGL here, for example over a remote desktop, or when " +
    "the graphics card is blocked. The steps on the left still work. To see the 3D view, open this page in another browser or at the computer itself.",
  layers: "Layers",
  skyDomeTransparency: "Transparency",
  voxelCount: (count: number) => `${groupedDigits(count)} voxels`,
  storeyCount: (count: number) => `${count} ${count === 1 ? "storey" : "storeys"}`,
  sunPathDays: (dayCount: number) => `${dayCount} ${dayCount === 1 ? "day" : "days"}`,
  skyPatchCount: (count: number) => `${count} patches`,
  outOfDate: "out of date",
  viewEmpty: "3D view, empty.",
  viewShowing: (layerList: string) => `3D view showing: ${layerList}.`,
  hourLabel: (hour: number) => `${hour}\u00a0h`,
  storeyLabel: (storeyNumber: number) => `Storey ${storeyNumber}`,
  northLetter: "N",
  compassRingLetters: ["N", "E", "S", "W"],       // clockwise from north, every 90 degrees on the compass ring
  scaleBar: (length: string) => `0 to ${length}\u00a0m`,
  lengthInMetres: (length: string) => `${length}\u00a0m`,
  compass: "Compass. Show the top view with north up",
  axisGizmo: "Axes: X, Y and Z",
  frameAll: "Frame all",
  topView: "Top view with north up",
  darkViewport: "Dark viewport",
  lightViewport: "Light viewport",
  // The ground aid button names the aid it switches to: off, ground grid and compass ring follow each other in a cycle
  groundAidSwitchTo: { grid: "Show the ground grid", compass_ring: "Show the compass ring", off: "Hide the compass ring" },
  keptVoxelsNote: (cutoff: string) => `Kept voxels. Carved voxels score above ${cutoff}.`,
  keptVoxelsSingleValue: (valueWithUnit: string) => `All kept voxels: ${valueWithUnit}`,
  thinnedVoxels: (step: number) => `Showing 1 of every ${groupedDigits(step)} voxels`,
  sunPathLegend: (days: string, hours: string) => `Sun path, ${days}; sun at ${hours}\u00a0h`,
  skyDomeLegend: (mode: string | null) => (mode !== null && Object.hasOwn(SKY_PATCH_WEIGHT_OF_MODE, mode)
    ? SKY_PATCH_WEIGHT_OF_MODE[mode] : "Sky patch weight"),
  buildingMassingLegend: "Building massing, by storey",
  carvedByCriterionLegend: "Carved voxels, by the criterion that removed them",
  legend: "Legend",
};

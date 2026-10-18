// The interface texts of UX spec sections 4, 5, 6.1, 7, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here. A unit follows its number after a no-break space (\u00a0), as in format_numbers.ts.
import { formattedNumber, groupedDigits, withUnit } from "./steps/format_numbers";

const MONTH_ABBREVIATIONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// What the sky patch weights of each weighted mode measure, for the sky dome legend (UX 8.2). The weights are read relative to
// each other, as the scores of the weighted modes are ("Obstruction score (relative)"), so no unit of the engine is shown.
const SKY_PATCH_WEIGHT_OF_MODE: Record<string, string> = {
  irradiance: "solar energy",
  benefit: "solar heat in hours that need heating",
  daylight: "overcast sky light",
  radiative_cooling: "night sky cooling",
};

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

  // The steps and their summary lines (4.1)
  stepTitles: {
    inputs: "Inputs",
    mode: "Mode",
    settings: "Settings",
    carving: "Carving",
    envelope_and_massing: "Envelope and massing",
    export: "Export",
  },
  inputsSummary: (volumeCount: number, testSurfaceCount: number, hasWeatherFile: boolean) =>
    `${volumeCount} ${volumeCount === 1 ? "volume" : "volumes"}, ${testSurfaceCount} ${testSurfaceCount === 1 ? "test surface" : "test surfaces"}` +
    (hasWeatherFile === true ? ", weather" : ""),
  maxVolumeMissing: "Maximum volume missing",
  testSurfacesMissing: "Test surfaces missing",
  maxVolumeAndTestSurfacesMissing: "Maximum volume and test surfaces missing",
  // The analysis period in words (R2 4.3), in the step summary, under the period's strips and in its tooltip: "21 Dec, 10 to
  // 14 h", "21 to 22 Dec, 22 to 2 h" (one month written once), "1 Oct to 30 Apr, 0 to 23 h", "22 Dec to 21 Dec, 10 to 14 h"
  // (across the new year within one month). One date with hours across midnight is what the engine runs: every night of the year.
  periodSummary: (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number) => {
    const hours = `${startHour} to ${endHour}\u00a0h`;
    const oneDate = startMonth === endMonth && startDay === endDay;
    if (oneDate && startHour > endHour) return `Every day, ${hours}`;
    const endDate = `${endDay} ${MONTH_ABBREVIATIONS[endMonth - 1]}`;
    const dates = oneDate ? endDate : startMonth === endMonth && startDay < endDay ? `${startDay} to ${endDate}`
      : `${startDay} ${MONTH_ABBREVIATIONS[startMonth - 1]} to ${endDate}`;
    return `${dates}, ${hours}`;
  },
  voxelsOfSize: (voxelSizeText: string) => `${voxelSizeText} voxels`,
  settingsSummary: (periodText: string, voxelsText: string) => `${periodText}; ${voxelsText}`,
  keptShare: (percentText: string) => `${percentText} kept`,
  notRunYet: "Not run yet",
  outOfDateSummary: "Out of date",
  massingSummary: (floorAreaText: string, storeysText: string) => `${floorAreaText}, ${storeysText}`,
  notBuiltYet: "Not built yet",
  // What exists of the two parts of Envelope and massing (R2 5): "Envelope built, massing not built".
  envelopePartStates: { current: "Envelope built", out_of_date: "Envelope out of date", missing: "Envelope not built" },
  massingPartStates: { current: "massing built", out_of_date: "massing out of date", missing: "massing not built" },
  envelopeAndMassingParts: (envelopeText: string, massingText: string) => `${envelopeText}, ${massingText}`,
  exportReady: "Ready",
  envelopeReady: "Envelope ready",
  massingReady: "Massing ready",
  carvingNeedsAnalysis: "Run the analysis in Settings to see the carving",
  envelopeNeedsAnalysis: "Run the analysis in Settings before building the envelope and massing",
  exportNeedsBuild: "Build the envelope or the massing to export them",

  // Inputs (5.2)
  maxVolumeTitle: "Maximum volume",
  testSurfacesTitle: "Test surfaces",
  weatherFileTitle: "Weather file (optional)",
  weatherFileNeededTitle: "Weather file",
  requiredInput: "Required",
  weatherFileExtension: ".epw",
  maxVolumeHint: "The largest building you would allow, as one or more closed meshes.",
  testSurfacesHint: "The surfaces whose sun or sky the carving protects, such as neighbouring facades.",
  weatherNeededFor: (modeNames: string) => `Needed for ${modeNames}.`,
  orDropThemHere: "or drop them here",
  replaceFile: "Replace",
  removeFile: (fileName: string) => `Remove ${fileName}`,
  triangleCount: (count: number) => `${groupedDigits(count)} ${count === 1 ? "triangle" : "triangles"}`,
  fileProblem: (fileName: string, reason: string) => `${fileName}: ${reason}`,
  // A file the service accepted (the engine reads it) that the 3D view cannot draw, said in its box as fileProblem(name, reason)
  meshCannotBeDrawn: "The 3D view cannot read this file, so it is not drawn. Runs still use it.",
  meshTypeCannotBeShown: (extension: string) => `Meshes of type '${extension}' cannot be shown.`,
  inputsSizeTitle: "Size of all inputs together",
  inputsSize: (sideX: string, sideY: string, sideZ: string) => `${sideX} × ${sideY} × ${sideZ}\u00a0m`,

  // Mode (5.3). The names, lines and tooltips of the six modes are in steps/mode_tiles.json.
  modeGroupLabel: "Mode",
  modeFillsStartingValues: "Choosing a mode fills its starting values in Settings.",
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

  // Run buttons (5.4, 6.4)
  runAnalysis: "Run analysis",
  runInProgress: "A run is in progress",
  addMaxVolumeToRun: "Add a maximum volume to run the analysis",
  addTestSurfacesToRun: "Add test surfaces to run the analysis",
  addMaxVolumeAndTestSurfacesToRun: "Add a maximum volume and test surfaces to run the analysis",
  fixSettingsToRun: "Fix the settings above to run the analysis.",

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
  noInputsYet: "Add a maximum volume and test surfaces to start",
  addFiles: "Add files",
  orTryAnExample: "or try an example",
  weatherFileNeeded: "Add a weather file to run this mode",
  fixSettingToRun: (settingLabel: string) => `Fix the ${String(settingLabel).toLowerCase()} to run the analysis.`,
  fixSettingInStepToRun: (settingLabel: string, stepTitle: string) => `Fix the ${String(settingLabel).toLowerCase()} in ${stepTitle} to run the analysis.`,
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
  stageStates: { waiting: "waiting", running: "running", done: "done" },
  rayBatches: (done: number, total: number) => `${groupedDigits(done)} of ${groupedDigits(total)} batches`,
  elapsedTime: (secondsText: string) => `Elapsed ${secondsText}`,
  cancelRun: "Cancel",
  runFailed: "The run stopped on an error.",
  errorType: (errorType: string) => `Error type: ${errorType}`,
  goToSetting: (settingLabel: string) => `Go to ${String(settingLabel).toLowerCase()}`,
  runConnectionLost: "The connection to the engine was lost during the run.",
  runReportUnreadable: "The run report could not be read. Build the envelope and massing again to write it.",
  warningsTitle: "Warnings",
  warningCount: (count: number) => `${count} ${count === 1 ? "warning" : "warnings"}`,
  summaryWithWarnings: (summary: string, warningsText: string) => `${summary}, ${warningsText}`,

  // Carving (5.5)
  angleRuleHasNoThreshold: "The angle rule has no threshold: everything above the planes is removed. Change the angle in Settings.",
  analysisOutOfDate: "Settings changed since the analysis. Run the analysis again to update the carving.",
  sliderLowestEnd: "0",
  sliderHighestScore: (highestText: string) => `${highestText}, the highest score`,
  updateWhenThresholdChanges: "Update when I change the threshold",
  updateCarving: "Update carving",
  buildEnvelopeAndMassing: "Build envelope and massing",
  // Why the build buttons wait while Carving is locked: a build would run the analysis first (M10).
  buildWaitsForAnalysis: "Settings changed since the analysis. Run the analysis again before building.",
  histogramTitle: "Scores of the voxels",
  histogramScaleLabel: "Scale of the counts",
  logScale: "Log",
  linearScale: "Linear",
  histogramAxisShadowTolerated: "Shadow tolerated at which a voxel is carved, m²·h",
  histogramAxisRelative: "Score compared with the cutoff (relative)",
  histogramKept: "Kept",
  histogramCarved: "Carved",
  histogramBinRange: (lowerText: string, upperText: string, unit: string) => `${lowerText} to ${upperText}${unit ? ` ${unit}` : ""}`,
  histogramBinCounts: (kept: number, carved: number) => `${groupedDigits(kept)} kept, ${groupedDigits(carved)} carved`,
  histogramDescription: (voxelCount: number, cutoffText: string) =>
    `Histogram of the scores of ${groupedDigits(voxelCount)} voxels, cutoff at ${cutoffText}. Use the arrow keys to read each bar.`,
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
  floorAreaPerStorey: "Floor area per storey",
  storeyColumns: { storey: "Storey", bottom: "Bottom, m", top: "Top, m", area: "Area, m²" },
  storeyRowLabel: (storeyNumber: number) => (storeyNumber === 1 ? "1, ground" : String(storeyNumber)),
  totalRow: "Total",
  outOfDateForCarving: "Out of date for the current carving",
  openRunReport: "Open the run report",
  runReportTitle: "Run report",
  closePanel: "Close",

  // Export (5.7)
  envelopeMeshDownload: (formatName: string) => `Carved envelope (${formatName})`,
  massingObjDownload: "Building massing (OBJ)",
  massingJsonDownload: "Building massing data (JSON)",
  settingsDownload: "Settings (config.yaml)",
  projectZipDownload: "Whole project (zip)",
  outOfDateFile: "Out of date",

  // Settings form (5.4 to 5.7, 7). The labels, units and help texts of the settings are in settings_form/setting_presentation.json.
  moreSettingsOfGroup: {
    "When": "More sun settings",
    "Mode specific": "More mode settings",
    "Detail": "More detail settings",
    "How much to carve": "More carving settings",
    "Envelope": "More envelope settings",
    "Building massing": "More massing settings",
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
  sampleSpacingLoweredToVoxelSize: (sampleSpacing: number) =>
    `Sample spacing lowered to ${withUnit(formattedNumber(sampleSpacing), "m")} to match the voxel size.`,
  // Errors of the whole config, said under the settings they name (UX 11); the engine's own words are for the YAML.
  samplingAboveVoxelSize: (samplingLabel: string, samplingText: string, voxelSizeLabel: string, voxelSizeText: string) =>
    `${samplingLabel} (${samplingText}) must not be larger than the ${String(voxelSizeLabel).toLowerCase()} (${voxelSizeText}). ` +
    `Use a larger ${String(voxelSizeLabel).toLowerCase()} or a smaller ${String(samplingLabel).toLowerCase()}.`,
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
  periodFrom: "From",
  periodTo: "To",
  periodFieldNames: {
    start_day: "Start day", start_month: "Start month", start_hour: "Start hour",
    end_day: "End day", end_month: "End month", end_hour: "End hour",
  },
  hourUnit: "h",
  // The analysis period control (R2 4.3): the month marks of the year strip, its four handles and what they say to a screen
  // reader, the presets, and the words under the strips, which open the typed fields.
  monthInitials: MONTH_ABBREVIATIONS.map((abbreviation) => abbreviation[0]),
  periodHandleNames: { start_date: "Start date", end_date: "End date", start_hour: "Start hour", end_hour: "End hour" },
  periodDateSpoken: (month: number, day: number) => `${day} ${MONTH_NAMES[month - 1]}`,
  periodHourSpoken: (hour: number) => `${hour}\u00a0h`,
  periodPresets: "Presets",
  periodPresetNames: { winter_solstice: "21 December", summer_solstice: "21 June", heating_season: "Heating season, October to April", whole_year: "Whole year" },
  periodWordsButton: (periodWords: string) => `${periodWords}: type exact dates and hours`,
  periodNotSet: "Not set yet",
  // The typed hour fields, named apart from the hour handles of the strip.
  periodTypedHourNames: { start_hour: "Start hour, typed", end_hour: "End hour, typed" },
  oneAngle: "One angle",
  oneAnglePerDirection: "One per direction",
  compassDirections: ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
  angleTowards: (direction: string) => `Plane angle for test surfaces facing ${direction}`,
  sunStepsOption: (stepsPerHour: number) =>
    stepsPerHour === 1 ? "1 (every hour)" : stepsPerHour === 60 ? "60 (every minute)" : `${stepsPerHour} (every ${60 / stepsPerHour} minutes)`,
  meshFormatNames: { ply: "PLY", obj: "OBJ", stl: "STL", glb: "GLB" },
  floorStackingChoices: { supported: "Supported", free: "Free" },
  carvingRuleChoices: { carve_fraction: "Carve amount (recommended)", headtail: "Automatic split", cutoff: "Score cutoff" },
  carveAmountNotUsed: (ruleName: string) =>
    `Carve amount is not used with the carving rule ${ruleName}. Choose Carve amount under More carving settings to use it.`,
  scoreCutoffValue: "Score cutoff value",
  // The balance temperature slider (R2 4.2): its two handles, and the band between them.
  balanceTemperatureHandle: "Balance temperature",
  deadBandLowerEndHandle: "Lower end of the dead band",
  deadBandOnTrack: "Dead band",

  // The 3D view (8)
  layerNames: {
    max_volume: "Maximum volume",
    test_surfaces: "Test surfaces",
    kept_voxels: "Kept voxels, coloured by score",
    carved_voxels: "Carved voxels",
    sun_path: "Sun path",
    sky_dome: "Sky dome",
    envelope: "Carved envelope",
    building_massing: "Building massing",
  },
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
  keptVoxelsShadingCaused: "Shading caused, m²·h",
  keptVoxelsObstructionScore: "Obstruction score (relative)",
  keptVoxelsScoreIn: (unit: string) => `Score, ${unit}`,
  keptVoxelsNote: (cutoff: string) => `Kept voxels. Carved voxels score above ${cutoff}.`,
  keptVoxelsSingleValue: (valueWithUnit: string) => `All kept voxels: ${valueWithUnit}`,
  thinnedVoxels: (step: number) => `Showing 1 of every ${groupedDigits(step)} voxels`,
  sunPathLegend: (days: string, hours: string) => `Sun path, ${days}; sun at ${hours}\u00a0h`,
  skyDomeLegend: (mode: string | null) => mode !== null && Object.hasOwn(SKY_PATCH_WEIGHT_OF_MODE, mode)
    ? `Sky patch weight, ${SKY_PATCH_WEIGHT_OF_MODE[mode]} (relative)` : "Sky patch weight (relative)",
  buildingMassingLegend: "Building massing, by storey",
  legend: "Legend",
};

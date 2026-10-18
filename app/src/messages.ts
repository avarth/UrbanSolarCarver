// The interface texts of UX spec sections 4, 5, 6.1, 7, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here. A unit follows its number after a no-break space (\u00a0), as in format_numbers.ts.
import { groupedDigits } from "./steps/format_numbers";

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
  periodSummary: (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number) => {
    const startDate = `${startDay} ${MONTH_ABBREVIATIONS[startMonth - 1]}`, endDate = `${endDay} ${MONTH_ABBREVIATIONS[endMonth - 1]}`;
    return `${startDate === endDate ? startDate : `${startDate} to ${endDate}`}, ${startHour} to ${endHour}\u00a0h`;
  },
  voxelsOfSize: (voxelSizeText: string) => `${voxelSizeText} voxels`,
  settingsSummary: (periodText: string, voxelsText: string) => `${periodText}; ${voxelsText}`,
  keptShare: (percentText: string) => `${percentText} kept`,
  notRunYet: "Not run yet",
  outOfDateSummary: "Out of date",
  massingSummary: (floorAreaText: string, storeysText: string) => `${floorAreaText}, ${storeysText}`,
  notBuiltYet: "Not built yet",
  exportReady: "Ready",
  buildEnvelopeFirst: "Build the envelope first",
  carvingNeedsAnalysis: "Run the analysis in Settings to see the carving",
  envelopeNeedsAnalysis: "Run the analysis in Settings before building the envelope and massing",
  exportNeedsBuild: "Build the envelope and massing to export them",

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
  engineName: (engineName: string): MessagePart[] => ["Engine name: ", { code: String(engineName) }],
  experimental: "Experimental",
  aboutMode: (plainName: string) => `About ${plainName}`,

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

  // Envelope and massing (5.6)
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
  automatic: "automatic",
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
  periodText: (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number) =>
    `${startDay} ${MONTH_ABBREVIATIONS[startMonth - 1]} ${startHour}\u00a0h to ${endDay} ${MONTH_ABBREVIATIONS[endMonth - 1]} ${endHour}\u00a0h`,
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
  scaleBar: (length: string) => `0 to ${length}\u00a0m`,
  lengthInMetres: (length: string) => `${length}\u00a0m`,
  compass: "Compass. Show the top view with north up",
  axisGizmo: "Axes: X, Y and Z",
  frameAll: "Frame all",
  topView: "Top view with north up",
  darkViewport: "Dark viewport",
  lightViewport: "Light viewport",
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

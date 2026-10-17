// The interface texts of UX spec sections 4, 5, 6.1, 7, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here.
import { groupedDigits } from "./steps/format_numbers";

const MONTH_ABBREVIATIONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

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
    return `${startDate === endDate ? startDate : `${startDate} to ${endDate}`}, ${startHour} to ${endHour} h`;
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
  inputsSizeTitle: "Size of all inputs together",
  inputsSize: (sideX: string, sideY: string, sideZ: string) => `${sideX} × ${sideY} × ${sideZ} m`,

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
    advice: `Use ${smallestVoxelSize} m or more.`,   // shown in bold
  }),
  details: "Details",
  resultsOutOfDate: "Results are out of date; run the analysis again",
  runCancelled: "Cancelled.",
  engineStopped: ["The USC engine stopped. Start it again with ", { code: "usc ui" }, ", then reload this page."] as MessagePart[],
  accessLost: ["This page has lost its access to the engine. Open it again from the link that ", { code: "usc ui" }, " printed."] as MessagePart[],
  resultsUpToDate: "Results are up to date",
  modelMoreThan10Km: "This model is more than 10 km across. Is it in meters?",
  modelLessThan1M: "This model is less than 1 m across. Is it in meters?",

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
    `${startDay} ${MONTH_ABBREVIATIONS[startMonth - 1]} ${startHour} h to ${endDay} ${MONTH_ABBREVIATIONS[endMonth - 1]} ${endHour} h`,
  oneAngle: "One angle",
  oneAnglePerDirection: "One per direction",
  compassDirections: ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
  angleTowards: (direction: string) => `Plane angle for test surfaces facing ${direction}`,
  sunStepsOption: (stepsPerHour: number) =>
    stepsPerHour === 1 ? "1 (every hour)" : stepsPerHour === 60 ? "60 (every minute)" : `${stepsPerHour} (every ${60 / stepsPerHour} minutes)`,
  meshFormatNames: { ply: "PLY", obj: "OBJ", stl: "STL", glb: "GLB" },
  floorStackingChoices: { supported: "Supported", free: "Free" },
  carvingRuleChoices: { carve_fraction: "Carve amount (recommended)", headtail: "Automatic split", cutoff: "Score cutoff" },
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
  layers: "Layers",
  skyDomeTransparency: "Transparency",
  voxelCount: (count: number) => `${groupedDigits(count)} voxels`,
  storeyCount: (count: number) => `${count} ${count === 1 ? "storey" : "storeys"}`,
  sunPathDays: (dayCount: number) => `${dayCount} ${dayCount === 1 ? "day" : "days"}`,
  skyPatchCount: (count: number) => `${count} patches`,
  outOfDate: "out of date",
  viewEmpty: "3D view, empty.",
  viewShowing: (layerList: string) => `3D view showing: ${layerList}.`,
  hourLabel: (hour: number) => `${hour} h`,
  storeyLabel: (storeyNumber: number) => `Storey ${storeyNumber}`,
  northLetter: "N",
  scaleBar: (length: string) => `0 to ${length} m`,
  lengthInMetres: (length: string) => `${length} m`,
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
  thinnedVoxels: (step: number) => `Showing 1 of every ${groupedDigits(step)} voxels`,
  sunPathLegend: (days: string, hours: string) => `Sun path, ${days}; sun at ${hours} h`,
  skyDomeLegend: (unit: string) => `Sky patch weight, ${unit}`,
  buildingMassingLegend: "Building massing, by storey",
  legend: "Legend",
};

// The interface texts of UX spec sections 4, 5, 6.1, 7, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here. A unit follows its number after a no-break space (\u00a0), as in format_numbers.ts.
import { formattedNumber, groupedDigits, withUnit } from "./steps/format_numbers";

// The words for an input role inside a sentence.
const INPUT_ROLE_WORDS: Record<string, string> = {
  max_volume: "maximum volume", test_surfaces: "test surface", context: "existing surroundings", terrain: "terrain", weather: "weather file",
};

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

// What a study's sky dome shows for each metric (Simulate's Layers menu): the value each patch carried in its last result.
const STUDY_SKY_PATCH_VALUE_OF_METRIC: Record<string, string> = {
  solar_energy: "Solar energy from each sky patch, kWh/m²",
  useful_solar_energy: "Useful solar gains from each sky patch, kWh/m²",
  sky_component: "Share of the overcast sky in each patch",
  cooling_sky: "Share of the night sky cooling in each patch",
  sky_view: "Share of the sky in each patch",
};

// What the score of a voxel measures in each mode, for the histogram axis and the kept voxels legend (UX 5.5, 8.1). The unit is
// the engine's (mode_registry score_unit, in the score points): m²·h, kWh, or m² of fully hidden sky.
const SCORE_OF_MODE: Record<string, string> = {
  "time-based": "Shade each voxel casts",
  irradiance: "Solar energy each voxel blocks",
  benefit: "Useful solar heat each voxel blocks",
  daylight: "Overcast sky each voxel hides",
  radiative_cooling: "Night sky cooling each voxel hides",
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
  backToProjects: "Back to the projects",
  startScreenHeading: "Projects",
  darkTheme: "Dark theme",
  switchToDarkTheme: "Switch to the dark theme",
  switchToLightTheme: "Switch to the light theme",
  workspaceModeLabel: "Workspace mode",
  workspaceModes: { design: "Carve", simulate: "Simulate", inspect: "Inspect" },

  // Simulate: the studies panel over the 3D view, a study's popover and Run (simulate design, sections 3, 4 and 7)
  studiesTitle: "Studies",
  studiesShownOnView: "Show",
  studiesShownOnViewHint: "Show the selected study's values on the view, with its legend and result card",
  addStudy: "Add study",
  addStudyMenuTitle: "New study",
  likeCriterion: (criterionName: string) => `Like ${criterionName}`,
  metricNeedsWeatherFile: "Needs a weather file",
  metricOption: (label: string, unit: string) => `${label} (${unit})`,
  metricUnavailableOption: (label: string) => `${label}, needs a weather file`,
  runStudies: "Run",
  studySettingsOf: (studyName: string) => `Settings of ${studyName}`,
  studyName: "Name",
  studyMetric: "Metric",
  studyMoreSettings: "More settings",
  // A study's surfaces are "study surfaces", apart from the criteria's test surfaces: its files and the project's surfaces it samples.
  studySurfaces: "Study surfaces",
  studyNoSurfaceFiles: "No study surface files yet",
  addStudySurfaces: "Add study surfaces",
  studySurfacesFrom: { context: "The surroundings", terrain: "The terrain", ground: "The ground around the site" } as Record<string, string>,
  // The same in the line of a study's row, after its file names: "facades.obj, the surroundings".
  studySurfacesFromInLine: { context: "the surroundings", terrain: "the terrain", ground: "the ground" } as Record<string, string>,
  studyNeedsSurroundingsFiles: "The project has no surroundings files: add them in Inputs",
  useFileOfProject: "Use a file of the project",
  deleteStudy: "Delete study",
  closeStudySettings: "Close",
  designRunInProgress: "A carving run is in progress",
  simulationInProgress: "A simulation is in progress",
  // Results on the view (simulate design, section 3): the geometry switch, the target legend and the result card
  geometrySwitch: "Geometry",
  studyGeometries: { max_volume: "Max volume", envelope: "Envelope", massing: "Massing" },
  buildGeometryFirst: { envelope: "Build the envelope first", massing: "Build the massing first" },
  runStudyAgainFor: { envelope: "Run the study again to see it on the envelope", massing: "Run the study again to see it on the massing" },
  outOfDateInDesign: "Out of date in Carve",
  changeToggle: "Change",
  changeToggleHint: "Colours each point by its change from the maximum volume",
  changeNeedsGeometry: "Choose Envelope or Massing",
  changeLegend: (unit: string) => `Change from max volume (${unit})`,
  changeLoss: "Loss",
  // Colouring by the value (the default), or by each point's share of what it receives with nothing built on the plot (the no-build
  // value: the surroundings and terrain still block), between the two ends of the colour range.
  shareLegend: (label: string) => `${label}, share of the no-build value`,
  colourBy: "Colour by",
  colourByShare: "% of no-build",
  colourByValue: (unit: string) => `Value (${unit})`,
  rangeLow: "Low end of the colours (target)",
  rangeHigh: "High end of the colours",
  rangeEndHint: "Drag to move. Values beyond an end take its colour. Delete puts it back.",
  resultCard: "Result",
  studyShownWhenRunEnds: "Shown when the run ends",
  resultKept: (percent: string) => `keeps ${percent} of the no-build value`,
  resultMean: (value: string) => `mean ${value}`,
  resultLowestTenth: (value: string) => `lowest tenth ${value}`,
  resultAtTarget: (value: string) => `at target ${value}`,

  // Inspect: the Files panel over the 3D view, a file's summary, flipping its surfaces (inspect design, sections 3, 5 and 6). The
  // titles of the roles are the layers' (layerNames).
  inspectFilesTitle: "Files",
  inspectArrows: "Face normals",
  inspectFileLine: (triangles: number, areaSquareMetres: number) =>
    `${groupedDigits(triangles)} triangles, ${withUnit(formattedNumber(areaSquareMetres), "m²")}`,
  surfacesTurnedNotSaved: (count: number) =>
    (count === 1 ? "1 surface turned, not saved" : `${groupedDigits(count)} surfaces turned, not saved`),
  // The coordinates come formatted (formattedNumber): x, y and z, each from its minimum to its maximum.
  inspectBounds: (xMin: string, xMax: string, yMin: string, yMax: string, zMin: string, zMax: string) =>
    `Bounds: x ${xMin} to ${xMax}, y ${yMin} to ${yMax}, z ${zMin} to ${withUnit(zMax, "m")}`,
  georeferencedCoordinates: (kilometres: number) => `Georeferenced coordinates, about ${withUnit(groupedDigits(Math.round(kilometres)), "km")} from 0.`,
  inspectSurfaces: (count: number) => `Surfaces: ${groupedDigits(count)}`,
  inspectViewOrigin: (x: string, y: string, z: string) => `The view is drawn around x ${x}, y ${y}, z ${z}.`,
  flipMode: "Flip mode",
  flipAll: "Flip all",
  saveTurns: "Save",
  discardTurns: "Discard",
  restoreOriginal: "Restore original",
  closedAsWhole: "This file is closed as a whole, so its surfaces cannot be flipped.",
  stagedTurnsDropped: "The file changed, so its turns not saved were dropped.",
  saveTurnsBeforeLeaving: "Save the turned surfaces before leaving Inspect?",
  stayInInspect: "Stay",
  inspectSaveUnderWay: "A save is under way.",
  newProject: "New project",
  newProjectLead: "Start empty and add your own files.",
  projectNameLabel: "Project name",
  projectNameHint: "Up to 64 letters, numbers, spaces, hyphens or underscores.",
  createProject: "Create project",
  openProject: "Open a project",
  noProjectsYet: "No projects yet.",
  tryExample: "Try an example",
  tryExampleLead: "A project with its files and settings, ready to run.",

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
  // A weighted mode reports the share of the obstruction it removed; the others the share of the volume that reached the criterion.
  criterionResultOfScore: (percentText: string, volumeText: string) => `Removes ${percentText} of the obstruction, ${volumeText}`,
  criterionResultOfVolume: (percentText: string, volumeText: string) => `Removes ${volumeText}, ${percentText} of what reached it`,
  criterionScoreCarved: (percentText: string) => `Removes ${percentText} of the obstruction`,
  criterionVolumeCarved: (percentText: string) => `Removes ${percentText} of what reached it`,
  // Under the cards of two or more criteria (7.2): what the chain kept of the maximum volume; the volume alone without the share.
  chainKept: (volumeText: string, percentText: string) => `After all criteria: kept ${volumeText}, ${percentText} of the maximum volume`,
  chainKeptVolume: (volumeText: string) => `After all criteria: kept ${volumeText}`,
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
  // The editor of one criterion (its header): back to the list, where it stands in carving order, its neighbours
  allCriteria: "All criteria",
  criterionPosition: (position: number, count: number) => `${position} of ${count}`,
  // Said by the editor's header after Previous or Next criterion: the criterion now shown and where it stands ("Daylight, 2 of 3")
  criterionShownAt: (name: string, position: string) => `${name}, ${position}`,
  previousCriterion: "Previous criterion",
  nextCriterion: "Next criterion",
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
  // The shown criterion's messages that name no setting, with several criteria
  fixSettingsOfCriterionToRun: (criterionName: string) => `Fix the settings of ${criterionName} to run the analysis`,
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
  // A setting of the shown criterion, with several criteria
  fixSettingOfCriterionToRun: (settingLabel: string, criterionName: string) =>
    `Fix the ${String(settingLabel).toLowerCase()} of ${criterionName} to run the analysis`,
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
  buildWaitsForAnalysis: "Settings changed: run the analysis again before building",
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
  // The Mode section's line, closed, while the criterion's mode needs a weather file the project lacks
  modeNeedsWeatherFileSummary: (plainModeName: string) => `${plainModeName}, needs a weather file`,
  // Said to screen readers in the header of a closed section that has something to fix
  sectionNeedsAttention: "Needs attention",
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
  // The histogram axis and the kept voxels legend: "Solar energy each voxel blocks, kWh".
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
  // The carving rule's numbers are this criterion's: what it kept of the volume that reached it (the maximum volume for the first).
  keptHere: "Kept here",
  keptHereShare: (percentText: string) => `${percentText} of what reached this criterion`,
  keptHereOfWhatReached: "of what reached this criterion",
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
  // Said after the line above in an energy-weighted criterion, which does not count the cold hours.
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

  // Input files changed in the project folder from outside the app, or missing from it (the stage status lists them).
  inputFileInRole: (fileName: string, role: string) => `${fileName} (${INPUT_ROLE_WORDS[role] ?? role})`,
  inputFilesChangedInFolder: (files: string) =>
    `Changed in the project folder: ${files}. The app now uses the new version; what was built on the old one is out of date.`,
  inputFilesMissingFromFolder: (files: string) => `Missing from the project folder: ${files}. Put it back, or remove it here, before the next run.`,
  dismissInputChanges: "OK",

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
    study_values: "Study values",
    inspect_surfaces: "Surface orientation",
    sun_study: "Sun path of the year",
  },
  // The entry of a criterion under "Test surfaces" in the layers menu (two or more criteria): its name, marked when it is switched off.
  testSurfacesOfCriterion: (criterionName: string, off: boolean) => (off ? `${criterionName} (off)` : criterionName),
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
  inspectSurfaceCount: (count: number) => `${groupedDigits(count)} ${count === 1 ? "surface" : "surfaces"}`,
  studyPointCount: (count: number) => `${groupedDigits(count)} ${count === 1 ? "point" : "points"}`,
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
  // The ground aid button names the aid it switches to: off, ground grid and compass ring follow each other in a cycle
  groundAidSwitchTo: { grid: "Show the ground grid", compass_ring: "Show the compass ring", off: "Hide the compass ring" },
  keptVoxelsNote: (cutoff: string) => `Kept voxels. Carved voxels score above ${cutoff}.`,
  keptVoxelsSingleValue: (valueWithUnit: string) => `All kept voxels: ${valueWithUnit}`,
  thinnedVoxels: (step: number) => `Showing 1 of every ${groupedDigits(step)} voxels`,
  sunPathLegend: (days: string, hours: string) => `Sun path, ${days}; sun at ${hours}\u00a0h`,
  skyDomeLegend: (mode: string | null) => (mode !== null && Object.hasOwn(SKY_PATCH_WEIGHT_OF_MODE, mode)
    ? SKY_PATCH_WEIGHT_OF_MODE[mode] : "Sky patch weight"),
  studySkyDomeLegend: (metric: string | undefined) => (metric !== undefined && Object.hasOwn(STUDY_SKY_PATCH_VALUE_OF_METRIC, metric)
    ? STUDY_SKY_PATCH_VALUE_OF_METRIC[metric] : "Sky patch weight"),
  buildingMassingLegend: "Building massing, by storey",
  carvedByCriterionLegend: "Carved voxels, by the criterion that removed them",
  legend: "Legend",
  // Simulate's sun tool (the Sun panel) and the hours in shade on the view.
  sunToolTitle: "Sun",
  sunToolNoWeatherFile: "Add a weather file in Carve (Inputs) to see the sun: its location gives the sun's path.",
  sunToolDay: "Day",
  sunToolClock: "Clock",
  sunToolTimeBases: { standard: "Local standard time", solar: "Local solar time", daylight_saving: "Local daylight saving time" } as Record<string, string>,
  sunToolShow: "Show",
  sunToolViews: { none: "Sun path only", shadows: "Shadows at a time", shade: "Hours in shade" } as Record<string, string>,
  studySkyDomeNeedsRun: "Run the study again to see its sky dome: its result was computed before the sky patches were kept.",
  sunToolMoment: "Moment of the shadows",
  sunToolKeyDays: "Equinoxes and solstices",
  sunToolPeriod: "Days and hours",
  sunToolColours: "Colours",
  shadePaletteNames: { viridis: "Viridis", grey: "Grey" } as Record<string, string>,
  sunToolDayName: (day: number, month: number) => `${day} ${MONTH_ABBREVIATIONS[month - 1]}`,
  sunToolTime: "Time",
  sunToolSunAt: (altitude: string, azimuth: string) => `Sun ${altitude}° above the horizon, ${azimuth}° from north`,
  sunToolBelowHorizon: "The sun is below the horizon.",
  sunToolShadeNote: "A quick count of what the view shows, at the shadow map's resolution; Simulate's sun hours are the precise count.",
  sunToolDays: (first: string, last: string, dayStep: number) => (dayStep > 1 ? `mean of ${first} to ${last}, every ${dayStep} days` : `mean of ${first} to ${last}`),
  shadeHoursLegend: (start: string, end: string, days: string) => `Hours in shade per day, ${start} to ${end}, ${days}`,

  // Which hours count in Solar usefulness, and the typical building an energy-weighted criterion counts them by: the switch and
  // the box in the criterion's Settings, and the window where the building is edited and calculated.
  whichHoursCount: "Which hours count",
  whichHoursCountChoices: { cold_hours: "Cold hours", energy_weighted: "Energy-weighted" },
  energyWeightedSummary: (summary: string) => `Energy-weighted, ${summary}`,
  whichHoursCountHelp: "Cold hours: the sun of the hours colder than the balance temperature counts. Energy-weighted: each hour counts by " +
    "what its sun saves a typical building in heating over the year, from a simple hourly model of one room.",
  typicalBuilding: "Typical building",
  typicalBuildingStates: { current: "Calculated", out_of_date: "Changed since it was calculated", missing: "Not calculated yet" },
  // Under the state while the weights are not current: the run does it on its own.
  typicalBuildingRunCalculates: "Run analysis calculates it first.",
  typicalBuildingReading: "Reading the typical building",
  editBuilding: "Edit building",
  // A project has no typical building until one is chosen from the library.
  noBuildingChosen: "None chosen",
  chooseBuilding: "Choose building",
  chooseBuildingToRun: "Choose one from the library to run the analysis.",
  closeTypicalBuilding: "Close",
  done: "Done",
  // The library of typical buildings, at the top of the sheet: the examples in the groups the service names, then the user's own.
  typicalBuildingLibrary: "Library",
  ownBuildings: "Your buildings",
  // What the building is, in the library section's line and the box in Settings.
  changedFrom: (entryName: string) => `Changed from ${entryName}`,
  goneFromLibrary: (entryName: string) => `${entryName}, no longer in the library`,
  notFromLibrary: "Not from the library",
  libraryChooseNote: "Choosing a building replaces the values below with its own.",
  libraryChooseFirst: "The project has no typical building yet: choose one to start from, then change its values.",
  saveToLibrary: "Save to library",
  saveAsNew: "Save as new",
  exampleCannotChange: (entryName: string) => `${entryName} is an example: Save as new keeps these values in the library.`,
  renameLibraryEntry: (entryName: string) => `Rename ${entryName}`,
  deleteLibraryEntry: (entryName: string) => `Delete ${entryName}`,
  rename: "Rename",
  delete: "Delete",
  save: "Save",
  libraryEntryName: "Name",
  libraryEntryNeedsName: "Give the building a name.",      // the service's words for an empty name
  deleteLibraryEntryTitle: "Delete building",
  deleteLibraryEntryExplanation: (entryName: string) => `${entryName} leaves the library. Projects that use it keep their own copy.`,
  // The groups of the sheet: Use, Fabric and Summer shading, then under Advanced, Room, Roof and floor, and Air.
  typicalBuildingGroups: {
    use: "Use", fabric: "Fabric", shading: "Summer shading", room: "Room", roof_and_floor: "Roof and floor", air: "Air",
  } as Record<string, string>,
  typicalBuildingAdvanced: "Advanced",
  typicalBuildingFields: {
    schedule: "Hours in use", t_set_heating: "Heating set point", t_set_cooling: "Cooling set point", gains_w_m2: "Internal gains while in use",
    fresh_air_m3h_m2: "Fresh air while in use", heat_recovery: "Heat recovery", u_wall: "U of the walls", u_window: "U of the windows",
    g_value: "Window solar transmittance (g)", mass_capacity_kj_m2k: "Thermal capacity",
    shading_factor: "Shading factor", shading_start: "From", shading_end: "To", room: "Kind of room", height: "Storey height", depth: "Room depth",
    width: "Width, east to west", length: "Length, north to south", orientation: "Orientation", wwr: "Window share of each wall",
    roof_exposed: "Roof exposed", u_roof: "U of the roof", floor_exposed: "Floor exposed", u_floor: "U of the floor",
    ach_infiltration: "Infiltration",
  } as Record<string, string>,
  // The cases of use the hours come from (typical_building.SCHEDULES).
  schedules: { residential: "Residential: 6:00 to 24:00 every day", office: "Office: 8:00 to 18:00, Monday to Friday", always: "Always" } as Record<string, string>,
  scheduleWords: { residential: "Residential hours", office: "Office hours", always: "Every hour" } as Record<string, string>,
  roomKinds: { average: "Average room", box: "Box" } as Record<string, string>,
  typicalBuildingDay: "Day",
  typicalBuildingMonth: "Month",
  typicalBuildingSides: {
    ne: "North-east", se: "South-east", sw: "South-west", nw: "North-west", north: "North", east: "East", south: "South", west: "West",
  } as Record<string, string>,
  typicalBuildingSideInitials: { ne: "NE", se: "SE", sw: "SW", nw: "NW", north: "N", east: "E", south: "S", west: "W" } as Record<string, string>,
  typicalBuildingUnits: {
    metres: "m", degrees: "°", uValue: "W/m²K", celsius: "°C", wattsPerSquareMetre: "W/m²", airPerFloor: "m³/h per m²", capacity: "kJ/m²K",
    airChanges: "1/h",
  },
  typicalBuildingNotes: {
    schedule: "Internal gains and fresh air apply in these hours, infiltration in every hour.",
    gains_w_m2: "People, equipment and lighting, per m² of floor.",
    fresh_air_m3h_m2: "Per m² of floor.",
    heat_recovery: "The share of the exhaust heat the ventilation recovers, 0 to 1.",
    g_value: "The whole window, frame included, 0 to 1.",
    mass_capacity_kj_m2k: "The heat the room's walls, floors and ceilings store per m² of floor for each degree they warm; " +
      "a heavier construction stores more of the day's sun for the night.",
    shading_factor: "0 to 1 for every window; 1 lets all the sun through. Empty: no shading.",
    shading_period: "No shading outside these dates. An end before the start runs across the new year.",
    average: "A square room turned 45° with the same window share on its four walls (NE, SE, SW, NW), so no direction is favoured. " +
      "Its side is 4 times the depth: the weights depend on the ratios, not on the size.",
    orientation: "Clockwise from north; 0 has the south wall facing south.",
    wwr: "The glazed share of each wall, 0 to 0.9.",
    roof_and_floor: "Off, no heat passes through it (adiabatic), as for a storey between others.",
    ach_infiltration: "Outdoor air leaking in, in room volumes per hour, in every hour.",
  },
  // The one line of each group of the sheet while it is closed.
  useSummary: (scheduleText: string, heatingText: string, coolingText: string, gainsText: string) =>
    `${scheduleText}, ${heatingText} to ${coolingText} °C, gains ${gainsText} W/m²`,
  fabricSummary: (wallText: string, windowText: string, gText: string, capacityText: string) =>
    `U ${wallText} and ${windowText} W/m²K, g ${gText}, mass ${capacityText} kJ/m²K`,
  shadingSummary: (factorText: string, startText: string, endText: string) => `${factorText} from ${startText} to ${endText}`,
  noShading: "None",
  averageRoomSummary: (depthText: string, heightText: string, sharesText: string) => `Average, ${depthText} m deep, ${heightText} m storey; ${sharesText}`,
  boxRoomSummary: (widthText: string, lengthText: string, heightText: string, orientationText: string, sharesText: string) =>
    `Box ${widthText} × ${lengthText} × ${heightText} m, ${orientationText}° from north; ${sharesText}`,
  sameShareSummary: (shareText: string) => `windows ${shareText} on each side`,
  noWindows: "no windows",
  roofAndFloorSummary: (roofText: string | null, floorText: string | null) =>
    roofText === null && floorText === null ? "Both adiabatic"
      : roofText === null ? `Roof adiabatic, floor U ${floorText} W/m²K`
        : floorText === null ? `Roof U ${roofText} W/m²K, floor adiabatic` : `Roof U ${roofText}, floor U ${floorText} W/m²K`,
  airSummary: (infiltrationText: string) => `Infiltration ${infiltrationText} air changes per hour`,
  monthAbbreviations: MONTH_ABBREVIATIONS,
  calculate: "Calculate",
  calculateAgain: "Calculate again",
  calculating: "Calculating, about 10 s",
  // Why Calculate waits: one sentence without a final period, as the run buttons' reasons.
  calculateNeedsWeatherFile: "Add a weather file in Carve (Inputs) to calculate the typical building",
  calculateWaitsForValues: "Fix the values marked above to calculate",
  typicalBuildingOutOfDate: "The building or the weather file changed since this was calculated.",
  // The chart of each hour: benefit minus harm (benefit alone when the criterion does not count harm), sun-down hours grey.
  effectChartTitle: "Effect of sunlight, by hour",
  effectChartLabel: (countsHarm: boolean) =>
    "Effect of sunlight, by hour: day of the year across, hour of the day down; red where the sun offsets heating" +
    `${countsHarm ? ", blue where it adds to cooling" : ""}, grey with the sun down`,
  effectLegend: { heating: "offsets heating", cooling: "adds to cooling", none: "no effect", sunDown: "sun down" },
  weightsChartWaits: "Reading the weights",
  heatingDemand: "Heating",
  coolingDemand: "Cooling",
  demandPerYear: (valueText: string) => `${valueText} kWh/m² a year`,
  countedHours: "Hours that count",
  countedHoursOfDaytime: (count: number, daytimeCount: number) => `${groupedDigits(count)} of ${groupedDigits(daytimeCount)} daytime hours`,
  countedHoursNote: "Hours with the sun up whose weight is above 0.01.",
};

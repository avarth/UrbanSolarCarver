// The interface texts of UX spec sections 4, 5, 6.1, 7, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here. A unit follows its number after a no-break space (\u00a0), as in format_numbers.ts.
import { formattedNumber, groupedDigits, withUnit } from "./format_numbers";

// The words for an input role inside a sentence.
const INPUT_ROLE_WORDS: Record<string, string> = {
  max_volume: "maximum volume", test_surfaces: "test surface", context: "context", terrain: "terrain", weather: "weather file",
};

const MONTH_ABBREVIATIONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// What the sky patch weights of each weighted mode measure, for the sky dome legend (UX 8.2), with their unit: the energy from a
// patch per square metre facing it (Solar energy, Solar heating), or the patch's share of its sky (Daylight, Night cooling).
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

/** 2nd, 3rd, 22nd, 11th: an English ordinal. */
function ordinalOf(value: number): string {
  const tens = value % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[value % 10] ?? "th";
  return `${value}${suffix}`;
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
  metricNeedsWeatherFile: "Add a weather file in Settings",
  metricOption: (label: string, unit: string) => `${label} (${unit})`,
  metricUnavailableOption: (label: string) => `${label}, needs a weather file (Settings)`,
  runStudies: "Run",
  studySettingsOf: (studyName: string) => `Settings of ${studyName}`,
  studyName: "Name",
  studyMetric: "Metric",
  studyMoreSettings: "More settings",
  // A study's surfaces are "study surfaces", apart from the criteria's test surfaces: its files and the project's surfaces it samples.
  studySurfaces: "Study surfaces",
  studyNoSurfaceFiles: "No study surface files yet",
  addStudySurfaces: "Add study surfaces",
  studySurfacesFrom: { context: "Context", terrain: "Terrain", ground: "Ground" } as Record<string, string>,
  studySurfacesFromHint: { context: "The faces of the context files, without their bottoms",
                           terrain: "The terrain file",
                           ground: "A flat disc on the compass circle, at the foot of the max volume" } as Record<string, string>,
  // The same in the line of a study's row: "the massing, facades.obj, the context".
  studySurfacesFromInLine: { context: "the context", terrain: "the terrain", ground: "the ground" } as Record<string, string>,
  studyNeedsSurroundingsFiles: "The project has no context files: add them in Site",
  useFileOfProject: "Use a file of the project",
  deleteStudy: "Delete study",
  closeStudySettings: "Close",
  designRunInProgress: "A carving run is in progress",
  simulationInProgress: "A simulation is in progress",
  // What a study stands on the plot (its "geometry" setting), and whether it samples the faces of it.
  studyStands: { none: "Nothing", max_volume: "Max volume", base_volume: "Base volume", envelope: "Envelope", massing: "Massing" } as Record<string, string>,
  studyAccountFor: "Account for",
  studyAccountForHint: "What stands on the plot and blocks; the context and the terrain always block",
  buildGeometryFirst: { envelope: "Build the envelope in Carve", massing: "Build the massing in Carve", base_volume: "Set a base height in Settings" } as Record<string, string>,
  studySimulate: "Simulate",
  studySimulateGeometryHint: "Test points on its facades and roofs: how much the building itself gets",
  nothingToSimulate: "Nothing stands on the plot",
  studyTestSurfaceFiles: "Test surface files",
  studyQuick: "Quick count",
  studyQuickHint: "Counts the sun on every n-th day of the period (at most about 240 sun positions): about a second. Off: every hour",
  resultQuick: (step: number) => `Quick count: the sun on every ${ordinalOf(step)} day`,
  studyNoTestSurfaceFiles: "The project has no test surface files yet: add them to a criterion in Carve.",
  studyStandWaiting: (stand: string, reason: string) => `${stand} (${String(reason).replace(/^./, (first) => first.toLowerCase())})`,
  // In the line of a study's row: "the massing, facades.obj, the context".
  studyStandInLine: { max_volume: "the max volume", base_volume: "the base volume", envelope: "the envelope", massing: "the massing" } as Record<string, string>,
  studySpacing: "Spacing (m)",
  studySpacingFromCarve: (spacing: string) => `${spacing}, from Carve`,
  studySpacingHint: "Test points every this many meters. Follows the carving's spacing until you type one",
  studySpacingFollowsCarve: "Follows Carve",
  studySpacingReset: "Follow Carve",
  duplicateStudy: "Duplicate study",
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
  resultAtTarget: (value: string) => `${value} at or above the target`,
  // The result card's blocks: the study's other surfaces, and the faces of its geometry, whole and by the way they face.
  resultSurroundings: "Study surfaces",
  resultBuilding: { max_volume: "The max volume", base_volume: "The base volume", envelope: "The envelope", massing: "The massing" } as Record<string, string>,
  resultByFacing: "By facing",
  resultCardMinimise: "Minimise the result",
  resultCardShow: "Show the result",
  resultFacings: { roof: "Roofs", N: "North", E: "East", S: "South", W: "West" } as Record<string, string>,
  resultFacingColumns: { facing: "Facing", mean: "Mean", lowestTenth: "Lowest tenth", atTarget: "At target" },

  // Inspect: the Geometries panel over the 3D view, a file's summary, flipping its surfaces (inspect design, sections 3, 5 and 6). The
  // titles of the roles are the layers' (layerNames).
  inspectFilesTitle: "Geometries",
  inspectViewOriginLabel: "View origin",
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
  inspectViewOrigin: (x: string, y: string, z: string) => `The view is drawn around x ${x}, y ${y}, z ${z} of the files' coordinates.`,
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
  inspectRestoreUnderWay: "A restore is under way.",
  // A save or restore changed a test surface file that an analysis read.
  analysisOutOfDateAfterSave: (criteria: number) => (criteria === 1
    ? "The surfaces changed, so 1 criterion is out of date. Run the analysis again in Carve."
    : `The surfaces changed, so ${groupedDigits(criteria)} criteria are out of date. Run the analysis again in Carve.`),
  goToCarve: "Go to Carve",
  newProject: "New project",
  newProjectLead: "Start empty and add your own files.",
  projectNameLabel: "Project name",
  projectNameHint: "Up to 64 letters, numbers, spaces, hyphens or underscores. Start with a letter or number.",
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
    inputs: "Site",
    criteria: "Criteria",
    envelope_and_massing: "Envelope and massing",
    export: "Export",
  },
  // The site's files (the test surfaces belong to the criteria, the weather file to Settings): "1 volume, 2 surroundings files, terrain".
  inputsSummary: (volumeCount: number, contextCount = 0, hasTerrain = false) =>
    `${volumeCount} ${volumeCount === 1 ? "volume" : "volumes"}` +
    (contextCount > 0 ? `, ${contextCount} ${contextCount === 1 ? "context file" : "context files"}` : "") +
    (hasTerrain ? ", terrain" : ""),
  maxVolumeMissing: "Maximum volume missing",
  // The project settings, in the Settings button's tooltip: "THESSALONIKI, GRC. North 10°, 0.5 m voxels"
  projectSettingsSummary: (location: string | null, northText: string, voxelsText: string) =>
    `${location ?? "No weather file"}. North ${northText}°, ${voxelsText}`,
  // The project settings window (the settings every criterion shares), opened from the Settings button in the top bar
  projectSettingsButton: "Settings",
  // Where a setting to fix is, in "Fix the voxel size in Settings to run the analysis"
  projectSettingsPlace: "Settings",
  projectSettingsTitle: "Project settings",
  projectSettingsHint: (summaryText: string) => `${summaryText}. Opens the settings every criterion shares.`,
  projectSettingsButtonWithFixes: (count: number) => `Settings, ${count} ${count === 1 ? "setting" : "settings"} to fix`,
  projectSettingsIntro: "These settings apply to every criterion. A change puts every criterion out of date.",
  closeProjectSettings: "Close",
  // The setup of a new project (design/new-project-setup.md): the project settings a page at a time
  setupTitle: "Set up the project",
  setupPageOf: (page: number, pages: number) => `${page} of ${pages}`,
  setupLocationLine: "The weather file gives the site's sun and sky; the modes that count sun or sky need it. North turns the site to the compass. "
    + "You can set both later in Settings.",
  setupSiteTitle: "The site",
  setupSiteLine: "How you give the largest volume that may be built. You can switch later in the Site step.",
  setupHeightsLine: "You can change them later in Settings.",
  setupBack: "Back",
  setupNext: "Next",
  setupStart: "Start",
  skipSetup: "Skip setup",
  openProjectSettings: "Open settings",
  // A setting that needs the surroundings or the terrain, shown greyed out in the window without them
  needsSurroundingsOrTerrain: "Add context or terrain in Site to use this.",
  siteMissing: "Site missing",
  // A project that uses its sites: "2 sites, 3,450 m², terrain"
  sitesInputsSummary: (siteCount: number, area: number, contextCount = 0, hasTerrain = false) =>
    `${siteCount} ${siteCount === 1 ? "site" : "sites"}, ${groupedDigits(Math.round(area))}\u00a0m²` +
    (contextCount > 0 ? `, ${contextCount} ${contextCount === 1 ? "context file" : "context files"}` : "") +
    (hasTerrain ? ", terrain" : ""),
  addSiteToRun: "Draw a site to run the analysis",
  // Criteria with one criterion: its mode and its carving, "Solar heating, 56 % kept"
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
  criterionScoreCarved: (percentText: string) => `Removes ${percentText} of the obstruction`,
  criterionVolumeCarved: (percentText: string) => `Removes ${percentText} of what reached it`,
  // With a base height (design/base-height.md): what the base kept and what was built above it.
  builtAboveBase: (keptText: string, builtText: string, studiedText: string, percentText: string) =>
    `Base kept: ${keptText} m³. Built above it: ${builtText} m³ of ${studiedText} m³ (${percentText})`,
  baseHoldsObstruction: (percentText: string) =>
    `The base alone holds ${percentText} of the obstruction of the test surfaces; carving above it cannot remove that`,
  // Under the cards of two or more criteria (7.2): the share of the maximum volume the chain kept.
  chainKept: (percentText: string) => `After all criteria: kept ${percentText} of the maximum volume`,
  criterionOutOfDate: "Out of date",
  criterionUpdatesFrom: (criterionName: string) => `Updates from ${criterionName}`,
  criterionRunning: "Running",
  criterionOff: "Off",
  allCriteriaOff: "All off",
  criterionNeedsTestSurfaces: "Choose test surfaces",
  criterionNotRunYet: "Not run yet",
  // Criteria with several criteria: the ones that are on in order, each with the share it kept, "Daylight on windows 70 %, then
  // Solar heating 80 %"
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
  addTestSurfacesTo: (criterionName: string) => `Choose test surfaces for ${criterionName}.`,
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
  contextTitle: "Context",
  terrainTitle: "Terrain",
  weatherFileTitle: "Weather file",
  // The muted line under the title of a box (design/new-project-setup.md, section 5)
  optionalInput: "Optional",
  weatherAlsoInSettings: "Also in Settings",
  maxVolumeHint: "The largest building you would allow, as one or more closed meshes.",
  testSurfacesHint: "The surfaces whose sun or sky the carving protects, such as neighbouring facades.",
  contextHint: "Buildings and large trees that stay. They block sun and sky, and nothing is built in their place.",
  terrainHint: "The ground. It blocks sun and sky; the site stays buildable above it.",
  weatherNeededFor: (modeNames: string) => `Needed for ${modeNames}.`,
  orDropFilesHere: "You can also drag files onto this box.",
  orDropWeatherFileHere: "You can also drag the .epw file onto this box.",
  replaceFile: "Replace",
  removeFile: (fileName: string) => `Remove ${fileName}`,
  fileRemoved: (fileName: string) => `${fileName} was removed.`,
  undoRemoval: "Undo",
  removedFilesKept: (count: number) => (count === 1 ? "1 removed file is kept in the project folder." : `${count} removed files are kept in the project folder.`),
  showRemovedFiles: "Show",
  removeFileTitle: (fileName: string) => `Remove ${fileName} from the project. The file is kept in the project folder, under inputs/removed`,
  triangleCount: (count: number) => `${groupedDigits(count)} ${count === 1 ? "triangle" : "triangles"}`,
  fileProblem: (fileName: string, reason: string) => `${fileName}: ${reason}`,
  // A file the service accepted (the engine reads it) that the 3D view cannot draw, said in its box as fileProblem(name, reason)
  meshCannotBeDrawn: "The 3D view cannot read this file, so it is not drawn. Runs still use it.",
  meshTypeCannotBeShown: (extension: string) => `Meshes of type '${extension}' cannot be shown.`,
  // A site as the input (design/site-input.md): the choice between a maximum volume and a site, the Site card, drawing and editing
  inputChoiceTitle: "Start from",
  inputChoiceMaxVolume: "Maximum volume",
  inputChoiceMaxVolumeLine: "Add mesh files of the largest volume a building may take",
  inputChoiceSite: "Sites",
  inputChoiceSiteLine: "Draw the site boundaries in the view and give each a height",
  useSiteInstead: "Draw sites instead",
  useMaxVolumeInstead: "Use a maximum volume instead",
  switchInputTitle: (toSite: boolean) => (toSite ? "Draw sites instead?" : "Use a maximum volume instead?"),
  switchInputText: (toSite: boolean) => `The results will go out of date. Your ${toSite ? "maximum volume files are" : "sites are"} kept, so `
    + "you can switch back.",
  switchInput: "Switch",
  siteTitle: "Sites",
  siteHint: "The plots you may build on: closed outlines in plan, drawn in the 3D view or imported, each with its base and max height.",
  drawSite: "Draw",
  // Drawn context blocks (design/context-blocks.md)
  drawBlock: "Draw",
  blockNamed: (number: number) => `Block ${number}`,
  blockNameLabel: "Block name",
  blockHeightLabel: (blockName: string) => `${blockName}: height`,
  editBlock: "Edit",
  placeBlockOnTerrain: "Place on terrain",
  removeBlockShort: "Remove",
  blockActions: (blockName: string) => `Actions for ${blockName}`,
  drawnBlocks: "Drawn blocks",
  blockHeightHeading: "Height (m)",      // one line over the height column of the drawn blocks
  undoBlockChange: "Undo",
  // Sites from DXF and OBJ files (design/site-import.md)
  importSites: "Import",
  // Test surfaces picked on the surroundings, and surface sets (design/test-surfaces-on-context.md)
  pickFromSurroundings: "Pick",
  pickingSurfaces: "Picking test surfaces on the context",
  pickingSteps: "Click the facades and roofs of the context to protect. Click a picked face again to drop it.",
  pickedSetTarget: "Where the picked faces go",
  newSurfaceSet: "New set",
  addToSurfaceSet: (name: string) => `Add to ${name}`,
  surfaceSetName: "Name of the new set",
  editingSurfaceSet: (name: string) => `Editing ${name}`,
  useFaces: (count: number) => `Use ${count} ${count === 1 ? "face" : "faces"}`,
  savePicks: "Save picks",
  renameSurfaceSet: "Rename",
  renameSurfaceSetTitle: (name: string) => `Rename ${name}`,
  editPicks: "Edit picks",
  surfaceSetActions: (name: string) => `Actions for ${name}`,
  pickedOnSurroundings: "picked on the context",
  surfaceSetsHint: "Windows, facades or roofs whose sun or sky the carving protects, as files or as faces picked on the context. Each criterion and study chooses which of them to use.",
  usedBy: (names: string) => `Used by ${names}`,
  surfaceSetInUse: (names: string) => `Used by ${names}: switch it off there to remove it`,
  noSurfaceSets: "The project has no test surfaces yet. Import files or pick them on the context in the Site step.",
  openSiteStep: "Open the Site step",
  unusedSurfaceSets: "Test surfaces no criterion uses",
  useSurfaceSet: (name: string) => `Use ${name}`,
  picksLost: (count: number) => `${count} picked ${count === 1 ? "face is" : "faces are"} gone from the context`,
  importSitesTitle: (fileName: string) => `Import sites from ${fileName}`,
  importSitesFound: (count: number, unit: string) =>
    `${count} closed ${count === 1 ? "polyline" : "polylines"}, read in ${unit}. Their elevations are kept relative to each other, from the level new sites start at.`,
  importSiteLine: (areaText: string, riseText: string, holeCount = 0) =>
    `${areaText}\u00a0m², rise ${riseText}\u00a0m${holeCount > 0 ? `, ${holeCount} ${holeCount === 1 ? "hole" : "holes"}` : ""}`,
  importLeftOut: "Left out:",
  importFarFromInputs: (kilometres: string) => `The outlines are ${kilometres}\u00a0km from the other inputs. Are they in the same coordinates?`,
  importSitesButton: (count: number) => `Import ${count} ${count === 1 ? "site" : "sites"}`,
  placeOnTerrain: "Place on terrain",
  placeOnTerrainHint: "Each vertex takes the height of the terrain below it.",
  placeOnTerrainNeedsTerrain: "Add terrain in the Site step to use this",
  placedOffTerrain: (count: number) => `${count} ${count === 1 ? "vertex has" : "vertices have"} no terrain under ${count === 1 ? "it" : "them"} and kept ${count === 1 ? "its" : "their"} elevation.`,
  siteDropHint: "You can also drag a DXF or OBJ file of closed polylines onto this box.",
  siteEmptyHint: "Draw the site boundary in the 3D view, then click its vertices to set their elevations.",
  siteName: (number: number) => `Site ${number}`,
  siteHeightOf: (siteName: string) => `Max height of ${siteName}`,
  siteBaseOf: (siteName: string) => `Base height of ${siteName}`,
  siteNoBase: "none",
  doubleClickToRename: "Double click to rename",
  siteBaseNotBelowMax: (base: number, top: number) =>
    `its base height (${formattedNumber(base)} m) must be less than its max height (${formattedNumber(top)} m)`,
  heightsGroup: "Heights",
  baseHeight: "Base height",
  maxHeight: "Max height",
  forAllSites: "Global",
  perSite: "Per site",
  heightsHelp: "Base height protects the volume up to this height: use it for existing or permitted buildings to see how much more can "
    + "be built. Max height is the most that can be built. Both are measured from each site's lowest corner.",
  meshBaseHelp: "Base height protects the volume up to this height: use it for existing or permitted buildings to see how much more can "
    + "be built above them. Measured from the lowest point of the maximum volume.",
  heightNeedsValue: "Give the max height for all sites.",
  heightNotPositive: "A height must be more than 0 m.",
  siteNameOf: (siteName: string) => `Name of ${siteName}`,
  siteArea: (area: number) => `${groupedDigits(Math.round(area))}\u00a0m²`,
  // A site's area and its holes (design/site-holes.md): "2 697 m², 1 hole"
  siteAreaAndHoles: (area: number, holeCount: number) =>
    `${groupedDigits(Math.round(area))}\u00a0m²${holeCount > 0 ? `, ${holeCount} ${holeCount === 1 ? "hole" : "holes"}` : ""}`,
  holeName: (number: number) => `Hole ${number}`,
  holeActions: (siteName: string, number: number) => `Actions for hole ${number} of ${siteName}`,
  makeHoleOf: (siteName: string) => `Make a hole of ${siteName}`,
  deleteHole: "Delete hole",
  holeVertexHandle: (hole: number, index: number) => `Hole ${hole} vertex ${index}`,
  sitesOverlap: (first: string, second: string) => `${first} and ${second} overlap: check their outlines.`,
  siteLiesInside: (inner: string, outer: string) => `${inner} lies inside ${outer}: make it a hole of ${outer}, or move it.`,
  siteOverlapsAnother: "This site overlaps another site",
  holeTooFewVertices: (number: number) => `hole ${number} needs at least 3 vertices`,
  holeCrossesItself: (number: number) => `hole ${number} crosses itself`,
  holeTooSmall: (number: number, area: number) => `hole ${number}'s area is ${area.toFixed(2)}\u00a0m², less than 1\u00a0m²`,
  holeNotInside: (number: number) => `hole ${number} is not strictly inside the outline`,
  holesTouch: (first: number, second: number) => `hole ${first} and hole ${second} touch or cross`,
  siteElevations: (rise: number) => (rise < 0.005 ? "Flat" : `Elevations 0 to ${formattedNumber(rise)}\u00a0m`),
  siteActions: (siteName: string) => `Actions for ${siteName}`,
  renameSite: "Rename",
  editSite: "Edit outline",
  deleteSite: "Delete",
  sitesSummary: (count: number, area: number) => `${count} ${count === 1 ? "site" : "sites"}, ${groupedDigits(Math.round(area))}\u00a0m²`,
  siteNoNumber: "a vertex has no number for a coordinate",
  siteTooFewVertices: "an outline needs at least 3 vertices",
  siteCrossesItself: "the outline crosses itself",
  siteTooSmall: (area: number) => `the site's area is ${area.toFixed(2)}\u00a0m², less than 1\u00a0m²`,
  siteHeightNotPositive: "the height must be more than 0\u00a0m",
  siteTooLow: (rise: number) => `this site rises ${rise.toFixed(2)}\u00a0m, so its height must be more than ${rise.toFixed(2)}\u00a0m`,
  siteNotSaved: (reason: string) => `Not saved: ${reason}.`,
  drawingSite: (siteName: string) => `Drawing ${siteName}`,
  drawingHole: (siteName: string) => `Drawing a hole in ${siteName}`,
  drawHole: "Draw hole",
  drawingSteps: "Click to add points · click the first point or press Enter to close · Backspace removes the last · Esc cancels",
  editingSite: (siteName: string) => `Editing ${siteName}`,
  editingSteps: "Drag a vertex to move it · click it to type its elevation · double click an edge to add a vertex · Delete removes the "
    + "selected vertex",
  doneDrawing: "Done",
  cancelDrawing: "Cancel",
  undoSiteChange: "Undo",
  redoSiteChange: "Redo",
  segmentLength: (length: number) => `${formattedNumber(length)}\u00a0m`,
  vertexElevation: "Elevation",
  vertexElevationHelp: "In the coordinates of the input files",
  relativeElevation: (value: number) => `${value >= 0 ? "+" : ""}${formattedNumber(value)}\u00a0m above the lowest point`,
  vertexHandle: (index: number) => `Vertex ${index}`,
  siteCannotBeDrawnWhileRunning: "Sites cannot change while the analysis runs.",
  inputsSizeTitle: "Overall size",
  inputsSize: (sideX: string, sideY: string, sideZ: string) => `${sideX} × ${sideY} × ${sideZ}\u00a0m`,

  // Mode (5.3). The names, lines and tooltips of the six modes are in mode_tiles.json.
  modeGroupLabel: "Mode",
  firstModeTitle: "Choose a mode for the first criterion",
  chooseModeSummary: "Choose a mode",
  criterionModeLine: (plainName: string) => `Mode: ${plainName}`,
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
  addTestSurfacesToRun: "Choose test surfaces to run the analysis",
  addMaxVolumeAndTestSurfacesToRun: "Add a maximum volume and choose test surfaces to run the analysis",
  // Another criterion that is on protects nothing (7.2: the run refuses to start until every one protects something)
  addTestSurfacesOfCriterionToRun: (criterionName: string) => `Choose test surfaces for ${criterionName} to run the analysis`,
  openCriterion: (criterionName: string) => `Open ${criterionName}`,
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
  // Beside the device status, after a run of the open project in this page: how long the last one took.
  lastRun: (secondsText: string) => `Last run ${secondsText}`,
  cpuMode: "CPU mode",
  gpuNotAvailable: "GPU not available",
  noCudaGpuFound: "No CUDA-enabled GPU found. USC runs on the CPU, which is slower.",
  cpuModeChosenAtLaunch: "CPU mode, chosen at launch.",      // usc ui --device cpu on a computer that has a CUDA device
  runButtonWaitsForGpu: "Waiting for the GPU to be ready",

  // Empty, error and warning states (11)
  noInputsYet: "Add a maximum volume to start",
  addFiles: "Import",
  orTryAnExample: "or try an example",
  weatherFileNeeded: "Add a weather file in Settings to run this mode",
  // A criterion that is on has a mode that needs a weather file (with several criteria the shown one is named too)
  weatherFileNeededFor: (criterionName: string) => `Add a weather file in Settings to run ${criterionName}`,
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
  modelMoreThan10Km: "This model is more than 10\u00a0km across. Is it in metres?",
  modelLessThan1M: "This model is less than 1\u00a0m across. Is it in metres?",

  // Units written after the numbers of the run steps (UX 5.5 to 5.7, 9)
  units: { shadeHours: "m²·h", percent: "%", squareMetres: "m²", cubicMetres: "m³", seconds: "s", minutes: "min", hours: "h" },

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
  engineWarnings: "As the engine wrote them",
  issueOfCriterion: (criterionName: string, text: string) => `${criterionName}: ${text}`,
  issueOfStudy: (studyName: string, text: string) => `${studyName}: ${text}`,
  // Two criteria in the summary that would read alike, numbered in chain order.
  numberedName: (name: string, number: number) => `${name} (${number})`,
  // A run's warnings by their code (common/issue_text.ts)
  issues: {
    everythingCarved: "Every voxel was carved: the threshold is probably too low.",
    nothingCarved: "Nothing was carved: the threshold is probably too high.",
    nothingLeftToCarve: "The criterion before this one kept no voxel, so this one had nothing to carve.",
    thresholdValueDisagrees: "The threshold value and the carve fraction disagree; the threshold value is used.",
    settingUnused: (label: string) => `${label} is not used by this mode.`,
    settingsUnused: (labels: string[]) => `This mode does not use: ${labels.join(", ")}.`,
    smoothingClipped: (radius: string | null) =>
      radius === null ? "Score smoothing was reduced to the largest it can be at this voxel size."
        : `Score smoothing was reduced to ${radius} m, the largest it can be at this voxel size.`,
    edgeTaperIgnored: "The edge strip with less weight has no effect in this mode.",
    edgeTaperExcluded: "A test surface is narrower than about twice the edge strip with less weight, so it is only partly protected.",
    testPointsBlocked: (blocked: string, total: string) =>
      `${blocked} of ${total} test points see no sky: they lie inside or below the context or the terrain, or face into it, so they protect nothing. Check the test surfaces there.`,
    testSurfacesSkipped: (counts: string) =>
      `Test surfaces skipped and not protected: ${counts}. Each one must be a single flat face. The Layers menu shows them.`,
    horizontalTestSurfaces: (flat: string, total: string) =>
      `${flat} of ${total} sample points lie on horizontal test surfaces, which face no direction a tilted plane can follow; there the plane protects only the sky straight above.`,
    contextNotClosed: "The context is not a closed mesh, so where it reaches the grid the voxels it removes may be too few or too many. It still blocks rays.",
    footprintUnreadable: "The footprint of the maximum volume could not be read; the building massing uses the voxel footprint.",
    footprintMismatch: (percent: string) =>
      `The footprint of the maximum volume does not match the voxels (${percent}% of them lie outside it); the building massing uses the voxel footprint.`,
    raisedPart: (height: string) => `A part of the envelope starts ${height} m above the lowest point; its floors are counted from the lowest point.`,
    noPlatesFit: "No storey of the building massing fits the envelope with these settings.",
    nonfiniteScores: (percent: string) => `${percent}% of the voxels have no valid score and are always carved. Check the input geometry.`,
    noSunVectors: "The sun is never above the “Ignore sun below” altitude in the analysis period, so nothing was carved.",
    noSunPositions: "The sun is never above the “Ignore sun below” altitude in the check period, so every test point gets 0 sun hours.",
    noColdHours: "No hour of the analysis period is below the balance temperature, so no sun counts as useful and the carving has nothing to go on. Widen the period or raise the balance temperature.",
    harmEverywhere: "Overheating outweighs the useful sun from every part of the sky, so the carving has nothing to go on. Narrow the period or stop subtracting summer overheating.",
    zeroWeights: "The typical building gains nothing from the sun in the analysis period, so the carving has nothing to go on. Widen the period.",
    dewPointOutsideFit: (celsius: string) =>
      `The night dew point, ${celsius} °C, is outside −15 to 25 °C, where the sky emissivity formula holds; the cooling weights may be off.`,
    balancePointUnused: "The balance temperature is not used: the typical building's weights decide which hours count.",
    rayBatchClamped: (size: string) => `Rays per batch was too large and was lowered to ${size}.`,
    keptLargestPart: "Every part of the envelope mesh is smaller than the mesh cleanup keeps, so only the largest part was kept.",
    experimentalMode: "This mode is experimental and may change.",
  },
  warningCount: (count: number) => `${count} ${count === 1 ? "warning" : "warnings"}`,
  summaryWithWarnings: (summary: string, warningsText: string) => `${summary}, ${warningsText}`,

  // Carving (5.5)
  angleRuleHasNoThreshold: "The angle rule has no threshold: everything above the planes is removed. Change the angle above.",
  analysisOutOfDate: "The settings changed since the analysis. Run it again to update the carving.",
  sliderLowestEnd: "0",
  sliderHighestScore: (highestText: string) => `${highestText}, the highest of any voxel`,
  updateWhenThresholdChanges: "Update the carving as I change its settings",
  carvingGroup: "Carving",
  updateWhenThresholdChangesHelp: "On: a change of a criterion's carving rule carves again at once. Off: Update carving does, in the bar under the steps or on the view.",
  updateCarving: "Update carving",
  // Under the pinned buttons once a carving update has finished, while its results are current.
  carvingUpdated: "Carving updated.",
  carvingUpdatedOf: (criterionNames: string) => `Carving updated: ${criterionNames}.`,
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
  addTestSurfacesFirst: (criterionName: string) => `Choose test surfaces for ${criterionName} first`,
  // The panel of a criterion that is off, in place of its carving rule
  criterionOffNote: "Off: the chain skips this criterion",
  // The folded sections of a criterion's panel, each saying in one line what it holds while it is closed
  panelSectionTitles: { test_surfaces: "Test surfaces", settings: "Settings", carving: "Carving rule" },
  noTestSurfacesYet: "None yet",
  // The Settings section's line, closed, while the criterion's mode needs a weather file the project lacks
  needsWeatherFileSummary: "Needs a weather file",
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
    `Histogram of the scores of ${groupedDigits(voxelCount)} ${voxelCount === 1 ? "voxel" : "voxels"}, cutoff at ${cutoffText}. Use the arrow keys to read each bar.`,
  // The handle of the cutoff line on the histogram (a slider for the keyboard), and what it says of its value.
  cutoffHandle: "Cutoff",
  cutoffHandleValue: (cutoffText: string, keptText: string) => `${cutoffText}, keeps about ${keptText} of the volume`,
  // Under the histogram while the line shows a cutoff not run yet: dragged, or set in the form since the carving shown.
  cutoffPreview: (cutoffText: string, keptText: string) =>
    `Preview: a cut at ${cutoffText} keeps about ${keptText} of the volume, before the slope limit.`,
  cutoffPreviewWithCarveAmount: (carveAmountText: string, cutoffText: string, keptText: string) =>
    `Preview: carve amount ${carveAmountText}, a cut at ${cutoffText}, keeps about ${keptText} of the volume, before the slope limit.`,
  slopeLimitNote: (count: number) => `The slope limit removed ${groupedDigits(count)} ${count === 1 ? "voxel" : "voxels"} below the cutoff.`,

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
    "Mode specific": "More mode settings",
    "Detail": "Detail settings",
  },
  aboutSetting: (settingLabel: string) => `About ${String(settingLabel).toLowerCase()}`,
  configNameAndDefault: (configName: string, defaultText: string): MessagePart[] =>
    ["Config name: ", { code: String(configName) }, `, default ${defaultText}`],
  analysisPeriodConfigNames: "start_month ... end_hour",
  gridSize: (voxelsPerSide: number, totalVoxels: number) => `${groupedDigits(voxelsPerSide)} voxels per side, ${groupedDigits(totalVoxels)} in total`,
  // Under Voxel size after a run: the grid, then how long the last run's scoring took on this machine and a rough time at this size.
  gridSizeAndScoring: (gridText: string, scoringText: string) => `${gridText}. ${scoringText}`,
  lastScoring: (secondsText: string) => `The last analysis took ${secondsText} to score`,
  lastScoringAndEstimate: (secondsText: string, estimateText: string) => `The last analysis took ${secondsText} to score; at this size, about ${estimateText}`,
  // The grid line while the voxel size shown was refused: the grid is the one of the voxel size last saved.
  gridSizeAtSavedVoxelSize: (voxelSizeText: string, voxelsPerSide: number, totalVoxels: number) =>
    `Grid at the saved voxel size of ${voxelSizeText}: ${groupedDigits(voxelsPerSide)} voxels per side, ${groupedDigits(totalVoxels)} in total`,
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
  typeADate: "Click to type a date, as 21 Dec or 21/12, then press Enter",
  typeAnHour: "Click to type an hour from 0 to 23, then press Enter",
  periodDateOnBubble: (month: number, day: number) => `${day} ${MONTH_ABBREVIATIONS[month - 1]}`,
  periodPresets: "Presets",
  // The cold period of the weather file (round 2, section 8), a preset of Solar heating: the longest run of days whose
  // month-around mean temperature is below the balance temperature minus the dead band.
  coldPeriodPreset: "Cold period from the weather file",
  coldPeriodPresetWithDates: (startText: string, endText: string) => `Cold period: ${startText} to ${endText}`,
  // Under the strips: the last date and the last hour count.
  periodCounts: (days: number, hoursPerDay: number) =>
    `${groupedDigits(days)} ${days === 1 ? "day" : "days"}, ${hoursPerDay} ${hoursPerDay === 1 ? "hour" : "hours"} a day`,
  anglesPerDirectionSummary: "One angle per direction",
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
  // The notice of a weather file added or replaced in this session (settings_form/weather_change_notice.ts), over the criterion's settings in Criteria.
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
  // Without harm counted the strip has one handle, and the setting is named and explained by it.
  balanceSunCountsBelow: "Sun counts below",
  balanceSunCountsBelowHelp: "Sun counts in the hours colder than this temperature; warmer hours are left out. It lies a little below " +
    "the building's balance temperature, about 12 °C for offices and 18 °C for homes. With summer overheating subtracted, a second " +
    "handle sets the temperature above which sun counts against it.",

  // Input files changed in the project folder from outside the app, or missing from it (the stage status lists them).
  inputFileInRole: (fileName: string, role: string) => `${fileName} (${INPUT_ROLE_WORDS[role] ?? role})`,
  inputFilesChangedInFolder: (files: string) =>
    `Changed in the project folder: ${files}. The app now uses the new version; what was built on the old one is out of date.`,
  inputFilesMissingFromFolder: (files: string) => `Missing from the project folder: ${files}. Put it back, or remove it here, before the next run.`,
  dismissInputChanges: "OK",

  // The 3D view (8)
  layerNames: {
    max_volume: "Maximum volume",
    base_volume: "Base volume",
    test_surfaces: "Test surfaces",
    skipped_surfaces: "Skipped test surfaces",
    context: "Context",
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
  skyDomeUnreadable: "The sky dome of this run could not be read: its file may be damaged. Change a value under Settings and run the analysis to write it again.",
  skippedSurfaceCount: (count: number) => `${count} ${count === 1 ? "surface" : "surfaces"}`,
  skippedSurfaceReasons: { "non-planar": "not flat", "no samples": "too small for the grid", degenerate: "no area" } as Record<string, string>,
  /** The line under the layer: how many surfaces protect nothing; *why* counts them by reason. */
  skippedSurfacesLine: (skipped: number, surfaceCount: number, why: string) => `${skipped} of ${surfaceCount} surfaces not protected: ${why}.`,
  edgeStripCarriedOver: (metres: number) => `The edge strip of ${metres} m set in Night cooling counts here too. Switch to Night cooling to change it.`,
  resultUnreadable: "This result could not be read: its file may be damaged. Change a value under Settings and run again to write it.",
  viewerNeedsWebGl: "The 3D view cannot start because this browser cannot use WebGL here, for example over a remote desktop, or when " +
    "the graphics card is blocked. The steps on the left still work. To see the 3D view, open this page in another browser or at the computer itself.",
  layers: "Layers",
  skyDomeTransparency: "Transparency",
  voxelCount: (count: number) => `${groupedDigits(count)} ${count === 1 ? "voxel" : "voxels"}`,
  storeyCount: (count: number) => `${count} ${count === 1 ? "storey" : "storeys"}`,
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
  keptVoxelsPlain: "Kept voxels",
  keptVoxelsCastNoShade: "Kept voxels cast no shade in the period.",
  flatPanelsHint: "Flat panels; a curved or folded one is skipped.",
  exampleDetail: (modeName: string, description: string) => `${modeName}. ${description}`,
  keptVoxelsNote: (cutoff: string) => `Kept voxels. Carved voxels score above ${cutoff}.`,
  keptVoxelsSingleValue: (valueWithUnit: string) => `All kept voxels: ${valueWithUnit}`,
  thinnedVoxels: (step: number) => `Showing 1 of every ${groupedDigits(step)} voxels`,
  sunPathLegend: (days: string, hours: string) => `Sun path, ${days}; sun at ${hours}\u00a0h`,
  skyDomeLegend: (mode: string | null) => (mode !== null && Object.hasOwn(SKY_PATCH_WEIGHT_OF_MODE, mode)
    ? SKY_PATCH_WEIGHT_OF_MODE[mode] : "Sky patch weight"),
  studySkyDomeLegend: (metric: string | undefined) => (metric !== undefined && Object.hasOwn(STUDY_SKY_PATCH_VALUE_OF_METRIC, metric)
    ? STUDY_SKY_PATCH_VALUE_OF_METRIC[metric] : "Sky patch weight"),
  carvedByCriterionLegend: "Carved voxels, by the criterion that removed them",
  legend: "Legend",
  // Simulate's sun tool (the Sun panel) and the hours in shade on the view.
  sunToolTitle: "Sun",
  sunToolNoWeatherFile: "Add a weather file in Settings to see the sun: its location gives the sun's path.",
  sunToolDay: "Day",
  sunToolClock: "Clock",
  sunToolTimeBases: { standard: "Local standard time", solar: "Local solar time", daylight_saving: "Local daylight saving time" } as Record<string, string>,
  sunToolShow: "Show",
  sunToolViews: { none: "Sun path only", shadows: "Shadows at a time" } as Record<string, string>,
  sunToolHint: "Sun: the sun path and the shadows at a time",
  sunToolClose: "Close the sun tool",
  studySkyDomeNeedsRun: "Run the study again to see its sky dome: its result was computed before the sky patches were kept.",
  sunToolMoment: "Moment of the shadows",
  sunToolKeyDays: "Equinoxes and solstices",
  sunToolDayName: (day: number, month: number) => `${day} ${MONTH_ABBREVIATIONS[month - 1]}`,
  sunToolTime: "Time",
  sunToolSunAt: (altitude: string, azimuth: string) => `Sun ${altitude}° above the horizon, ${azimuth}° from north`,
  sunToolBelowHorizon: "The sun is below the horizon.",

  // Which hours count in Solar heating, and the typical building an energy-weighted criterion counts them by: the switch and
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
    schedule: "Hours in use", t_set_heating: "Comfort band, from", t_set_cooling: "Comfort band, to", gains_w_m2: "Internal gains while in use",
    fresh_air_m3h_m2: "Fresh air while in use", heat_recovery: "Heat recovery", u_wall: "U of the walls", u_window: "U of the windows",
    g_value: "Window solar transmittance (g)", mass_capacity_kj_m2k: "Thermal capacity",
    shading_factor: "Shading factor", shading_start: "From", shading_end: "To", room: "Kind of room", height: "Storey height", depth: "Room depth",
    width: "Width, east to west", length: "Length, north to south", orientation: "Orientation", wwr: "Window share of each wall",
    roof_exposed: "Roof exposed", u_roof: "U of the roof", floor_exposed: "Floor exposed", u_floor: "U of the floor",
    ach_infiltration: "Infiltration", vent_above: "Open the windows above", vent_ach: "Open windows let in at most",
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
    comfort_band: "The room runs free, with no heating or cooling. The sun counts for it where it warms the room while the room " +
      "is colder than this band, and against it where it warms the room above the band.",
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
    vent_above: "When the room would be warmer than this and outdoors is cooler, the windows open, as far as needed to bring it " +
      "back to this temperature.",
    vent_ach: "The most outdoor air open windows let in, in room volumes per hour.",
  },
  // The one line of each group of the sheet while it is closed.
  useSummary: (scheduleText: string, heatingText: string, coolingText: string, gainsText: string) =>
    `${scheduleText}, comfort ${heatingText} to ${coolingText} °C, gains ${gainsText} W/m²`,
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
  airSummary: (infiltrationText: string, ventAboveText: string, ventAchText: string) =>
    `Infiltration ${infiltrationText} air changes per hour; windows open above ${ventAboveText} °C, up to ${ventAchText} per hour`,
  monthAbbreviations: MONTH_ABBREVIATIONS,
  calculate: "Calculate",
  calculateAgain: "Calculate again",
  calculating: "Calculating, about 10 s",
  calculationProgress: "Calculation progress",
  // Why Calculate waits: one sentence without a final period, as the run buttons' reasons.
  calculateNeedsWeatherFile: "Add a weather file in Settings to calculate the typical building",
  calculateWaitsForValues: "Fix the values marked above to calculate",
  typicalBuildingOutOfDate: "The building or the weather file changed since this was calculated.",
  // The chart of each hour: benefit minus harm (benefit alone when the criterion does not count harm), sun-down hours grey.
  effectChartTitle: "Effect of sunlight, by hour",
  effectChartLabel: (countsHarm: boolean) =>
    "Effect of sunlight, by hour: day of the year across, hour of the day down; red where the sun warms the room below the " +
    `comfort band${countsHarm ? ", blue where it warms it above the band" : ""}, grey with the sun down`,
  effectLegend: { heating: "warms it below the band", cooling: "warms it above the band", none: "no effect", sunDown: "sun down" },
  weightsChartWaits: "Reading the weights",
  heatingDemand: "Heating",
  coolingDemand: "Cooling",
  demandPerYear: (valueText: string) => `${valueText} kWh/m² a year`,
  belowBand: "Below the comfort band",
  aboveBand: "Above the comfort band",
  degreeHoursPerYear: (degreeHoursText: string, hoursText: string) => `${degreeHoursText} K·h a year, in ${hoursText} hours`,
  degreeHoursNote: "Degree-hours: in each hour, how many degrees the room is outside the band, added over the year.",
  countedHours: "Hours that count",
  countedHoursOfDaytime: (count: number, daytimeCount: number) => `${groupedDigits(count)} of ${groupedDigits(daytimeCount)} daytime hours`,
  countedHoursNote: "Hours with the sun up whose weight is above 0.01.",
};

// The interface texts of UX spec sections 5.1, 6.1, 8 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, why Warp cannot run, the message of a failed run) are shown as the
// engine gives them and have no entry here.

/** 690807104 as "690 807 104". */
export function groupedDigits(count: number): string {
  return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** A measured value: whole from 100 up, up to two decimals from 1 up, up to three below, digits grouped ("1 250", "1.5", "0.012"). */
export function formattedNumber(value: number): string {
  const magnitude = Math.abs(value);
  const rounded = Number(value.toFixed(magnitude >= 100 ? 0 : magnitude >= 1 ? 2 : 3));
  const [whole, fraction] = String(Math.abs(rounded)).split(".");
  return `${rounded < 0 ? "-" : ""}${groupedDigits(Number(whole))}${fraction === undefined ? "" : `.${fraction}`}`;
}

const MONTH_ABBREVIATIONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "12-21" (month and day) as "21 Dec". */
export function dayAndMonth(monthDay: string): string {
  const [month, day] = monthDay.split("-").map(Number);
  return `${day} ${MONTH_ABBREVIATIONS[month - 1]}`;
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
  // Start screen (5.1)
  newProject: "New project",
  projectNameLabel: "Project name",
  projectNameHint: "Up to 64 letters, numbers, spaces, hyphens or underscores.",
  createProject: "Create project",
  openProject: "Open a project",
  tryExample: "Try an example",

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

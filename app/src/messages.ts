// The interface texts of UX spec sections 5.1, 6.1 and 11, in one place. A text that takes values is a function.
// Texts that the engine writes (a file that cannot be read, the size warning, why Warp cannot run, the message of a failed run)
// are shown as the engine gives them and have no entry here.

/** 690807104 as "690 807 104". */
function groupedDigits(count: number): string {
  return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
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
  engineStopped: "The USC engine stopped. Start it again with `usc ui`, then reload this page.",
  resultsUpToDate: "Results are up to date",
};

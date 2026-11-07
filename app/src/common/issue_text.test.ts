import { expect, test } from "vitest";
import { issueTextOf } from "./issue_text";

const labelOf = (name: string) => ({ edge_taper: "Edge strip with less weight", voxel_size: "Voxel size" })[name] ?? name;

test("a warning the app knows is said in plain words with the setting that changes it", () => {
  expect(issueTextOf({ code: "everything_carved", message: "Thresholding produced an all-False mask (everything carved). Threshold value 0.12 may be too low." }, labelOf))
    .toEqual({ text: "Every voxel was carved: the threshold is probably too low.", setting: "threshold" });
  expect(issueTextOf({ code: "smoothing_radius_clipped", message: "score_smoothing=9 m is 9 voxels; clipped to 4 voxels (4 m)." }, labelOf))
    .toEqual({ text: "Score smoothing was reduced to 4 m, the largest it can be at this voxel size.", setting: "score_smoothing" });
  expect(issueTextOf({ code: "test_points_blocked", message: "preprocessing: 12 of 400 test points have every ray blocked" }, labelOf).text)
    .toMatch(/^12 of 400 test points see no sky/);
});

test("the settings a mode does not use are named by their labels", () => {
  expect(issueTextOf({ code: "settings_unused_by_mode", message: "mode 'tilted_plane' does not use: edge_taper, voxel_size (ignored)" }, labelOf).text)
    .toBe("This mode does not use: Edge strip with less weight, Voxel size.");
});

test("the three kinds of zero weights point to the setting each depends on", () => {
  const settingOf = (message: string) => issueTextOf({ code: "zero_patch_weights", message }, labelOf).setting;
  expect(settingOf("benefit mode: no hours in the analysis period are below balance_temperature - balance_offset = 12 °C")).toBe("balance_temperature");
  expect(settingOf("benefit mode (include_harm=true): hot-hour harm exceeds cold-hour benefit for every sky patch")).toBe("include_harm");
  expect(settingOf("benefit mode (simulated_weights_path): the artifact's benefit weights are zero everywhere")).toBe("start_month");
});

test("an unknown code, or a message whose numbers cannot be read, keeps the engine's wording", () => {
  expect(issueTextOf({ code: "w", message: "1 panel skipped" }, labelOf)).toEqual({ text: "1 panel skipped", setting: null });
  expect(issueTextOf({ code: "test_points_blocked", message: "blocked" }, labelOf)).toEqual({ text: "blocked", setting: null });
});

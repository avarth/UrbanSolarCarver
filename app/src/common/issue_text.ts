// The warnings of a run in plain words (UX 6.3): the engine reports each with a code and a message written for the command line
// (config names, "all-False mask"). The app says it by its code, with numbers read from the message, and names the setting that
// changes it, which the run panel links to. A code the app does not know shows the engine's message as written.
import { messages } from "../messages";
import type { RunIssue } from "./run_state";

export interface IssueText {
  text: string;
  /** The setting that changes what the warning is about; null: none in the app. */
  setting: string | null;
}

/** The numbers in *message*, in order, as written ("12", "0.25", "-15"). */
function numbersIn(message: string): string[] {
  return message.match(/-?\d+(?:[.,]\d+)*(?:e-?\d+)?/gi) ?? [];
}

/** The text after *prefix* up to *end* in *message*; null when it is not there. */
function between(message: string, prefix: string, end: string): string | null {
  const start = message.indexOf(prefix);
  if (start < 0) return null;
  const from = start + prefix.length;
  const stop = message.indexOf(end, from);
  return message.slice(from, stop < 0 ? undefined : stop);
}

/** The plain text of an issue and its setting; *labelOf* gives a setting's label in the form. */
export function issueTextOf(issue: Pick<RunIssue, "code" | "message">, labelOf: (settingName: string) => string): IssueText {
  const { code, message } = issue;
  const words = messages.issues;
  const n = numbersIn(message);
  switch (code) {
    case "everything_carved":
      return { text: words.everythingCarved, setting: "threshold" };
    case "nothing_carved":
      return { text: words.nothingCarved, setting: "threshold" };
    case "nothing_left_to_carve":
      return { text: words.nothingLeftToCarve, setting: null };
    case "threshold_value_disagrees":
      return { text: words.thresholdValueDisagrees, setting: "threshold" };
    case "carve_fraction_unused":
      return { text: words.settingUnused(labelOf("carve_fraction")), setting: null };
    case "settings_unused_by_mode": {
      const names = between(message, "does not use: ", " (ignored)");
      if (names === null) break;
      return { text: words.settingsUnused(names.split(", ").map(labelOf)), setting: null };
    }
    case "smoothing_radius_clipped": {
      const radius = between(message, "voxels (", " m)");
      return { text: words.smoothingClipped(radius), setting: "score_smoothing" };
    }
    case "edge_taper_ignored":
      return { text: words.edgeTaperIgnored, setting: "edge_taper" };
    case "edge_taper_excluded_component":
      return { text: words.edgeTaperExcluded, setting: "edge_taper" };
    case "test_points_blocked":
      if (n.length < 2) break;
      return { text: words.testPointsBlocked(n[0], n[1]), setting: null };
    case "test_surface_components_skipped": {
      const counts = between(message, "Test surface: ", " components");
      if (counts === null) break;
      return { text: words.testSurfacesSkipped(counts), setting: null };
    }
    case "horizontal_test_surfaces":
      if (n.length < 2) break;
      return { text: words.horizontalTestSurfaces(n[0], n[1]), setting: "tilted_plane_angle_deg" };
    case "context_not_closed":
      return { text: words.contextNotClosed, setting: null };
    case "footprint_unreadable":
      return { text: words.footprintUnreadable, setting: null };
    case "footprint_mismatch":
      if (n.length < 1) break;
      return { text: words.footprintMismatch(n[0]), setting: null };
    case "raised_part":
      if (n.length < 2) break;
      return { text: words.raisedPart(n[1]), setting: null };
    case "no_plates_fit":
      return { text: words.noPlatesFit, setting: "min_plate_dimension" };
    case "nonfinite_scores": {
      const share = between(message, "values (", "%");
      if (share === null) break;
      return { text: words.nonfiniteScores(share), setting: null };
    }
    case "no_sun_vectors":
      return { text: words.noSunVectors, setting: "min_altitude" };
    case "no_sun_positions":
      return { text: words.noSunPositions, setting: "min_altitude" };
    case "zero_patch_weights":
      if (message.includes("below")) return { text: words.noColdHours, setting: "balance_temperature" };
      if (message.includes("harm")) return { text: words.harmEverywhere, setting: "include_harm" };
      return { text: words.zeroWeights, setting: "start_month" };
    case "dew_point_outside_fit":
      if (n.length < 1) break;
      return { text: words.dewPointOutsideFit(n[0]), setting: "dew_point_celsius" };
    case "balance_point_unused":
      return { text: words.balancePointUnused, setting: null };
    case "ray_batch_size_clamped":
      if (n.length < 2) break;
      return { text: words.rayBatchClamped(n[1]), setting: "ray_batch_size" };
    case "mesh_cleanup_kept_largest_part":
      return { text: words.keptLargestPart, setting: null };
    case "experimental_mode":
      return { text: words.experimentalMode, setting: null };
  }
  return { text: message, setting: null };
}

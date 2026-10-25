// The settings the engine reads in one mode only (mode_registry.py, each ModeSpec's extra_params): a mode leaves the others out
// of its stage settings (stage_settings.py, PreprocessingSettings.effective_values), so a stored one is ignored there. Any setting
// not listed here is read by the engine in every mode, even where the form shows no field for it (edge_taper). engine_modes.test.ts
// reads mode_registry.py and fails when the two disagree.
import { ANALYSIS_PERIOD_FIELDS } from "./presentation";

const WEATHER_AND_PERIOD = ["epw_path", ...ANALYSIS_PERIOD_FIELDS];
const SKY_PATCH_RAYS = ["rays_per_patch"];

export const ENGINE_SETTINGS_OF_MODE: Readonly<Record<string, readonly string[]>> = {
  "time-based": [...WEATHER_AND_PERIOD, "min_altitude", "sun_steps_per_hour", "time_basis"],
  irradiance: [...WEATHER_AND_PERIOD, ...SKY_PATCH_RAYS],
  benefit: [...WEATHER_AND_PERIOD, ...SKY_PATCH_RAYS, "balance_temperature", "balance_offset", "include_harm", "simulated_weights_path"],
  daylight: SKY_PATCH_RAYS,
  radiative_cooling: [...SKY_PATCH_RAYS, "dew_point_celsius", "bliss_k", "min_sky_elevation_deg"],
  tilted_plane: ["tilted_plane_angle_deg"],
};

const MODE_SPECIFIC_SETTINGS = new Set(Object.values(ENGINE_SETTINGS_OF_MODE).flat());

/** Whether the engine ignores *setting* in *mode*: it is the setting of other modes only. False for a mode it does not know. */
export function engineIgnoresIn(setting: string, mode: string): boolean {
  const ownSettings = ENGINE_SETTINGS_OF_MODE[mode];
  return ownSettings !== undefined && MODE_SPECIFIC_SETTINGS.has(setting) && !ownSettings.includes(setting);
}

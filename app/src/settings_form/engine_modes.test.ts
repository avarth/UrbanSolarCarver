import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { ENGINE_SETTINGS_OF_MODE, engineIgnoresIn } from "./engine_modes";

// The checkout may turn the file's line ends into CRLF.
const MODE_REGISTRY = readFileSync("../src/urbansolarcarver/mode_registry.py", "utf8").replaceAll("\r\n", "\n");

/** The settings of a mode's extra_params in mode_registry.py, with its named sets (_EPW_AND_PERIOD, _PERIOD_FIELDS) expanded. */
function engineSettingsOf(mode: string): string[] {
  const namedSets: Record<string, string[]> = {};
  for (const match of MODE_REGISTRY.matchAll(/^(_[A-Z_]+) = frozenset\(\{([^}]*)\}\)( \| (_[A-Z_]+))?/gm)) {
    namedSets[match[1]] = [...match[2].matchAll(/"([a-z_]+)"/g)].map((name) => name[1]).concat(match[4] ? namedSets[match[4]] ?? [] : []);
  }
  const block = MODE_REGISTRY.split(`"${mode}": ModeSpec(`)[1].split("ModeSpec(")[0];
  const expression = /extra_params=([\s\S]*?),\n\s+[a-z_]+=/.exec(block)![1];
  const named = [...expression.matchAll(/\b(_[A-Z_]+)\b/g)].flatMap((name) => namedSets[name[1]] ?? []);
  return [...named, ...[...expression.matchAll(/"([a-z_]+)"/g)].map((name) => name[1])].sort();
}

test("the settings of each mode are the engine's extra_params of mode_registry.py", () => {
  expect(Object.keys(ENGINE_SETTINGS_OF_MODE).sort()).toEqual(["benefit", "daylight", "irradiance", "radiative_cooling", "tilted_plane", "time-based"]);
  for (const [mode, settings] of Object.entries(ENGINE_SETTINGS_OF_MODE)) expect([...settings].sort(), mode).toEqual(engineSettingsOf(mode));
});

test("the engine ignores a setting of other modes only; edge_taper is read in every mode", () => {
  expect(engineIgnoresIn("balance_temperature", "time-based")).toBe(true);
  expect(engineIgnoresIn("balance_temperature", "benefit")).toBe(false);
  expect(engineIgnoresIn("edge_taper", "time-based")).toBe(false);
  expect(engineIgnoresIn("voxel_size", "tilted_plane")).toBe(false);
  expect(engineIgnoresIn("start_day", "daylight")).toBe(true);
  expect(engineIgnoresIn("start_day", "unknown")).toBe(false);
});

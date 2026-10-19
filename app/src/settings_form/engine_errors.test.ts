// The engine's wording that engine_errors.ts turns into the interface's sentences, pinned to pydantic_schemas.py: when the
// engine rewords one of these messages this test fails, instead of the form quietly falling back to the generic words.
import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { errorOfHiddenSetting, shownConfigErrorOf } from "./engine_errors";

const SCHEMAS = readFileSync("../src/urbansolarcarver/pydantic_schemas.py", "utf8").replaceAll("\r\n", "\n");

test("the engine still writes the messages the form says in its own words", () => {
  expect(SCHEMAS).toContain('f"{prefix}_day={day} is invalid for month {month} "\n                        f"(max {max_day} days)"');
  expect(SCHEMAS).toContain('f"mode \'{self.mode}\' requires analysis period fields: {\', \'.join(missing)}"');
  expect(SCHEMAS).toContain('raise ValueError(f"mode \'{self.mode}\' requires epw_path")');
});

test("each of those messages, as the engine renders it, gets the interface's sentence", () => {
  // As Pydantic reports a model validator: no field, "Value error, " in front.
  const shown = (message: string, mode = "time-based") => shownConfigErrorOf(null, `Value error, ${message}`, mode);
  expect(shown("end_day=31 is invalid for month 4 (max 30 days)"))
    .toEqual({ settings: ["end_day"], message: "April has 30 days, so the end day cannot be 31." });
  expect(shown("mode 'benefit' requires analysis period fields: start_day", "benefit"))
    .toEqual({ settings: ["start_month"], message: "Solar usefulness needs the whole analysis period: every day, month and hour." });
  expect(shown("mode 'irradiance' requires epw_path", "irradiance")).toEqual({ settings: [], message: "Add a weather file to run this mode" });
});

test("a field the form does not show is named in plain words, and a hidden setting's label is not said twice", () => {
  expect(shownConfigErrorOf("mode", "mode must be one of the six modes", "daylight"))
    .toEqual({ settings: [], message: "Mode: mode must be one of the six modes" });
  const generic = shownConfigErrorOf(null, "Value error, tilted_plane_angle_deg must have length 8", "time-based");
  expect(errorOfHiddenSetting("tilted_plane_angle_deg", generic.message, "time-based")).toBe("Plane angle must have length 8");
  expect(errorOfHiddenSetting("edge_taper", "Input should be greater than or equal to 0", "time-based"))
    .toBe("Edge strip with less weight: Input should be greater than or equal to 0");
});

import { describe, expect, it } from "vitest";
import { STUDY_STANDS } from "../viewer/study_values";
import { standOf } from "./use_study_view";

describe("standOf", () => {
  it("gives back each geometry a study can stand", () => {
    for (const stand of STUDY_STANDS) expect(standOf({ geometry: stand })).toBe(stand);
  });

  it("stands the maximum volume until one is chosen", () => {
    expect(standOf(undefined)).toBe("max_volume");
    expect(standOf({})).toBe("max_volume");
    expect(standOf({ geometry: "something else" })).toBe("max_volume");
  });
});

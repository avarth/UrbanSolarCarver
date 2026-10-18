import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ModeInfo, SkyDome } from "../api_client/client";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import { renderForTest, type RenderedOverlay } from "./render_for_test";
import { NO_VIEWER_RESULTS, ViewerPane, type ViewerPaneProps } from "./ViewerPane";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let rendered: RenderedOverlay | null = null;

beforeEach(() => pretendTheBrowserHasWebGl());

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.restoreAllMocks();
});

const SKY_DOME: SkyDome = { directions: [[0, 0, 1], [0, 1, 0.2]], solid_angles: [0.1, 0.1], weights: [0.2, 1.4] };

function viewWithSkyDome(mode: string): ViewerPaneProps {
  return {
    maxVolume: null, testSurfaces: null, sunPath: null, hemisphere: { centre: [0, 0, 0], radius: 30 }, maxVolumeAppearance: "ghost",
    shownByDefault: ["sky_dome"], northDegrees: 0, framingRequest: 0, centreContent: null, mode, analysisCurrent: true,
    results: { ...NO_VIEWER_RESULTS, skyDome: SKY_DOME },       // the score points have not loaded (yet)
  };
}

test("the sky dome legend names the weights of the mode in plain words, relative, before the score points have loaded", () => {
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} />);
  expect(FakeViewerScene.latest!.layersWithObjects()).toEqual(["sky_dome"]);
  const title = rendered.container.querySelector(".viewer-legend h3")!.textContent;
  expect(title).toBe("Sky patch weight, overcast sky light (relative)");
  for (const mode of ["irradiance", "benefit", "radiative_cooling"]) {
    rendered.rerender(<ViewerPane {...viewWithSkyDome(mode)} />);
    const modeTitle = rendered.container.querySelector(".viewer-legend h3")!.textContent!;
    expect(modeTitle).toMatch(/^Sky patch weight, [a-z ]+ \(relative\)$/);
    expect(modeTitle).not.toMatch(/kWh|dimensionless|fraction|CIE/);
  }
});

test("the sky dome legend of a mode without sky weights (the form left the analysed mode) has no unit and no dangling comma", () => {
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("time-based")} />);
  expect(rendered.container.querySelector(".viewer-legend h3")!.textContent).toBe("Sky patch weight (relative)");
});

const weightedMode = (name: string, weightUnit: string): ModeInfo =>
  ({ name, description: "", needs_epw: name !== "daylight", needs_period: name !== "daylight", experimental: false, score_kind: "weighted_sum",
     weight_unit: weightUnit, starting_values: {} });
const MODES = [weightedMode("irradiance", "kWh/m²"), weightedMode("daylight", "CIE overcast sky obstruction score (dimensionless)")];

/** Score points of a daylight analysis without a carving: their header names the weights the analysis used. */
const DAYLIGHT_SCORE_POINTS: ScorePoints = {
  header: { origin: [0, 0, 0], shape: [1, 1, 1], voxel_size: 1, scores_kind: "weighted_sum", weight_unit: "CIE overcast sky obstruction score (dimensionless)",
            score_min: 0, score_max: 1, occupied_count: 1, point_count: 1, thinning_step: 1, has_mask: false, has_compared_scores: false },
  indices: Uint32Array.from([0]), scores: Float32Array.from([0.5]), kept: null, comparedScores: null,
};

test("the sky dome keeps the words of the mode it was analysed in after the mode changes, or says no mode when that is not known", () => {
  const legendTitle = () => rendered!.container.querySelector(".viewer-legend h3")!.textContent;
  const analysedInDaylight = { ...viewWithSkyDome("irradiance"), modes: MODES, analysisCurrent: false };
  rendered = renderForTest(<ViewerPane {...analysedInDaylight} results={{ ...NO_VIEWER_RESULTS, skyDome: SKY_DOME, scorePoints: DAYLIGHT_SCORE_POINTS }} />);
  expect(legendTitle()).toBe("Sky patch weight, overcast sky light (relative)");       // Solar energy chosen since: the dome is daylight's
  rendered.rerender(<ViewerPane {...analysedInDaylight} />);                             // the score points are not there
  expect(legendTitle()).toBe("Sky patch weight (relative)");
  rendered.rerender(<ViewerPane {...analysedInDaylight} analysisCurrent />);             // the analysis is of the mode the form shows
  expect(legendTitle()).toBe("Sky patch weight, solar energy (relative)");
});

test("an error of the scene that is not a missing WebGL is logged, and the view does not claim WebGL is missing", () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => ({}) as RenderingContext);     // WebGL is there
  const fault = new Error("a fault of the scene");
  FakeViewerScene.constructorError = fault;
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} />);
  expect(consoleError).toHaveBeenCalledWith(fault);
  expect(rendered.container.querySelector(".viewer-unavailable")).toBeNull();
});

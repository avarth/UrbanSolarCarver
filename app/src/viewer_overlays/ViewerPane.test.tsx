import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { SkyDome } from "../api_client/client";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import { click, renderForTest, type RenderedOverlay } from "./render_for_test";
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
  window.localStorage.clear();
});

const SKY_DOME: SkyDome = { directions: [[0, 0, 1], [0, 1, 0.2]], solid_angles: [0.1, 0.1], weights: [0.2, 1.4] };

function viewWithSkyDome(mode: string): ViewerPaneProps {
  return {
    maxVolume: null, testSurfaces: null, sunPath: null, hemisphere: { centre: [0, 0, 0], radius: 30 }, maxVolumeAppearance: "ghost",
    shownByDefault: ["sky_dome"], northDegrees: 0, framingRequest: 0, centreContent: null, mode, analysisCurrent: true,
    results: { ...NO_VIEWER_RESULTS, skyDome: SKY_DOME },       // the score points have not loaded (yet)
  };
}

test("the sky dome legend names the weights of the mode in plain words, with their unit, before the score points have loaded", () => {
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} />);
  expect(FakeViewerScene.latest!.layersWithObjects()).toEqual(["sky_dome"]);
  const legendTitle = () => rendered!.container.querySelector(".viewer-legend h3")!.textContent;
  expect(legendTitle()).toBe("Share of the overcast sky in each patch");
  const titles = Object.fromEntries(["irradiance", "benefit", "radiative_cooling"].map((mode) => {
    rendered!.rerender(<ViewerPane {...viewWithSkyDome(mode)} />);
    return [mode, legendTitle()];
  }));
  expect(titles).toEqual({ irradiance: "Solar energy from each sky patch, kWh/m²", benefit: "Useful solar heat from each sky patch, kWh/m²",
                           radiative_cooling: "Share of the night sky cooling in each patch" });
  for (const title of Object.values(titles)) expect(title).not.toMatch(/relative|dimensionless|CIE/);
});

test("the sky dome legend of a mode without sky weights (the form left the analysed mode) has no unit and no dangling comma", () => {
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("time-based")} />);
  expect(rendered.container.querySelector(".viewer-legend h3")!.textContent).toBe("Sky patch weight");
});

/** Score points of a daylight analysis without a carving: their header names the mode of the analysis. */
const DAYLIGHT_SCORE_POINTS: ScorePoints = {
  header: { origin: [0, 0, 0], shape: [1, 1, 1], voxel_size: 1, mode: "daylight", scores_kind: "weighted_sum",
            weight_unit: "share of the CIE overcast sky (sums to 1)", score_unit: "m²",
            score_min: 0, score_max: 1, compared_score_max: null, occupied_count: 1, point_count: 1, thinning_step: 1, has_mask: false, has_compared_scores: false },
  indices: Uint32Array.from([0]), scores: Float32Array.from([0.5]), kept: null, comparedScores: null,
};

test("the sky dome keeps the words of the mode it was analysed in after the mode changes, or says no mode when that is not known", () => {
  const legendTitle = () => rendered!.container.querySelector(".viewer-legend h3")!.textContent;
  const analysedInDaylight = { ...viewWithSkyDome("irradiance"), analysisCurrent: false };
  rendered = renderForTest(<ViewerPane {...analysedInDaylight} results={{ ...NO_VIEWER_RESULTS, skyDome: SKY_DOME, scorePoints: DAYLIGHT_SCORE_POINTS }} />);
  expect(legendTitle()).toBe("Share of the overcast sky in each patch");       // Solar energy chosen since: the dome is daylight's
  rendered.rerender(<ViewerPane {...analysedInDaylight} />);                     // the score points are not there
  expect(legendTitle()).toBe("Sky patch weight");
  rendered.rerender(<ViewerPane {...analysedInDaylight} analysisCurrent />);     // the analysis is of the mode the form shows
  expect(legendTitle()).toBe("Solar energy from each sky patch, kWh/m²");
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

test("the view starts with the ground aid chosen last on this computer, and the toolbar button moves the scene to the next one", () => {
  window.localStorage.setItem("usc.groundAid", "compass_ring");
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} />);
  expect(FakeViewerScene.latest!.groundAid).toBe("compass_ring");
  click(rendered.container.querySelector(".viewer-ground-aid-button")!);
  expect(FakeViewerScene.latest!.groundAid).toBe("off");
  expect(window.localStorage.getItem("usc.groundAid")).toBe("off");
});

test("while a dimmed result is shown, a stamp at the top of the view says it is out of date, or being updated during a run; nothing to dismiss", () => {
  const stamp = () => rendered!.container.querySelector(".viewer-out-of-date");
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} />);
  expect(stamp()).toBeNull();                                                    // current results: no stamp
  rendered.rerender(<ViewerPane {...viewWithSkyDome("daylight")} dimmedLayers={["sky_dome"]} />);
  expect(stamp()!.getAttribute("role")).toBe("status");
  expect(stamp()!.textContent).toBe("Out of date" + "The dimmed results do not match the settings.");
  expect(stamp()!.querySelector("button")).toBeNull();
  rendered.rerender(<ViewerPane {...viewWithSkyDome("daylight")} dimmedLayers={["sky_dome"]} runProgress={0.4} />);
  expect(stamp()!.textContent).toBe("Updating" + "The dimmed results are being replaced.");
  // A dimmed layer that is not shown (another step's, or hidden in the Layers menu) brings no stamp.
  rendered.rerender(<ViewerPane {...viewWithSkyDome("daylight")} dimmedLayers={["envelope"]} />);
  expect(stamp()).toBeNull();
  rendered.rerender(<ViewerPane {...viewWithSkyDome("daylight")} shownByDefault={[]} dimmedLayers={["sky_dome"]} />);
  expect(stamp()).toBeNull();
});

test("with surroundings and terrain, the layers menu lists them after the test surfaces, shown as the step asks", async () => {
  const { BoxGeometry } = await import("three");
  const { LAYERS_SHOWN_IN_STEP } = await import("../steps/ProjectWorkspace");
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} testSurfaces={new BoxGeometry(1, 1, 0.1)} context={new BoxGeometry(2, 2, 2)}
                                       terrain={new BoxGeometry(50, 50, 0.1)} shownByDefault={LAYERS_SHOWN_IN_STEP.inputs} />);
  expect(FakeViewerScene.latest!.layersWithObjects()).toEqual(expect.arrayContaining(["context", "terrain"]));
  expect(FakeViewerScene.latest!.visibleLayers.has("context")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("terrain")).toBe(true);
  click(rendered.container.querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!);
  const names = [...rendered.container.querySelectorAll(".viewer-layers-panel label")].map((label) => label.textContent);
  expect(names.slice(0, 3)).toEqual(["Test surfaces", "Existing surroundings", "Terrain"]);
  for (const step of Object.values(LAYERS_SHOWN_IN_STEP)) expect(step).toEqual(expect.arrayContaining(["context", "terrain"]));
});

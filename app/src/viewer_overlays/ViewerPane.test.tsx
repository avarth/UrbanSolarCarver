import { afterEach, expect, test, vi } from "vitest";
import type { SkyDome } from "../api_client/client";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { renderForTest, type RenderedOverlay } from "./render_for_test";
import { NO_VIEWER_RESULTS, ViewerPane, type ViewerPaneProps } from "./ViewerPane";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const SKY_DOME: SkyDome = { directions: [[0, 0, 1], [0, 1, 0.2]], solid_angles: [0.1, 0.1], weights: [0.2, 1.4] };

function viewWithSkyDome(mode: string): ViewerPaneProps {
  return {
    maxVolume: null, testSurfaces: null, sunPath: null, hemisphere: { centre: [0, 0, 0], radius: 30 }, maxVolumeAppearance: "ghost",
    shownByDefault: ["sky_dome"], northDegrees: 0, framingRequest: 0, centreContent: null, mode,
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

import { readFileSync } from "node:fs";
import { afterEach, expect, test, vi } from "vitest";
import { messages } from "../messages";
import { AxisGizmo } from "./AxisGizmo";
import { Compass } from "./Compass";
import { LayersMenu } from "./LayersMenu";
import { Legend, keptVoxelsLegendTitle } from "./Legend";
import { ScaleBar } from "./ScaleBar";
import { ViewerPane, type ViewerPaneProps } from "./ViewerPane";
import { ViewToolbar, rememberedViewportTheme } from "./ViewToolbar";
import { click, renderForTest, type RenderedOverlay } from "./render_for_test";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  window.localStorage.clear();
});

test("the legend shows the kept voxel range, its note and the thinning", () => {
  rendered = renderForTest(<Legend theme="light" content={{ keptVoxels: { title: keptVoxelsLegendTitle("violation_count", "m²·h (shaded test surface x duration)"), cutoff: 1.5, thinningStep: 3 } }} />);
  const text = rendered.container.textContent;
  expect(text).toContain("Shading caused, m²·h");
  expect(text).toContain("Kept voxels. Carved voxels score above 1.5.");
  expect(text).toContain("Showing 1 of every 3 voxels");
});

test("the legend titles of the weighted modes and the building massing swatches", () => {
  expect(keptVoxelsLegendTitle("weighted_sum", "kWh/m²")).toBe("Obstruction score (relative)");
  rendered = renderForTest(<Legend theme="dark" content={{ sunPath: "Sun path, 21 Dec; sun at 10, 12 and 14\u00a0h", buildingMassing: { storeyCount: 3 } }} />);
  const text = rendered.container.textContent;
  expect(text).toContain("Sun path, 21 Dec; sun at 10, 12 and 14\u00a0h");
  expect(text).toContain("Building massing, by storey");
  expect(Array.from(rendered.container.querySelectorAll(".viewer-storey-swatch")).map((swatch) => swatch.textContent)).toEqual(["1", "2", "3"]);
  expect(rendered.container.querySelector("[data-viewport-theme='dark']")).not.toBeNull();
});

test("the scale bar reads 0 to its length", () => {
  rendered = renderForTest(<ScaleBar theme="light" metresPerPixel={0.13} />);
  expect(rendered.container.textContent).toBe("0 to 20\u00a0m");
});

test("the compass shows the top view when clicked", () => {
  const onViewTop = vi.fn();
  rendered = renderForTest(<Compass theme="light" yawDegrees={30} northDegrees={20} onViewTop={onViewTop} />);
  click(rendered.container.querySelector("button")!);
  expect(onViewTop).toHaveBeenCalledOnce();
  expect(rendered.container.querySelector("button")!.getAttribute("aria-label")).toBe("Compass. Show the top view with north up");
});

test("the axis gizmo letters its axes", () => {
  rendered = renderForTest(<AxisGizmo theme="light" yawDegrees={0} elevationDegrees={60} />);
  expect(Array.from(rendered.container.querySelectorAll("text")).map((letter) => letter.textContent)).toEqual(["X", "Y", "Z"]);
});

test("the toolbar has three named buttons and remembers the viewport theme", () => {
  const onThemeChange = vi.fn();
  expect(rememberedViewportTheme()).toBe("light");
  rendered = renderForTest(<ViewToolbar theme="light" onFrameAll={() => {}} onTopView={() => {}} onThemeChange={onThemeChange} />);
  const names = Array.from(rendered.container.querySelectorAll("button")).map((button) => button.getAttribute("aria-label"));
  expect(names).toEqual(["Frame all", "Top view with north up", "Dark viewport"]);
  click(rendered.container.querySelectorAll("button")[2]);
  expect(onThemeChange).toHaveBeenCalledWith("dark");
  expect(window.localStorage.getItem("usc.viewportTheme")).toBe("dark");
  expect(rememberedViewportTheme()).toBe("dark");
});

test("the layers menu lists the layers that exist, with the missing-result note and the sky dome slider", () => {
  const onVisibleChange = vi.fn();
  rendered = renderForTest(
    <LayersMenu theme="light" skyDomeOpacity={0.6} onVisibleChange={onVisibleChange} onSkyDomeOpacityChange={() => {}}
                entries={[{ name: "kept_voxels", available: true, visible: true }, { name: "sky_dome", available: true, visible: true },
                          { name: "envelope", available: false, visible: false }]} />);
  click(rendered.container.querySelector("button")!);
  const text = rendered.container.textContent;
  expect(text).toContain("Kept voxels, coloured by score");
  expect(text).toContain("No result for this stage: the last run stopped before it");
  expect(text).not.toContain("Building massing");
  expect(rendered.container.querySelector("input[type='range']")).not.toBeNull();
  click(rendered.container.querySelector("input[type='checkbox']")!);
  expect(onVisibleChange).toHaveBeenCalledWith("kept_voxels", false);
});

test("the overlay styles take every colour from the tokens and keep the toolbar focus outline visible", () => {
  const overlaysCss = readFileSync("src/viewer_overlays/overlays.css", "utf8");
  expect(overlaysCss).not.toMatch(/#[0-9a-f]{3,6}|rgb\(/i);
  expect(overlaysCss).toMatch(/\.viewer-toolbar button {[^}]*outline-offset: -2px/);
});

const EMPTY_VIEW: ViewerPaneProps = {
  maxVolume: null, testSurfaces: null, sunPath: null, hemisphere: null, maxVolumeAppearance: "solid", shownByDefault: [], northDegrees: 0,
  framingRequest: 0, centreContent: null,
};

test("without WebGL (jsdom has none, like a remote desktop) the view says so, and the run progress and the run report still show", () => {
  rendered = renderForTest(<ViewerPane {...EMPTY_VIEW} runProgress={0.5} overlayContent={<div className="run-report-panel">Run report</div>} />);
  const unavailable = rendered.container.querySelector(".viewer-unavailable")!;
  expect(unavailable.textContent).toBe(messages.viewerNeedsWebGl);
  expect(unavailable.getAttribute("role")).toBe("status");
  expect(rendered.container.querySelector("canvas")).toBeNull();
  expect(rendered.container.querySelector("[role='progressbar']")!.getAttribute("aria-valuenow")).toBe("50");
  expect(rendered.container.querySelector(".run-report-panel")!.textContent).toBe("Run report");
  expect(rendered.container.querySelector(".viewer-toolbar")).toBeNull();      // no controls for a view that is not there
});

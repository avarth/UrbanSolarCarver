import { readFileSync } from "node:fs";
import { afterEach, expect, test, vi } from "vitest";
import { messages } from "../messages";
import { pretendTheBrowserHasNoWebGl } from "../viewer/fake_scene_for_test";
import { AxisGizmo } from "./AxisGizmo";
import { Compass } from "./Compass";
import { LayersMenu } from "./LayersMenu";
import { Legend } from "./Legend";
import { ScaleBar } from "./ScaleBar";
import { ViewerPane, type ViewerPaneProps } from "./ViewerPane";
import { AppThemeProvider } from "../theme/app_theme";
import { ViewToolbar, rememberedGroundAid } from "./ViewToolbar";
import { addStyleSheetForTest, click, renderForTest, type RenderedOverlay } from "./render_for_test";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  window.localStorage.clear();
  vi.restoreAllMocks();
});

test("the legend shows the kept voxel range, its note and the thinning", () => {
  rendered = renderForTest(<Legend theme="light" content={{ keptVoxels: { title: messages.scoreOfModeWithUnit("time-based", "m²·h"), cutoff: 1.5, unit: "m²·h", thinningStep: 3 } }} />);
  const text = rendered.container.textContent;
  expect(text).toContain("Shade each voxel casts, m²·h");
  expect(text).toContain("Kept voxels. Carved voxels score above 1.5\u00a0m²·h.");
  expect(text).toContain("Showing 1 of every 3 voxels");
});

test("a kept range of a single value reads 'All kept voxels' with the unit and draws no colour ramp", () => {
  const title = messages.scoreOfModeWithUnit("time-based", "m²·h");
  rendered = renderForTest(<Legend theme="light" content={{ keptVoxels: { title, cutoff: 0, unit: "m²·h", thinningStep: 1 } }} />);
  const text = rendered.container.textContent;
  expect(text).toContain("All kept voxels: 0\u00a0m²·h");
  expect(text).not.toContain("0 to 0");
  expect(rendered.container.querySelector(".viewer-legend-ramp")).toBeNull();
  expect(text).toContain("Kept voxels. Carved voxels score above 0\u00a0m²·h.");
});

test("the kept voxels of a weighted mode are named by what they block, in the unit of the scores", () => {
  rendered = renderForTest(<Legend theme="light" content={{ keptVoxels: { title: messages.scoreOfModeWithUnit("irradiance", "kWh"), cutoff: 0, unit: "kWh", thinningStep: 1 } }} />);
  expect(rendered.container.querySelector(".viewer-legend h3")!.textContent).toBe("Solar energy each voxel blocks, kWh");
  expect(rendered.container.querySelector(".viewer-legend-single-value")!.textContent).toBe("All kept voxels: 0\u00a0kWh");
  expect(messages.scoreOfModeWithUnit("daylight", "m²")).toBe("Overcast sky each voxel hides, m²");
  expect(messages.scoreOfModeWithUnit("radiative_cooling", "m²")).toBe("Night sky cooling each voxel hides, m²");
  expect(messages.scoreOfModeWithUnit("benefit", "kWh")).toBe("Useful solar heat each voxel blocks, kWh");
  expect(messages.scoreOfModeWithUnit(null, "")).toBe("Score of a voxel");
});

test("a kept range from 0 to a positive cutoff keeps the colour ramp", () => {
  rendered = renderForTest(<Legend theme="light" content={{ keptVoxels: { title: "Shading caused, m²·h", cutoff: 1.5, unit: "m²·h", thinningStep: 1 } }} />);
  expect(rendered.container.querySelector(".viewer-legend-ramp")).not.toBeNull();
  expect(rendered.container.textContent).not.toContain("All kept voxels");
});

test("the sun path and the building massing swatches", () => {
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

test("the axis gizmo letters its axes in the ink of the overlay, not in the axis colours", () => {
  rendered = renderForTest(<AxisGizmo theme="light" yawDegrees={0} elevationDegrees={60} />);
  const letters = Array.from(rendered.container.querySelectorAll("text"));
  expect(letters.map((letter) => letter.textContent)).toEqual(["X", "Y", "Z"]);
  for (const letter of letters) expect(letter.getAttribute("fill")).toBe("currentColor");
});

test("the axis gizmo is drawn straight on the viewport, without a background, a border or a shadow, its letters outlined in the viewport colour", () => {
  const removeStyles = addStyleSheetForTest("src/viewer_overlays/overlays.css");
  try {
    for (const theme of ["light", "dark"] as const) {
      rendered = renderForTest(<AxisGizmo theme={theme} yawDegrees={0} elevationDegrees={60} />);
      const style = getComputedStyle(rendered.container.querySelector(".viewer-axis-gizmo")!);
      expect(style.backgroundColor).toMatch(/^(transparent|rgba\(0, 0, 0, 0\))$/);
      expect(style.backgroundImage).toMatch(/^(none|)$/);
      expect(style.borderTopStyle).toMatch(/^(none|)$/);
      expect(style.boxShadow).toBe("none");
      for (const letter of rendered.container.querySelectorAll("text")) {
        const letterStyle = getComputedStyle(letter);
        expect(letterStyle.getPropertyValue("stroke")).toBe(`var(--colour-viewport-${theme})`);
        expect(letterStyle.getPropertyValue("paint-order")).toBe("stroke");
      }
      rendered.unmount();
      rendered = null;
    }
  } finally {
    removeStyles();
  }
});

const TOOLBAR_CALLBACKS = { onFrameAll: () => {}, onTopView: () => {}, onGroundAidChange: () => {} };

test("the toolbar has three named buttons; the light or dark viewport is the app's theme, not a button here", () => {
  rendered = renderForTest(<ViewToolbar {...TOOLBAR_CALLBACKS} theme="dark" groundAid="grid" />);
  const names = Array.from(rendered.container.querySelectorAll("button")).map((button) => button.getAttribute("aria-label"));
  expect(names).toEqual(["Frame all", "Top view with north up", "Show the compass ring"]);
  expect(rendered.container.querySelector(".viewer-toolbar")!.getAttribute("data-viewport-theme")).toBe("dark");
});

test("the ground aid button names the aid it switches to, and the choice is remembered on this computer", () => {
  const onGroundAidChange = vi.fn();
  expect(rememberedGroundAid()).toBe("grid");          // nothing chosen yet: the ground grid
  const groundAidButton = () => rendered!.container.querySelector<HTMLButtonElement>(".viewer-ground-aid-button")!;
  const expected = [["off", "Show the ground grid", "grid"], ["grid", "Show the compass ring", "compass_ring"],
                    ["compass_ring", "Hide the compass ring", "off"]] as const;
  for (const [current, name, next] of expected) {
    rendered?.unmount();
    rendered = renderForTest(<ViewToolbar {...TOOLBAR_CALLBACKS} theme="light" groundAid={current} onGroundAidChange={onGroundAidChange} />);
    expect(groundAidButton().getAttribute("aria-label")).toBe(name);
    expect(groundAidButton().getAttribute("title")).toBe(name);
    click(groundAidButton());
    expect(onGroundAidChange).toHaveBeenLastCalledWith(next);
    expect(window.localStorage.getItem("usc.groundAid")).toBe(next);
    expect(rememberedGroundAid()).toBe(next);
  }
  window.localStorage.setItem("usc.groundAid", "something else");
  expect(rememberedGroundAid()).toBe("grid");
});

test("the remembered ground aid is the ground grid when this browser blocks its storage", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("storage is blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage is blocked"); });
  try {
    expect(rememberedGroundAid()).toBe("grid");
    const onGroundAidChange = vi.fn();
    rendered = renderForTest(<ViewToolbar {...TOOLBAR_CALLBACKS} theme="light" groundAid="grid" onGroundAidChange={onGroundAidChange} />);
    click(rendered.container.querySelector(".viewer-ground-aid-button")!);
    expect(onGroundAidChange).toHaveBeenCalledWith("compass_ring");     // the choice lasts for this page
  } finally {
    vi.restoreAllMocks();
  }
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

test("a layers menu entry with parts lists a check box and a swatch for each, and reports a part's change with its id", () => {
  const onVisibleChange = vi.fn(), onPartVisibleChange = vi.fn();
  rendered = renderForTest(
    <LayersMenu theme="light" skyDomeOpacity={0.6} onVisibleChange={onVisibleChange} onPartVisibleChange={onPartVisibleChange} onSkyDomeOpacityChange={() => {}}
                entries={[{ name: "test_surfaces", available: true, visible: true,
                            parts: [{ id: "a", label: "Winter sun", colour: "#4477aa", visible: true }, { id: "b", label: "Spring sun (off)", colour: "#ee6677", visible: false }] }]} />);
  click(rendered.container.querySelector("button")!);
  const [parent, first, second] = [...rendered.container.querySelectorAll<HTMLLIElement>(".viewer-layers-panel li")];
  expect([first.textContent, second.textContent]).toEqual(["Winter sun", "Spring sun (off)"]);
  expect([first, second].map((item) => item.querySelector<HTMLElement>(".viewer-criterion-swatch")!.style.backgroundColor)).toEqual(["rgb(68, 119, 170)", "rgb(238, 102, 119)"]);
  expect([first, second].map((item) => item.querySelector("input")!.checked)).toEqual([true, false]);
  expect(parent.contains(first)).toBe(true);          // the parts are a list inside the entry
  click(second.querySelector("input")!);
  expect(onPartVisibleChange).toHaveBeenCalledWith("test_surfaces", "b", true);
  click(parent.querySelector("input")!);
  expect(onVisibleChange).toHaveBeenCalledWith("test_surfaces", false);
});

test("the overlay styles take every colour from the tokens and keep the toolbar focus outline visible", () => {
  const overlaysCss = readFileSync("src/viewer_overlays/overlays.css", "utf8");
  expect(overlaysCss).not.toMatch(/#[0-9a-f]{3,6}|rgb\(/i);
  expect(overlaysCss).toMatch(/\.viewer-toolbar button {[^}]*outline-offset: -2px/);
});

const EMPTY_VIEW: ViewerPaneProps = {
  maxVolume: null, testSurfaces: [], sunPath: null, hemisphere: null, maxVolumeAppearance: "solid", shownByDefault: [], northDegrees: 0,
  framingRequest: 0, centreContent: null,
};

test("without WebGL (jsdom has none, like a remote desktop) the view says so, and the run progress and the run report still show", () => {
  pretendTheBrowserHasNoWebGl();
  rendered = renderForTest(<ViewerPane {...EMPTY_VIEW} runProgress={0.5} overlayContent={<div className="run-report-panel">Run report</div>} />);
  const unavailable = rendered.container.querySelector(".viewer-unavailable")!;
  expect(unavailable.textContent).toBe(messages.viewerNeedsWebGl);
  expect(unavailable.getAttribute("role")).toBe("status");
  expect(rendered.container.querySelector("canvas")).toBeNull();
  expect(rendered.container.querySelector("[role='progressbar']")!.getAttribute("aria-valuenow")).toBe("50");
  expect(rendered.container.querySelector(".run-report-panel")!.textContent).toBe("Run report");
  expect(rendered.container.querySelector(".viewer-toolbar")).toBeNull();      // no controls for a view that is not there
  expect(unavailable.textContent).toContain("for example over a remote desktop, or when the graphics card is blocked");
});

test("the view is light or dark with the app's theme: the overlay content (Simulate's legend) is given the theme", () => {
  pretendTheBrowserHasNoWebGl();
  const overlayContent = (theme: string) => <div className="run-report-panel">{theme}</div>;
  rendered = renderForTest(<AppThemeProvider value="dark"><ViewerPane {...EMPTY_VIEW} overlayContent={overlayContent} /></AppThemeProvider>);
  expect(rendered.container.querySelector(".run-report-panel")!.textContent).toBe("dark");
  rendered.rerender(<AppThemeProvider value="light"><ViewerPane {...EMPTY_VIEW} overlayContent={overlayContent} /></AppThemeProvider>);
  expect(rendered.container.querySelector(".run-report-panel")!.textContent).toBe("light");
});

test("without WebGL the empty project's way to start (the hint, Add files, the examples) stays under the message", () => {
  pretendTheBrowserHasNoWebGl();
  const emptyState = <div className="viewer-empty-state"><p>{messages.noInputsYet}</p><button type="button">{messages.addFiles}</button></div>;
  rendered = renderForTest(<ViewerPane {...EMPTY_VIEW} centreContent={emptyState} />);
  const texts = [...rendered.container.querySelectorAll(".viewer-pane p, .viewer-pane button")].map((element) => element.textContent);
  expect(texts).toEqual([messages.viewerNeedsWebGl, messages.noInputsYet, messages.addFiles]);
});

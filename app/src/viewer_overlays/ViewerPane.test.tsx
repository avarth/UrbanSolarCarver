import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as THREE from "three";
import type { SkyDome } from "../api_client/client";
import { decodeCarvedByCriterion } from "../viewer/carved_by_criterion_decoder";
import { packCarvedByCriterion } from "../viewer/packed_results_for_test";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { FakeViewerScene, pretendTheBrowserHasWebGl } from "../viewer/fake_scene_for_test";
import { Legend } from "./Legend";
import { click, renderForTest, type RenderedOverlay } from "./render_for_test";
import { NO_VIEWER_RESULTS, ViewerPane, type TestSurfaceGroup, type ViewerPaneProps } from "./ViewerPane";

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
    maxVolume: null, testSurfaces: [], sunPath: null, hemisphere: { centre: [0, 0, 0], radius: 30 }, maxVolumeAppearance: "ghost",
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
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} testSurfaces={[group("1", "#4477aa", new BoxGeometry(1, 1, 0.1))]} context={new BoxGeometry(2, 2, 2)}
                                       terrain={new BoxGeometry(50, 50, 0.1)} shownByDefault={LAYERS_SHOWN_IN_STEP.inputs} />);
  expect(FakeViewerScene.latest!.layersWithObjects()).toEqual(expect.arrayContaining(["context", "terrain"]));
  expect(FakeViewerScene.latest!.visibleLayers.has("context")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("terrain")).toBe(true);
  click(rendered.container.querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!);
  const names = [...rendered.container.querySelectorAll(".viewer-layers-panel label")].map((label) => label.textContent);
  expect(names.slice(0, 3)).toEqual(["Test surfaces", "Existing surroundings", "Terrain"]);
  for (const step of Object.values(LAYERS_SHOWN_IN_STEP)) expect(step).toEqual(expect.arrayContaining(["context", "terrain"]));
});

const CRITERIA = [
  { id: "1", name: "Winter sun on facades", colour: "#4477aa" },
  { id: "2", name: "Spring sun on windows", colour: "#ee6677" },
  { id: "3", name: "Daylight on roofs", colour: "#228833" },
];
// Two voxels of a (2, 2, 1) grid were carved: one by the first criterion that was on (id 1), one by the second (id 3).
const CARVED_BY = decodeCarvedByCriterion(packCarvedByCriterion([2, 2, 1], ["1", "3"], [0, 1, 2, 0]));

function viewCarvedBy(shownByDefault: ViewerPaneProps["shownByDefault"]): ViewerPaneProps {
  return { ...viewWithSkyDome("daylight"), shownByDefault, results: { ...NO_VIEWER_RESULTS, carvedByCriterion: CARVED_BY }, criteria: CRITERIA };
}

const hexOf = (colour: string) => new THREE.Color(colour).getHexString();

test("test the carved-by-criterion layer colours each voxel by its criterion", () => {
  rendered = renderForTest(<ViewerPane {...viewCarvedBy([])} />);
  expect(FakeViewerScene.latest!.layers.get("carved_by_criterion") ?? null).toBeNull();   // hidden: not built until the Layers menu turns it on
  click(rendered.container.querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!);
  const entry = [...rendered.container.querySelectorAll<HTMLLabelElement>(".viewer-layers-panel label")].find((label) => label.textContent === "Carved voxels, by criterion")!;
  click(entry.querySelector("input")!);
  expect(FakeViewerScene.latest!.visibleLayers.has("carved_by_criterion")).toBe(true);
  const layer = FakeViewerScene.latest!.layers.get("carved_by_criterion") as THREE.InstancedMesh;
  const colourOf = (voxel: number) => {
    const colour = new THREE.Color();
    layer.getColorAt(voxel, colour);
    return colour.getHexString();
  };
  expect(layer.count).toBe(2);
  expect([colourOf(0), colourOf(1)]).toEqual([hexOf("#4477aa"), hexOf("#228833")]);      // the criteria 1 and 3, in their own colours
  click(entry.querySelector("input")!);                                                    // hidden again: the cubes are dropped
  expect(FakeViewerScene.latest!.layers.get("carved_by_criterion") ?? null).toBeNull();
});

test("the legend of the carved-by-criterion layer says when the voxels drawn are thinned, and only then", () => {
  const criteria = [{ name: "Winter sun on facades", colour: "#4477aa" }];
  rendered = renderForTest(<Legend content={{ carvedByCriterion: { criteria, thinningStep: 3 } }} theme="light" />);
  expect(rendered.container.querySelector(".viewer-legend")!.textContent).toContain("Showing 1 of every 3 voxels");
  rendered.rerender(<Legend content={{ carvedByCriterion: { criteria, thinningStep: 1 } }} theme="light" />);
  expect(rendered.container.querySelector(".viewer-legend")!.textContent).not.toContain("Showing 1 of every");
});

test("test the legend names each criterion", () => {
  rendered = renderForTest(<ViewerPane {...viewCarvedBy([])} />);
  expect(rendered.container.querySelector(".viewer-legend")).toBeNull();                  // hidden layer, no legend
  rendered.rerender(<ViewerPane {...viewCarvedBy(["carved_by_criterion"])} />);
  const items = [...rendered.container.querySelectorAll<HTMLElement>(".viewer-legend .viewer-criterion-legend li")];
  expect(items.map((item) => item.textContent)).toEqual(["Winter sun on facades", "Daylight on roofs"]);      // the criteria that were on, not criterion 2
  expect(items.map((item) => item.querySelector<HTMLElement>(".viewer-criterion-swatch")!.style.backgroundColor)).toEqual(["rgb(68, 119, 170)", "rgb(34, 136, 51)"]);
});

const BOX = () => new THREE.BoxGeometry(1, 1, 0.1);
const group = (id: string, colour: string | null, geometry: THREE.BufferGeometry | null, extra: Partial<TestSurfaceGroup> = {}): TestSurfaceGroup =>
  ({ id, name: `Criterion ${id}`, colour, off: false, shown: true, geometry, ...extra });
const TWO_GROUPS = () => [group("1", "#4477aa", BOX()), group("2", "#ee6677", BOX())];
const menuEntries = () => [...rendered!.container.querySelectorAll<HTMLLIElement>(".viewer-layers-panel li")];
const openLayersMenu = () => click(rendered!.container.querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!);
const testSurfacesView = (testSurfaces: TestSurfaceGroup[], onChange = vi.fn()): ViewerPaneProps =>
  ({ ...viewWithSkyDome("daylight"), results: NO_VIEWER_RESULTS, shownByDefault: ["test_surfaces"], testSurfaces, onTestSurfacesShownChange: onChange });
const materialOf = (object: THREE.Object3D) => (object as THREE.Mesh).material as THREE.MeshLambertMaterial;

test("each criterion's test surfaces are one mesh in its colour, all at full strength; a criterion that is hidden draws nothing", () => {
  rendered = renderForTest(<ViewerPane {...testSurfacesView(TWO_GROUPS())} />);
  const layer = () => FakeViewerScene.latest!.layers.get("test_surfaces")!;
  const meshes = () => layer().children.map((child) => ({ name: child.name, colour: materialOf(child).color.getHexString(), opacity: materialOf(child).opacity }));
  expect(meshes()).toEqual([{ name: "1", colour: hexOf("#4477aa"), opacity: 1 }, { name: "2", colour: hexOf("#ee6677"), opacity: 1 }]);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  rendered.rerender(<ViewerPane {...testSurfacesView([group("1", "#4477aa", BOX()), group("2", "#ee6677", null, { shown: false })])} />);
  expect(meshes().map(({ name }) => name)).toEqual(["1"]);
  rendered.rerender(<ViewerPane {...testSurfacesView([group("1", "#4477aa", null, { shown: false }), group("2", "#ee6677", null, { shown: false })])} />);
  expect(FakeViewerScene.latest!.layers.get("test_surfaces") ?? null).toBeNull();
});

test("a criterion's test surfaces, with no maximum volume, still make the test surfaces layer", () => {
  rendered = renderForTest(<ViewerPane {...testSurfacesView([group("1", "#4477aa", BOX())])} />);
  expect(FakeViewerScene.latest!.layersWithObjects()).toContain("test_surfaces");
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
});

test("without test surfaces there is no Test surfaces entry; with every criterion hidden there still is, so they can be shown again", () => {
  rendered = renderForTest(<ViewerPane {...testSurfacesView([group("1", "#4477aa", null), group("2", "#ee6677", null)])} />);
  expect(FakeViewerScene.latest!.layersWithObjects()).not.toContain("test_surfaces");
  rendered.rerender(<ViewerPane {...testSurfacesView([group("1", "#4477aa", null, { shown: false }), group("2", "#ee6677", null, { shown: false })])} />);
  openLayersMenu();
  expect(menuEntries().map((item) => item.querySelector("label")!.textContent)).toEqual(["Test surfaces", "Criterion 1", "Criterion 2"]);
  expect(menuEntries().map((item) => item.querySelector("input")!.checked)).toEqual([false, false, false]);
});

test("with two or more criteria the Test surfaces entry has a sub-entry for each, in chain order, with its swatch; a criterion that is off says so", () => {
  rendered = renderForTest(<ViewerPane {...testSurfacesView([group("1", "#4477aa", BOX()), group("2", "#ee6677", BOX(), { off: true })])} />);
  openLayersMenu();
  const [parent, ...subs] = menuEntries();
  expect(parent.querySelector("label")!.textContent).toBe("Test surfaces");
  expect(parent.querySelector("input")!.checked).toBe(true);
  expect(subs.map((item) => item.textContent)).toEqual(["Criterion 1", "Criterion 2 (off)"]);
  expect(subs.map((item) => item.querySelector<HTMLElement>(".viewer-criterion-swatch")!.style.backgroundColor)).toEqual(["rgb(68, 119, 170)", "rgb(238, 102, 119)"]);
  expect(subs.map((item) => item.querySelector("input")!.checked)).toEqual([true, true]);
});

test("a sub-entry's check box shows or hides that criterion's test surfaces only", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<ViewerPane {...testSurfacesView(TWO_GROUPS(), onChange)} />);
  openLayersMenu();
  click(menuEntries()[2].querySelector("input")!);
  expect(onChange).toHaveBeenLastCalledWith(["2"], false);
  rendered.rerender(<ViewerPane {...testSurfacesView([group("1", "#4477aa", BOX()), group("2", "#ee6677", null, { shown: false })], onChange)} />);
  expect(menuEntries().map((item) => item.querySelector("input")!.checked)).toEqual([true, true, false]);       // the entry stays checked while one is shown
  click(menuEntries()[2].querySelector("input")!);
  expect(onChange).toHaveBeenLastCalledWith(["2"], true);
});

test("the Test surfaces check box shows or hides all the criteria's test surfaces; it is unchecked when none is shown", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<ViewerPane {...testSurfacesView(TWO_GROUPS(), onChange)} />);
  openLayersMenu();
  click(menuEntries()[0].querySelector("input")!);
  expect(onChange).toHaveBeenLastCalledWith(["1", "2"], false);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(false);
  expect(menuEntries().map((item) => item.querySelector("input")!.checked)).toEqual([false, false, false]);
  click(menuEntries()[0].querySelector("input")!);
  expect(onChange).toHaveBeenLastCalledWith(["1", "2"], true);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  rendered.rerender(<ViewerPane {...testSurfacesView([group("1", "#4477aa", null, { shown: false }), group("2", "#ee6677", null, { shown: false })], onChange)} />);
  expect(menuEntries().map((item) => item.querySelector("input")!.checked)).toEqual([false, false, false]);       // all hidden by their own check boxes
});

test("checking a sub-entry while the whole layer is hidden shows that criterion alone", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<ViewerPane {...testSurfacesView(TWO_GROUPS(), onChange)} shownByDefault={[]} />);
  openLayersMenu();
  expect(menuEntries().map((item) => item.querySelector("input")!.checked)).toEqual([false, false, false]);       // the layer is not shown in this step
  click(menuEntries()[1].querySelector("input")!);
  expect(onChange.mock.calls).toEqual([[["2"], false], [["1"], true]]);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
});

test("with one criterion the menu keeps a single Test surfaces entry, drawn in that criterion's colour", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<ViewerPane {...testSurfacesView([group("1", "#4477aa", BOX())], onChange)} />);
  openLayersMenu();
  expect(menuEntries().map((item) => item.querySelector("label")!.textContent)).toEqual(["Test surfaces"]);
  expect(materialOf(FakeViewerScene.latest!.layers.get("test_surfaces")!.children[0]).color.getHexString()).toBe(hexOf("#4477aa"));
  click(menuEntries()[0].querySelector("input")!);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(false);
  expect(onChange).not.toHaveBeenCalled();           // the one criterion has no entry of its own: the layer is what is hidden
});

test("a layer listed as missing says no result for it, and cannot be turned on", () => {
  rendered = renderForTest(<ViewerPane {...viewWithSkyDome("daylight")} missingLayers={["carved_by_criterion"]} />);
  click(rendered.container.querySelector<HTMLButtonElement>(".viewer-layers-menu > button")!);
  const entry = [...rendered.container.querySelectorAll<HTMLElement>(".viewer-layers-panel li")].find((item) => item.textContent!.includes("Carved voxels, by criterion"))!;
  expect(entry.querySelector("input")!.disabled).toBe(true);
  expect(entry.querySelector(".viewer-layer-note")!.textContent).toBe("Shows once every criterion that is on has run.");
});

test("a dimmed carved-by-criterion layer is drawn dimmed, and the stamp says so while it is shown", () => {
  rendered = renderForTest(<ViewerPane {...viewCarvedBy(["carved_by_criterion"])} dimmedLayers={["carved_by_criterion"]} />);
  expect(FakeViewerScene.latest!.dimmed.has("carved_by_criterion")).toBe(true);
  expect(rendered.container.querySelector(".viewer-out-of-date")).not.toBeNull();
});

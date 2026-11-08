// The 3D view beside the step panel (UX 4, 8): the scene and its overlays, the layers built from what the project has so far.
// Each step shows its own layers by default (UX 8.2); the layers menu turns them on and off until another step opens.
// The sky dome is the exception: once hidden in the menu it stays hidden on this computer until shown again.
// The maximum volume is a light solid in Inputs, Mode and Settings and a ghost, off by default, in the later steps. Result
// layers that are out of date, or being replaced by a run, are dimmed (UX 6.3), and while one of them is shown a stamp at the top
// of the view says so ("Out of date", or "Updating" during a run); a thin bar along the top shows a run's progress. In Simulate
// the selected study's values are one more layer, dimmed when the study is out of date, and the stamp shows while it is.
// In Inspect the orientation of the test surfaces is one more layer, which replaces the test surfaces in the view; a click on a surface
// is reported, and a request to frame a box moves the camera. Simulate's sun tool draws the year's sun path with the chosen day and
// the sun (the sun_study layer) and the shadows at that time (the scene's setSunStudy). The sun tool's button is in the toolbar, its
// panel (given by the workspace) under it, in every workspace.
// Without WebGL (a remote desktop, a blocked graphics card) the scene cannot start: the view says so, and the steps go on working.
// Framing leaves out the part of the view a panel lies over (leftInsetOf), so the model is never hidden behind it; the picture shifts and the camera still orbits about the centre of the compass ring.
// The shift follows the panels as they open, close or resize, and the window as it resizes (watchPanelsCoveringView), so that point stays in the middle of the free part of the view.
import { useEffect, useEffectEvent, useMemo, useRef, useState, type ReactNode } from "react";
import type * as THREE from "three";
import type { RunSummary, SkippedSurfaces, SkyDome } from "../api_client/client";
import { useChangedDuringRender } from "../hooks/use_changed_during_render";
import { messages } from "../messages";
import { carvedVoxelsByCriterion, type CarvedByCriterion } from "../viewer/carved_by_criterion_decoder";
import { colourToken, keptScoreRange } from "../viewer/colour_scales";
import type { StudyView } from "../viewer/study_values";
import { patchCorners } from "../viewer/study_values_decoder";
import {
  buildingMassingLayer, carvedByCriterionLayer, carvedVoxelsLayer, contextLayer, envelopeLayer, inspectSurfacesLayer, keptColumnTops, keptVoxelsLayer, maxVolumeLayer,
  skippedSurfacesLayer, skyDomeLayer, splitScorePoints, storeyOfPart, studyValuesLayer, sunPathLayer, sunStudyLayer, terrainLayer, testSurfacesLayer, volumeOutline, type InspectLayerFile, type MaxVolumeAppearance,
  type VolumeOutline,
} from "../viewer/layers";
import { layerHooks } from "../viewer/layer_hooks";
import type { Point3 } from "../viewer/local_origin";
import { DEFAULT_SKY_DOME_OPACITY, ViewerScene, type CameraState, type GroundAid, type LayerName, type ViewportTheme } from "../viewer/scene";
import { voxelCentres, type ScorePoints } from "../viewer/score_points_decoder";
import type { Hemisphere } from "../viewer/sky_dome";
import { sunPathLegend, sunPathObjects, type SunPathWithNorth } from "../viewer/sun_path";
import { sunStudyObjects } from "../viewer/sun_study";
import type { SunStudyView } from "../viewer/sun_study";
import { useAppTheme } from "../theme/app_theme";
import { AxisGizmo } from "./AxisGizmo";
import { Compass } from "./Compass";
import { LayersMenu, type LayersMenuEntry } from "./LayersMenu";
import { Legend, type LegendContent } from "./Legend";
import { ScaleBar } from "./ScaleBar";
import { useKeyedValue } from "../hooks/use_keyed_value";
import { useSceneLayers } from "./use_scene_layers";
import { rememberedGroundAid, ViewToolbar } from "./ViewToolbar";
import "./overlays.css";

const PANELS_COVERING_VIEW = "[data-covers-view-left], .workspace-panel";

/**
 * How many pixels of *view*'s left side a panel lies over: a floating panel marked data-covers-view-left (Simulate's studies, Inspect's
 * files), or the step panel when a narrow window lays it over the view. A panel beside the view, or in its right half, covers nothing.
 */
export function leftInsetOf(view: HTMLElement): number {
  const viewRect = view.getBoundingClientRect();
  let inset = 0;
  for (const panel of document.querySelectorAll<HTMLElement>(PANELS_COVERING_VIEW)) {
    if (panel.hidden) continue;
    const rect = panel.getBoundingClientRect();
    if (rect.width === 0 || rect.bottom <= viewRect.top || rect.top >= viewRect.bottom || rect.left > viewRect.left + viewRect.width / 2) continue;
    inset = Math.max(inset, rect.right - viewRect.left);
  }
  return inset;
}

/**
 * Calls *changed*, at most once a frame, when what the panels cover of *view* may have changed: the view or a panel resized, a panel
 * opened, closed or shown (another workspace). Returns the function that stops watching.
 */
export function watchPanelsCoveringView(view: HTMLElement, changed: () => void): () => void {
  let frame: number | null = null;
  const queue = () => {
    if (frame === null) frame = requestAnimationFrame(() => { frame = null; changed(); });
  };
  // Every browser the app supports has ResizeObserver; the test environment (jsdom) does not, and there only the mutations are watched
  const resizes = typeof ResizeObserver === "function" ? new ResizeObserver(queue) : null;
  const watched = new Set<Element>();
  const watchPanels = () => {
    for (const panel of document.querySelectorAll(PANELS_COVERING_VIEW)) {
      if (watched.has(panel)) continue;
      watched.add(panel);
      resizes?.observe(panel);
    }
  };
  resizes?.observe(view);
  watchPanels();
  const mutations = new MutationObserver(() => { watchPanels(); queue(); });
  mutations.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
  return () => {
    mutations.disconnect();
    resizes?.disconnect();
    if (frame !== null) cancelAnimationFrame(frame);
  };
}

const SKY_DOME_HIDDEN_KEY = "usc.skyDomeHidden";

/** Whether the user hid the sky dome on this computer (it then starts hidden until shown again); false when storage is blocked. */
function rememberedSkyDomeHidden(): boolean {
  try {
    return window.localStorage.getItem(SKY_DOME_HIDDEN_KEY) === "true";
  } catch {
    return false;
  }
}

function rememberSkyDomeHidden(hidden: boolean): void {
  try {
    if (hidden) window.localStorage.setItem(SKY_DOME_HIDDEN_KEY, "true");
    else window.localStorage.removeItem(SKY_DOME_HIDDEN_KEY);
  } catch {
    // storage is blocked: the choice lasts for this view only
  }
}

/** The line under the skipped surfaces in the layers menu: how many, counted by reason. */
export function skippedSurfacesLine({ surface_count, surfaces }: SkippedSurfaces): string {
  const counts = new Map<string, number>();
  for (const { reason } of surfaces) counts.set(reason, (counts.get(reason) ?? 0) + 1);
  const why = [...counts].map(([reason, count]) => `${count} ${messages.skippedSurfaceReasons[reason] ?? reason}`).join(", ");
  return messages.skippedSurfacesLine(surfaces.length, surface_count, why);
}

/** What the runs have produced for the view; each is null until its stage has written it. */
export interface ViewerResults {
  scorePoints: ScorePoints | null;
  carving: RunSummary["carving"];
  skyDome: SkyDome | null;
  /** The test surfaces of the criterion shown that the run left out; null when it left none out. */
  skippedSurfaces: SkippedSurfaces | null;
  envelope: THREE.BufferGeometry | null;
  massing: THREE.BufferGeometry | null;
  /** Which criterion removed each voxel; null with fewer than two criteria on, or until every one has run. */
  carvedByCriterion: CarvedByCriterion | null;
}

export const NO_VIEWER_RESULTS: ViewerResults = { scorePoints: null, carving: null, skyDome: null, skippedSurfaces: null, envelope: null, massing: null, carvedByCriterion: null };

/** What the carved-by-criterion layer and its legend need of a criterion. */
export interface CriterionSwatch {
  id: string;
  name: string;
  colour: string;       // "#RRGGBB"
}

/** The test surfaces of one criterion: drawn in its colour, listed under "Test surfaces" in the layers menu when there are two or more. */
export interface TestSurfaceGroup {
  id: string;
  name: string;
  colour: string | null;        // "#RRGGBB"; null: the accent colour (a project that lists no criteria)
  off: boolean;                 // the criterion is switched off: its entry says so
  shown: boolean;               // its entry is checked
  geometry: THREE.BufferGeometry | null;      // the files drawn in its colour; null when it has none, or is not shown
}

/** What Inspect shows: the files as the surface orientation layer draws them, and what the view reports back. */
export interface InspectView {
  files: InspectLayerFile[];
  arrows: boolean;
  /** A click on a surface of a file. */
  onSurfaceClick: (fileName: string, surface: number) => void;
  /** The box to bring into view (local coordinates); a new *request* number moves the camera, the same one does not. */
  frame: { min: Point3; max: Point3; request: number } | null;
}

export interface ViewerPaneProps {
  maxVolume: THREE.BufferGeometry | null;
  /** The test surfaces by criterion, in chain order; a project without criteria has one group without a colour. */
  testSurfaces: readonly TestSurfaceGroup[];
  /** The groups whose entries were checked or unchecked in the layers menu (the pane does not keep which are shown). */
  onTestSurfacesShownChange?: (groupIds: readonly string[], shown: boolean) => void;
  /** The criteria that are on, for the colours and names of the carved-by-criterion layer. */
  criteria?: readonly CriterionSwatch[];
  /** The existing surroundings and the terrain, when the project has them. */
  context?: THREE.BufferGeometry | null;
  terrain?: THREE.BufferGeometry | null;
  /** The sun path of the stored settings; it turns by the North shown since (*northDegrees*), as the compass ring does. */
  sunPath: SunPathWithNorth | null;
  /**
   * Where the sun path and the sky dome are drawn, and the compass ring lies: around the maximum volume and the test surfaces
   * together (R2 2).
   */
  hemisphere: Hemisphere | null;
  maxVolumeAppearance: MaxVolumeAppearance;
  /** The layers the open step shows; a change of step brings these back. */
  shownByDefault: readonly LayerName[];
  northDegrees: number;
  /** Changing this number frames everything visible (the inputs changed). */
  framingRequest: number;
  /** Shown in the middle of the view, over the grid (the empty state of UX 11). */
  centreContent: ReactNode;
  results?: ViewerResults;
  /** The local origin the score points are placed in, as the meshes are. */
  localOrigin?: Point3;
  /** Result layers drawn dimmed: out of date, or waiting for the run under way. */
  dimmedLayers?: readonly LayerName[];
  /** Result layers listed in the layers menu without data: the last run stopped before their stage. */
  missingLayers?: readonly LayerName[];
  /** What the layers menu says under a missing layer, where it is not the run stopping before its stage (Simulate's sky dome). */
  missingLayerNotes?: Partial<Record<LayerName, string>>;
  /** How far the run under way is, 0 to 1; null without a run. */
  runProgress?: number | null;
  /**
   * Whether the sky dome shown is the analysis' (Carve), whose choice to hide it is remembered on this computer and applies; false
   * for Simulate's study dome, which neither reads nor writes that choice. Absent: true.
   */
  skyDomeChoiceRemembered?: boolean;
  /** Shown over the view (the run report). A function is given the viewport theme (Simulate's legend colours follow it). */
  overlayContent?: ReactNode | ((theme: ViewportTheme) => ReactNode);
  /** The mode the form shows. */
  mode?: string | null;
  /** The analysis (preprocessing) is current: it was made in the mode the form shows. */
  analysisCurrent?: boolean;
  /** The sky dome legend's title for a dome that is not Design's (Simulate's study dome); Design's names the mode it was made in. */
  skyDomeTitle?: string;
  /** The study Simulate shows, drawn as the study_values layer (dimmed when out of date); null for none. */
  study?: StudyView | null;
  /** The study selected in Simulate is out of date: the stamp shows, whether or not its values are drawn. */
  studyOutOfDate?: boolean;
  /** The envelope is drawn see-through even without the building massing (Simulate's envelope). */
  envelopeSeeThrough?: boolean;
  /** Inspect: while set, the test surfaces are hidden and the surface orientation layer is shown in their place. */
  inspect?: InspectView | null;
  /** The sun tool: the sun path, the sun and its shadows; null: none. */
  sunStudy?: SunStudyView | null;
  /** The sun tool's button in the toolbar and, while open, its panel under it; null: no sun tool (no project open). */
  sunTool?: { open: boolean; onToggle: () => void; panel: ReactNode } | null;
  /** A tool drawn over the view that needs the scene (drawing and editing sites, sites/SiteEditor.tsx); null: none. */
  sceneTool?: ((scene: ViewerScene) => ReactNode) | null;
}

const NO_CAMERA: CameraState = { yawDegrees: 0, elevationDegrees: 90, metresPerPixel: 0 };
const NO_SHIFT: Point3 = [0, 0, 0];
const NO_LAYERS: readonly LayerName[] = [];
const EMPTY_OUTLINE: VolumeOutline = { segments: new Float32Array(0), outwardNormals: new Float32Array(0) };
const NO_CRITERIA: readonly CriterionSwatch[] = [];
const RESULT_LAYERS: readonly LayerName[] = ["skipped_surfaces", "kept_voxels", "carved_voxels", "carved_by_criterion", "sky_dome", "envelope", "building_massing"];
const WEBGL_CONTEXT = "webgl2";     // what three.js's WebGLRenderer asks the canvas for

/**
 * The mode the sky dome on screen was analysed in, for its legend: the one its score points name; without them, the form's mode
 * while the analysis is current; else null (no mode named), since the form's mode may not be the one the dome on screen was made in.
 */
export function analysedSkyDomeMode(scorePointsMode: string | null, formMode: string | null, analysisCurrent: boolean): string | null {
  return scorePointsMode ?? (analysisCurrent ? formMode : null);
}

/** Whether the browser gives a canvas a WebGL context; the test context is freed again at once. */
function browserHasWebGl(): boolean {
  const context = document.createElement("canvas").getContext(WEBGL_CONTEXT) as WebGL2RenderingContext | null;
  context?.getExtension?.("WEBGL_lose_context")?.loseContext();
  return context !== null;
}

/** The number of storeys of a building massing mesh: the highest storey of its parts, plus one. */
function storeyCountOf(massing: THREE.BufferGeometry): number {
  const partNames: string[] = massing.userData.partNames ?? [];
  return partNames.reduce((count, name) => Math.max(count, (storeyOfPart(name) ?? 0) + 1), 0);
}

export function ViewerPane({ maxVolume, testSurfaces, onTestSurfacesShownChange, criteria = NO_CRITERIA, context = null, terrain = null, sunPath, hemisphere,
                             maxVolumeAppearance, shownByDefault,
                             northDegrees, framingRequest, centreContent, results = NO_VIEWER_RESULTS, localOrigin = NO_SHIFT, dimmedLayers = NO_LAYERS,
                             missingLayers = NO_LAYERS, missingLayerNotes, runProgress = null, overlayContent, mode = null,
                             analysisCurrent = false, skyDomeTitle, skyDomeChoiceRemembered = true, study = null, studyOutOfDate = false, envelopeSeeThrough = false, inspect = null, sunStudy = null, sunTool = null,
                             sceneTool = null }: ViewerPaneProps) {
  const container = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState<ViewerScene | null>(null);
  const [sceneUnavailable] = useState(() => !browserHasWebGl());
  const [camera, setCamera] = useState<CameraState>(NO_CAMERA);
  const theme: ViewportTheme = useAppTheme();
  const [groundAid, setGroundAid] = useState<GroundAid>(rememberedGroundAid);
  const [visibleByChoice, setVisibleByChoice] = useState<Partial<Record<LayerName, boolean>>>({});
  // The sky dome shows where the step shows it, so a first sky-based run shows what it weighed; hidden by the user, it stays hidden
  // (across steps, projects and launches on this computer) until shown again.
  const [skyDomeHidden, setSkyDomeHidden] = useState(rememberedSkyDomeHidden);
  const [skyDomeOpacity, setSkyDomeOpacity] = useState(DEFAULT_SKY_DOME_OPACITY);
  // A change of step brings back its layers: the choices made in the menu are dropped.
  useChangedDuringRender(shownByDefault.join(","), () => setVisibleByChoice({}));
  const { scorePoints, carving, skyDome, skippedSurfaces, envelope, massing, carvedByCriterion } = results;
  const origin = useKeyedValue(localOrigin, localOrigin.join(","));

  useEffect(() => {
    if (sceneUnavailable) return;
    let viewer: ViewerScene;
    try {
      viewer = new ViewerScene(container.current!);
    } catch (error) {
      // A fault of the scene, not a missing WebGL: said in the console; the view stays empty and the steps go on working
      console.error(error);
      return;
    }
    const stopListening = viewer.onCameraChange(setCamera);
    viewer.setLeftInsetSource(() => leftInsetOf(container.current!));
    const stopWatchingPanels = watchPanelsCoveringView(container.current!, () => viewer.fitPictureToPanels());
    setScene(viewer);
    return () => {
      stopWatchingPanels();
      stopListening();
      viewer.dispose();
      setScene(null);
    };
  }, [sceneUnavailable]);

  useEffect(() => scene?.setViewportTheme(theme), [scene, theme]);
  useEffect(() => scene?.setGroundAid(groundAid), [scene, groundAid]);
  useEffect(() => scene?.setNorth(northDegrees), [scene, northDegrees]);
  useEffect(() => scene?.setSceneHemisphere(hemisphere), [scene, hemisphere]);
  useEffect(() => scene?.setSkyDomeOpacity(skyDomeOpacity), [scene, skyDomeOpacity]);

  // The objects of the layers, each made again when what it is drawn from changes (and for a new scene), and only once there is a
  // scene. Every layer gets its own copy of the geometry: the scene disposes a layer's objects when the layer is replaced.
  const maxVolumeObject = useMemo(() => scene && maxVolume && maxVolumeLayer(maxVolume.clone(), maxVolumeAppearance), [scene, maxVolume, maxVolumeAppearance]);
  const testSurfacesObject = useMemo(() => {
    if (scene === null) return null;
    const parts = testSurfaces.flatMap(({ id, colour, shown, geometry }) => (shown && geometry !== null ? [{ name: id, colour, geometry: geometry.clone() }] : []));
    return parts.length > 0 ? testSurfacesLayer(parts) : null;
  }, [scene, testSurfaces]);
  const contextObject = useMemo(() => scene && context && contextLayer(context.clone()), [scene, context]);
  const terrainObject = useMemo(() => scene && terrain && terrainLayer(terrain.clone()), [scene, terrain]);
  const sunPathObject = useMemo(() => {
    const northTurnDegrees = sunPath === null ? 0 : northDegrees - sunPath.northDegrees;
    return scene && sunPath && hemisphere && sunPathLayer(sunPathObjects(sunPath.path, hemisphere, northTurnDegrees), hemisphere);
  }, [scene, sunPath, hemisphere, northDegrees]);

  // The voxels need the mask and the cutoff of a carving: score points without them (the carving did not run) are not drawn.
  const voxels = useMemo(() => {
    if (scorePoints === null || scorePoints.kept === null || carving === null) return null;
    return splitScorePoints(scorePoints, voxelCentres(scorePoints.header, scorePoints.indices, origin));
  }, [scorePoints, carving, origin]);
  const outline = useMemo(() => (maxVolume ? volumeOutline(maxVolume) : EMPTY_OUTLINE), [maxVolume]);
  const keptVoxelsObject = useMemo(() => scene && voxels && carving && scorePoints && keptVoxelsLayer({
    voxels: voxels.kept, voxelSize: scorePoints.header.voxel_size, colourRange: keptScoreRange(carving.threshold_value), voxelCount: carving.voxels_kept,
  }), [scene, voxels, carving, scorePoints]);
  const carvedVoxelsObject = useMemo(() => scene && voxels && carving && scorePoints && carvedVoxelsLayer({
    voxels: voxels.carved, voxelSize: scorePoints.header.voxel_size, voxelCount: carving.voxels_removed, outline, keptTopAt: keptColumnTops(scorePoints, origin),
  }), [scene, voxels, carving, scorePoints, outline, origin]);
  // Each carved voxel in the colour of the criterion that removed it, whose id the layer names; the layer is drawn again when a colour
  // changes. It is a layer of up to a million cubes that starts hidden: it is built (and the voxels listed, thinned to the cap of the
  // score points) only while it is shown, and dropped when it is hidden again.
  const isVisible = (name: LayerName) => visibleByChoice[name]
    ?? (name === "inspect_surfaces" || (shownByDefault.includes(name) && !(name === "sky_dome" && skyDomeChoiceRemembered && skyDomeHidden)));
  const showsCarvedByCriterion = carvedByCriterion !== null && isVisible("carved_by_criterion");
  const carvedVoxelsOfCriteria = useMemo(() => (carvedByCriterion !== null && showsCarvedByCriterion ? carvedVoxelsByCriterion(carvedByCriterion, origin) : null),
                                         [carvedByCriterion, showsCarvedByCriterion, origin]);
  const listedColours = carvedByCriterion === null ? [] : carvedByCriterion.criterionIds.map((id) => criteria.find((entry) => entry.id === id)?.colour ?? colourToken("carved"));
  const criterionColours = useKeyedValue(listedColours, listedColours.join(","));
  const carvedByCriterionObject = useMemo(() => scene && carvedByCriterion && carvedVoxelsOfCriteria
    && carvedByCriterionLayer({ voxels: carvedVoxelsOfCriteria, colours: criterionColours, voxelSize: carvedByCriterion.voxelSize }),
  [scene, carvedByCriterion, carvedVoxelsOfCriteria, criterionColours]);
  const skyDomeObject = useMemo(() => scene && skyDome && hemisphere && skyDomeLayer(skyDome, hemisphere), [scene, skyDome, hemisphere]);
  const skippedSurfacesObject = useMemo(() => scene && skippedSurfaces && skippedSurfacesLayer(skippedSurfaces.surfaces, origin), [scene, skippedSurfaces, origin]);
  const envelopeObject = useMemo(() => scene && envelope && envelopeLayer(envelope.clone()), [scene, envelope]);
  const massingObject = useMemo(() => scene && massing && buildingMassingLayer(massing.clone()), [scene, massing]);

  // The study's patches are placed once per set of values and made into a layer once per set of patches; the colours are painted
  // then, and again in place for a new column shown, target or range.
  const studyValues = study?.values ?? null;
  const studyCorners = useMemo(() => (studyValues === null ? null : patchCorners(studyValues, origin)), [studyValues, origin]);
  const drawnStudy = study !== null && study.values.values[study.column] !== undefined ? study : null;
  const studyDrawn = drawnStudy !== null;
  const studyObject = useMemo(() => (scene && studyDrawn && studyCorners ? studyValuesLayer(studyCorners) : null), [scene, studyDrawn, studyCorners]);

  // Inspect: the surface orientation is made once per set of files and arrows; a click on it goes to the newest onSurfaceClick.
  const inspectFiles = inspect !== null && inspect.files.length > 0 ? inspect.files : null;
  const inspectArrows = inspect?.arrows ?? false;
  const inspecting = inspect !== null;
  const inspectObject = useMemo(() => scene && inspectFiles && inspectSurfacesLayer(inspectFiles, { arrows: inspectArrows }), [scene, inspectFiles, inspectArrows]);

  // Simulate's sun tool: its layer is made again when the day, the time or the hemisphere changes (a few hundred line points).
  const sunChart = sunStudy?.chart ?? null;
  const sunVector = useKeyedValue(sunStudy?.sun ?? null, sunStudy?.sun?.join(",") ?? "");
  const sunStudyObject = useMemo(() => scene && sunChart && hemisphere && sunStudyLayer(sunStudyObjects(sunChart, sunVector, hemisphere), hemisphere),
                                 [scene, sunChart, hemisphere, sunVector]);
  const sunShadows = sunStudy?.shadows ?? false;

  // The layers in the order of the layers menu. *listed*: the menu lists the layer (a layer whose criteria are all hidden stays listed,
  // so they can be shown again; in Inspect the orientation layer takes the test surfaces' place, which are hidden). A slot keeps its
  // dimmed state when its layer is replaced, so new data of a layer still out of date stays dimmed.
  const layer = (name: LayerName, listed: boolean, object: THREE.Object3D | null, visible: boolean | null = listed ? isVisible(name) : null) => ({
    name, listed, object, visible,
    dimmed: name === "study_values" ? (drawnStudy?.dimmed ?? false) : RESULT_LAYERS.includes(name) && dimmedLayers.includes(name),
  });
  const layers = [
    layer("max_volume", maxVolume !== null, maxVolumeObject),
    layer("test_surfaces", !inspecting && testSurfaces.some(({ geometry, shown }) => geometry !== null || !shown), testSurfacesObject,
          inspecting ? false : undefined),
    layer("skipped_surfaces", skippedSurfaces !== null, skippedSurfacesObject),
    layer("context", context !== null, contextObject),
    layer("terrain", terrain !== null, terrainObject),
    layer("kept_voxels", voxels !== null, keptVoxelsObject),
    layer("carved_voxels", voxels !== null, carvedVoxelsObject),
    layer("carved_by_criterion", carvedByCriterion !== null, carvedByCriterionObject),
    layer("sun_path", sunPath !== null && hemisphere !== null, sunPathObject),
    layer("sky_dome", skyDome !== null && hemisphere !== null, skyDomeObject),
    layer("envelope", envelope !== null, envelopeObject),
    layer("building_massing", massing !== null, massingObject),
    layer("study_values", studyDrawn, studyObject),
    layer("inspect_surfaces", inspectFiles !== null, inspectObject),
    layer("sun_study", false, sunStudyObject),          // drawn while the sun tool is open; not in the menu
  ];
  useSceneLayers(scene, layers);
  const present = layers.filter(({ listed }) => listed).map(({ name }) => name);

  const { colourBy: studyColourBy, range: [studyLow, studyHigh] = [], palette: studyPalette, column: studyColumn } = drawnStudy ?? {};
  const paintStudy = useEffectEvent(() => {
    if (drawnStudy === null || studyObject === null) return;
    layerHooks(studyObject).recolour?.(drawnStudy);
    scene?.redraw();
  });
  useEffect(() => paintStudy(), [studyObject, studyColumn, studyColourBy, studyLow, studyHigh, studyPalette]);

  const surfaceClicked = useEffectEvent((intersection: THREE.Intersection) => {
    const hit = inspectObject && layerHooks(inspectObject).fileAndSurfaceOf?.(intersection);
    if (hit) inspect?.onSurfaceClick(hit.fileName, hit.surface);
  });
  useEffect(() => {
    if (!scene || !inspecting) return;
    return scene.onLayerClick("inspect_surfaces", (intersection) => surfaceClicked(intersection));
  }, [scene, inspecting]);
  const inspectFrame = inspect?.frame ?? null;
  const orbitsAboutInspectedFile = useRef(false);
  const inspectFrameRequest = inspectFrame?.request;
  const frameInspected = useEffectEvent(() => {
    if (!inspectFrame) return;
    scene?.frameBox(inspectFrame.min, inspectFrame.max);
    orbitsAboutInspectedFile.current = true;
  });
  useEffect(() => frameInspected(), [scene, inspectFrameRequest]);
  useEffect(() => {                                       // leaving Inspect takes the orbit back from the file it framed to the model
    if (inspecting || !orbitsAboutInspectedFile.current) return;
    orbitsAboutInspectedFile.current = false;
    scene?.frameAll();
  }, [scene, inspecting]);
  useEffect(() => scene?.setSunStudy(sunVector, sunShadows), [scene, sunVector, sunShadows]);
  useEffect(() => scene?.setEnvelopeSeeThrough(envelopeSeeThrough), [scene, envelopeSeeThrough]);
  useEffect(() => {
    if (framingRequest > 0) scene?.frameAll();
  }, [scene, framingRequest]);

  // With two or more criteria the test surfaces have an entry for each. The layer's own check box works as the others' do (a change of
  // step brings back the step's choice) and is checked while the layer is shown with any criterion, half checked while some are not;
  // which criteria are shown is kept apart (*testSurfaces*), so hiding the layer does not change it.
  const testSurfaceParts = testSurfaces.length < 2 ? undefined : testSurfaces.map(({ id, name, colour, off, shown }) =>
    ({ id, label: messages.testSurfacesOfCriterion(name, off), colour, visible: isVisible("test_surfaces") && shown }));
  const entries: LayersMenuEntry[] = [
    ...present.map((name) => (name === "test_surfaces" && testSurfaceParts
      ? { name, available: true, visible: testSurfaceParts.some((part) => part.visible), partlyVisible: testSurfaceParts.some((part) => part.visible)
          && !testSurfaceParts.every((part) => part.visible), parts: testSurfaceParts }
      : { name, available: true, visible: isVisible(name), note: name === "skipped_surfaces" && skippedSurfaces !== null ? skippedSurfacesLine(skippedSurfaces) : undefined })),
    ...missingLayers.filter((name) => !present.includes(name)).map((name) => ({ name, available: false, visible: false, note: missingLayerNotes?.[name] })),
  ];
  const changeVisible = (name: LayerName, visible: boolean) => {
    setVisibleByChoice((choices) => ({ ...choices, [name]: visible }));
    if (name === "sky_dome" && skyDomeChoiceRemembered) {
      rememberSkyDomeHidden(!visible);
      setSkyDomeHidden(!visible);
    }
    // Shown again with every criterion hidden by its own entry: nothing would appear, so they are all shown
    if (visible && name === "test_surfaces" && testSurfaceParts && !testSurfaces.some((group) => group.shown)) onTestSurfacesShownChange?.(testSurfaces.map(({ id }) => id), true);
  };
  const changePartVisible = (_name: LayerName, id: string, visible: boolean) => {
    if (visible && !isVisible("test_surfaces")) {
      setVisibleByChoice((choices) => ({ ...choices, test_surfaces: true }));
      // Every entry showed as unchecked and none was hidden by choice: showing one criterion shows that one alone
      if (testSurfaces.every((group) => group.shown)) onTestSurfacesShownChange?.(testSurfaces.filter((group) => group.id !== id).map((group) => group.id), false);
    }
    onTestSurfacesShownChange?.([id], visible);
  };
  const shown = (name: LayerName) => present.includes(name) && isVisible(name);
  const legend: LegendContent = {
    sunPath: shown("sun_path") && sunPath ? sunPathLegend(sunPath.path) : undefined,
    keptVoxels: shown("kept_voxels") && scorePoints && carving
      ? { title: messages.scoreOfModeWithUnit(scorePoints.header.mode, scorePoints.header.score_unit), mode: scorePoints.header.mode, cutoff: carving.threshold_value,
          unit: scorePoints.header.score_unit || undefined, thinningStep: scorePoints.header.thinning_step }
      : undefined,
    skyDome: shown("sky_dome") && skyDome
      ? { title: skyDomeTitle ?? messages.skyDomeLegend(analysedSkyDomeMode(scorePoints?.header.mode ?? null, mode, analysisCurrent)),
          lowestWeight: Math.min(...skyDome.weights),
          highestWeight: Math.max(...skyDome.weights) }
      : undefined,
    buildingMassing: shown("building_massing") && massing ? { storeyCount: storeyCountOf(massing) } : undefined,
    carvedByCriterion: shown("carved_by_criterion") && carvedByCriterion
      ? { criteria: carvedByCriterion.criterionIds.flatMap((id) => criteria.filter((entry) => entry.id === id).map(({ name, colour }) => ({ name, colour }))),
          thinningStep: carvedVoxelsOfCriteria?.thinningStep ?? 1 }
      : undefined,
  };
  const dimmedResultShown = dimmedLayers.some(shown) || studyOutOfDate;
  const overlay = typeof overlayContent === "function" ? overlayContent(theme) : overlayContent;
  const progressPercent = runProgress === null ? 0 : Math.round(runProgress * 100);
  const progressBar = runProgress !== null && (
    <div className="viewer-run-progress" role="progressbar" aria-label={messages.runProgress} aria-valuemin={0} aria-valuemax={100}
         aria-valuenow={progressPercent}>
      <div className="viewer-run-progress-bar" style={{ width: `${progressPercent}%` }} />
    </div>
  );
  if (sceneUnavailable) {
    return (
      <div className="viewer-pane viewer-pane-unavailable">
        {progressBar}
        <div className="viewer-unavailable-content">
          <p className="viewer-unavailable" role="status">{messages.viewerNeedsWebGl}</p>
          {centreContent}
        </div>
        {overlay}
      </div>
    );
  }
  return (
    <div className="viewer-pane">
      <div ref={container} className="viewer-canvas" />
      {progressBar}
      <Compass yawDegrees={camera.yawDegrees} northDegrees={northDegrees} theme={theme} onViewTop={() => scene?.viewTop()} />
      <ViewToolbar theme={theme} groundAid={groundAid} onFrameAll={() => scene?.frameAll()} onTopView={() => scene?.viewTop()}
                   onGroundAidChange={setGroundAid} sunTool={sunTool === null ? null : { open: sunTool.open, onToggle: sunTool.onToggle }} />
      {sunTool !== null && sunTool.open && <div className="viewer-sun-tool">{sunTool.panel}</div>}
      {entries.length > 0 && (
        <LayersMenu entries={entries} skyDomeOpacity={skyDomeOpacity} theme={theme} onSkyDomeOpacityChange={setSkyDomeOpacity}
                    onVisibleChange={changeVisible} onPartVisibleChange={changePartVisible} />
      )}
      <AxisGizmo yawDegrees={camera.yawDegrees} elevationDegrees={camera.elevationDegrees} theme={theme} />
      <ScaleBar metresPerPixel={camera.metresPerPixel} theme={theme} />
      <Legend content={legend} theme={theme} />
      {dimmedResultShown && (
        <div className="viewer-overlay viewer-out-of-date" data-viewport-theme={theme} role="status">
          <strong>{runProgress === null ? messages.viewerStampOutOfDate : messages.viewerStampUpdating}</strong>
          <span>{runProgress === null ? messages.viewerStampOutOfDateNote : messages.viewerStampUpdatingNote}</span>
        </div>
      )}
      {centreContent && <div className="viewer-centre" data-viewport-theme={theme}>{centreContent}</div>}
      {overlay}
      {scene !== null && sceneTool !== null && sceneTool(scene)}
    </div>
  );
}

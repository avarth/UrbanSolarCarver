// The 3D view beside the step panel (UX 4, 8): the scene and its overlays, the layers built from what the project has so far.
// Each step shows its own layers by default (UX 8.2); the layers menu turns them on and off until another step opens.
// The maximum volume is a light solid in Inputs, Mode and Settings and a ghost, off by default, in the later steps. Result
// layers that are out of date, or being replaced by a run, are dimmed (UX 6.3), and while one of them is shown a stamp at the top
// of the view says so ("Out of date", or "Updating" during a run); a thin bar along the top shows a run's progress. In Simulate
// the selected study's values are one more layer, dimmed when the study is out of date, and the stamp shows while it is.
// In Inspect the orientation of the test surfaces is one more layer, which replaces the test surfaces in the view; a click on a surface
// is reported, and a request to frame a box moves the camera.
// Without WebGL (a remote desktop, a blocked graphics card) the scene cannot start: the view says so, and the steps go on working.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type * as THREE from "three";
import type { RunSummary, SkyDome } from "../api_client/client";
import { messages } from "../messages";
import { carvedVoxelsByCriterion, type CarvedByCriterion } from "../viewer/carved_by_criterion_decoder";
import { colourToken, keptScoreRange } from "../viewer/colour_scales";
import type { StudyView } from "../simulate/study_values";
import { patchCorners } from "../simulate/study_values_decoder";
import {
  buildingMassingLayer, carvedByCriterionLayer, carvedVoxelsLayer, contextLayer, envelopeLayer, inspectSurfacesLayer, keptColumnTops, keptVoxelsLayer, maxVolumeLayer,
  skyDomeLayer, splitScorePoints, storeyOfPart, studyValuesLayer, sunPathLayer, terrainLayer, testSurfacesLayer, volumeOutline, type InspectLayerFile, type MaxVolumeAppearance,
  type VolumeOutline,
} from "../viewer/layers";
import type { Point3 } from "../viewer/local_origin";
import { DEFAULT_SKY_DOME_OPACITY, ViewerScene, type CameraState, type GroundAid, type LayerName, type ViewportTheme } from "../viewer/scene";
import { voxelCentres, type ScorePoints } from "../viewer/score_points_decoder";
import type { Hemisphere } from "../viewer/sky_dome";
import { sunPathLegend, sunPathObjects, type SunPathWithNorth } from "../viewer/sun_path";
import { AxisGizmo } from "./AxisGizmo";
import { Compass } from "./Compass";
import { LayersMenu, type LayersMenuEntry } from "./LayersMenu";
import { Legend, type LegendContent } from "./Legend";
import { ScaleBar } from "./ScaleBar";
import { rememberedGroundAid, rememberedViewportTheme, ViewToolbar } from "./ViewToolbar";
import "./overlays.css";

/** What the runs have produced for the view; each is null until its stage has written it. */
export interface ViewerResults {
  scorePoints: ScorePoints | null;
  carving: RunSummary["carving"];
  skyDome: SkyDome | null;
  envelope: THREE.BufferGeometry | null;
  massing: THREE.BufferGeometry | null;
  /** Which criterion removed each voxel; null with fewer than two criteria on, or until every one has run. */
  carvedByCriterion: CarvedByCriterion | null;
}

export const NO_VIEWER_RESULTS: ViewerResults = { scorePoints: null, carving: null, skyDome: null, envelope: null, massing: null, carvedByCriterion: null };

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
  /** How far the run under way is, 0 to 1; null without a run. */
  runProgress?: number | null;
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
}

const NO_CAMERA: CameraState = { yawDegrees: 0, elevationDegrees: 90, metresPerPixel: 0 };
const NO_SHIFT: Point3 = [0, 0, 0];
const NO_LAYERS: readonly LayerName[] = [];
const EMPTY_OUTLINE: VolumeOutline = { segments: new Float32Array(0), outwardNormals: new Float32Array(0) };
const NO_CRITERIA: readonly CriterionSwatch[] = [];
const RESULT_LAYERS: readonly LayerName[] = ["kept_voxels", "carved_voxels", "carved_by_criterion", "sky_dome", "envelope", "building_massing"];
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
                             missingLayers = NO_LAYERS, runProgress = null, overlayContent, mode = null,
                             analysisCurrent = false, skyDomeTitle, study = null, studyOutOfDate = false, envelopeSeeThrough = false, inspect = null }: ViewerPaneProps) {
  const container = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState<ViewerScene | null>(null);
  const [sceneUnavailable, setSceneUnavailable] = useState(false);
  const [camera, setCamera] = useState<CameraState>(NO_CAMERA);
  const [theme, setTheme] = useState<ViewportTheme>(rememberedViewportTheme);
  const [groundAid, setGroundAid] = useState<GroundAid>(rememberedGroundAid);
  const [visibleByChoice, setVisibleByChoice] = useState<Partial<Record<LayerName, boolean>>>({});
  const [skyDomeOpacity, setSkyDomeOpacity] = useState(DEFAULT_SKY_DOME_OPACITY);
  const defaultsKey = shownByDefault.join(",");
  const { scorePoints, carving, skyDome, envelope, massing, carvedByCriterion } = results;
  const originKey = localOrigin.join(",");

  useEffect(() => {
    if (!browserHasWebGl()) {
      setSceneUnavailable(true);
      return;
    }
    let viewer: ViewerScene;
    try {
      viewer = new ViewerScene(container.current!);
    } catch (error) {
      // A fault of the scene, not a missing WebGL: said in the console; the view stays empty and the steps go on working
      console.error(error);
      return;
    }
    const stopListening = viewer.onCameraChange(setCamera);
    setScene(viewer);
    return () => {
      stopListening();
      viewer.dispose();
      setScene(null);
    };
  }, []);

  useEffect(() => scene?.setViewportTheme(theme), [scene, theme]);
  useEffect(() => scene?.setGroundAid(groundAid), [scene, groundAid]);
  useEffect(() => scene?.setNorth(northDegrees), [scene, northDegrees]);
  useEffect(() => scene?.setSceneHemisphere(hemisphere), [scene, hemisphere]);
  useEffect(() => scene?.setSkyDomeOpacity(skyDomeOpacity), [scene, skyDomeOpacity]);
  useEffect(() => setVisibleByChoice({}), [defaultsKey]);

  // Every layer gets its own copy of the geometry: the scene disposes a layer's geometry when the layer is replaced.
  useEffect(() => scene?.setLayer("max_volume", maxVolume && maxVolumeLayer(maxVolume.clone(), maxVolumeAppearance)), [scene, maxVolume, maxVolumeAppearance]);
  useEffect(() => {
    const parts = testSurfaces.flatMap(({ id, colour, shown, geometry }) => (shown && geometry !== null ? [{ name: id, colour, geometry: geometry.clone() }] : []));
    scene?.setLayer("test_surfaces", parts.length > 0 ? testSurfacesLayer(parts) : null);
  }, [scene, testSurfaces]);
  useEffect(() => scene?.setLayer("context", context && contextLayer(context.clone())), [scene, context]);
  useEffect(() => scene?.setLayer("terrain", terrain && terrainLayer(terrain.clone())), [scene, terrain]);
  useEffect(() => {
    const northTurnDegrees = sunPath === null ? 0 : northDegrees - sunPath.northDegrees;
    scene?.setLayer("sun_path", sunPath && hemisphere && sunPathLayer(sunPathObjects(sunPath.path, hemisphere, northTurnDegrees), hemisphere));
  }, [scene, sunPath, hemisphere, northDegrees]);

  // The voxels need the mask and the cutoff of a carving: score points without them (the carving did not run) are not drawn.
  const voxels = useMemo(() => {
    if (scorePoints === null || scorePoints.kept === null || carving === null) return null;
    return splitScorePoints(scorePoints, voxelCentres(scorePoints.header, scorePoints.indices, localOrigin));
  }, [scorePoints, carving, originKey]);
  const outline = useMemo(() => (maxVolume ? volumeOutline(maxVolume) : EMPTY_OUTLINE), [maxVolume]);
  useEffect(() => {
    scene?.setLayer("kept_voxels", voxels && carving && scorePoints && keptVoxelsLayer({
      voxels: voxels.kept, voxelSize: scorePoints.header.voxel_size, colourRange: keptScoreRange(carving.threshold_value), voxelCount: carving.voxels_kept,
    }));
  }, [scene, voxels]);
  useEffect(() => {
    scene?.setLayer("carved_voxels", voxels && carving && scorePoints && carvedVoxelsLayer({
      voxels: voxels.carved, voxelSize: scorePoints.header.voxel_size, voxelCount: carving.voxels_removed, outline,
      keptTopAt: keptColumnTops(scorePoints, localOrigin),
    }));
  }, [scene, voxels, outline]);
  // Each carved voxel in the colour of the criterion that removed it, whose id the layer names; the layer is drawn again when a colour
  // changes. It is a layer of up to a million cubes that starts hidden: it is built (and the voxels listed, thinned to the cap of the
  // score points) only while it is shown, and dropped when it is hidden again.
  const isVisible = (name: LayerName) => visibleByChoice[name] ?? (name === "inspect_surfaces" || shownByDefault.includes(name));
  const showsCarvedByCriterion = carvedByCriterion !== null && isVisible("carved_by_criterion");
  const carvedVoxelsOfCriteria = useMemo(() => (carvedByCriterion !== null && showsCarvedByCriterion ? carvedVoxelsByCriterion(carvedByCriterion, localOrigin) : null),
                                         [carvedByCriterion, showsCarvedByCriterion, originKey]);
  const criterionColours = carvedByCriterion === null ? [] : carvedByCriterion.criterionIds.map((id) => criteria.find((entry) => entry.id === id)?.colour ?? colourToken("carved"));
  const criterionColoursKey = criterionColours.join(",");
  useEffect(() => {
    scene?.setLayer("carved_by_criterion", carvedByCriterion && carvedVoxelsOfCriteria
      && carvedByCriterionLayer({ voxels: carvedVoxelsOfCriteria, colours: criterionColours, voxelSize: carvedByCriterion.voxelSize }));
  }, [scene, carvedVoxelsOfCriteria, criterionColoursKey]);
  useEffect(() => scene?.setLayer("sky_dome", skyDome && hemisphere && skyDomeLayer(skyDome, hemisphere)), [scene, skyDome, hemisphere]);
  useEffect(() => scene?.setLayer("envelope", envelope && envelopeLayer(envelope.clone())), [scene, envelope]);
  useEffect(() => scene?.setLayer("building_massing", massing && buildingMassingLayer(massing.clone())), [scene, massing]);
  useEffect(() => scene?.setEnvelopeSeeThrough(envelopeSeeThrough), [scene, envelopeSeeThrough]);

  // The study's patches are placed once per set of values and made into a layer once per geometry (the scene disposes the layer it
  // replaces: its geometry and material; the corners stay, held here); a new target or Change recolours that layer in place.
  const studyValues = study?.values ?? null;
  const studyCorners = useMemo(() => (studyValues === null ? null : patchCorners(studyValues, localOrigin)), [studyValues, originKey]);
  const drawnStudy = study !== null && study.values.values[study.geometry] !== undefined ? study : null;
  const studyLayer = useRef<THREE.Object3D | null>(null);
  useEffect(() => {
    studyLayer.current = drawnStudy && studyCorners && studyValuesLayer(drawnStudy, studyCorners);
    scene?.setLayer("study_values", studyLayer.current);
  }, [scene, studyCorners, drawnStudy?.geometry]);
  useEffect(() => {
    if (drawnStudy === null || studyLayer.current === null) return;
    studyLayer.current.userData.recolour(drawnStudy);
    scene?.redraw();
  }, [drawnStudy?.change, drawnStudy?.colourBy, drawnStudy?.range[0], drawnStudy?.range[1], drawnStudy?.palette]);
  const studyDimmed = drawnStudy?.dimmed ?? false;
  useEffect(() => scene?.setLayerDimmed("study_values", studyDimmed), [scene, studyDimmed]);

  // Inspect: the surface orientation is made once per set of files (the scene disposes the layer it replaces); a click is mapped to its
  // file and surface by that layer, and goes to the newest onSurfaceClick.
  const inspectFiles = inspect !== null && inspect.files.length > 0 ? inspect.files : null;
  const inspectArrows = inspect?.arrows ?? false;
  const inspecting = inspect !== null;
  const inspectLayer = useRef<THREE.Object3D | null>(null);
  useEffect(() => {
    inspectLayer.current = inspectFiles && inspectSurfacesLayer(inspectFiles, { arrows: inspectArrows });
    scene?.setLayer("inspect_surfaces", inspectLayer.current);
  }, [scene, inspectFiles, inspectArrows]);
  const onSurfaceClick = useRef(inspect?.onSurfaceClick);
  useEffect(() => { onSurfaceClick.current = inspect?.onSurfaceClick; }, [inspect?.onSurfaceClick]);
  useEffect(() => {
    if (!scene || !inspecting) return;
    return scene.onLayerClick("inspect_surfaces", (intersection) => {
      const hit: { fileName: string; surface: number } | null = inspectLayer.current?.userData.fileAndSurfaceOf(intersection) ?? null;
      if (hit) onSurfaceClick.current?.(hit.fileName, hit.surface);
    });
  }, [scene, inspecting]);
  const inspectFrame = inspect?.frame ?? null;
  useEffect(() => {
    if (inspectFrame) scene?.frameBox(inspectFrame.min, inspectFrame.max);
  }, [scene, inspectFrame?.request]);

  const present: LayerName[] = [];
  if (maxVolume) present.push("max_volume");
  // A layer whose criteria are all hidden stays listed, so they can be shown again. In Inspect the orientation layer takes their place.
  if (!inspecting && testSurfaces.some(({ geometry, shown }) => geometry !== null || !shown)) present.push("test_surfaces");
  if (context) present.push("context");
  if (terrain) present.push("terrain");
  if (voxels) present.push("kept_voxels", "carved_voxels");
  if (carvedByCriterion) present.push("carved_by_criterion");
  if (sunPath && hemisphere) present.push("sun_path");
  if (skyDome && hemisphere) present.push("sky_dome");
  if (envelope) present.push("envelope");
  if (massing) present.push("building_massing");
  if (drawnStudy) present.push("study_values");
  if (inspectFiles) present.push("inspect_surfaces");
  const visibilityKey = present.map((name) => `${name}:${isVisible(name)}`).join(",");
  const dimmedKey = dimmedLayers.join(",");

  useEffect(() => {
    for (const name of present) scene?.setLayerVisible(name, isVisible(name));
    if (inspecting) scene?.setLayerVisible("test_surfaces", false);
  }, [scene, visibilityKey, inspecting]);

  // A slot keeps its dimmed state when its layer is replaced, so new data of a layer still out of date stays dimmed.
  useEffect(() => {
    for (const name of RESULT_LAYERS) scene?.setLayerDimmed(name, dimmedLayers.includes(name));
  }, [scene, dimmedKey]);

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
      : { name, available: true, visible: isVisible(name) })),
    ...missingLayers.filter((name) => !present.includes(name)).map((name) => ({ name, available: false, visible: false })),
  ];
  const changeVisible = (name: LayerName, visible: boolean) => {
    setVisibleByChoice((choices) => ({ ...choices, [name]: visible }));
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
      ? { title: messages.scoreOfModeWithUnit(scorePoints.header.mode, scorePoints.header.score_unit), cutoff: carving.threshold_value,
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
      <ViewToolbar theme={theme} groundAid={groundAid} onFrameAll={() => scene?.frameAll()} onTopView={() => scene?.viewTop()} onThemeChange={setTheme}
                   onGroundAidChange={setGroundAid} />
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
    </div>
  );
}

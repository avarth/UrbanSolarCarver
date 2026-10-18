// The 3D view beside the step panel (UX 4, 8): the scene and its overlays, the layers built from what the project has so far.
// Each step shows its own layers by default (UX 8.2); the layers menu turns them on and off until another step opens.
// The maximum volume is a light solid in Inputs, Mode and Settings and a ghost, off by default, in the later steps. Result
// layers that are out of date, or being replaced by a run, are dimmed (UX 6.3); a thin bar along the top shows a run's progress.
// Without WebGL (a remote desktop, a blocked graphics card) the scene cannot start: the view says so, and the steps go on working.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type * as THREE from "three";
import type { ModeInfo, RunSummary, SkyDome, SunPath } from "../api_client/client";
import { messages } from "../messages";
import { keptScoreRange } from "../viewer/colour_scales";
import {
  buildingMassingLayer, carvedVoxelsLayer, envelopeLayer, keptColumnTops, keptVoxelsLayer, maxVolumeLayer, skyDomeLayer, splitScorePoints,
  storeyOfPart, sunPathLayer, testSurfacesLayer, volumeOutline, type MaxVolumeAppearance, type VolumeOutline,
} from "../viewer/layers";
import type { Point3 } from "../viewer/local_origin";
import { DEFAULT_SKY_DOME_OPACITY, ViewerScene, type CameraState, type LayerName, type ViewportTheme } from "../viewer/scene";
import { voxelCentres, type ScorePoints } from "../viewer/score_points_decoder";
import type { Hemisphere } from "../viewer/sky_dome";
import { sunPathLegend, sunPathObjects } from "../viewer/sun_path";
import { AxisGizmo } from "./AxisGizmo";
import { Compass } from "./Compass";
import { LayersMenu, type LayersMenuEntry } from "./LayersMenu";
import { keptVoxelsLegendTitle, Legend, type LegendContent } from "./Legend";
import { ScaleBar } from "./ScaleBar";
import { rememberedViewportTheme, ViewToolbar } from "./ViewToolbar";
import "./overlays.css";

/** What the runs have produced for the view; each is null until its stage has written it. */
export interface ViewerResults {
  scorePoints: ScorePoints | null;
  carving: RunSummary["carving"];
  skyDome: SkyDome | null;
  envelope: THREE.BufferGeometry | null;
  massing: THREE.BufferGeometry | null;
}

export const NO_VIEWER_RESULTS: ViewerResults = { scorePoints: null, carving: null, skyDome: null, envelope: null, massing: null };

export interface ViewerPaneProps {
  maxVolume: THREE.BufferGeometry | null;
  testSurfaces: THREE.BufferGeometry | null;
  sunPath: SunPath | null;
  /** Where the sun path and the sky dome are drawn: around the maximum volume. */
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
  /** Shown over the view (the run report). */
  overlayContent?: ReactNode;
  /** The mode the form shows. */
  mode?: string | null;
  /** The modes of the engine, for the mode an analysis on screen was made in. */
  modes?: readonly ModeInfo[];
  /** The analysis (preprocessing) is current: it was made in the mode the form shows. */
  analysisCurrent?: boolean;
}

const NO_CAMERA: CameraState = { yawDegrees: 0, elevationDegrees: 90, metresPerPixel: 0 };
const NO_SHIFT: Point3 = [0, 0, 0];
const NO_LAYERS: readonly LayerName[] = [];
const EMPTY_OUTLINE: VolumeOutline = { segments: new Float32Array(0), outwardNormals: new Float32Array(0) };
const RESULT_LAYERS: readonly LayerName[] = ["kept_voxels", "carved_voxels", "sky_dome", "envelope", "building_massing"];
const NO_MODES: readonly ModeInfo[] = [];
const WEBGL_CONTEXT = "webgl2";     // what three.js's WebGLRenderer asks the canvas for

/**
 * The mode the sky dome on screen was analysed in, for its legend: the weighted mode whose weight unit the score points of
 * that analysis name (each weighted mode has its own); without them, the form's mode while the analysis is current; else
 * null (no mode named), since the form's mode may not be the one the dome on screen was made in.
 */
export function analysedSkyDomeMode(modes: readonly ModeInfo[], scorePointsWeightUnit: string | null, formMode: string | null,
                                    analysisCurrent: boolean): string | null {
  const analysed = scorePointsWeightUnit === null ? []
    : modes.filter((mode) => mode.score_kind === "weighted_sum" && mode.weight_unit === scorePointsWeightUnit);
  if (analysed.length === 1) return analysed[0].name;
  return analysisCurrent ? formMode : null;
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

export function ViewerPane({ maxVolume, testSurfaces, sunPath, hemisphere, maxVolumeAppearance, shownByDefault, northDegrees, framingRequest,
                             centreContent, results = NO_VIEWER_RESULTS, localOrigin = NO_SHIFT, dimmedLayers = NO_LAYERS,
                             missingLayers = NO_LAYERS, runProgress = null, overlayContent, mode = null, modes = NO_MODES,
                             analysisCurrent = false }: ViewerPaneProps) {
  const container = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState<ViewerScene | null>(null);
  const [sceneUnavailable, setSceneUnavailable] = useState(false);
  const [camera, setCamera] = useState<CameraState>(NO_CAMERA);
  const [theme, setTheme] = useState<ViewportTheme>(rememberedViewportTheme);
  const [visibleByChoice, setVisibleByChoice] = useState<Partial<Record<LayerName, boolean>>>({});
  const [skyDomeOpacity, setSkyDomeOpacity] = useState(DEFAULT_SKY_DOME_OPACITY);
  const defaultsKey = shownByDefault.join(",");
  const { scorePoints, carving, skyDome, envelope, massing } = results;
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
  useEffect(() => scene?.setNorth(northDegrees), [scene, northDegrees]);
  useEffect(() => scene?.setSkyDomeOpacity(skyDomeOpacity), [scene, skyDomeOpacity]);
  useEffect(() => setVisibleByChoice({}), [defaultsKey]);

  // Every layer gets its own copy of the geometry: the scene disposes a layer's geometry when the layer is replaced.
  useEffect(() => scene?.setLayer("max_volume", maxVolume && maxVolumeLayer(maxVolume.clone(), maxVolumeAppearance)), [scene, maxVolume, maxVolumeAppearance]);
  useEffect(() => scene?.setLayer("test_surfaces", testSurfaces && testSurfacesLayer(testSurfaces.clone())), [scene, testSurfaces]);
  useEffect(() => scene?.setLayer("sun_path", sunPath && hemisphere && sunPathLayer(sunPathObjects(sunPath, hemisphere), hemisphere)),
    [scene, sunPath, hemisphere]);

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
  useEffect(() => scene?.setLayer("sky_dome", skyDome && hemisphere && skyDomeLayer(skyDome, hemisphere)), [scene, skyDome, hemisphere]);
  useEffect(() => scene?.setLayer("envelope", envelope && envelopeLayer(envelope.clone())), [scene, envelope]);
  useEffect(() => scene?.setLayer("building_massing", massing && buildingMassingLayer(massing.clone())), [scene, massing]);

  const present: LayerName[] = [];
  if (maxVolume) present.push("max_volume");
  if (testSurfaces) present.push("test_surfaces");
  if (voxels) present.push("kept_voxels", "carved_voxels");
  if (sunPath && hemisphere) present.push("sun_path");
  if (skyDome && hemisphere) present.push("sky_dome");
  if (envelope) present.push("envelope");
  if (massing) present.push("building_massing");
  const isVisible = (name: LayerName) => visibleByChoice[name] ?? shownByDefault.includes(name);
  const visibilityKey = present.map((name) => `${name}:${isVisible(name)}`).join(",");
  const dimmedKey = dimmedLayers.join(",");

  useEffect(() => {
    for (const name of present) scene?.setLayerVisible(name, isVisible(name));
  }, [scene, visibilityKey]);

  // A slot keeps its dimmed state when its layer is replaced, so new data of a layer still out of date stays dimmed.
  useEffect(() => {
    for (const name of RESULT_LAYERS) scene?.setLayerDimmed(name, dimmedLayers.includes(name));
  }, [scene, dimmedKey]);

  useEffect(() => {
    if (framingRequest > 0) scene?.frameAll();
  }, [scene, framingRequest]);

  const entries: LayersMenuEntry[] = [
    ...present.map((name) => ({ name, available: true, visible: isVisible(name) })),
    ...missingLayers.filter((name) => !present.includes(name)).map((name) => ({ name, available: false, visible: false })),
  ];
  const shown = (name: LayerName) => present.includes(name) && isVisible(name);
  const legend: LegendContent = {
    sunPath: shown("sun_path") && sunPath ? sunPathLegend(sunPath) : undefined,
    keptVoxels: shown("kept_voxels") && scorePoints && carving
      ? { title: keptVoxelsLegendTitle(scorePoints.header.scores_kind, scorePoints.header.weight_unit), cutoff: carving.threshold_value,
          thinningStep: scorePoints.header.thinning_step }
      : undefined,
    skyDome: shown("sky_dome") && skyDome
      ? { title: messages.skyDomeLegend(analysedSkyDomeMode(modes, scorePoints?.header.weight_unit ?? null, mode, analysisCurrent)),
          lowestWeight: Math.min(...skyDome.weights),
          highestWeight: Math.max(...skyDome.weights) }
      : undefined,
    buildingMassing: shown("building_massing") && massing ? { storeyCount: storeyCountOf(massing) } : undefined,
  };
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
        {overlayContent}
      </div>
    );
  }
  return (
    <div className="viewer-pane">
      <div ref={container} className="viewer-canvas" />
      {progressBar}
      <Compass yawDegrees={camera.yawDegrees} northDegrees={northDegrees} theme={theme} onViewTop={() => scene?.viewTop()} />
      <ViewToolbar theme={theme} onFrameAll={() => scene?.frameAll()} onTopView={() => scene?.viewTop()} onThemeChange={setTheme} />
      {entries.length > 0 && (
        <LayersMenu entries={entries} skyDomeOpacity={skyDomeOpacity} theme={theme} onSkyDomeOpacityChange={setSkyDomeOpacity}
                    onVisibleChange={(name, visible) => setVisibleByChoice((choices) => ({ ...choices, [name]: visible }))} />
      )}
      <AxisGizmo yawDegrees={camera.yawDegrees} elevationDegrees={camera.elevationDegrees} theme={theme} />
      <ScaleBar metresPerPixel={camera.metresPerPixel} theme={theme} />
      <Legend content={legend} theme={theme} />
      {centreContent && <div className="viewer-centre" data-viewport-theme={theme}>{centreContent}</div>}
      {overlayContent}
    </div>
  );
}

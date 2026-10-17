// The 3D view beside the step panel (UX 4, 8): the scene and its overlays, the layers built from what the project has so far.
// Each step shows its own layers by default (UX 8.2); the layers menu turns them on and off until another step opens.
// The maximum volume is a light solid in Inputs, Mode and Settings and a ghost, off by default, in the later steps.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type * as THREE from "three";
import type { SunPath } from "../api_client/client";
import { maxVolumeLayer, sunPathLayer, testSurfacesLayer, type MaxVolumeAppearance } from "../viewer/layers";
import { DEFAULT_SKY_DOME_OPACITY, ViewerScene, type CameraState, type LayerName, type ViewportTheme } from "../viewer/scene";
import type { Hemisphere } from "../viewer/sky_dome";
import { sunPathLegend, sunPathObjects } from "../viewer/sun_path";
import { AxisGizmo } from "./AxisGizmo";
import { Compass } from "./Compass";
import { LayersMenu, type LayersMenuEntry } from "./LayersMenu";
import { Legend } from "./Legend";
import { ScaleBar } from "./ScaleBar";
import { rememberedViewportTheme, ViewToolbar } from "./ViewToolbar";
import "./overlays.css";

export interface ViewerPaneProps {
  maxVolume: THREE.BufferGeometry | null;
  testSurfaces: THREE.BufferGeometry | null;
  sunPath: SunPath | null;
  /** Where the sun path is drawn: around the maximum volume. */
  hemisphere: Hemisphere | null;
  maxVolumeAppearance: MaxVolumeAppearance;
  /** The layers the open step shows; a change of step brings these back. */
  shownByDefault: readonly LayerName[];
  northDegrees: number;
  /** Changing this number frames everything visible (the inputs changed). */
  framingRequest: number;
  /** Shown in the middle of the view, over the grid (the empty state of UX 11). */
  centreContent: ReactNode;
}

const NO_CAMERA: CameraState = { yawDegrees: 0, elevationDegrees: 90, metresPerPixel: 0 };

export function ViewerPane({ maxVolume, testSurfaces, sunPath, hemisphere, maxVolumeAppearance, shownByDefault, northDegrees, framingRequest,
                             centreContent }: ViewerPaneProps) {
  const container = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState<ViewerScene | null>(null);
  const [camera, setCamera] = useState<CameraState>(NO_CAMERA);
  const [theme, setTheme] = useState<ViewportTheme>(rememberedViewportTheme);
  const [visibleByChoice, setVisibleByChoice] = useState<Partial<Record<LayerName, boolean>>>({});
  const [skyDomeOpacity, setSkyDomeOpacity] = useState(DEFAULT_SKY_DOME_OPACITY);
  const defaultsKey = shownByDefault.join(",");

  useEffect(() => {
    const viewer = new ViewerScene(container.current!);
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

  const present: LayerName[] = [];
  if (maxVolume) present.push("max_volume");
  if (testSurfaces) present.push("test_surfaces");
  if (sunPath && hemisphere) present.push("sun_path");
  const isVisible = (name: LayerName) => visibleByChoice[name] ?? shownByDefault.includes(name);
  const visibilityKey = present.map((name) => `${name}:${isVisible(name)}`).join(",");

  useEffect(() => {
    for (const name of present) scene?.setLayerVisible(name, isVisible(name));
  }, [scene, visibilityKey]);

  useEffect(() => {
    if (framingRequest > 0) scene?.frameAll();
  }, [scene, framingRequest]);

  const entries: LayersMenuEntry[] = present.map((name) => ({ name, available: true, visible: isVisible(name) }));
  const sunPathShown = sunPath !== null && present.includes("sun_path") && isVisible("sun_path");
  return (
    <div className="viewer-pane">
      <div ref={container} className="viewer-canvas" />
      <Compass yawDegrees={camera.yawDegrees} northDegrees={northDegrees} theme={theme} onViewTop={() => scene?.viewTop()} />
      <ViewToolbar theme={theme} onFrameAll={() => scene?.frameAll()} onTopView={() => scene?.viewTop()} onThemeChange={setTheme} />
      {entries.length > 0 && (
        <LayersMenu entries={entries} skyDomeOpacity={skyDomeOpacity} theme={theme} onSkyDomeOpacityChange={setSkyDomeOpacity}
                    onVisibleChange={(name, visible) => setVisibleByChoice((choices) => ({ ...choices, [name]: visible }))} />
      )}
      <AxisGizmo yawDegrees={camera.yawDegrees} elevationDegrees={camera.elevationDegrees} theme={theme} />
      <ScaleBar metresPerPixel={camera.metresPerPixel} theme={theme} />
      <Legend content={{ sunPath: sunPathShown ? sunPathLegend(sunPath) : undefined }} theme={theme} />
      {centreContent && <div className="viewer-centre" data-viewport-theme={theme}>{centreContent}</div>}
    </div>
  );
}

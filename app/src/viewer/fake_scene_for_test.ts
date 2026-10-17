// A stand-in for ViewerScene in tests. jsdom has no WebGL, so a test that renders ViewerPane (or the workspace around it)
// swaps the scene for this one with vi.mock and reads what the pane asked the scene to draw:
//   vi.mock("../viewer/scene", async (importOriginal) => ({
//     ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene }));
import type * as THREE from "three";
import type { CameraState, LayerName, ViewportTheme } from "./scene";

export class FakeViewerScene {
  /** The scene the last ViewerPane made. */
  static latest: FakeViewerScene | null = null;
  readonly layers = new Map<LayerName, THREE.Object3D | null>();
  readonly visibleLayers = new Set<LayerName>();
  readonly dimmed = new Set<LayerName>();
  disposed = false;

  constructor(_container: HTMLElement) {
    FakeViewerScene.latest = this;
  }

  setLayer(name: LayerName, object: THREE.Object3D | null): void {
    this.layers.set(name, object);
  }

  setLayerVisible(name: LayerName, visible: boolean): void {
    if (visible) this.visibleLayers.add(name);
    else this.visibleLayers.delete(name);
  }

  setLayerDimmed(name: LayerName, dimmed: boolean): void {
    if (dimmed) this.dimmed.add(name);
    else this.dimmed.delete(name);
  }

  /** The layers that hold an object, in the order they were first set. */
  layersWithObjects(): LayerName[] {
    return [...this.layers].filter(([, object]) => object !== null).map(([name]) => name);
  }

  setNorth(_northDegrees: number): void {}
  setSkyDomeOpacity(_opacity: number): void {}
  setViewportTheme(_theme: ViewportTheme): void {}
  frameAll(): void {}
  viewTop(): void {}

  onCameraChange(_listener: (camera: CameraState) => void): () => void {
    return () => {};
  }

  dispose(): void {
    this.disposed = true;
  }
}

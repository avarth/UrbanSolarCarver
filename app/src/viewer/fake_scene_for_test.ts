// A stand-in for ViewerScene in tests. jsdom has no WebGL, so a test that renders ViewerPane (or the workspace around it)
// swaps the scene for this one with vi.mock and reads what the pane asked the scene to draw:
//   vi.mock("../viewer/scene", async (importOriginal) => ({
//     ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene }));
import type * as THREE from "three";
import { vi } from "vitest";
import type { Point3 } from "./local_origin";
import type { CameraState, GroundAid, LayerName, ViewportTheme } from "./scene";
import type { Hemisphere } from "./sky_dome";
import type { ShadeHours } from "./sun_study";

/** Makes the canvas give a WebGL context, as a browser with WebGL does (jsdom gives none); vi.restoreAllMocks undoes it. */
export function pretendTheBrowserHasWebGl(): void {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((kind: string) => (kind === "webgl2" ? ({} as RenderingContext) : null));
}

/**
 * Makes the canvas give no context, as a browser without WebGL does, without jsdom's "Not implemented" line in the test output;
 * vi.restoreAllMocks undoes it.
 */
export function pretendTheBrowserHasNoWebGl(): void {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
}

export class FakeViewerScene {
  /** The scene the last ViewerPane made. */
  static latest: FakeViewerScene | null = null;
  /** When set, the next scene throws it from its constructor (a fault of the scene, not a missing WebGL). */
  static constructorError: Error | null = null;
  readonly layers = new Map<LayerName, THREE.Object3D | null>();
  readonly visibleLayers = new Set<LayerName>();
  readonly dimmed = new Set<LayerName>();
  /** The ground aid the pane chose last; undefined until it chooses one. */
  groundAid: GroundAid | undefined = undefined;
  /** The scene hemisphere the pane gave last; undefined until it gives one. */
  sceneHemisphere: Hemisphere | null | undefined = undefined;
  disposed = false;

  constructor(_container: HTMLElement) {
    const error = FakeViewerScene.constructorError;
    FakeViewerScene.constructorError = null;
    if (error !== null) throw error;
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
  setSceneHemisphere(hemisphere: Hemisphere | null): void {
    this.sceneHemisphere = hemisphere;
  }

  setGroundAid(aid: GroundAid): void {
    this.groundAid = aid;
  }

  setSkyDomeOpacity(_opacity: number): void {}

  /** The last call of setSunStudy: the sun, whether it casts shadows, the hours in shade. */
  sunStudy: { sun: Point3 | null; shadows: boolean; shade: ShadeHours | null } = { sun: null, shadows: false, shade: null };

  setSunStudy(sun: Point3 | null, shadows: boolean, shade: ShadeHours | null): void {
    this.sunStudy = { sun, shadows, shade };
  }

  /** How many times the pane asked for the frame to be drawn again (a layer changed in place). */
  redraws = 0;
  redraw(): void {
    this.redraws += 1;
  }

  /** Whether the pane asked for the envelope see-through on its own (Simulate); false until it asks. */
  envelopeSeeThrough = false;
  setEnvelopeSeeThrough(seeThrough: boolean): void {
    this.envelopeSeeThrough = seeThrough;
  }
  setViewportTheme(_theme: ViewportTheme): void {}
  leftInsetSource: (() => number) | null = null;
  setLeftInsetSource(source: () => number): void {
    this.leftInsetSource = source;
  }
  frameAll(): void {}

  /** The boxes the pane asked the camera to frame, in order. */
  framedBoxes: { min: Point3; max: Point3 }[] = [];
  frameBox(min: Point3, max: Point3): void {
    this.framedBoxes.push({ min, max });
  }

  private readonly clickListeners = new Map<LayerName, Set<(intersection: THREE.Intersection) => void>>();
  onLayerClick(name: LayerName, listener: (intersection: THREE.Intersection) => void): () => void {
    const listeners = this.clickListeners.get(name) ?? new Set();
    listeners.add(listener);
    this.clickListeners.set(name, listeners);
    return () => { listeners.delete(listener); };
  }

  /** Clicks the view as the user would, with *intersection* as what the click hit in the layer *name*. */
  clickLayer(name: LayerName, intersection: THREE.Intersection): void {
    for (const listener of [...(this.clickListeners.get(name) ?? [])]) listener(intersection);
  }

  /** How many listeners are waiting for a click on the layer *name*. */
  clickListenerCount(name: LayerName): number {
    return this.clickListeners.get(name)?.size ?? 0;
  }
  viewTop(): void {}

  onCameraChange(_listener: (camera: CameraState) => void): () => void {
    return () => {};
  }

  dispose(): void {
    this.disposed = true;
  }
}

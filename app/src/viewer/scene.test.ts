// The pure helpers of the scene, and the clicks of the real ViewerScene: jsdom has no WebGL, so the renderer is replaced by one
// that draws nothing, and the container and the canvas are given the size of a view.
import * as THREE from "three";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest } from "../viewer_overlays/render_for_test";
import { cameraOrientation, describeView, metresPerPixelAt, nextGroundAid, shiftPicture, ViewerScene } from "./scene";

vi.mock("three", async (importOriginal) => {
  const three = await importOriginal<typeof import("three")>();
  class RendererThatDrawsNothing {
    readonly domElement = document.createElement("canvas");
    readonly shadowMap = { enabled: false, type: 0 };
    setPixelRatio(): void {}
    setSize(): void {}
    render(): void {}
    dispose(): void {}
  }
  return { ...three, WebGLRenderer: RendererThatDrawsNothing };
});

test("camera yaw is the clockwise turn from the top view with +Y up the screen", () => {
  expect(cameraOrientation([0, 0, -1], [0, 1, 0])).toEqual({ yawDegrees: 0, elevationDegrees: 90 });
  const turned = cameraOrientation([0, 0, -1], [Math.sin(Math.PI / 6), Math.cos(Math.PI / 6), 0]);
  expect(turned.yawDegrees).toBeCloseTo(30);
  const level = cameraOrientation([-1, 0, 0], [0, 0, 1]);       // looking along -X
  expect(level.yawDegrees).toBeCloseTo(270);
  expect(level.elevationDegrees).toBeCloseTo(0);
});

test("a shifted picture puts what the camera looks at to the right by the shift, and a shift of 0 clears it", () => {
  const camera = new THREE.PerspectiveCamera(45, 1000 / 800, 1, 1000);
  camera.position.set(0, -100, 0);
  camera.up.set(0, 0, 1);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  shiftPicture(camera, 150, 1000, 800);
  const projected = new THREE.Vector3(0, 0, 0).project(camera);
  expect((projected.x + 1) / 2 * 1000).toBeCloseTo(650, 6);     // 150 px right of the middle of 1000 px
  expect(projected.y).toBeCloseTo(0, 9);
  shiftPicture(camera, 0, 1000, 800);
  expect(camera.view?.enabled ?? false).toBe(false);
  expect(new THREE.Vector3(0, 0, 0).project(camera).x).toBeCloseTo(0, 9);
});

test("metres per pixel at the orbit target", () => {
  expect(metresPerPixelAt(100, 90, 1000)).toBeCloseTo(0.2);
});

test("the accessible name lists the layers on screen with their counts and states", () => {
  expect(describeView([])).toBe("3D view, empty.");
  expect(describeView([
    { label: "Maximum volume", detail: null, dimmed: false },
    { label: "Kept voxels, coloured by score", detail: "16 126 voxels", dimmed: true },
  ])).toBe("3D view showing: Maximum volume; Kept voxels, coloured by score, 16 126 voxels, out of date.");
});

test("the ground aid button cycles off, ground grid, compass ring, and back to off", () => {
  expect(nextGroundAid("off")).toBe("grid");
  expect(nextGroundAid("grid")).toBe("compass_ring");
  expect(nextGroundAid("compass_ring")).toBe("off");
});

// Clicks on a layer -------------------------------------------------------------------------------------------------------------

const VIEW_WIDTH = 800, VIEW_HEIGHT = 600;

let removeTokens: () => void = () => {};
let viewer: ViewerScene | null = null;

beforeEach(() => {
  removeTokens = addStyleSheetForTest("src/theme/tokens.css");
  vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void {} });
  vi.stubGlobal("matchMedia", () => ({ matches: true }));          // prefers-reduced-motion: camera moves are instant
  const textContext = { font: "", fillStyle: "", textBaseline: "", measureText: () => ({ width: 40 }), fillText: () => {} };      // for the text of the ground grid
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((kind: string) => (kind === "2d" ? textContext : null)) as never);
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT));
  Object.assign(HTMLCanvasElement.prototype, { setPointerCapture: () => {}, releasePointerCapture: () => {}, hasPointerCapture: () => false });
});

afterEach(() => {
  viewer?.dispose();
  viewer = null;
  removeTokens();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A scene whose "inspect_surfaces" layer is a 4 m cube at the origin, framed so the middle of the view looks at it. */
function viewerWithACube(): { scene: ViewerScene; canvas: HTMLCanvasElement; cube: THREE.Mesh } {
  const container = document.createElement("div");
  Object.defineProperty(container, "clientWidth", { value: VIEW_WIDTH });
  Object.defineProperty(container, "clientHeight", { value: VIEW_HEIGHT });
  const scene = new ViewerScene(container);
  viewer = scene;
  const cube = new THREE.Mesh(new THREE.BoxGeometry(4, 4, 4), new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
  scene.setLayer("inspect_surfaces", cube);
  return { scene, canvas: container.querySelector("canvas")!, cube };
}

function pointer(canvas: HTMLCanvasElement, type: "pointerdown" | "pointerup", x: number, y: number, button = 0): void {
  canvas.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, button, bubbles: true }));
}

test("a pointerdown and a pointerup at the same place is a click: the listener gets the nearest mesh of the layer that was hit", () => {
  const { scene, canvas, cube } = viewerWithACube();
  const clicked: THREE.Intersection[] = [];
  scene.onLayerClick("inspect_surfaces", (intersection) => clicked.push(intersection));
  pointer(canvas, "pointerdown", 400, 300);
  pointer(canvas, "pointerup", 400, 300);
  expect(clicked).toHaveLength(1);
  expect(clicked[0].object).toBe(cube);
  expect(clicked[0].faceIndex).toBeGreaterThanOrEqual(0);
});

test("a pointer that moved 20 px between pointerdown and pointerup is an orbit drag, not a click; 3 px is a click", () => {
  const { scene, canvas } = viewerWithACube();
  const listener = vi.fn();
  scene.onLayerClick("inspect_surfaces", listener);
  pointer(canvas, "pointerdown", 400, 300);
  pointer(canvas, "pointerup", 420, 300);
  expect(listener).not.toHaveBeenCalled();
  pointer(canvas, "pointerdown", 400, 300);
  pointer(canvas, "pointerup", 402, 302);
  expect(listener).toHaveBeenCalledTimes(1);
});

test("a press held for more than 400 ms is not a click, and a right button press is not one either", () => {
  const { scene, canvas } = viewerWithACube();
  const listener = vi.fn();
  scene.onLayerClick("inspect_surfaces", listener);
  let now = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  pointer(canvas, "pointerdown", 400, 300);
  now += 401;
  pointer(canvas, "pointerup", 400, 300);
  expect(listener).not.toHaveBeenCalled();
  pointer(canvas, "pointerdown", 400, 300, 2);
  pointer(canvas, "pointerup", 400, 300, 2);
  expect(listener).not.toHaveBeenCalled();
  pointer(canvas, "pointerdown", 400, 300);
  now += 399;
  pointer(canvas, "pointerup", 400, 300);
  expect(listener).toHaveBeenCalledTimes(1);
});

test("a click that hits nothing of the layer, a layer that is hidden, and a listener that was removed do not call the listener", () => {
  const { scene, canvas } = viewerWithACube();
  const listener = vi.fn();
  const stop = scene.onLayerClick("inspect_surfaces", listener);
  const other = vi.fn();
  scene.onLayerClick("test_surfaces", other);
  const click = (x: number, y: number) => { pointer(canvas, "pointerdown", x, y); pointer(canvas, "pointerup", x, y); };
  click(5, 5);                                   // the corner of the view, beside the cube
  expect(listener).not.toHaveBeenCalled();
  scene.setLayerVisible("inspect_surfaces", false);
  click(400, 300);
  expect(listener).not.toHaveBeenCalled();
  scene.setLayerVisible("inspect_surfaces", true);
  click(400, 300);
  expect(listener).toHaveBeenCalledTimes(1);
  expect(other).not.toHaveBeenCalled();
  stop();
  click(400, 300);
  expect(listener).toHaveBeenCalledTimes(1);
});

/** A 2 m square test surface facing up at height *z*, centred on the origin, as the only mesh of a layer. */
function squareAt(z: number): THREE.Mesh {
  const square = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
  square.position.set(0, 0, z);
  return square;
}

/** A scene seen from straight above with a 4 m context box from z 0 to 4 under the middle of the view and *surface* as the test surfaces. */
function viewerWithAContextBox(surface: THREE.Mesh): { scene: ViewerScene; canvas: HTMLCanvasElement } {
  const { scene, canvas } = viewerWithACube();
  scene.setLayer("inspect_surfaces", surface);
  const box = new THREE.Mesh(new THREE.BoxGeometry(4, 4, 4), new THREE.MeshBasicMaterial());
  box.position.set(0, 0, 2);
  scene.setLayer("context", box);
  scene.frameBox([-5, -5, 0], [5, 5, 5]);
  scene.viewTop();
  return { scene, canvas };
}

test("a click on a context building does not reach a test surface behind it", () => {
  const { scene, canvas } = viewerWithAContextBox(squareAt(1));         // inside the box, under its roof
  const listener = vi.fn();
  scene.onLayerClick("inspect_surfaces", listener);
  pointer(canvas, "pointerdown", 400, 300);
  pointer(canvas, "pointerup", 400, 300);
  expect(listener).not.toHaveBeenCalled();
  scene.setLayerVisible("context", false);                              // a hidden layer hides nothing
  pointer(canvas, "pointerdown", 400, 300);
  pointer(canvas, "pointerup", 400, 300);
  expect(listener).toHaveBeenCalledTimes(1);
});

test("a click on a test surface lying on a face of a context building reaches it", () => {
  const { scene, canvas } = viewerWithAContextBox(squareAt(4));         // on the roof of the box
  const listener = vi.fn();
  scene.onLayerClick("inspect_surfaces", listener);
  pointer(canvas, "pointerdown", 400, 300);
  pointer(canvas, "pointerup", 400, 300);
  expect(listener).toHaveBeenCalledTimes(1);
});

test("frameBox puts the camera where frameAll would for a layer of that box: a box a tenth the size is seen from a tenth the distance", () => {
  const { scene } = viewerWithACube();
  const metresPerPixel: number[] = [];
  scene.onCameraChange((camera) => metresPerPixel.push(camera.metresPerPixel));
  scene.frameBox([-10, -10, -10], [10, 10, 10]);
  const wide = metresPerPixel[metresPerPixel.length - 1];
  scene.frameBox([-1, -1, -1], [1, 1, 1]);
  const close = metresPerPixel[metresPerPixel.length - 1];
  expect(close / wide).toBeCloseTo(0.1, 2);
  scene.frameBox([-10, -10, -10], [10, 10, 10]);
  expect(metresPerPixel[metresPerPixel.length - 1]).toBeCloseTo(wide);
});

test("framing beside a panel: the free part of the view sets the distance, the model is centred in it, and the panel counts for at most half", () => {
  const { scene, canvas, cube } = viewerWithACube();
  const metresPerPixel: number[] = [];
  scene.onCameraChange((camera) => metresPerPixel.push(camera.metresPerPixel));
  const framedWith = (insetPixels: number) => {
    scene.setLeftInsetSource(() => insetPixels);
    scene.frameAll(true);
    return metresPerPixel[metresPerPixel.length - 1];
  };
  const clear = framedWith(0);
  const beside = framedWith(VIEW_WIDTH * 0.375);
  expect(beside).toBeGreaterThan(clear);                    // the cube fits the narrower free part
  // The cube's centre is drawn at the middle of the free part, not of the whole view
  const clicked: THREE.Intersection[] = [];
  scene.onLayerClick("inspect_surfaces", (intersection) => clicked.push(intersection));
  const freeMiddle = VIEW_WIDTH * 0.375 + (VIEW_WIDTH * 0.625) / 2;
  pointer(canvas, "pointerdown", freeMiddle, VIEW_HEIGHT / 2);
  pointer(canvas, "pointerup", freeMiddle, VIEW_HEIGHT / 2);
  expect(clicked.map((hit) => hit.object)).toEqual([cube]);
  pointer(canvas, "pointerdown", VIEW_WIDTH * 0.1, VIEW_HEIGHT / 2);
  pointer(canvas, "pointerup", VIEW_WIDTH * 0.1, VIEW_HEIGHT / 2);
  expect(clicked).toHaveLength(1);                          // under the panel there is nothing
  // A panel wider than half the view counts as half
  expect(framedWith(VIEW_WIDTH * 0.9)).toBeCloseTo(framedWith(VIEW_WIDTH * 0.5), 9);
});

test("framing orbits about the maximum volume, however far the other visible layers reach, and still fits them", () => {
  const { scene } = viewerWithACube();
  const box = (centre: [number, number, number], side: number) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(side, side, side));
    mesh.position.set(...centre);
    mesh.updateMatrixWorld();
    return mesh;
  };
  scene.setLayer("max_volume", box([5, 5, 10], 10));
  scene.setLayer("sky_dome", box([5, -20, 60], 100));
  const { camera, controls } = scene as unknown as { camera: THREE.PerspectiveCamera; controls: { target: THREE.Vector3 } };

  scene.frameAll(true);
  expect(controls.target.toArray()).toEqual([5, 5, 10]);
  const framed = camera.position.distanceTo(controls.target);
  scene.setLayerVisible("max_volume", false);               // a hidden maximum volume stays the orbit point
  scene.frameAll(true);
  expect(controls.target.toArray()).toEqual([5, 5, 10]);
  scene.setLayerVisible("max_volume", true);

  scene.setLayer("sky_dome", null);
  scene.frameAll(true);
  expect(camera.position.distanceTo(controls.target)).toBeLessThan(framed);     // the dome's reach counted in the distance
});

test("with a scene hemisphere the orbit turns about the centre of the compass ring, at the middle height of the model", () => {
  const { scene } = viewerWithACube();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 20));
  mesh.position.set(5, 5, 10);
  mesh.updateMatrixWorld();
  scene.setLayer("max_volume", mesh);
  scene.setSceneHemisphere({ centre: [40, 30, 0], radius: 60 });
  const { controls } = scene as unknown as { controls: { target: THREE.Vector3 } };

  scene.frameAll(true);
  expect(controls.target.distanceTo(new THREE.Vector3(40, 30, 10))).toBeLessThan(1e-9);
  scene.viewTop();
  scene.setSceneHemisphere(null);
  scene.frameAll(true);
  expect(controls.target.toArray()).toEqual([5, 5, 10]);
});

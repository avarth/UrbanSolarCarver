// The ground aids of the real ViewerScene (R2 2): the ground grid, the compass ring, or neither, and no north arrow on the ground.
// jsdom has no WebGL and no 2D canvas: the renderer is replaced by one that keeps the scene it is asked to draw, and the canvas
// gives a 2D context that measures and draws nothing, for the text of the grid and the ring.
import * as THREE from "three";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest } from "../viewer_overlays/render_for_test";
import { maxVolumeLayer, testSurfacesLayer } from "./layers";
import { ViewerScene } from "./scene";

const drawn = vi.hoisted(() => ({ scene: null as THREE.Scene | null }));

vi.mock("three", async (importOriginal) => {
  const three = await importOriginal<typeof import("three")>();
  class RendererKeepingTheScene {
    readonly domElement = document.createElement("canvas");
    setPixelRatio(): void {}
    setSize(): void {}
    render(scene: THREE.Scene): void { drawn.scene = scene; }
    dispose(): void {}
  }
  return { ...three, WebGLRenderer: RendererKeepingTheScene };
});

const TEXT_CONTEXT = { font: "", fillStyle: "", textBaseline: "", measureText: () => ({ width: 40 }), fillText: () => {} };

let removeTokens: () => void = () => {};
let viewer: ViewerScene | null = null;

beforeEach(() => {
  removeTokens = addStyleSheetForTest("src/theme/tokens.css");
  vi.stubGlobal("ResizeObserver", class { observe(): void {} disconnect(): void {} });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((kind: string) => (kind === "2d" ? TEXT_CONTEXT : null)) as never);
});

afterEach(() => {
  viewer?.dispose();
  viewer = null;
  drawn.scene = null;
  removeTokens();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function drawnScene(): Promise<THREE.Scene> {
  await new Promise((resolve) => requestAnimationFrame(resolve));
  return drawn.scene!;
}

function viewerWithInputs(): ViewerScene {
  const scene = new ViewerScene(document.createElement("div"));
  scene.setLayer("max_volume", maxVolumeLayer(new THREE.BoxGeometry(20, 10, 30).translate(10, 5, 15), "solid"));
  scene.setLayer("test_surfaces", testSurfacesLayer(new THREE.PlaneGeometry(10, 10).translate(45, 5, 0)));      // outside the max volume
  return scene;
}

test("the scene has no north arrow on the ground, and shows the ground grid until another ground aid is chosen", async () => {
  viewer = viewerWithInputs();
  const scene = await drawnScene();
  expect(scene.getObjectByName("north_arrow")).toBeUndefined();
  expect(scene.getObjectByName("ground_grid")!.visible).toBe(true);
  expect(scene.getObjectByName("compass_ring")!.visible).toBe(false);
});

test("the ground aid shows the compass ring, or neither the ring nor the grid", async () => {
  viewer = viewerWithInputs();
  viewer.setGroundAid("compass_ring");
  let scene = await drawnScene();
  expect(scene.getObjectByName("compass_ring")!.visible).toBe(true);
  expect(scene.getObjectByName("ground_grid")!.visible).toBe(false);
  viewer.setGroundAid("off");
  scene = await drawnScene();
  expect(scene.getObjectByName("compass_ring")!.visible).toBe(false);
  expect(scene.getObjectByName("ground_grid")!.visible).toBe(false);
  viewer.setNorth(90);             // the aids are built again for the new north and keep the choice
  scene = await drawnScene();
  expect(scene.getObjectByName("compass_ring")!.visible).toBe(false);
  expect(scene.getObjectByName("ground_grid")!.visible).toBe(false);
});

test("the compass ring is placed around the maximum volume and the test surfaces together, and turns with north", async () => {
  viewer = viewerWithInputs();
  viewer.setNorth(90);
  const ring = (await drawnScene()).getObjectByName("compass_ring")!;
  const north = ring.children.find((child) => child.userData.text === "N")!;
  // The scene runs from 0 to 50 m along x and 0 to 10 m along y: centre (25, 5), radius 75 m; north at 90 degrees is +X
  expect(north.position.x).toBeGreaterThan(25 + 75);
  expect(north.position.y).toBeCloseTo(5);
});

test("an empty scene has no compass ring to size", async () => {
  viewer = new ViewerScene(document.createElement("div"));
  viewer.setGroundAid("compass_ring");
  expect((await drawnScene()).getObjectByName("compass_ring")).toBeUndefined();
});

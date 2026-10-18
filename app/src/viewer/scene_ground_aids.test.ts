// The ground aids of the real ViewerScene (R2 2): the ground grid, the compass ring, or neither, and no north arrow on the ground.
// jsdom has no WebGL and no 2D canvas: the renderer is replaced by one that keeps the scene it is asked to draw, and the canvas
// gives a 2D context that measures and draws nothing, for the text of the grid and the ring.
import * as THREE from "three";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest } from "../viewer_overlays/render_for_test";
import { compassRing } from "./compass_ring";
import { disposeLayer, maxVolumeLayer } from "./layers";
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

/** The colours text was drawn in, in order. */
const textColours: string[] = [];
const TEXT_CONTEXT = {
  font: "", fillStyle: "", textBaseline: "", measureText: () => ({ width: 40 }),
  fillText(this: { fillStyle: string }) { textColours.push(this.fillStyle); },
};

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
  textColours.length = 0;
  removeTokens();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function drawnScene(): Promise<THREE.Scene> {
  await new Promise((resolve) => requestAnimationFrame(resolve));
  return drawn.scene!;
}

// The hemisphere of a scene running from 0 to 50 m along x and 0 to 10 m along y (ProjectWorkspace gives it, see sky_dome.test.ts)
const SCENE_HEMISPHERE = { centre: [25, 5, 0] as [number, number, number], radius: 75 };

function viewerWithInputs(): ViewerScene {
  const scene = new ViewerScene(document.createElement("div"));
  scene.setLayer("max_volume", maxVolumeLayer(new THREE.BoxGeometry(20, 10, 30).translate(10, 5, 15), "solid"));
  scene.setSceneHemisphere(SCENE_HEMISPHERE);
  return scene;
}

function letterOfRing(scene: THREE.Scene, letter: string): THREE.Object3D {
  return scene.getObjectByName("compass_ring")!.children.find((child) => child.userData.text === letter)!;
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

test("the compass ring lies on the rim of the scene hemisphere it is given, and turns with north", async () => {
  viewer = viewerWithInputs();
  let north = letterOfRing(await drawnScene(), "N");
  expect(north.position.x).toBeCloseTo(25);
  expect(north.position.y).toBeGreaterThan(5 + 75);                 // north at 0 degrees is +Y, just outside the 75 m rim
  expect(north.position.y).toBeLessThan(5 + 1.1 * 75);
  viewer.setNorth(90);
  north = letterOfRing(await drawnScene(), "N");
  expect(north.position.x).toBeGreaterThan(25 + 75);                // north at 90 degrees is +X
  expect(north.position.y).toBeCloseTo(5);
  viewer.setSceneHemisphere({ centre: [0, 0, 0], radius: 10 });     // the inputs changed
  north = letterOfRing(await drawnScene(), "N");
  expect(north.position.x).toBeGreaterThan(10);
  expect(north.position.x).toBeLessThan(11);
});

test("an empty scene with the compass ring chosen draws it around the local origin, 60 m wide, as the grid is drawn", async () => {
  viewer = new ViewerScene(document.createElement("div"));
  viewer.setGroundAid("compass_ring");
  const scene = await drawnScene();
  expect(scene.getObjectByName("compass_ring")!.visible).toBe(true);
  const north = letterOfRing(scene, "N");
  expect(north.position.x).toBeCloseTo(0);
  expect(north.position.y).toBeGreaterThan(60);
  expect(north.position.y).toBeLessThan(66);
});

test("the ring's letters are drawn once, in the ink of the viewport theme they are built for", () => {
  disposeLayer(compassRing({ centre: [0, 0, 0], radius: 10 }, 0, "dark"));
  expect(textColours).toEqual(Array(4).fill("#e6ecee"));          // ink-on-dark, for N, E, S and W
});

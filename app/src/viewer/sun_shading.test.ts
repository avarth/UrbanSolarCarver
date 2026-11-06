import * as THREE from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SunShading, isSolidMesh, type SunShadingHost } from "./sun_shading";
import type { ShadeHours } from "./sun_study";

const RECOUNT_DELAY = 250;

function fakeRenderer() {
  return {
    autoClear: true,
    shadowMap: { needsUpdate: false },
    getDrawingBufferSize: (size: THREE.Vector2) => size.set(64, 48),
    getClearColor: (colour: THREE.Color) => colour.set(0x123456),
    getClearAlpha: () => 0.5,
    setRenderTarget: vi.fn(),
    setClearColor: vi.fn(),
    clear: vi.fn(),
    render: vi.fn(),
  };
}

function hostWith(mesh: THREE.Mesh, box = new THREE.Box3(new THREE.Vector3(0, 0, 2), new THREE.Vector3(10, 10, 12))) {
  const scene = new THREE.Scene();
  scene.add(mesh);
  const renderer = fakeRenderer();
  const host = {
    scene, renderer: renderer as unknown as THREE.WebGLRenderer, camera: new THREE.PerspectiveCamera(),
    skyLight: new THREE.HemisphereLight(0xffffff, 0xffffff, 2), fixedLight: new THREE.DirectionalLight(0xffffff, 3),
    shadowMeshes: () => [mesh], siteBox: () => box, terrainShown: () => false, clipCircle: () => null, requestRender: vi.fn(),
  } satisfies SunShadingHost;
  return { host, renderer };
}

function shade(overrides: Partial<ShadeHours> = {}): ShadeHours {
  return { directions: [[0, 0, 1], [1, 0, 1]], hoursEach: 0.5, maxHours: 1, palette: "viridis", ...overrides } as ShadeHours;
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

test("a mesh is solid and a fat line, which three draws as a mesh, is not", () => {
  expect(isSolidMesh(new THREE.Mesh())).toBe(true);
  expect(isSolidMesh(new LineSegments2())).toBe(false);
  expect(isSolidMesh(new THREE.Line())).toBe(false);
  expect(isSolidMesh(new THREE.Group())).toBe(false);
});

test("while the sun casts shadows the fixed light is off, the sky light low and the meshes cast and catch; off again restores them", () => {
  const mesh = new THREE.Mesh();
  const { host, renderer } = hostWith(mesh);
  const shading = new SunShading(host);
  shading.set([0, -1, 1], true, null);
  shading.prepare();
  expect([shading.light.visible, shading.light.castShadow, mesh.castShadow, mesh.receiveShadow]).toEqual([true, true, true, true]);
  expect([host.skyLight.intensity, host.fixedLight.intensity]).toEqual([1.1, 0]);
  expect(shading.ground.visible).toBe(true);
  expect(renderer.shadowMap.needsUpdate).toBe(true);
  shading.set(null, true, null);
  shading.prepare();
  expect([shading.light.visible, mesh.castShadow, shading.ground.visible]).toEqual([false, false, false]);
  expect([host.skyLight.intensity, host.fixedLight.intensity]).toEqual([2, 3]);
});

test("the ground catches shadows just under the site, and not with the terrain shown or nothing loaded", () => {
  const { host } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set([0, 0, 1], true, null);
  shading.prepare();
  expect(shading.ground.position.toArray()).toEqual([5, 5, 1.98]);

  const terrain = hostWith(new THREE.Mesh());
  const onTerrain = new SunShading({ ...terrain.host, terrainShown: () => true });
  onTerrain.set([0, 0, 1], true, null);
  onTerrain.prepare();
  expect(onTerrain.ground.visible).toBe(false);

  const empty = hostWith(new THREE.Mesh(), new THREE.Box3());
  const onNothing = new SunShading(empty.host);
  onNothing.set([0, 0, 1], true, null);
  onNothing.prepare();
  expect(onNothing.ground.visible).toBe(false);
});

test("the light stands on the sun's side of the site, its shadow camera around the site", () => {
  const { host } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set([0, 0, 2], true, null);
  shading.prepare();
  const radius = Math.sqrt(3) * 5;
  const reach = 2.5 * radius;
  expect(shading.light.target.position.toArray()).toEqual([5, 5, 7]);
  expect(shading.light.position.z).toBeCloseTo(7 + 2 * reach);
  expect(shading.light.shadow.camera.right).toBeCloseTo(reach);
  expect(shading.light.shadow.camera.far).toBeCloseTo(4 * reach);
});

test("the count waits for things to rest, renders once for the mask and once per sun position, and asks for a frame", () => {
  const { host, renderer } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set(null, false, shade());
  shading.invalidate();
  vi.advanceTimersByTime(RECOUNT_DELAY - 1);
  expect(renderer.render).not.toHaveBeenCalled();
  shading.invalidate();                 // the camera moved again: the wait starts over
  vi.advanceTimersByTime(RECOUNT_DELAY - 1);
  expect(renderer.render).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(renderer.render).toHaveBeenCalledTimes(1 + 2);
  expect(host.requestRender).toHaveBeenCalledTimes(1);
});

test("another palette keeps the count, other hours count again", () => {
  const { host, renderer } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  const first = shade();
  shading.set(null, false, first);
  vi.advanceTimersByTime(RECOUNT_DELAY);
  renderer.render.mockClear();
  shading.set(null, false, { ...first, palette: "grey" });
  vi.advanceTimersByTime(RECOUNT_DELAY);
  expect(renderer.render).not.toHaveBeenCalled();
  shading.set(null, false, { ...first, hoursEach: 1 });
  vi.advanceTimersByTime(RECOUNT_DELAY);
  expect(renderer.render).toHaveBeenCalled();
});

test("the count leaves the scene, the lights and the renderer as they were", () => {
  const mesh = new THREE.Mesh();
  mesh.visible = false;
  const { host, renderer } = hostWith(mesh);
  const line = new THREE.Line();
  host.scene.add(line, host.skyLight, host.fixedLight);
  host.scene.background = new THREE.Color(0xffffff);
  const background = host.scene.background;
  const shading = new SunShading(host);
  let visibleWhileCounting: boolean[] = [];
  renderer.render.mockImplementation(() => { visibleWhileCounting = [mesh.visible, line.visible, host.skyLight.visible, shading.light.visible]; });
  shading.set(null, false, shade());
  vi.advanceTimersByTime(RECOUNT_DELAY);
  expect(visibleWhileCounting).toEqual([true, false, false, true]);
  expect([mesh.visible, line.visible, host.skyLight.visible, shading.light.visible]).toEqual([false, true, true, false]);
  expect([mesh.castShadow, mesh.receiveShadow, shading.light.castShadow]).toEqual([false, false, false]);
  expect(host.scene.background).toBe(background);
  expect(host.scene.overrideMaterial).toBeNull();
  expect(renderer.autoClear).toBe(true);
  expect(renderer.setRenderTarget).toHaveBeenLastCalledWith(null);
  expect(renderer.setClearColor).toHaveBeenLastCalledWith(expect.objectContaining({ r: expect.any(Number) }), 0.5);
});

test("without anything loaded nothing is counted, and the overlay waits for a count", () => {
  const { host, renderer } = hostWith(new THREE.Mesh(), new THREE.Box3());
  const shading = new SunShading(host);
  shading.set(null, false, shade());
  vi.advanceTimersByTime(RECOUNT_DELAY);
  shading.drawOverlay();
  expect(renderer.render).not.toHaveBeenCalled();
});

test("the overlay draws once counted, and a moved camera stops it until the next count", () => {
  const { host, renderer } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set(null, false, shade());
  vi.advanceTimersByTime(RECOUNT_DELAY);
  renderer.render.mockClear();
  shading.drawOverlay();
  expect(renderer.render).toHaveBeenCalledTimes(1);
  expect(renderer.autoClear).toBe(true);
  shading.invalidate();
  shading.drawOverlay();
  expect(renderer.render).toHaveBeenCalledTimes(1);
});

test("dispose stops a count that is waiting", () => {
  const { host, renderer } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set(null, false, shade());
  shading.dispose();
  vi.advanceTimersByTime(RECOUNT_DELAY);
  expect(renderer.render).not.toHaveBeenCalled();
});

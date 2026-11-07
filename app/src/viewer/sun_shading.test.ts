import * as THREE from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { expect, test } from "vitest";
import { SunShading, isSolidMesh, type SunShadingHost } from "./sun_shading";

function hostWith(mesh: THREE.Mesh, box = new THREE.Box3(new THREE.Vector3(0, 0, 2), new THREE.Vector3(10, 10, 12))) {
  const scene = new THREE.Scene();
  scene.add(mesh);
  const renderer = { shadowMap: { needsUpdate: false } };
  const host = {
    scene, renderer: renderer as unknown as THREE.WebGLRenderer,
    skyLight: new THREE.HemisphereLight(0xffffff, 0xffffff, 2), fixedLight: new THREE.DirectionalLight(0xffffff, 3),
    shadowMeshes: () => [mesh], siteBox: () => box, terrainShown: () => false,
  } satisfies SunShadingHost;
  return { host, renderer };
}

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
  shading.set([0, -1, 1], true);
  shading.prepare();
  expect([shading.light.visible, shading.light.castShadow, mesh.castShadow, mesh.receiveShadow]).toEqual([true, true, true, true]);
  expect([host.skyLight.intensity, host.fixedLight.intensity]).toEqual([1.1, 0]);
  expect(shading.ground.visible).toBe(true);
  expect(renderer.shadowMap.needsUpdate).toBe(true);
  shading.set(null, true);
  shading.prepare();
  expect([shading.light.visible, mesh.castShadow, shading.ground.visible]).toEqual([false, false, false]);
  expect([host.skyLight.intensity, host.fixedLight.intensity]).toEqual([2, 3]);
});

test("the ground catches shadows just under the site, and not with the terrain shown or nothing loaded", () => {
  const { host } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set([0, 0, 1], true);
  shading.prepare();
  expect(shading.ground.position.toArray()).toEqual([5, 5, 1.98]);

  const terrain = hostWith(new THREE.Mesh());
  const onTerrain = new SunShading({ ...terrain.host, terrainShown: () => true });
  onTerrain.set([0, 0, 1], true);
  onTerrain.prepare();
  expect(onTerrain.ground.visible).toBe(false);

  const empty = hostWith(new THREE.Mesh(), new THREE.Box3());
  const onNothing = new SunShading(empty.host);
  onNothing.set([0, 0, 1], true);
  onNothing.prepare();
  expect(onNothing.ground.visible).toBe(false);
});

test("the light stands on the sun's side of the site, its shadow camera around the site", () => {
  const { host } = hostWith(new THREE.Mesh());
  const shading = new SunShading(host);
  shading.set([0, 0, 2], true);
  shading.prepare();
  const radius = Math.sqrt(3) * 5;
  const reach = 2.5 * radius;
  expect(shading.light.target.position.toArray()).toEqual([5, 5, 7]);
  expect(shading.light.position.z).toBeCloseTo(7 + 2 * reach);
  expect(shading.light.shadow.camera.right).toBeCloseTo(reach);
  expect(shading.light.shadow.camera.far).toBeCloseTo(4 * reach);
});

// The sun tool in the 3D view: a sun light at the chosen time that casts shadows (three.js shadow maps) on the solid layers and on
// the ground where no terrain is. Simulate's Sun hours studies count the hours of sun per test point; the view only shows a moment.
import * as THREE from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import type { Point3 } from "./local_origin";

const SHADOW_MAP_PIXELS = 4096;
// The shadow camera covers this many site radii around the site's centre: the surroundings' shadows on the site, the site's on them.
const SHADOW_REACH = 2.5;
const SUN_INTENSITY = 2.4;
// While the sun casts shadows the sky light is lowered and the fixed light switched off, so the shade reads.
const SKY_INTENSITY_WITH_SHADOWS = 1.1;
const GROUND_SHADOW_OPACITY = 0.3;

/** What the sun shading needs of the view. */
export interface SunShadingHost {
  scene: THREE.Scene;
  renderer: THREE.WebGLRenderer;
  skyLight: THREE.HemisphereLight;
  fixedLight: THREE.DirectionalLight;
  /** The meshes that cast and catch the sun's shadows: the solid layers shown. */
  shadowMeshes(): THREE.Mesh[];
  /** The box of the site (the maximum volume and what lies on it); empty before anything is loaded. */
  siteBox(): THREE.Box3;
  /** The terrain is shown: it catches the shadows on the ground, so the shadow catcher stays hidden. */
  terrainShown(): boolean;
}

/** Whether *object* is a solid mesh that casts and catches shadows (not a fat line, which three draws as a mesh). */
export function isSolidMesh(object: THREE.Object3D): object is THREE.Mesh {
  return (object as THREE.Mesh).isMesh === true && !(object instanceof LineSegments2);
}

export class SunShading {
  readonly light = new THREE.DirectionalLight(0xffffff, SUN_INTENSITY);
  /** Catches the shadows on the ground where no terrain is. */
  readonly ground: THREE.Mesh;
  private readonly host: SunShadingHost;
  private direction: THREE.Vector3 | null = null;
  private shadows = false;
  private readonly skyIntensity: number;
  private readonly fixedIntensity: number;

  constructor(host: SunShadingHost) {
    this.host = host;
    this.skyIntensity = host.skyLight.intensity;
    this.fixedIntensity = host.fixedLight.intensity;
    this.light.visible = false;
    this.light.shadow.mapSize.set(SHADOW_MAP_PIXELS, SHADOW_MAP_PIXELS);
    this.ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ opacity: GROUND_SHADOW_OPACITY }));
    this.ground.receiveShadow = true;
    this.ground.visible = false;
    host.scene.add(this.light, this.light.target, this.ground);
  }

  /** The sun toward *direction* (null: none), casting shadows when *shadows*. */
  set(direction: Point3 | null, shadows: boolean): void {
    this.direction = direction === null ? null : new THREE.Vector3(...direction).normalize();
    this.shadows = shadows && direction !== null;
  }

  /** Before each frame: the sun, its shadow flags and the lights as the tool is set. */
  prepare(): void {
    const casting = this.shadows && this.direction !== null;
    this.light.visible = casting;
    this.light.castShadow = casting;
    this.host.skyLight.intensity = casting ? SKY_INTENSITY_WITH_SHADOWS : this.skyIntensity;
    this.host.fixedLight.intensity = casting ? 0 : this.fixedIntensity;
    for (const mesh of this.host.shadowMeshes()) {
      mesh.castShadow = casting;
      mesh.receiveShadow = casting;
    }
    this.ground.visible = casting && !this.host.terrainShown() && this.placeGround();
    if (casting) this.placeLight(this.direction!);
    this.host.renderer.shadowMap.needsUpdate = casting;
  }

  dispose(): void {
    this.light.shadow.dispose();
    this.ground.geometry.dispose();
    (this.ground.material as THREE.Material).dispose();
  }

  /** The site's centre and radius, for the shadow camera and the ground; null before anything is loaded. */
  private site(): { centre: THREE.Vector3; radius: number; groundZ: number } | null {
    const box = this.host.siteBox();
    if (box.isEmpty()) return null;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    return { centre: sphere.center, radius: Math.max(sphere.radius, 1), groundZ: box.min.z };
  }

  private placeGround(): boolean {
    const site = this.site();
    if (site === null) return false;
    const width = 2 * SHADOW_REACH * site.radius;
    this.ground.scale.set(width, width, 1);
    this.ground.position.set(site.centre.x, site.centre.y, site.groundZ - 0.02);
    return true;
  }

  /** The sun toward *direction*, its orthographic shadow camera around the site. */
  private placeLight(direction: THREE.Vector3): void {
    const site = this.site();
    if (site === null) return;
    const reach = SHADOW_REACH * site.radius;
    this.light.target.position.copy(site.centre);
    this.light.position.copy(site.centre).addScaledVector(direction, 2 * reach);
    const shadowCamera = this.light.shadow.camera;
    shadowCamera.left = -reach;
    shadowCamera.right = reach;
    shadowCamera.top = reach;
    shadowCamera.bottom = -reach;
    shadowCamera.near = 0.01;
    shadowCamera.far = 4 * reach;
    shadowCamera.updateProjectionMatrix();
    this.light.target.updateMatrixWorld();
    this.light.updateMatrixWorld();
    // A texel of the shadow map is 2 reach / SHADOW_MAP_PIXELS wide: offsets of about a texel keep lit faces from shading themselves.
    this.light.shadow.normalBias = (3 * reach) / SHADOW_MAP_PIXELS;
    this.light.shadow.bias = -0.0002;
  }
}

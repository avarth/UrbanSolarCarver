// Inspect's sun tool in the 3D view: a sun light at the chosen time that casts shadows (three.js shadow maps), and a quick count of
// the hours in shade over a range of times.
//
// The count draws the solid meshes from the camera once for every sun position into a float target, adding the hours each position
// stands for wherever a surface is in shade (behind something from the sun, or turned away from it), and shows the sum over the view
// in a colour ramp: viridis, from yellow at no shade to dark at the whole range in shade. It is a picture of what the camera sees,
// counted again once the camera rests and hidden while it moves, at the shadow map's resolution; Simulate's sun hours are the precise
// count, per test point.
import * as THREE from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import type { Point3 } from "./local_origin";
import { studyPaletteColour } from "./study_palettes";
import type { ShadeHours } from "./sun_study";

const SHADOW_MAP_PIXELS = 4096;
// The shadow camera covers this many site radii around the site's centre: the surroundings' shadows on the site, the site's on them.
const SHADOW_REACH = 2.5;
const SUN_INTENSITY = 2.4;
// While the sun casts shadows the sky light is lowered and the fixed light switched off, so the shade reads.
const SKY_INTENSITY_WITH_SHADOWS = 1.1;
const GROUND_SHADOW_OPACITY = 0.3;
const SHADE_OVERLAY_OPACITY = 0.85;
const RECOUNT_DELAY_MILLISECONDS = 250;
const LIT_THRESHOLD = 1e-4;
const RAMP_ENTRIES = 256;

/** What the sun shading needs of the view. */
export interface SunShadingHost {
  scene: THREE.Scene;
  renderer: THREE.WebGLRenderer;
  camera: THREE.Camera;
  skyLight: THREE.HemisphereLight;
  fixedLight: THREE.DirectionalLight;
  /** The meshes that cast and catch the sun's shadows: the solid layers shown. */
  shadowMeshes(): THREE.Mesh[];
  /** The box of the site (the maximum volume and what lies on it); empty before anything is loaded. */
  siteBox(): THREE.Box3;
  /** The terrain is shown: it catches the shadows on the ground, so the shadow catcher stays hidden. */
  terrainShown(): boolean;
  requestRender(): void;
}

/** Whether *object* is a solid mesh that casts and catches shadows (not a fat line, which three draws as a mesh). */
export function isSolidMesh(object: THREE.Object3D): object is THREE.Mesh {
  return (object as THREE.Mesh).isMesh === true && !(object instanceof LineSegments2);
}

/** viridis as RGBA bytes from 0 to 1, for the overlay's lookup. */
function viridisRamp(): THREE.DataTexture {
  const bytes = new Uint8Array(RAMP_ENTRIES * 4);
  const colour = new THREE.Color();
  for (let entry = 0; entry < RAMP_ENTRIES; entry++) {
    colour.setStyle(studyPaletteColour("viridis", (entry + 0.5) / RAMP_ENTRIES), THREE.NoColorSpace);
    bytes.set([Math.round(colour.r * 255), Math.round(colour.g * 255), Math.round(colour.b * 255), 255], entry * 4);
  }
  const texture = new THREE.DataTexture(bytes, RAMP_ENTRIES, 1);
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

export class SunShading {
  readonly light = new THREE.DirectionalLight(0xffffff, SUN_INTENSITY);
  /** Catches the shadows on the ground where no terrain is. */
  readonly ground: THREE.Mesh;
  private readonly host: SunShadingHost;
  private direction: THREE.Vector3 | null = null;
  private shadows = false;
  private shade: ShadeHours | null = null;
  private target: THREE.WebGLRenderTarget | null = null;
  private counted = false;
  private recountTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly skyIntensity: number;
  private readonly fixedIntensity: number;
  private readonly maskMaterial = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
  private readonly countMaterial: THREE.MeshLambertMaterial;
  private readonly hoursEach = { value: 0 };
  private readonly overlayScene = new THREE.Scene();
  private readonly overlayCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private readonly overlayMaterial: THREE.ShaderMaterial;

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

    // The count: Lambert lit by the sun alone, written as the hours of this position where nothing of the sun arrives, added up.
    this.countMaterial = new THREE.MeshLambertMaterial({
      side: THREE.DoubleSide, blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor,
      blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor, depthWrite: false, depthFunc: THREE.LessEqualDepth,
      polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
    });
    this.countMaterial.onBeforeCompile = (shader) => {
      shader.uniforms.shadeHours = this.hoursEach;
      shader.fragmentShader = `uniform float shadeHours;\n${shader.fragmentShader}`.replace("#include <opaque_fragment>",
        `#include <opaque_fragment>\n\tgl_FragColor = vec4(vec3(dot(outgoingLight, vec3(1.0)) < ${LIT_THRESHOLD.toExponential()} ? shadeHours : 0.0), 0.0);`);
    };
    this.overlayMaterial = new THREE.ShaderMaterial({
      uniforms: { counted: { value: null }, ramp: { value: viridisRamp() }, maxHours: { value: 1 }, opacity: { value: SHADE_OVERLAY_OPACITY } },
      vertexShader: "varying vec2 vUv;\nvoid main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader: [
        "uniform sampler2D counted; uniform sampler2D ramp; uniform float maxHours; uniform float opacity; varying vec2 vUv;",
        "void main() {",
        "  vec4 sum = texture2D(counted, vUv);",
        "  if (sum.a < 0.5) discard;",
        "  float share = clamp(sum.r / maxHours, 0.0, 1.0);",
        "  gl_FragColor = vec4(texture2D(ramp, vec2(1.0 - share, 0.5)).rgb, opacity);",
        "}",
      ].join("\n"),
      transparent: true, depthTest: false, depthWrite: false,
    });
    this.overlayScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.overlayMaterial));
  }

  /** The sun toward *direction* (null: none), casting shadows when *shadows*; the hours in shade over a range, or null. */
  set(direction: Point3 | null, shadows: boolean, shade: ShadeHours | null): void {
    this.direction = direction === null ? null : new THREE.Vector3(...direction).normalize();
    this.shadows = shadows && direction !== null;
    if (shade !== this.shade) {
      this.shade = shade;
      this.invalidate();
    }
  }

  /** The camera or the content changed: the count no longer matches the view; it is counted again once things rest. */
  invalidate(): void {
    this.counted = false;
    if (this.recountTimer !== null) clearTimeout(this.recountTimer);
    this.recountTimer = null;
    if (this.shade === null) return;
    this.recountTimer = setTimeout(() => {
      this.recountTimer = null;
      this.count();
      this.host.requestRender();
    }, RECOUNT_DELAY_MILLISECONDS);
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
  }

  /** After each frame: the hours in shade over the view, when counted for the camera as it is. */
  drawOverlay(): void {
    if (this.shade === null || !this.counted || this.target === null) return;
    this.overlayMaterial.uniforms.counted.value = this.target.texture;
    this.overlayMaterial.uniforms.maxHours.value = Math.max(this.shade.maxHours, 1e-6);
    const autoClear = this.host.renderer.autoClear;
    this.host.renderer.autoClear = false;
    this.host.renderer.render(this.overlayScene, this.overlayCamera);
    this.host.renderer.autoClear = autoClear;
  }

  dispose(): void {
    if (this.recountTimer !== null) clearTimeout(this.recountTimer);
    this.target?.dispose();
    this.light.shadow.dispose();
    this.ground.geometry.dispose();
    (this.ground.material as THREE.Material).dispose();
    this.maskMaterial.dispose();
    this.countMaterial.dispose();
    this.overlayMaterial.uniforms.ramp.value.dispose();
    this.overlayMaterial.dispose();
  }

  // ------------------------------------------------------------------------------------------------------------------------

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

  /** Counts the hours in shade over the view: the meshes only, lit by the sun alone, once per sun position. */
  private count(): void {
    const shade = this.shade;
    const { renderer, scene, camera } = this.host;
    if (shade === null || this.site() === null) return;
    const size = renderer.getDrawingBufferSize(new THREE.Vector2());
    if (this.target === null || this.target.width !== size.x || this.target.height !== size.y) {
      this.target?.dispose();
      this.target = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType });
    }
    const meshes = new Set<THREE.Object3D>(this.host.shadowMeshes());
    const groundCounts = !this.host.terrainShown() && this.placeGround();
    if (groundCounts) meshes.add(this.ground);
    // Everything else is hidden for the count, and every light but the sun.
    const hidden: THREE.Object3D[] = [];
    scene.traverse((object) => {
      const drawn = (object as THREE.Mesh).isMesh || (object as THREE.Line).isLine || (object as THREE.Points).isPoints || (object as THREE.Sprite).isSprite
        || (object as THREE.Light).isLight;
      if (drawn && object.visible && !meshes.has(object) && object !== this.light) {
        object.visible = false;
        hidden.push(object);
      }
    });
    const flags = [...meshes].map((object) => [object, object.visible, (object as THREE.Mesh).castShadow, (object as THREE.Mesh).receiveShadow] as const);
    for (const object of meshes) {
      object.visible = true;
      (object as THREE.Mesh).castShadow = object !== this.ground;
      (object as THREE.Mesh).receiveShadow = true;
    }
    const lightState = [this.light.visible, this.light.castShadow] as const;
    this.light.visible = true;
    this.light.castShadow = true;
    const background = scene.background;
    const clearColour = renderer.getClearColor(new THREE.Color());
    const clearAlpha = renderer.getClearAlpha();
    const autoClear = renderer.autoClear;
    scene.background = null;
    renderer.autoClear = false;
    renderer.setRenderTarget(this.target);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    // The surfaces seen, marked with alpha 1; then one pass per sun position adds its hours where the surface is in shade.
    scene.overrideMaterial = this.maskMaterial;
    renderer.render(scene, camera);
    scene.overrideMaterial = this.countMaterial;
    this.hoursEach.value = shade.hoursEach;
    for (const direction of shade.directions) {
      this.placeLight(new THREE.Vector3(...direction).normalize());
      renderer.shadowMap.needsUpdate = true;
      renderer.render(scene, camera);
    }
    scene.overrideMaterial = null;
    renderer.setRenderTarget(null);
    renderer.setClearColor(clearColour, clearAlpha);
    renderer.autoClear = autoClear;
    scene.background = background;
    [this.light.visible, this.light.castShadow] = lightState;
    for (const [object, visible, castShadow, receiveShadow] of flags) {
      object.visible = visible;
      (object as THREE.Mesh).castShadow = castShadow;
      (object as THREE.Mesh).receiveShadow = receiveShadow;
    }
    for (const object of hidden) object.visible = true;
    this.counted = true;
  }
}

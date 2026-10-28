// The 3D view (UX 8): a three.js scene with Z up in local coordinates, one ground aid (the ground grid, the compass ring or
// neither, R2 2), and one slot per layer.
// Orbit with the left mouse button, pan with the right, zoom with the wheel. A click (a press and release within 5 px and 400 ms)
// goes to the listeners of onLayerClick, unless an opaque surrounding (context, terrain) is nearer along the ray. Camera moves of frameAll, frameBox and viewTop take 400 ms, and are instant under
// prefers-reduced-motion. No React here: the overlays (viewer_overlays/) read the camera through
// onCameraChange and call the methods below. Simulate's sun tool adds a sun that casts shadows and a count of the hours in shade
// (sun_shading.ts).
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { messages } from "../messages";
import { colourToken, viewportBackground, type ViewportTheme } from "./colour_scales";
import { northDirection } from "./compass";
import { compassRing } from "./compass_ring";
import { groundGrid, groundGridSpacing } from "./ground_grid";
import type { Point3 } from "./local_origin";
import { LAYER_NAMES, SURROUNDING_LAYERS, applyLayerAppearance, dimmedAppearance, disposeLayer, type LayerName } from "./layers";
import type { Hemisphere } from "./sky_dome";
import { isSolidMesh, SunShading } from "./sun_shading";
import type { ShadeHours } from "./sun_study";
import { fitTextSpritesToView } from "./text_sprite";

export type { LayerName } from "./layers";
export type { ViewportTheme } from "./colour_scales";

/** What lies on the ground (R2 2): nothing, the ground grid of UX 8.1, or the compass ring around the scene. */
export type GroundAid = "off" | "grid" | "compass_ring";

/** The ground aids in the order the toolbar button goes through them. */
export const GROUND_AIDS: readonly GroundAid[] = ["off", "grid", "compass_ring"];

/** The ground aid the toolbar button switches to from *current*: off, ground grid, compass ring, and off again. */
export function nextGroundAid(current: GroundAid): GroundAid {
  return GROUND_AIDS[(GROUND_AIDS.indexOf(current) + 1) % GROUND_AIDS.length];
}

export interface CameraState {
  yawDegrees: number;          // clockwise turn of the view about Z from the top view with +Y up the screen
  elevationDegrees: number;    // how far the view looks down: 90 in the top view, 0 looking level
  metresPerPixel: number;      // at the orbit target
}

export interface LayerDescription {
  label: string;
  detail: string | null;
  dimmed: boolean;
}

const CAMERA_MOVE_MILLISECONDS = 400;
export const DEFAULT_SKY_DOME_OPACITY = 0.6;
const FIELD_OF_VIEW_DEGREES = 35;
const FRAME_MARGIN = 1.1;
const CLICK_MAX_PIXELS = 5;                 // a press that moved further is an orbit drag
const CLICK_MAX_MILLISECONDS = 400;
// The layers drawn opaque that a click does not pass through to the layer listened to (the maximum volume is see-through in Inspect).
const CLICK_OCCLUDING_LAYERS: readonly LayerName[] = SURROUNDING_LAYERS;
// How much farther than the nearest occluding hit a layer's hit may be and still take the click: test surfaces lie on context faces.
const CLICK_OCCLUSION_TOLERANCE_METRES = 0.05;
const TOP_VIEW_TILT_RADIANS = 1e-3;         // a hair off straight down, so "up" on the screen is defined and points north
const FIRST_VIEW_DIRECTION = new THREE.Vector3(-0.5, -0.9, 0.75).normalize();     // from the south-south-west, above
const EMPTY_SCENE_RADIUS_METRES = 60;
const EMPTY_SCENE_HEMISPHERE: Hemisphere = { centre: [0, 0, 0], radius: EMPTY_SCENE_RADIUS_METRES };
// The layers drawn after the hours in shade, over them: the sun path and the sky dome, and the compass ring (three.js layer 1; the
// rest is layer 0).
const OVER_THE_COUNT_LAYERS: readonly LayerName[] = ["sun_path", "sky_dome", "sun_study"];
const OVER_THE_COUNT = 1;
// The layers whose meshes cast and catch the sun's shadows, and those that make up the site the shadow camera covers.
const SHADOW_LAYERS: readonly LayerName[] = ["max_volume", "test_surfaces", "context", "terrain", "envelope", "building_massing", "inspect_surfaces"];
const SITE_LAYERS: readonly LayerName[] = ["max_volume", "test_surfaces", "envelope", "building_massing", "inspect_surfaces"];

const toDegrees = (radians: number) => (radians / Math.PI) * 180;
const normalisedDegrees = (angle: number) => ((angle % 360) + 360) % 360;

/** Camera yaw and elevation from its forward and its screen-up directions (both unit vectors in model coordinates). */
export function cameraOrientation(forward: ArrayLike<number>, screenUp: ArrayLike<number>): { yawDegrees: number; elevationDegrees: number } {
  // Without roll, the forward and the screen-up directions share the horizontal direction the view faces; their sum is never
  // vertical, whether the camera looks straight down (forward vertical) or level (screen-up vertical).
  const facingX = forward[0] + screenUp[0], facingY = forward[1] + screenUp[1];
  return {
    yawDegrees: normalisedDegrees(toDegrees(Math.atan2(facingX, facingY))),
    elevationDegrees: toDegrees(Math.asin(Math.max(-1, Math.min(1, -forward[2])))),
  };
}

export function metresPerPixelAt(distanceMetres: number, fieldOfViewDegrees: number, viewportHeightPixels: number): number {
  return (2 * distanceMetres * Math.tan((fieldOfViewDegrees * Math.PI) / 360)) / viewportHeightPixels;
}

/** The view's accessible name (UX 12): the layers on screen, with their counts and whether they are out of date. */
export function describeView(layers: LayerDescription[]): string {
  if (!layers.length) return messages.viewEmpty;
  const items = layers.map((layer) => [layer.label, layer.detail, layer.dimmed ? messages.outOfDate : null].filter(Boolean).join(", "));
  return messages.viewShowing(items.join("; "));
}

interface LayerSlot {
  object: THREE.Object3D | null;
  visible: boolean;
  dimmed: boolean;
}

interface Press {
  x: number;
  y: number;
  time: number;
}

interface CameraMove {
  startTime: number;
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
  from: THREE.Spherical;
  to: THREE.Spherical;
}

function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

/** Spherical coordinates of an offset about Z (phi from +Z, theta from +X toward +Y). */
function sphericalAboutZ(offset: THREE.Vector3): THREE.Spherical {
  const radius = offset.length();
  return new THREE.Spherical(radius, Math.acos(Math.max(-1, Math.min(1, offset.z / radius))), Math.atan2(offset.y, offset.x));
}

function offsetOf(spherical: THREE.Spherical): THREE.Vector3 {
  const horizontal = spherical.radius * Math.sin(spherical.phi);
  return new THREE.Vector3(horizontal * Math.cos(spherical.theta), horizontal * Math.sin(spherical.theta), spherical.radius * Math.cos(spherical.phi));
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export class ViewerScene {
  private readonly container: HTMLElement;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly resizeObserver: ResizeObserver;
  private readonly hoverLabel: HTMLDivElement;
  private readonly slots = new Map<LayerName, LayerSlot>(LAYER_NAMES.map((name) => [name, { object: null, visible: true, dimmed: false }]));
  private readonly cameraListeners = new Set<(camera: CameraState) => void>();
  private theme: ViewportTheme = "light";
  private northDegrees = 0;
  private skyDomeOpacity = DEFAULT_SKY_DOME_OPACITY;
  private envelopeSeeThrough = false;
  private groundAid: GroundAid = "grid";
  private sceneHemisphere: Hemisphere | null = null;
  private grid: THREE.Group | null = null;
  private ring: THREE.Group | null = null;
  private hasFramedContent = false;
  private cameraMove: CameraMove | null = null;
  private frameRequest: number | null = null;
  private pendingHover: { x: number; y: number } | null = null;
  private press: Press | null = null;
  private readonly clickListeners = new Map<LayerName, Set<(intersection: THREE.Intersection) => void>>();
  private readonly sunShading: SunShading;

  constructor(container: HTMLElement) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.shadowMap.enabled = true;          // only Simulate's sun casts shadows, and only while asked to
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.shadowMap.autoUpdate = false;      // drawn again when the sun casts (SunShading.prepare, count)
    const canvas = this.renderer.domElement;
    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.setAttribute("role", "img");
    container.appendChild(canvas);

    this.camera = new THREE.PerspectiveCamera(FIELD_OF_VIEW_DEGREES, 1, 0.1, 10_000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.addEventListener("change", () => this.cameraChanged());
    this.controls.addEventListener("start", () => { this.cameraMove = null; });     // the user takes over from a camera move

    const skyLight = new THREE.HemisphereLight(colourToken("light-sky"), colourToken("light-ground"), 2.2);
    skyLight.position.set(0, 0, 1);
    const fixedLight = new THREE.DirectionalLight(colourToken("light-sky"), 1.6);
    fixedLight.position.set(-0.45, -0.7, 1);
    this.scene.add(skyLight, fixedLight);
    this.sunShading = new SunShading({
      scene: this.scene, renderer: this.renderer, camera: this.camera, skyLight, fixedLight,
      shadowMeshes: () => this.shadowMeshes(),
      siteBox: () => this.boxOf(SITE_LAYERS, false),
      terrainShown: () => { const terrain = this.slots.get("terrain")!; return terrain.object !== null && terrain.visible; },
      clipCircle: () => (this.sceneHemisphere === null ? null
        : { centre: [this.sceneHemisphere.centre[0], this.sceneHemisphere.centre[1]], radius: this.sceneHemisphere.radius }),
      requestRender: () => this.requestRender(),
    });

    this.hoverLabel = document.createElement("div");
    this.hoverLabel.style.cssText = "position:absolute;pointer-events:none;display:none;padding:2px 6px;border-radius:var(--radius-small);" +
      "font:var(--text-secondary)/var(--line-height) var(--font-family);";
    container.appendChild(this.hoverLabel);
    canvas.addEventListener("pointermove", (event) => this.queueHover(event));
    canvas.addEventListener("pointerleave", () => { this.pendingHover = null; this.hoverLabel.style.display = "none"; });
    canvas.addEventListener("pointerdown", (event) => { this.press = event.button === 0 ? { x: event.clientX, y: event.clientY, time: performance.now() } : null; });
    canvas.addEventListener("pointercancel", () => { this.press = null; });
    canvas.addEventListener("pointerup", (event) => this.released(event));

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);

    this.rebuildGroundAids();
    this.placeCamera(new THREE.Vector3(), FIRST_VIEW_DIRECTION.clone().multiplyScalar(this.fittingDistance(EMPTY_SCENE_RADIUS_METRES)));
    this.setViewportTheme("light");
    this.resize();
  }

  setNorth(northDegrees: number): void {
    this.northDegrees = northDegrees;
    this.rebuildGroundAids();
    this.cameraChanged();
  }

  /** Puts an object in a layer's slot (null empties it); the slot keeps its visible and dimmed states. */
  setLayer(name: LayerName, object: THREE.Object3D | null): void {
    const slot = this.slots.get(name)!;
    if (slot.object) {
      this.scene.remove(slot.object);
      disposeLayer(slot.object);
    }
    slot.object = object;
    if (object) {
      object.name = name;
      if (OVER_THE_COUNT_LAYERS.includes(name)) object.traverse((child) => child.layers.set(OVER_THE_COUNT));
      object.userData.applyTheme?.(this.theme);
      object.userData.followCamera?.(this.camera.position);
      this.scene.add(object);
    }
    this.refreshLayers();
    if (name === "max_volume" || !this.slots.get("max_volume")!.object) this.rebuildGroundAids();
    if (object && !this.hasFramedContent) {
      this.hasFramedContent = true;
      this.frameAll(true);
    }
  }

  setLayerVisible(name: LayerName, visible: boolean): void {
    this.slots.get(name)!.visible = visible;
    this.refreshLayers();
  }

  /** Out of date: drawn at 35 % opacity and desaturated. */
  setLayerDimmed(name: LayerName, dimmed: boolean): void {
    this.slots.get(name)!.dimmed = dimmed;
    this.refreshLayers();
  }

  /** The hemisphere around the whole scene (R2 2), the one the sun path and the sky dome are drawn on: the compass ring lies on its rim. */
  setSceneHemisphere(hemisphere: Hemisphere | null): void {
    this.sceneHemisphere = hemisphere;
    this.sunShading?.invalidate();      // the hours in shade are clipped to its rim
    this.rebuildGroundAids();
  }

  setGroundAid(aid: GroundAid): void {
    this.groundAid = aid;
    this.showChosenGroundAid();
    this.requestRender();
  }

  setSkyDomeOpacity(opacity: number): void {
    this.skyDomeOpacity = Math.min(1, Math.max(0, opacity));
    this.refreshLayers();
  }

  /**
   * Simulate's sun tool: the sun toward *sun* (a vector toward it in model coordinates; null for none), casting shadows on the solid
   * layers and the ground when *shadows*, and the hours in shade over a range drawn over the view (null for none).
   */
  setSunStudy(sun: Point3 | null, shadows: boolean, shade: ShadeHours | null): void {
    this.sunShading.set(sun, shadows, shade);
    this.requestRender();
  }

  /** Draws the frame again: a layer changed in place (the study's values recoloured for a new target). */
  redraw(): void {
    this.requestRender();
  }

  /** Draws the envelope see-through whether or not the building massing is shown (Simulate, the study's values on the envelope). */
  setEnvelopeSeeThrough(seeThrough: boolean): void {
    this.envelopeSeeThrough = seeThrough;
    this.refreshLayers();
  }

  setViewportTheme(theme: ViewportTheme): void {
    this.theme = theme;
    this.scene.background = new THREE.Color(viewportBackground(theme));
    this.grid?.userData.applyTheme(theme);
    this.ring?.userData.applyTheme(theme);
    for (const slot of this.slots.values()) slot.object?.userData.applyTheme?.(theme);
    const dark = theme === "dark";
    this.hoverLabel.style.background = colourToken(dark ? "overlay-on-dark" : "panel");
    this.hoverLabel.style.color = colourToken(dark ? "ink-on-dark" : "ink");
    this.hoverLabel.style.border = `1px solid ${colourToken(dark ? "line-on-dark" : "line")}`;
    this.requestRender();
  }

  /** Moves the camera, in its current direction, so every visible layer fits the view. */
  frameAll(instant = false): void {
    const { centre, radius } = this.contentSphere();
    this.frameSphere(centre, radius, instant);
  }

  /** Moves the camera, in its current direction, so the box from *min* to *max* (local coordinates) fits the view, as frameAll does for the layers. */
  frameBox(min: Point3, max: Point3): void {
    const sphere = new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max)).getBoundingSphere(new THREE.Sphere());
    this.frameSphere(sphere.center, Math.max(sphere.radius, 0.5));
  }

  /** Looks straight down on everything visible, with north up the screen. */
  viewTop(): void {
    const { centre, radius } = this.contentSphere();
    const [northX, northY] = northDirection(this.northDegrees);
    const offset = new THREE.Vector3(-northX * Math.sin(TOP_VIEW_TILT_RADIANS), -northY * Math.sin(TOP_VIEW_TILT_RADIANS), Math.cos(TOP_VIEW_TILT_RADIANS));
    this.moveCamera(centre, offset.multiplyScalar(this.fittingDistance(radius)));
  }

  /** Calls *listener* now and after every camera change; returns the function that stops the calls. */
  onCameraChange(listener: (camera: CameraState) => void): () => void {
    this.cameraListeners.add(listener);
    listener(this.cameraState());
    return () => this.cameraListeners.delete(listener);
  }

  /**
   * Calls *listener* with the nearest mesh hit in the layer *name* whenever the view is clicked: the left button pressed and released
   * within 5 px and 400 ms, which an orbit drag is not. A click that hits nothing of the layer, or a hidden layer, calls nothing, and
   * so does one whose hit lies behind a visible context or terrain mesh (by more than 5 cm, so a surface lying on one takes it).
   * Returns the function that stops the calls.
   */
  onLayerClick(name: LayerName, listener: (intersection: THREE.Intersection) => void): () => void {
    const listeners = this.clickListeners.get(name) ?? new Set();
    listeners.add(listener);
    this.clickListeners.set(name, listeners);
    return () => { listeners.delete(listener); };
  }

  describe(): string {
    const shown: LayerDescription[] = [];
    for (const name of LAYER_NAMES) {
      const slot = this.slots.get(name)!;
      if (slot.object && slot.visible) shown.push({ label: messages.layerNames[name], detail: slot.object.userData.summary ?? null, dimmed: slot.dimmed });
    }
    return describeView(shown);
  }

  dispose(): void {
    if (this.frameRequest !== null) cancelAnimationFrame(this.frameRequest);
    this.resizeObserver.disconnect();
    this.controls.dispose();
    for (const slot of this.slots.values()) if (slot.object) disposeLayer(slot.object);
    if (this.grid) disposeLayer(this.grid);
    if (this.ring) disposeLayer(this.ring);
    this.sunShading.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.hoverLabel.remove();
  }

  // ------------------------------------------------------------------------------------------------------------------------

  private frameSphere(centre: THREE.Vector3, radius: number, instant = false): void {
    const direction = this.camera.position.clone().sub(this.controls.target).normalize();
    this.moveCamera(centre, direction.multiplyScalar(this.fittingDistance(radius)), instant);
  }

  private refreshLayers(): void {
    const envelope = this.slots.get("envelope")!, massing = this.slots.get("building_massing")!;
    envelope.object?.userData.setSeeThrough?.(this.envelopeSeeThrough || (envelope.visible && massing.visible && massing.object !== null));
    for (const [name, slot] of this.slots) {
      if (!slot.object) continue;
      slot.object.visible = slot.visible;
      const [dimmedOpacity, desaturation] = slot.dimmed ? dimmedAppearance(name) : [1, 0];
      applyLayerAppearance(slot.object, dimmedOpacity * (name === "sky_dome" ? this.skyDomeOpacity : 1), desaturation);
    }
    this.fitPixelSizedObjects();
    this.renderer.domElement.setAttribute("aria-label", this.describe());
    this.sunShading.invalidate();
    this.requestRender();
  }

  /** The solid meshes of the visible layers that cast and catch the sun's shadows. */
  private shadowMeshes(): THREE.Mesh[] {
    const meshes: THREE.Mesh[] = [];
    for (const name of SHADOW_LAYERS) {
      const slot = this.slots.get(name)!;
      if (slot.object && slot.visible) slot.object.traverse((object) => { if (isSolidMesh(object)) meshes.push(object); });
    }
    return meshes;
  }

  /**
   * The ground aids, both built and only the chosen one shown. The grid is sized and placed for the maximum volume (or whatever
   * is in the view without one); the compass ring lies on the rim of the scene hemisphere (R2 2). Without a scene hemisphere
   * (nothing loaded yet) the ring is drawn around the local origin, EMPTY_SCENE_RADIUS_METRES wide, as the grid is.
   */
  private rebuildGroundAids(): void {
    const modelLayers = this.slots.get("max_volume")!.object ? ["max_volume" as const] : LAYER_NAMES.filter((name) => name !== "sky_dome" && name !== "sun_path"
      && !SURROUNDING_LAYERS.includes(name));
    const modelBox = this.boxOf(modelLayers, false);     // a hidden maximum volume still sets the grid
    const size = modelBox.isEmpty() ? new THREE.Vector3() : modelBox.getSize(new THREE.Vector3());
    const centre = modelBox.isEmpty() ? new THREE.Vector3() : modelBox.getCenter(new THREE.Vector3());
    const longestSide = Math.max(size.x, size.y, size.z);
    for (const aid of [this.grid, this.ring]) {
      if (!aid) continue;
      this.scene.remove(aid);
      disposeLayer(aid);
    }
    this.grid = groundGrid(groundGridSpacing(longestSide || EMPTY_SCENE_RADIUS_METRES), [centre.x, centre.y]);
    this.grid.userData.applyTheme(this.theme);
    this.ring = compassRing(this.sceneHemisphere ?? EMPTY_SCENE_HEMISPHERE, this.northDegrees, this.theme);
    this.ring.traverse((child) => child.layers.set(OVER_THE_COUNT));
    this.scene.add(this.grid, this.ring);
    this.showChosenGroundAid();
    this.fitPixelSizedObjects();
    this.requestRender();
  }

  private showChosenGroundAid(): void {
    if (this.grid) this.grid.visible = this.groundAid === "grid";
    if (this.ring) this.ring.visible = this.groundAid === "compass_ring";
  }

  private boxOf(names: readonly LayerName[], visibleOnly = true): THREE.Box3 {
    const box = new THREE.Box3();
    for (const name of names) {
      const slot = this.slots.get(name)!;
      if (slot.object && (slot.visible || !visibleOnly)) box.expandByObject(slot.object);
    }
    return box;
  }

  /** What the camera frames: the visible layers, the surroundings only when nothing else is shown (they can reach far beyond the site). */
  private contentSphere(): { centre: THREE.Vector3; radius: number } {
    const siteBox = this.boxOf(LAYER_NAMES.filter((name) => !SURROUNDING_LAYERS.includes(name)));
    const box = siteBox.isEmpty() ? this.boxOf(SURROUNDING_LAYERS) : siteBox;
    if (box.isEmpty()) return { centre: new THREE.Vector3(), radius: EMPTY_SCENE_RADIUS_METRES };
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    return { centre: sphere.center, radius: Math.max(sphere.radius, 0.5) };
  }

  /** The camera distance at which a sphere of *radius* fills the narrower side of the view. */
  private fittingDistance(radius: number): number {
    const verticalHalfAngle = (this.camera.fov * Math.PI) / 360;
    const horizontalHalfAngle = Math.atan(Math.tan(verticalHalfAngle) * this.camera.aspect);
    return (FRAME_MARGIN * radius) / Math.sin(Math.min(verticalHalfAngle, horizontalHalfAngle));
  }

  private moveCamera(target: THREE.Vector3, offset: THREE.Vector3, instant = false): void {
    if (instant || prefersReducedMotion()) {
      this.cameraMove = null;
      this.placeCamera(target, offset);
      return;
    }
    this.cameraMove = {
      startTime: performance.now(),
      fromTarget: this.controls.target.clone(),
      toTarget: target.clone(),
      from: sphericalAboutZ(this.camera.position.clone().sub(this.controls.target)),
      to: sphericalAboutZ(offset),
    };
    this.requestRender();
  }

  private placeCamera(target: THREE.Vector3, offset: THREE.Vector3): void {
    this.controls.target.copy(target);
    this.camera.position.copy(target).add(offset);
    this.controls.update();
    this.cameraChanged();
  }

  private stepCameraMove(now: number): void {
    const move = this.cameraMove!;
    const t = Math.min(1, (now - move.startTime) / CAMERA_MOVE_MILLISECONDS);
    const eased = easeInOut(t);
    let turn = move.to.theta - move.from.theta;
    turn = Math.atan2(Math.sin(turn), Math.cos(turn));        // the shorter way round
    const spherical = new THREE.Spherical(
      move.from.radius + (move.to.radius - move.from.radius) * eased,
      move.from.phi + (move.to.phi - move.from.phi) * eased,
      move.from.theta + turn * eased,
    );
    if (t >= 1) this.cameraMove = null;
    this.placeCamera(move.fromTarget.clone().lerp(move.toTarget, eased), offsetOf(spherical));
  }

  private cameraState(): CameraState {
    const forward = this.camera.getWorldDirection(new THREE.Vector3());
    const screenUp = new THREE.Vector3(0, 1, 0).applyQuaternion(this.camera.quaternion);
    const heightPixels = Math.max(1, this.container.clientHeight);
    return {
      ...cameraOrientation(forward.toArray(), screenUp.toArray()),
      metresPerPixel: metresPerPixelAt(this.camera.position.distanceTo(this.controls.target), this.camera.fov, heightPixels),
    };
  }

  private cameraChanged(): void {
    const distance = this.camera.position.distanceTo(this.controls.target);
    this.camera.near = Math.max(0.01, distance / 1000);
    this.camera.far = distance * 20 + 4000;         // the grid reaches 1 km past the model
    this.camera.updateProjectionMatrix();
    for (const slot of this.slots.values()) slot.object?.userData.followCamera?.(this.camera.position);
    const state = this.cameraState();
    for (const listener of this.cameraListeners) listener(state);
    this.sunShading.invalidate();
    this.requestRender();
  }

  private resize(): void {
    const width = Math.max(1, this.container.clientWidth), height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.fitPixelSizedObjects();
    this.cameraChanged();
  }

  /** The 3 px lines and the labels are sized in pixels and need the size of the view. */
  private fitPixelSizedObjects(): void {
    const width = Math.max(1, this.container.clientWidth), height = Math.max(1, this.container.clientHeight);
    this.scene.traverse((object) => {
      const material = (object as THREE.Mesh).material;
      if (material instanceof LineMaterial) material.resolution.set(width, height);
    });
    fitTextSpritesToView(this.scene, height, this.camera.fov);
  }

  private queueHover(event: PointerEvent): void {
    const bounds = this.renderer.domElement.getBoundingClientRect();
    this.pendingHover = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    this.requestRender();
  }

  /** The hover label of the layer under the pointer (the storey of the building massing). */
  private updateHover(): void {
    const pointer = this.pendingHover;
    this.pendingHover = null;
    const massing = this.slots.get("building_massing")!;
    let label: string | null = null;
    if (pointer && massing.object && massing.visible && massing.object.userData.hoverLabel) {
      const raycaster = new THREE.Raycaster();
      const width = this.container.clientWidth, height = this.container.clientHeight;
      raycaster.setFromCamera(new THREE.Vector2((pointer.x / width) * 2 - 1, -(pointer.y / height) * 2 + 1), this.camera);
      const hit = raycaster.intersectObject(massing.object, true).find((intersection) => intersection.object instanceof THREE.Mesh);
      label = hit ? massing.object.userData.hoverLabel(hit) : null;
    }
    if (!pointer) return;
    this.hoverLabel.style.display = label ? "block" : "none";
    if (label) {
      this.hoverLabel.textContent = label;
      this.hoverLabel.style.left = `${pointer.x + 12}px`;
      this.hoverLabel.style.top = `${pointer.y + 12}px`;
    }
  }

  private released(event: PointerEvent): void {
    const press = this.press;
    this.press = null;
    if (!press || event.button !== 0) return;
    const moved = Math.hypot(event.clientX - press.x, event.clientY - press.y);
    if (moved > CLICK_MAX_PIXELS || performance.now() - press.time > CLICK_MAX_MILLISECONDS) return;
    const bounds = this.renderer.domElement.getBoundingClientRect();
    if (bounds.width === 0 || bounds.height === 0) return;
    this.camera.updateMatrixWorld();          // the camera may have moved since the last frame
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(new THREE.Vector2(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -((event.clientY - bounds.top) / bounds.height) * 2 + 1), this.camera);
    const nearestMeshHit = (name: LayerName): THREE.Intersection | undefined => {
      const slot = this.slots.get(name)!;
      if (!slot.object || !slot.visible) return undefined;
      slot.object.updateMatrixWorld(true);
      return raycaster.intersectObject(slot.object, true).find((intersection) => intersection.object instanceof THREE.Mesh);
    };
    for (const [name, listeners] of this.clickListeners) {
      if (listeners.size === 0) continue;
      const hit = nearestMeshHit(name);
      if (!hit) continue;
      const occluders = CLICK_OCCLUDING_LAYERS.filter((occluding) => occluding !== name).map(nearestMeshHit);
      const nearestOccluder = Math.min(...occluders.map((occluder) => occluder?.distance ?? Infinity));
      if (hit.distance > nearestOccluder + CLICK_OCCLUSION_TOLERANCE_METRES) continue;
      for (const listener of [...listeners]) listener(hit);
    }
  }

  private requestRender(): void {
    if (this.frameRequest !== null) return;
    this.frameRequest = requestAnimationFrame((now) => {
      this.frameRequest = null;
      if (this.cameraMove) this.stepCameraMove(now);
      if (this.pendingHover) this.updateHover();
      // The scene, the hours in shade over it, then the sun path and the sky dome over both (tested against the scene's depth).
      this.sunShading.prepare();
      this.camera.layers.set(0);
      this.renderer.render(this.scene, this.camera);
      this.sunShading.drawOverlay();
      // A colour background makes three.js clear the frame whatever autoClear says: the second pass goes without it.
      this.camera.layers.set(OVER_THE_COUNT);
      const autoClear = this.renderer.autoClear, background = this.scene.background;
      this.renderer.autoClear = false;
      this.scene.background = null;
      this.renderer.render(this.scene, this.camera);
      this.scene.background = background;
      this.renderer.autoClear = autoClear;
      this.camera.layers.set(0);
      if (this.cameraMove) this.requestRender();
    });
  }
}

// The 3D view (UX 8): a three.js scene with Z up in local coordinates, the ground grid and north arrow, and one slot per layer.
// Orbit with the left mouse button, pan with the right, zoom with the wheel. Camera moves of frameAll and viewTop take 400 ms,
// and are instant under prefers-reduced-motion. No React here: the overlays (viewer_overlays/) read the camera through
// onCameraChange and call the methods below.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { messages } from "../messages";
import { colourToken, viewportBackground, type ViewportTheme } from "./colour_scales";
import { northArrow, northDirection } from "./compass";
import { groundGrid, groundGridSpacing } from "./ground_grid";
import { LAYER_NAMES, applyLayerAppearance, disposeLayer, type LayerName } from "./layers";
import { fitTextSpritesToView } from "./text_sprite";

export type { LayerName } from "./layers";
export type { ViewportTheme } from "./colour_scales";

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
const DIMMED_OPACITY = 0.35;
const DIMMED_DESATURATION = 1;
const DEFAULT_SKY_DOME_OPACITY = 0.6;
const FIELD_OF_VIEW_DEGREES = 35;
const FRAME_MARGIN = 1.1;
const TOP_VIEW_TILT_RADIANS = 1e-3;         // a hair off straight down, so "up" on the screen is defined and points north
const FIRST_VIEW_DIRECTION = new THREE.Vector3(-0.5, -0.9, 0.75).normalize();     // from the south-south-west, above
const EMPTY_SCENE_RADIUS_METRES = 60;
const NORTH_ARROW_SHARE = 0.12;             // of the model's longest side
const NORTH_ARROW_SMALLEST_METRES = 2;

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
  private grid: THREE.Group | null = null;
  private arrow: THREE.Group | null = null;
  private hasFramedContent = false;
  private cameraMove: CameraMove | null = null;
  private frameRequest: number | null = null;
  private pendingHover: { x: number; y: number } | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
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

    const skyLight = new THREE.HemisphereLight("#ffffff", "#8a9499", 2.2);
    skyLight.position.set(0, 0, 1);
    const sunLight = new THREE.DirectionalLight("#ffffff", 1.6);
    sunLight.position.set(-0.45, -0.7, 1);
    this.scene.add(skyLight, sunLight);

    this.hoverLabel = document.createElement("div");
    this.hoverLabel.style.cssText = "position:absolute;pointer-events:none;display:none;padding:2px 6px;border-radius:var(--radius-small);" +
      "font:var(--text-secondary)/var(--line-height) var(--font-family);";
    container.appendChild(this.hoverLabel);
    canvas.addEventListener("pointermove", (event) => this.queueHover(event));
    canvas.addEventListener("pointerleave", () => { this.pendingHover = null; this.hoverLabel.style.display = "none"; });

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
      object.userData.applyTheme?.(this.theme);
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

  setSkyDomeOpacity(opacity: number): void {
    this.skyDomeOpacity = Math.min(1, Math.max(0, opacity));
    this.refreshLayers();
  }

  setViewportTheme(theme: ViewportTheme): void {
    this.theme = theme;
    this.scene.background = new THREE.Color(viewportBackground(theme));
    this.grid?.userData.applyTheme(theme);
    this.arrow?.userData.applyTheme(theme);
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
    const direction = this.camera.position.clone().sub(this.controls.target).normalize();
    this.moveCamera(centre, direction.multiplyScalar(this.fittingDistance(radius)), instant);
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
    if (this.arrow) disposeLayer(this.arrow);
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.hoverLabel.remove();
  }

  // ------------------------------------------------------------------------------------------------------------------------

  private refreshLayers(): void {
    const envelope = this.slots.get("envelope")!, massing = this.slots.get("building_massing")!;
    envelope.object?.userData.setSeeThrough?.(envelope.visible && massing.visible && massing.object !== null);
    for (const [name, slot] of this.slots) {
      if (!slot.object) continue;
      slot.object.visible = slot.visible;
      const opacityFactor = (slot.dimmed ? DIMMED_OPACITY : 1) * (name === "sky_dome" ? this.skyDomeOpacity : 1);
      applyLayerAppearance(slot.object, opacityFactor, slot.dimmed ? DIMMED_DESATURATION : 0);
    }
    this.fitPixelSizedObjects();
    this.renderer.domElement.setAttribute("aria-label", this.describe());
    this.requestRender();
  }

  /** The ground grid and the north arrow, sized and placed for the maximum volume (or whatever is in the view without one). */
  private rebuildGroundAids(): void {
    const modelLayers = this.slots.get("max_volume")!.object ? ["max_volume" as const] : LAYER_NAMES.filter((name) => name !== "sky_dome" && name !== "sun_path");
    const modelBox = this.boxOf(modelLayers, false);     // a hidden maximum volume still sets the grid
    const size = modelBox.isEmpty() ? new THREE.Vector3() : modelBox.getSize(new THREE.Vector3());
    const centre = modelBox.isEmpty() ? new THREE.Vector3() : modelBox.getCenter(new THREE.Vector3());
    const longestSide = Math.max(size.x, size.y, size.z);
    for (const aid of [this.grid, this.arrow]) {
      if (!aid) continue;
      this.scene.remove(aid);
      disposeLayer(aid);
    }
    const spacing = groundGridSpacing(longestSide || EMPTY_SCENE_RADIUS_METRES);
    this.grid = groundGrid(spacing, [centre.x, centre.y]);
    const arrowLength = Math.max(NORTH_ARROW_SMALLEST_METRES, NORTH_ARROW_SHARE * (longestSide || EMPTY_SCENE_RADIUS_METRES));
    this.arrow = northArrow(this.northDegrees, arrowLength);
    const corner = modelBox.isEmpty() ? new THREE.Vector3() : modelBox.min;
    this.arrow.position.set(corner.x - 1.5 * arrowLength, corner.y - 1.5 * arrowLength, 0);
    this.grid.userData.applyTheme(this.theme);
    this.arrow.userData.applyTheme(this.theme);
    this.scene.add(this.grid, this.arrow);
    this.fitPixelSizedObjects();
    this.requestRender();
  }

  private boxOf(names: readonly LayerName[], visibleOnly = true): THREE.Box3 {
    const box = new THREE.Box3();
    for (const name of names) {
      const slot = this.slots.get(name)!;
      if (slot.object && (slot.visible || !visibleOnly)) box.expandByObject(slot.object);
    }
    return box;
  }

  private contentSphere(): { centre: THREE.Vector3; radius: number } {
    const box = this.boxOf(LAYER_NAMES);
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
    const state = this.cameraState();
    for (const listener of this.cameraListeners) listener(state);
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

  private requestRender(): void {
    if (this.frameRequest !== null) return;
    this.frameRequest = requestAnimationFrame((now) => {
      this.frameRequest = null;
      if (this.cameraMove) this.stepCameraMove(now);
      if (this.pendingHover) this.updateHover();
      this.renderer.render(this.scene, this.camera);
      if (this.cameraMove) this.requestRender();
    });
  }
}

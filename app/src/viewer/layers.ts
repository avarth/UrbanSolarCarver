// The layers of the 3D view and how each is drawn (UX 8.2). A builder returns a three.js object whose userData tells the scene
// what it needs: a summary for the accessible name, applyTheme(theme) for colours that follow the viewport theme, and for some
// layers setSeeThrough(on) or hoverLabel(intersection). Every material is made dimmable (out of date: faded and desaturated).
import * as THREE from "three";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import type { SkyDome } from "../api_client/client";
import { messages } from "../messages";
import { changeOf, changeTolerance, highestOf, OPEN_COLUMN, type StudyView } from "../simulate/study_values";
import { changeRamp, changeRampStops, cividis, colourToken, storeyColour, sunRamp, type ViewportTheme } from "./colour_scales";
import type { CarvedVoxels } from "./carved_by_criterion_decoder";
import type { Point3 } from "./local_origin";
import type { ScorePoints } from "./score_points_decoder";
import { pointOnHemisphere, skyPatchOutline, skyPatchShares, type Hemisphere } from "./sky_dome";
import type { SunPathObjects } from "./sun_path";
import { recolourTextSprite, textSprite, type TextSprite } from "./text_sprite";

export type LayerName = "max_volume" | "test_surfaces" | "context" | "terrain" | "kept_voxels" | "carved_voxels" | "carved_by_criterion" | "sun_path" |
  "sky_dome" | "envelope" | "building_massing" | "study_values";

/** The layers in the order of UX 8.2, which the layers menu and the accessible name follow; then the study of Simulate. */
export const LAYER_NAMES: readonly LayerName[] = ["max_volume", "test_surfaces", "context", "terrain", "kept_voxels", "carved_voxels", "carved_by_criterion",
  "sun_path", "sky_dome", "envelope", "building_massing", "study_values"];

/** The layers that can reach far beyond the site (a city model, a terrain kilometres wide): the camera frames the rest. */
export const SURROUNDING_LAYERS: readonly LayerName[] = ["context", "terrain"];

export type MaxVolumeAppearance = "solid" | "ghost";

const GHOST_OPACITY = 0.15;
const SOFT_EDGE_OPACITY = 0.15;
const GHOST_EDGE_OPACITY = 0.3;
const SEE_THROUGH_ENVELOPE_OPACITY = 0.3;
const SEE_THROUGH_EDGE_OPACITY = 0.2;
const CARVED_VOXEL_OPACITY = 0.1;
const CARVED_OUTLINE_OPACITY = 0.6;
const MASSING_EDGE_OPACITY = 0.25;
const FEATURE_EDGE_DEGREES = 20;
const CUBES_UP_TO = 300_000;               // more voxels are drawn as square points, which stay interactive up to 1 000 000
const PERIOD_PATH_PIXELS = 3;
const SUN_DISC_SHARE = 0.04;               // of the hemisphere radius
const HOUR_LABEL_PIXELS = 12;
const DASH_SHARE = 0.015;
const SKY_PATCH_GAP_DEGREES = 0.4;
const SKY_PATCH_ROWS = 2;
const SKY_PATCH_DEGREES_PER_COLUMN = 4;
const VERTICAL_TOLERANCE_METRES = 1e-4;

// Dimming and opacity --------------------------------------------------------------------------------------------------------

const LUMINANCE = "vec3(0.2126, 0.7152, 0.0722)";

/** Gives a material its base opacity and a desaturation uniform the scene drives (layer dimmed or not). */
export function layerMaterial<Material extends THREE.Material>(material: Material, baseOpacity = 1): Material {
  const desaturation = { value: 0 };
  material.userData.baseOpacity = baseOpacity;
  material.userData.desaturation = desaturation;
  material.userData.alwaysTransparent = material.transparent;    // made transparent for its texture or its blending, not its opacity
  material.opacity = baseOpacity;
  material.transparent = material.transparent || baseOpacity < 1;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.layerDesaturation = desaturation;
    let fragment = `uniform float layerDesaturation;\n${shader.fragmentShader}`;
    fragment = fragment.includes("#include <opaque_fragment>")
      ? fragment.replace("#include <opaque_fragment>",
        `outgoingLight = mix(outgoingLight, vec3(dot(outgoingLight, ${LUMINANCE})), layerDesaturation);\n#include <opaque_fragment>`)
      : fragment.replace("#include <color_fragment>",       // the fat line material has no opaque_fragment
        `#include <color_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, vec3(dot(diffuseColor.rgb, ${LUMINANCE})), layerDesaturation);`);
    shader.fragmentShader = fragment;
  };
  return material;
}

function materialsOf(object: THREE.Object3D): THREE.Material[] {
  const materials: THREE.Material[] = [];
  object.traverse((child) => {
    const material = (child as THREE.Mesh).material;
    if (material) materials.push(...(Array.isArray(material) ? material : [material]));
  });
  return materials;
}

/** Sets each material's opacity to its base opacity times *opacityFactor*, and its desaturation (0 to 1). */
export function applyLayerAppearance(object: THREE.Object3D, opacityFactor: number, desaturation: number): void {
  for (const material of materialsOf(object)) {
    if (material.userData.baseOpacity === undefined) continue;
    material.opacity = material.userData.baseOpacity * opacityFactor;
    const transparent = material.opacity < 1 || material.userData.alwaysTransparent === true;
    if (material.transparent !== transparent) {
      material.transparent = transparent;
      material.needsUpdate = true;
    }
    material.userData.desaturation.value = desaturation;
  }
}

export function disposeLayer(object: THREE.Object3D): void {
  object.traverse((child) => {
    (child as THREE.Mesh).geometry?.dispose();
    if (child instanceof THREE.InstancedMesh) child.dispose();
  });
  for (const material of materialsOf(object)) {
    (material as THREE.MeshBasicMaterial).map?.dispose();
    material.dispose();
  }
}

// Solids ---------------------------------------------------------------------------------------------------------------------

/** Solids are pushed back a little in depth so their edge lines draw over them; *pullForward* draws them in front instead. */
function solidMaterial(colour: string, baseOpacity: number, side: THREE.Side = THREE.FrontSide, pullForward = false): THREE.MeshLambertMaterial {
  const [polygonOffsetFactor, polygonOffsetUnits] = pullForward ? [-2, -8] : [1, 1];
  const material = layerMaterial(new THREE.MeshLambertMaterial({ color: colour, flatShading: true, side, polygonOffset: true, polygonOffsetFactor, polygonOffsetUnits }), baseOpacity);
  material.depthWrite = baseOpacity >= 1;
  return material;
}

function edgeLines(geometry: THREE.BufferGeometry, colour: string, baseOpacity: number): THREE.LineSegments {
  const material = layerMaterial(new THREE.LineBasicMaterial({ color: colour, transparent: true, depthWrite: false }), baseOpacity);
  return new THREE.LineSegments(new THREE.EdgesGeometry(geometry, FEATURE_EDGE_DEGREES), material);
}

function inkColour(theme: ViewportTheme): string {
  return colourToken(theme === "dark" ? "ink-on-dark" : "ink");
}

function solidWithEdges(geometry: THREE.BufferGeometry, bodyOpacity: number, edgeOpacity: number): { group: THREE.Group; body: THREE.Mesh; edges: THREE.LineSegments } {
  const body = new THREE.Mesh(geometry, solidMaterial(colourToken("panel"), bodyOpacity, THREE.DoubleSide));
  const edges = edgeLines(geometry, colourToken("ink"), edgeOpacity);
  const group = new THREE.Group();
  group.add(body, edges);
  group.userData.applyTheme = (theme: ViewportTheme) => (edges.material as THREE.LineBasicMaterial).color.set(inkColour(theme));
  return { group, body, edges };
}

/** The maximum volume: a light solid, or in later steps a see-through ghost. */
export function maxVolumeLayer(geometry: THREE.BufferGeometry, appearance: MaxVolumeAppearance): THREE.Object3D {
  const ghost = appearance === "ghost";
  return solidWithEdges(geometry, ghost ? GHOST_OPACITY : 1, ghost ? GHOST_EDGE_OPACITY : SOFT_EDGE_OPACITY).group;
}

/** The test surfaces of one criterion (*name* is its id): their *colour* ("#RRGGBB"), or null for the accent colour. */
export interface TestSurfacesPart {
  name: string;
  colour: string | null;
  geometry: THREE.BufferGeometry;
}

/**
 * The test surfaces, one mesh per part at full strength in the part's colour. A part without a colour takes the accent colour, a
 * lighter blue on the dark viewport; a criterion's colour does not change with the theme. They usually lie on a context facade or
 * on the maximum volume, so they are pulled forward in depth to draw over that face instead of flickering through it.
 */
export function testSurfacesLayer(parts: readonly TestSurfacesPart[]): THREE.Object3D {
  const layer = new THREE.Group();
  const accentMaterials: THREE.MeshLambertMaterial[] = [];
  for (const { name, colour, geometry } of parts) {
    const material = solidMaterial(colour ?? colourToken("accent"), 1, THREE.DoubleSide, true);
    const surfaces = new THREE.Mesh(geometry, material);
    surfaces.name = name;
    if (colour === null) accentMaterials.push(material);
    layer.add(surfaces);
  }
  layer.userData.applyTheme = (theme: ViewportTheme) => accentMaterials.forEach((material) => material.color.set(colourToken(theme === "dark" ? "test-surface-on-dark" : "accent")));
  return layer;
}

/** The existing surroundings: neutral grey massing with soft edges. */
export function contextLayer(geometry: THREE.BufferGeometry): THREE.Object3D {
  const body = new THREE.Mesh(geometry, solidMaterial(colourToken("context"), 1, THREE.DoubleSide));
  const edges = edgeLines(geometry, colourToken("ink"), SOFT_EDGE_OPACITY);
  const group = new THREE.Group();
  group.add(body, edges);
  group.userData.applyTheme = (theme: ViewportTheme) => (edges.material as THREE.LineBasicMaterial).color.set(inkColour(theme));
  return group;
}

/** The terrain: a ground surface, without edges (a terrain mesh has many). */
export function terrainLayer(geometry: THREE.BufferGeometry): THREE.Object3D {
  return new THREE.Mesh(geometry, solidMaterial(colourToken("terrain"), 1, THREE.DoubleSide));
}

/** The carved envelope: a light solid with soft edges, or translucent white while the building massing is shown inside it. */
export function envelopeLayer(geometry: THREE.BufferGeometry): THREE.Object3D {
  const { group, body, edges } = solidWithEdges(geometry, 1, SOFT_EDGE_OPACITY);
  group.userData.setSeeThrough = (seeThrough: boolean) => {
    const bodyMaterial = body.material as THREE.Material;
    bodyMaterial.userData.baseOpacity = seeThrough ? SEE_THROUGH_ENVELOPE_OPACITY : 1;
    bodyMaterial.depthWrite = !seeThrough;
    (edges.material as THREE.Material).userData.baseOpacity = seeThrough ? SEE_THROUGH_EDGE_OPACITY : SOFT_EDGE_OPACITY;
  };
  return group;
}

/** The storey index of a building massing part named "floor_<n>_plate_<m>" by the engine; null for another name. */
export function storeyOfPart(partName: string): number | null {
  const match = /^floor_(\d+)/.exec(partName);
  return match ? Number(match[1]) : null;
}

/** The building massing, one colour per storey on the light-to-slate ramp, the storey number on hover. */
export function buildingMassingLayer(geometry: THREE.BufferGeometry): THREE.Object3D {
  const partNames: string[] = geometry.userData.partNames ?? [];
  const partStoreys = partNames.map((name) => storeyOfPart(name) ?? 0);
  const storeyCount = partStoreys.length ? Math.max(...partStoreys) + 1 : 0;
  geometry.groups.forEach((group, partIndex) => { group.materialIndex = partStoreys[partIndex] ?? 0; });
  if (!geometry.groups.length) geometry.addGroup(0, Infinity, 0);
  const materials = Array.from({ length: storeyCount }, (_, storey) => solidMaterial(storeyColour(storey, storeyCount), 1));
  const body = new THREE.Mesh(geometry, materials);
  const edges = edgeLines(geometry, colourToken("ink"), MASSING_EDGE_OPACITY);
  const massing = new THREE.Group();
  massing.add(body, edges);
  massing.userData.applyTheme = (theme: ViewportTheme) => (edges.material as THREE.LineBasicMaterial).color.set(inkColour(theme));
  massing.userData.summary = messages.storeyCount(storeyCount);
  massing.userData.storeyCount = storeyCount;
  massing.userData.hoverLabel = (intersection: THREE.Intersection) =>
    intersection.object === body && intersection.face ? messages.storeyLabel(intersection.face.materialIndex + 1) : null;
  return massing;
}

// Voxels ---------------------------------------------------------------------------------------------------------------------

export interface VoxelSet {
  centres: Float32Array;      // x, y, z per voxel, local coordinates
  scores: Float32Array;
}

/** The score points split by the mask into kept and carved voxels; without a mask (no carving yet) all are drawn as kept. */
export function splitScorePoints(points: ScorePoints, centres: Float32Array): { kept: VoxelSet; carved: VoxelSet } {
  const keptFlags = points.kept;
  const keptCount = keptFlags ? keptFlags.reduce((count, flag) => count + (flag ? 1 : 0), 0) : points.scores.length;
  const kept = { centres: new Float32Array(keptCount * 3), scores: new Float32Array(keptCount) };
  const carved = { centres: new Float32Array((points.scores.length - keptCount) * 3), scores: new Float32Array(points.scores.length - keptCount) };
  let keptIndex = 0, carvedIndex = 0;
  for (let point = 0; point < points.scores.length; point++) {
    const target = !keptFlags || keptFlags[point] ? kept : carved;
    const index = target === kept ? keptIndex++ : carvedIndex++;
    target.scores[index] = points.scores[point];
    target.centres.set(centres.subarray(point * 3, point * 3 + 3), index * 3);
  }
  return { kept, carved };
}

/** For a point of the ground, the top of the highest kept voxel in the grid columns within half a voxel of it (grid bottom without one). */
export function keptColumnTops(points: ScorePoints, origin: Point3): (x: number, y: number) => number {
  const { shape: [columnCount, rowCount, layerCount], voxel_size: size } = points.header;
  const corner = [0, 1, 2].map((axis) => points.header.origin[axis] - origin[axis]);
  const topLayers = new Map<number, number>();          // column i * rowCount + j -> number of layers up to its highest kept voxel
  points.indices.forEach((flatIndex, point) => {
    if (points.kept && !points.kept[point]) return;
    const column = Math.floor(flatIndex / layerCount);
    topLayers.set(column, Math.max(topLayers.get(column) ?? 0, (flatIndex % layerCount) + 1));
  });
  return (x, y) => {
    let layers = 0;
    const iRange = [Math.floor((x - corner[0]) / size - 0.5), Math.floor((x - corner[0]) / size + 0.5)];
    const jRange = [Math.floor((y - corner[1]) / size - 0.5), Math.floor((y - corner[1]) / size + 0.5)];
    for (let i = Math.max(0, iRange[0]); i <= Math.min(columnCount - 1, iRange[1]); i++)
      for (let j = Math.max(0, jRange[0]); j <= Math.min(rowCount - 1, jRange[1]); j++) layers = Math.max(layers, topLayers.get(i * rowCount + j) ?? 0);
    return corner[2] + layers * size;
  };
}

/** The maximum volume's feature edges, and the outward horizontal normal of each vertical one (0, 0 for the others). */
export interface VolumeOutline {
  segments: Float32Array;           // pairs of points
  outwardNormals: Float32Array;     // nx, ny per segment
}

function isVertical(ax: number, ay: number, bx: number, by: number): boolean {
  return Math.abs(ax - bx) < VERTICAL_TOLERANCE_METRES && Math.abs(ay - by) < VERTICAL_TOLERANCE_METRES;
}

function pointKey(point: THREE.Vector3): string {
  return `${point.x.toFixed(4)},${point.y.toFixed(4)},${point.z.toFixed(4)}`;
}

function edgeKey(first: THREE.Vector3, second: THREE.Vector3): string {
  const [a, b] = [pointKey(first), pointKey(second)].sort();
  return `${a}|${b}`;
}

/** The feature edges of the maximum volume; a vertical edge's outward normal is the sum of the horizontal normals of the faces beside it. */
export function volumeOutline(geometry: THREE.BufferGeometry): VolumeOutline {
  const positions = geometry.getAttribute("position");
  const index = geometry.index;
  const cornerCount = index ? index.count : positions.count;
  const horizontalNormals = new Map<string, [number, number]>();
  const corners = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const faceNormal = new THREE.Vector3();
  for (let first = 0; first + 2 < cornerCount; first += 3) {
    corners.forEach((corner, offset) => corner.fromBufferAttribute(positions, index ? index.getX(first + offset) : first + offset));
    THREE.Triangle.getNormal(corners[0], corners[1], corners[2], faceNormal);
    for (let side = 0; side < 3; side++) {
      const [a, b] = [corners[side], corners[(side + 1) % 3]];
      if (!isVertical(a.x, a.y, b.x, b.y)) continue;
      const key = edgeKey(a, b);
      const sum = horizontalNormals.get(key) ?? [0, 0];
      horizontalNormals.set(key, [sum[0] + faceNormal.x, sum[1] + faceNormal.y]);
    }
  }
  const edges = new THREE.EdgesGeometry(geometry, FEATURE_EDGE_DEGREES);
  const segments = Float32Array.from(edges.getAttribute("position").array);
  edges.dispose();
  const outwardNormals = new Float32Array((segments.length / 6) * 2);
  const [a, b] = [new THREE.Vector3(), new THREE.Vector3()];
  for (let segment = 0; segment < segments.length / 6; segment++) {
    a.fromArray(segments, segment * 6);
    b.fromArray(segments, segment * 6 + 3);
    if (!isVertical(a.x, a.y, b.x, b.y)) continue;
    const [nx, ny] = horizontalNormals.get(edgeKey(a, b)) ?? [0, 0];
    const length = Math.hypot(nx, ny) || 1;
    outwardNormals.set([nx / length, ny / length], segment * 2);
  }
  return { segments, outwardNormals };
}

/**
 * The parts of the maximum volume's edges drawn over the carved voxels (UX 8.2): its top edges, at its highest z, and the
 * vertical edges that face the camera (outward normal toward it), from the kept top up. Bottom edges and the vertical edges at
 * the back are left out: above the kept voxels nothing hides them.
 */
export function carvedOutlineSegments(outline: VolumeOutline, keptTopAt: (x: number, y: number) => number, cameraXY: [number, number]): Float32Array {
  const { segments, outwardNormals } = outline;
  let topZ = -Infinity;
  for (let value = 2; value < segments.length; value += 3) topZ = Math.max(topZ, segments[value]);
  const drawn: number[] = [];
  for (let segment = 0; segment < segments.length / 6; segment++) {
    const [ax, ay, az, bx, by, bz] = segments.subarray(segment * 6, segment * 6 + 6);
    if (isVertical(ax, ay, bx, by)) {
      const facesCamera = outwardNormals[segment * 2] * (cameraXY[0] - ax) + outwardNormals[segment * 2 + 1] * (cameraXY[1] - ay) > 0;
      const low = Math.max(Math.min(az, bz), keptTopAt(ax, ay)), high = Math.max(az, bz);
      if (facesCamera && high - low > VERTICAL_TOLERANCE_METRES) drawn.push(ax, ay, low, ax, ay, high);
    } else if (Math.abs(az - topZ) < VERTICAL_TOLERANCE_METRES && Math.abs(bz - topZ) < VERTICAL_TOLERANCE_METRES) {
      drawn.push(ax, ay, az, bx, by, bz);
    }
  }
  return Float32Array.from(drawn);
}

/**
 * The size a points material needs for a point to be as wide on screen as a voxel. With size attenuation three.js draws a point
 * size * (view height / 2) / depth pixels wide, and a voxel spans voxelSize * view height / (2 * depth * tan(fov / 2)) pixels.
 */
export function pointSizeForVoxel(voxelSize: number, fieldOfViewDegrees: number): number {
  return voxelSize / Math.tan((fieldOfViewDegrees * Math.PI) / 360);
}

function voxelObject(centres: Float32Array, voxelSize: number, colours: THREE.Color[] | null, colour: string, baseOpacity: number): THREE.Object3D {
  const count = centres.length / 3;
  if (count > CUBES_UP_TO) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(centres, 3));
    if (colours) geometry.setAttribute("color", new THREE.Float32BufferAttribute(colours.flatMap((each) => [each.r, each.g, each.b]), 3));
    const material = layerMaterial(new THREE.PointsMaterial({ size: voxelSize, sizeAttenuation: true, vertexColors: colours !== null, color: colours ? "#ffffff" : colour }), baseOpacity);
    material.depthWrite = baseOpacity >= 1;
    const points = new THREE.Points(geometry, material);
    points.onBeforeRender = (_renderer, _scene, camera) => {
      if (camera instanceof THREE.PerspectiveCamera) material.size = pointSizeForVoxel(voxelSize, camera.fov);
    };
    return points;
  }
  const cubes = new THREE.InstancedMesh(new THREE.BoxGeometry(voxelSize, voxelSize, voxelSize), solidMaterial(colours ? "#ffffff" : colour, baseOpacity), count);
  const placement = new THREE.Matrix4();
  for (let voxel = 0; voxel < count; voxel++) {
    cubes.setMatrixAt(voxel, placement.makeTranslation(centres[voxel * 3], centres[voxel * 3 + 1], centres[voxel * 3 + 2]));
    if (colours) cubes.setColorAt(voxel, colours[voxel]);
  }
  cubes.computeBoundingBox();
  cubes.computeBoundingSphere();
  return cubes;
}

const CIVIDIS_COLOURS = Array.from({ length: 256 }, (_, index) => new THREE.Color(cividis((index + 0.5) / 256)));

export interface KeptVoxelsDrawing {
  voxels: VoxelSet;
  voxelSize: number;
  colourRange: [number, number];      // keptScoreRange(cutoff): 0 to the cutoff
  voxelCount: number;                 // of the whole grid, before thinning
}

/** The kept voxels coloured by raw score with cividis over the colour range. */
export function keptVoxelsLayer({ voxels, voxelSize, colourRange: [low, high], voxelCount }: KeptVoxelsDrawing): THREE.Object3D {
  const span = high > low ? high - low : 1;
  const colours = Array.from(voxels.scores, (score) =>
    CIVIDIS_COLOURS[Math.min(255, Math.max(0, Math.floor(((score - low) / span) * 256)))]);
  const layer = voxelObject(voxels.centres, voxelSize, colours, "#ffffff", 1);
  layer.userData.summary = messages.voxelCount(voxelCount);
  return layer;
}

export interface CarvedVoxelsDrawing {
  voxels: VoxelSet;
  voxelSize: number;
  voxelCount: number;
  outline: VolumeOutline;             // volumeOutline of the maximum volume
  keptTopAt: (x: number, y: number) => number;      // keptColumnTops of the score points
}

/**
 * The carved voxels in the carved colour at 10 % opacity, with the maximum volume's top edges and front vertical edges above the
 * kept voxels at 60 %. Which vertical edges are in front depends on the camera: the scene calls userData.followCamera(position).
 */
export function carvedVoxelsLayer({ voxels, voxelSize, voxelCount, outline, keptTopAt }: CarvedVoxelsDrawing): THREE.Object3D {
  const carvedColour = colourToken("carved");
  const layer = new THREE.Group();
  if (voxels.scores.length) layer.add(voxelObject(voxels.centres, voxelSize, null, carvedColour, CARVED_VOXEL_OPACITY));
  // One buffer large enough for every edge; each camera move rewrites it with the edges to draw.
  const outlinePositions = new THREE.BufferAttribute(new Float32Array(outline.segments.length), 3);
  const outlineGeometry = new THREE.BufferGeometry().setAttribute("position", outlinePositions);
  outlineGeometry.boundingSphere = new THREE.Box3().setFromArray(outline.segments).getBoundingSphere(new THREE.Sphere());
  outlineGeometry.setDrawRange(0, 0);
  layer.userData.followCamera = (cameraPosition: THREE.Vector3) => {
    const drawn = carvedOutlineSegments(outline, keptTopAt, [cameraPosition.x, cameraPosition.y]);
    (outlinePositions.array as Float32Array).set(drawn);
    outlinePositions.needsUpdate = true;
    outlineGeometry.setDrawRange(0, drawn.length / 3);
  };
  const outlineMaterial = layerMaterial(new THREE.LineBasicMaterial({ color: carvedColour, depthWrite: false }), CARVED_OUTLINE_OPACITY);
  layer.add(new THREE.LineSegments(outlineGeometry, outlineMaterial));
  layer.userData.summary = messages.voxelCount(voxelCount);
  return layer;
}

export interface CarvedByCriterionDrawing {
  voxels: CarvedVoxels;
  colours: readonly string[];         // the colour of each criterion, in the order of the layer's criterion ids
  voxelSize: number;
}

/** The voxels some criterion removed, each in the colour of the criterion that removed it; one without a colour here is drawn in the carved colour. */
export function carvedByCriterionLayer({ voxels, colours, voxelSize }: CarvedByCriterionDrawing): THREE.Object3D {
  const count = voxels.criterionIndex.length;
  if (count === 0) return new THREE.Group();
  const carvedColour = new THREE.Color(colourToken("carved"));
  const colourOf = colours.map((colour) => new THREE.Color(colour));
  const layer = voxelObject(voxels.centres, voxelSize, Array.from(voxels.criterionIndex, (criterion) => colourOf[criterion] ?? carvedColour), "#ffffff", 1);
  layer.userData.summary = messages.voxelCount(voxels.carvedCount);
  return layer;
}

// The study of Simulate ------------------------------------------------------------------------------------------------------

const CHANGE_RAMP_STEPS = 256;

/** Writes each point's colour into its four corners of *colours*, as studyValuesLayer describes. */
function paintStudyValues(colours: Float32Array, view: StudyView, theme: ViewportTheme): void {
  const { values: studyValues, geometry: shownGeometry, change, target } = view;
  const shown = studyValues.values[shownGeometry];
  const count = shown.length;
  const paint = (point: number, colour: THREE.Color) => {
    for (let at = point * 12; at < point * 12 + 12; at += 3) {
      colours[at] = colour.r;
      colours[at + 1] = colour.g;
      colours[at + 2] = colour.b;
    }
  };
  if (change) {
    const changes = changeOf(shown, studyValues.values.max_volume);
    const tolerance = changeTolerance(studyValues.values[OPEN_COLUMN], studyValues.values.max_volume);
    const highest = highestOf(changes);
    const ramp = changeRampStops(CHANGE_RAMP_STEPS).map((colour) => new THREE.Color(colour));
    const loss = new THREE.Color(changeRamp(-1));
    for (let point = 0; point < count; point++) {
      const value = changes[point];
      const share = Math.abs(value) <= tolerance || highest <= 0 ? 0 : value / highest;
      paint(point, value < -tolerance ? loss : ramp[Math.round(Math.min(1, share) * (CHANGE_RAMP_STEPS - 1))]);
    }
  } else {
    const highest = highestOf(shown);
    const span = highest > 0 ? highest : 1;
    const belowTarget = new THREE.Color(colourToken(theme === "dark" ? "below-target-on-dark" : "below-target"));
    for (let point = 0; point < count; point++) {
      const value = shown[point];
      paint(point, target !== null && value < target ? belowTarget : CIVIDIS_COLOURS[Math.min(255, Math.max(0, Math.floor((value / span) * 256)))]);
    }
  }
}

/**
 * The selected study's test point patches on the geometry shown (*corners*: study_values_decoder.patchCorners), unlit so the colours
 * read as the legend's. By value: cividis from 0 to the highest value of the geometry shown, the points below the target in one
 * muted mauve (apart from the greys of the surroundings and volumes; a darker one on the dark viewport). By change from the maximum
 * volume: the change ramp from no change to the largest gain, a loss in the carved colour, a change within the tolerance none. The
 * patches lie on test surfaces, so they are pulled forward in depth as those are. A new target or Change of the same values and
 * geometry recolours the patches in place (userData.recolour), as the viewport theme does (userData.applyTheme).
 */
export function studyValuesLayer(view: StudyView, corners: Float32Array): THREE.Object3D {
  const count = view.values.values[view.geometry].length;
  const colours = new Float32Array(count * 4 * 3);
  const drawn = { view, theme: "light" as ViewportTheme };
  paintStudyValues(colours, view, drawn.theme);
  // Two triangles per patch, around its corners in order: 0 1 2 and 0 2 3.
  const index = new Uint32Array(count * 6);
  for (let point = 0, at = 0; point < count; point++, at += 6) {
    const first = point * 4;
    index[at] = first;
    index[at + 1] = first + 1;
    index[at + 2] = first + 2;
    index[at + 3] = first;
    index[at + 4] = first + 2;
    index[at + 5] = first + 3;
  }
  const geometry = new THREE.BufferGeometry();
  const positions = new THREE.BufferAttribute(corners, 3);
  const colourAttribute = new THREE.BufferAttribute(colours, 3);
  geometry.setAttribute("position", positions);
  geometry.setAttribute("color", colourAttribute);
  geometry.setIndex(new THREE.BufferAttribute(index, 1));
  // The sphere around the corners' box: one pass over the points where computeBoundingSphere takes two.
  geometry.boundingSphere = new THREE.Box3().setFromBufferAttribute(positions).getBoundingSphere(new THREE.Sphere());
  const material = layerMaterial(new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -8,
  }));
  const patches = new THREE.Mesh(geometry, material);
  const repaint = () => {
    paintStudyValues(colours, drawn.view, drawn.theme);
    colourAttribute.needsUpdate = true;
  };
  /** *next* has the same values and geometry as the view the layer was made for: its target or Change differ. */
  patches.userData.recolour = (next: StudyView) => {
    drawn.view = next;
    repaint();
  };
  patches.userData.applyTheme = (theme: ViewportTheme) => {
    if (theme === drawn.theme) return;
    drawn.theme = theme;
    repaint();
  };
  patches.userData.summary = messages.studyPointCount(count);
  return patches;
}

// Sun path and sky dome ------------------------------------------------------------------------------------------------------

let sunDiscTexture: THREE.CanvasTexture | null = null;

function discTexture(): THREE.CanvasTexture {
  if (sunDiscTexture) return sunDiscTexture;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d")!;
  context.fillStyle = "#ffffff";
  context.beginPath();
  context.arc(32, 32, 30, 0, 2 * Math.PI);
  context.fill();
  sunDiscTexture = new THREE.CanvasTexture(canvas);
  return sunDiscTexture;
}

/** The sun path: per day a dashed line for the whole day, a solid 3 px line for the analysis hours, and the hour suns with labels. */
export function sunPathLayer(objects: SunPathObjects, sphere: Hemisphere): THREE.Object3D {
  const sun = colourToken("sun");
  const layer = new THREE.Group();
  for (const line of objects.lines) {
    if (line.kind === "day_path") {
      for (const run of line.runs) {
        const geometry = new THREE.BufferGeometry().setFromPoints(run.map((point) => new THREE.Vector3(...point)));
        const material = layerMaterial(new THREE.LineDashedMaterial({ color: sun, dashSize: DASH_SHARE * sphere.radius, gapSize: DASH_SHARE * sphere.radius }));
        layer.add(new THREE.Line(geometry, material).computeLineDistances());
      }
    } else {
      const pairs = line.runs.flatMap((run) => run.slice(1).flatMap((point, index) => [...run[index], ...point]));
      if (!pairs.length) continue;
      const material = layerMaterial(new LineMaterial({ color: sun, linewidth: PERIOD_PATH_PIXELS, worldUnits: false }));
      layer.add(new LineSegments2(new LineSegmentsGeometry().setPositions(pairs), material));
    }
  }
  const labels: TextSprite[] = [];
  for (const marker of objects.markers) {
    const disc = new THREE.Sprite(layerMaterial(new THREE.SpriteMaterial({ map: discTexture(), color: sun, depthWrite: false })));
    disc.position.set(...marker.position);
    disc.scale.setScalar(SUN_DISC_SHARE * sphere.radius);
    const label = textSprite(marker.label, colourToken("ink"), { pixels: HOUR_LABEL_PIXELS }, [0.5, -0.9]);
    layerMaterial(label.material);
    label.position.set(...marker.position);
    labels.push(label);
    layer.add(disc, label);
  }
  layer.userData.applyTheme = (theme: ViewportTheme) => labels.forEach((label) => recolourTextSprite(label, inkColour(theme)));
  return layer;
}

function addSkyPatch(positions: number[], sphere: Hemisphere, altitudeRange: [number, number], azimuthRange: [number, number]): number {
  const [lowAltitude, highAltitude] = [altitudeRange[0] + SKY_PATCH_GAP_DEGREES, Math.min(90, altitudeRange[1] - (altitudeRange[1] < 90 ? SKY_PATCH_GAP_DEGREES : 0))];
  const isCap = azimuthRange[1] - azimuthRange[0] >= 360;
  const [firstAzimuth, lastAzimuth] = isCap ? azimuthRange : [azimuthRange[0] + SKY_PATCH_GAP_DEGREES, azimuthRange[1] - SKY_PATCH_GAP_DEGREES];
  const columns = Math.max(1, Math.ceil((lastAzimuth - firstAzimuth) / SKY_PATCH_DEGREES_PER_COLUMN));
  const corner = (row: number, column: number) =>
    pointOnHemisphere(sphere, lowAltitude + ((highAltitude - lowAltitude) * row) / SKY_PATCH_ROWS, firstAzimuth + ((lastAzimuth - firstAzimuth) * column) / columns);
  const start = positions.length;
  for (let row = 0; row < SKY_PATCH_ROWS; row++) {
    for (let column = 0; column < columns; column++) {
      const [a, b, c, d] = [corner(row, column), corner(row, column + 1), corner(row + 1, column + 1), corner(row + 1, column)];
      positions.push(...a, ...b, ...c, ...a, ...c, ...d);
    }
  }
  return (positions.length - start) / 3;
}

/** The 145 sky patches on the hemisphere, coloured by weight on the sun ramp. */
export function skyDomeLayer(skyDome: SkyDome, sphere: Hemisphere): THREE.Object3D {
  const positions: number[] = [];
  const verticesPerPatch = skyDome.directions.map((direction) => {
    const outline = skyPatchOutline(direction);
    return addSkyPatch(positions, sphere, outline.altitudeRange, outline.azimuthRange);
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const colourAttribute = new THREE.Float32BufferAttribute(new Float32Array(positions.length), 3);
  geometry.setAttribute("color", colourAttribute);
  const material = layerMaterial(new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, transparent: true, depthWrite: false }));
  const dome = new THREE.Mesh(geometry, material);
  const shares = skyPatchShares(skyDome.weights);
  dome.userData.summary = messages.skyPatchCount(skyDome.directions.length);
  dome.userData.applyTheme = (theme: ViewportTheme) => {
    const colour = new THREE.Color();
    let vertex = 0;
    shares.forEach((share, patch) => {
      colour.set(sunRamp(share, theme));
      for (let corner = 0; corner < verticesPerPatch[patch]; corner++, vertex++) colourAttribute.setXYZ(vertex, colour.r, colour.g, colour.b);
    });
    colourAttribute.needsUpdate = true;
  };
  return dome;
}

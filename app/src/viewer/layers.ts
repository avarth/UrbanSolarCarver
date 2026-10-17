// The layers of the 3D view and how each is drawn (UX 8.2). A builder returns a three.js object whose userData tells the scene
// what it needs: a summary for the accessible name, applyTheme(theme) for colours that follow the viewport theme, and for some
// layers setSeeThrough(on) or hoverLabel(intersection). Every material is made dimmable (out of date: faded and desaturated).
import * as THREE from "three";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import type { SkyDome } from "../api_client/client";
import { messages } from "../messages";
import { cividis, colourToken, storeyColour, sunRamp, type ViewportTheme } from "./colour_scales";
import type { Point3 } from "./local_origin";
import type { ScorePoints } from "./score_points_decoder";
import { pointOnHemisphere, skyPatchOutline, skyPatchShares, type Hemisphere } from "./sky_dome";
import type { SunPathObjects } from "./sun_path";
import { recolourTextSprite, textSprite, type TextSprite } from "./text_sprite";

export type LayerName = "max_volume" | "test_surfaces" | "kept_voxels" | "carved_voxels" | "sun_path" | "sky_dome" | "envelope" | "building_massing";

/** The layers in the order of UX 8.2, which the layers menu and the accessible name follow. */
export const LAYER_NAMES: readonly LayerName[] = ["max_volume", "test_surfaces", "kept_voxels", "carved_voxels", "sun_path", "sky_dome", "envelope", "building_massing"];

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

function solidMaterial(colour: string, baseOpacity: number, side: THREE.Side = THREE.FrontSide): THREE.MeshLambertMaterial {
  const material = layerMaterial(new THREE.MeshLambertMaterial({ color: colour, flatShading: true, side, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }), baseOpacity);
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

/** The test surfaces in the accent colour, a lighter blue on the dark viewport. */
export function testSurfacesLayer(geometry: THREE.BufferGeometry): THREE.Object3D {
  const material = solidMaterial(colourToken("accent"), 1, THREE.DoubleSide);
  const surfaces = new THREE.Mesh(geometry, material);
  surfaces.userData.applyTheme = (theme: ViewportTheme) => material.color.set(colourToken(theme === "dark" ? "test-surface-on-dark" : "accent"));
  return surfaces;
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
  const massing = new THREE.Group();
  massing.add(body, edgeLines(geometry, colourToken("ink"), MASSING_EDGE_OPACITY));
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

/**
 * The parts of the maximum volume's edges (pairs of points) that lie above the kept voxels: vertical edges from the kept top up,
 * other edges when both their ends are above it. Drawn over the carved voxels, they show the volume that was carved away.
 */
export function carvedOutlineSegments(edgeSegments: Float32Array, keptTopAt: (x: number, y: number) => number): Float32Array {
  const outline: number[] = [];
  for (let start = 0; start < edgeSegments.length; start += 6) {
    const [ax, ay, az, bx, by, bz] = edgeSegments.subarray(start, start + 6);
    if (Math.abs(ax - bx) < VERTICAL_TOLERANCE_METRES && Math.abs(ay - by) < VERTICAL_TOLERANCE_METRES) {
      const low = Math.max(Math.min(az, bz), keptTopAt(ax, ay)), high = Math.max(az, bz);
      if (high - low > VERTICAL_TOLERANCE_METRES) outline.push(ax, ay, low, ax, ay, high);
    } else if (az >= keptTopAt(ax, ay) - VERTICAL_TOLERANCE_METRES && bz >= keptTopAt(bx, by) - VERTICAL_TOLERANCE_METRES) {
      outline.push(ax, ay, az, bx, by, bz);
    }
  }
  return Float32Array.from(outline);
}

/** The feature edges of a mesh as pairs of points. */
export function featureEdgeSegments(geometry: THREE.BufferGeometry): Float32Array {
  const edges = new THREE.EdgesGeometry(geometry, FEATURE_EDGE_DEGREES);
  const segments = Float32Array.from(edges.getAttribute("position").array);
  edges.dispose();
  return segments;
}

function voxelObject(centres: Float32Array, voxelSize: number, colours: THREE.Color[] | null, colour: string, baseOpacity: number): THREE.Object3D {
  const count = centres.length / 3;
  if (count > CUBES_UP_TO) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(centres, 3));
    if (colours) geometry.setAttribute("color", new THREE.Float32BufferAttribute(colours.flatMap((each) => [each.r, each.g, each.b]), 3));
    const material = layerMaterial(new THREE.PointsMaterial({ size: voxelSize, sizeAttenuation: true, vertexColors: colours !== null, color: colours ? "#ffffff" : colour }), baseOpacity);
    material.depthWrite = baseOpacity >= 1;
    return new THREE.Points(geometry, material);
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
  outlineSegments: Float32Array;      // carvedOutlineSegments of the maximum volume's edges
}

/** The carved voxels in the carved colour at 10 % opacity, with the maximum volume's edges above the kept voxels at 60 %. */
export function carvedVoxelsLayer({ voxels, voxelSize, voxelCount, outlineSegments }: CarvedVoxelsDrawing): THREE.Object3D {
  const carvedColour = colourToken("carved");
  const layer = new THREE.Group();
  if (voxels.scores.length) layer.add(voxelObject(voxels.centres, voxelSize, null, carvedColour, CARVED_VOXEL_OPACITY));
  const outlineGeometry = new THREE.BufferGeometry();
  outlineGeometry.setAttribute("position", new THREE.BufferAttribute(outlineSegments, 3));
  const outlineMaterial = layerMaterial(new THREE.LineBasicMaterial({ color: carvedColour, depthWrite: false }), CARVED_OUTLINE_OPACITY);
  layer.add(new THREE.LineSegments(outlineGeometry, outlineMaterial));
  layer.userData.summary = messages.voxelCount(voxelCount);
  return layer;
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

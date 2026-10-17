// The ground grid of UX 8.1 on z = 0 of the local origin: 10 m cells with stronger lines every 50 m and 100 m (1 m, 10 m and
// 50 m for a model under 30 m), distance labels on the 100 m lines, reaching 1 km from the model centre and fading with distance.
import * as THREE from "three";
import { messages } from "../messages";
import { formattedNumber } from "../steps/format_numbers";
import { colourToken, type ViewportTheme } from "./colour_scales";
import { recolourTextSprite, textSprite, type TextSprite } from "./text_sprite";

export interface GridSpacing {
  minorMetres: number;
  majorMetres: [number, number];
  extentMetres: number;
}

const SMALL_MODEL_METRES = 30;
const GRID_EXTENT_METRES = 1000;
const LABEL_LINE_METRES = 100;
const FADE_START_SHARE = 0.1;           // lines start to fade at a tenth of the extent from the model centre
const MAJOR_LINE_OPACITY = 0.75;        // the 50 m lines; the 100 m lines are drawn at full strength
const LABEL_PIXELS = 12;
const LABELLED_STEPS = 3;               // labels on the 100 m lines up to 300 m from the model centre (150 m for a small model)

export function groundGridSpacing(longestSideMetres: number): GridSpacing {
  return longestSideMetres < SMALL_MODEL_METRES
    ? { minorMetres: 1, majorMetres: [10, 50], extentMetres: GRID_EXTENT_METRES }
    : { minorMetres: 10, majorMetres: [50, 100], extentMetres: GRID_EXTENT_METRES };
}

/** The coordinates of the grid lines along one axis within *halfExtent* of *centre*, by strength. */
export function gridLineCoordinates(spacing: GridSpacing, centre: number, halfExtent: number): { minor: number[]; major: number[]; strongest: number[] } {
  const minorPerMajor = Math.round(spacing.majorMetres[0] / spacing.minorMetres);
  const minorPerStrongest = Math.round(spacing.majorMetres[1] / spacing.minorMetres);
  const lines = { minor: [] as number[], major: [] as number[], strongest: [] as number[] };
  const firstStep = Math.ceil((centre - halfExtent) / spacing.minorMetres);
  const lastStep = Math.floor((centre + halfExtent) / spacing.minorMetres);
  for (let step = firstStep; step <= lastStep; step++) {
    const coordinate = step * spacing.minorMetres + 0;      // + 0 turns -0 into 0
    if (step % minorPerStrongest === 0) lines.strongest.push(coordinate);
    else if (step % minorPerMajor === 0) lines.major.push(coordinate);
    else lines.minor.push(coordinate);
  }
  return lines;
}

const fadingLineVertexShader = `
  varying vec2 groundPosition;
  void main() {
    groundPosition = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const fadingLineFragmentShader = `
  uniform vec3 lineColour;
  uniform float lineOpacity;
  uniform vec2 fadeCentre;
  uniform float fadeStart;
  uniform float fadeEnd;
  varying vec2 groundPosition;
  void main() {
    float fade = 1.0 - smoothstep(fadeStart, fadeEnd, distance(groundPosition, fadeCentre));
    gl_FragColor = vec4(lineColour, lineOpacity * fade);
    #include <colorspace_fragment>
  }`;

function fadingLines(xLines: number[], yLines: number[], centre: [number, number], halfExtent: number, opacity: number): THREE.LineSegments {
  const positions: number[] = [];
  for (const x of xLines) positions.push(x, centre[1] - halfExtent, 0, x, centre[1] + halfExtent, 0);
  for (const y of yLines) positions.push(centre[0] - halfExtent, y, 0, centre[0] + halfExtent, y, 0);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.ShaderMaterial({
    vertexShader: fadingLineVertexShader,
    fragmentShader: fadingLineFragmentShader,
    uniforms: {
      lineColour: { value: new THREE.Color() },
      lineOpacity: { value: opacity },
      fadeCentre: { value: new THREE.Vector2(centre[0], centre[1]) },
      fadeStart: { value: FADE_START_SHARE * halfExtent },
      fadeEnd: { value: halfExtent },
    },
    transparent: true,
    depthWrite: false,
  });
  return new THREE.LineSegments(geometry, material);
}

/** The grid around *centre* (the model's footprint centre in local coordinates), with an applyTheme(theme) in its userData. */
export function groundGrid(spacing: GridSpacing, centre: [number, number]): THREE.Group {
  const halfExtent = spacing.extentMetres;
  const xLines = gridLineCoordinates(spacing, centre[0], halfExtent);
  const yLines = gridLineCoordinates(spacing, centre[1], halfExtent);
  const minor = fadingLines(xLines.minor, yLines.minor, centre, halfExtent, 1);
  const major = fadingLines(xLines.major, yLines.major, centre, halfExtent, MAJOR_LINE_OPACITY);
  const strongest = fadingLines(xLines.strongest, yLines.strongest, centre, halfExtent, 1);
  const grid = new THREE.Group();
  grid.name = "ground_grid";
  grid.renderOrder = -1;
  grid.add(minor, major, strongest);

  // Distances from the local origin on the 100 m lines, along the south and the west side of the model (the local origin is its
  // minimum corner), near the model, where the lines are not yet faded.
  const labels: TextSprite[] = [];
  const labelReach = LABELLED_STEPS * spacing.majorMetres[1];
  const labelled = (coordinates: number[], along: number) =>
    coordinates.filter((value) => value % LABEL_LINE_METRES === 0 && Math.abs(value - along) <= labelReach);
  for (const x of labelled([...xLines.strongest, ...xLines.major, ...xLines.minor], centre[0])) {
    const label = textSprite(messages.lengthInMetres(formattedNumber(x)), "#000000", { pixels: LABEL_PIXELS }, [0.5, 1.2]);
    label.position.set(x, 0, 0);
    labels.push(label);
  }
  for (const y of labelled([...yLines.strongest, ...yLines.major, ...yLines.minor], centre[1])) {
    if (y === 0) continue;        // the 0 m of the x labels already marks the corner
    const label = textSprite(messages.lengthInMetres(formattedNumber(y)), "#000000", { pixels: LABEL_PIXELS }, [1.1, 0.5]);
    label.position.set(0, y, 0);
    labels.push(label);
  }
  grid.add(...labels);

  grid.userData.applyTheme = (theme: ViewportTheme) => {
    (minor.material as THREE.ShaderMaterial).uniforms.lineColour.value.set(colourToken(`grid-minor-${theme}`));
    for (const lines of [major, strongest]) (lines.material as THREE.ShaderMaterial).uniforms.lineColour.value.set(colourToken(`grid-major-${theme}`));
    for (const label of labels) recolourTextSprite(label, colourToken(theme === "dark" ? "muted-on-dark" : "muted"));
  };
  return grid;
}

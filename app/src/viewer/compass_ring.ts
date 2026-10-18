// The compass ring of R2 2, one of the ground aids: a circle on the ground around the whole scene, with a tick every 10 degrees
// and a longer tick and the letters N, E, S and W every 90 degrees, turned by North direction. It lies on the rim of the scene
// hemisphere (sky_dome.ts), the one the sun path and the sky dome are drawn on. Its azimuths are degrees clockwise from +Y, the
// north_deg convention the compass overlay reads (compass.ts), so the ring's N and the overlay's needle always agree.
import * as THREE from "three";
import { messages } from "../messages";
import { colourToken, type ViewportTheme } from "./colour_scales";
import type { Bounds3, Point3 } from "./local_origin";
import { pointOnHemisphere, sceneHemisphere, type Hemisphere } from "./sky_dome";
import { recolourTextSprite, textSprite, type TextSprite } from "./text_sprite";

const TICK_STEP_DEGREES = 10;
const LETTER_STEP_DEGREES = 90;
const SHORT_TICK_SHARE = 0.03;          // of the ring radius, drawn inward from the circle
const LONG_TICK_SHARE = 0.08;
const LETTER_DISTANCE_SHARE = 1.06;     // the letters just outside the circle
const LETTER_PIXELS = 16;
const CIRCLE_SEGMENTS = 180;

export interface CompassRingTick {
  azimuthDegrees: number;
  long: boolean;
  inner: Point3;
  outer: Point3;      // on the circle
}

export interface CompassRingLetter {
  letter: string;
  position: Point3;
}

export interface CompassRingMarks {
  ticks: CompassRingTick[];
  letters: CompassRingLetter[];
}

/** A point on the rim of *sphere* at *share* of its radius from the centre, toward *azimuthDegrees*. */
function onGround(sphere: Hemisphere, share: number, azimuthDegrees: number): Point3 {
  return pointOnHemisphere({ centre: sphere.centre, radius: share * sphere.radius }, 0, azimuthDegrees);
}

/** The ticks and the letters of the ring on the rim of *sphere*, the N toward *northDegrees*. */
export function compassRingMarks(sphere: Hemisphere, northDegrees: number): CompassRingMarks {
  const ticks: CompassRingTick[] = [];
  for (let turn = 0; turn < 360; turn += TICK_STEP_DEGREES) {
    const azimuthDegrees = northDegrees + turn;
    const long = turn % LETTER_STEP_DEGREES === 0;
    ticks.push({ azimuthDegrees, long, inner: onGround(sphere, 1 - (long ? LONG_TICK_SHARE : SHORT_TICK_SHARE), azimuthDegrees),
                 outer: onGround(sphere, 1, azimuthDegrees) });
  }
  const letters = messages.compassRingLetters.map((letter, index) => ({
    letter, position: onGround(sphere, LETTER_DISTANCE_SHARE, northDegrees + index * LETTER_STEP_DEGREES),
  }));
  return { ticks, letters };
}

/** The ring around the scene of *sceneBounds* (maximum volume and test surfaces together), with an applyTheme(theme) in its userData. */
export function compassRing(sceneBounds: Bounds3, northDegrees: number): THREE.Group {
  const sphere = sceneHemisphere(sceneBounds);
  const { ticks, letters } = compassRingMarks(sphere, northDegrees);
  const positions: number[] = [];
  for (let segment = 0; segment < CIRCLE_SEGMENTS; segment++) {
    positions.push(...onGround(sphere, 1, (360 * segment) / CIRCLE_SEGMENTS), ...onGround(sphere, 1, (360 * (segment + 1)) / CIRCLE_SEGMENTS));
  }
  for (const tick of ticks) positions.push(...tick.inner, ...tick.outer);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const lineMaterial = new THREE.LineBasicMaterial({ transparent: true, depthWrite: false });
  const lines = new THREE.LineSegments(geometry, lineMaterial);
  const labels: TextSprite[] = letters.map(({ letter, position }) => {
    const label = textSprite(letter, "#000000", { pixels: LETTER_PIXELS });
    label.position.set(...position);
    return label;
  });
  const ring = new THREE.Group();
  ring.name = "compass_ring";
  ring.renderOrder = -1;
  ring.add(lines, ...labels);
  ring.userData.applyTheme = (theme: ViewportTheme) => {
    const dark = theme === "dark";
    lineMaterial.color.set(colourToken(dark ? "muted-on-dark" : "muted"));
    for (const label of labels) recolourTextSprite(label, colourToken(dark ? "ink-on-dark" : "ink"));
  };
  return ring;
}

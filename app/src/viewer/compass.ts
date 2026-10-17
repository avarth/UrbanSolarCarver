// Orientation aids of UX 8.1: the compass needle and the axis gizmo (drawn by the overlays from these angles) and the north arrow
// on the ground grid. North is the USC north_deg: degrees clockwise from +Y. Camera yaw is the clockwise turn of the view about Z
// from the top view with +Y up the screen; camera elevation is how far the view looks down, 90 in the top view.
import * as THREE from "three";
import { messages } from "../messages";
import { colourToken, type ViewportTheme } from "./colour_scales";
import { recolourTextSprite, textSprite } from "./text_sprite";

const DEGREES = Math.PI / 180;

function normalisedDegrees(angle: number): number {
  return ((angle % 360) + 360) % 360;
}

/** The needle's angle on screen, clockwise from up, in [0, 360). */
export function northNeedleScreenAngle(cameraYawDegrees: number, northDegrees: number): number {
  return normalisedDegrees(northDegrees - cameraYawDegrees);
}

/** The horizontal unit vector toward north in model coordinates. */
export function northDirection(northDegrees: number): [number, number, number] {
  return [Math.sin(northDegrees * DEGREES), Math.cos(northDegrees * DEGREES), 0];
}

/** Where the model's X, Y and Z axes point on screen (x to the right, y up; length 1 for an axis in the screen plane). */
export function axisScreenDirections(cameraYawDegrees: number, cameraElevationDegrees: number): Record<"x" | "y" | "z", [number, number]> {
  const yaw = cameraYawDegrees * DEGREES, elevation = cameraElevationDegrees * DEGREES;
  const away = [Math.sin(yaw), Math.cos(yaw), 0];                   // the horizontal direction the camera faces
  const right = [Math.cos(yaw), -Math.sin(yaw), 0];
  const up = [away[0] * Math.sin(elevation), away[1] * Math.sin(elevation), Math.cos(elevation)];
  const onScreen = (axis: number): [number, number] => [right[axis], up[axis]];
  return { x: onScreen(0), y: onScreen(1), z: onScreen(2) };
}

/** The north arrow on the ground: a flat arrow *length* metres long pointing north, with an N at its tip; applyTheme in its userData. */
export function northArrow(northDegrees: number, length: number): THREE.Group {
  const shape = new THREE.Shape();
  const halfWidth = length * 0.18;
  shape.moveTo(0, length / 2);
  shape.lineTo(halfWidth, -length / 2);
  shape.lineTo(0, -length / 4);
  shape.lineTo(-halfWidth, -length / 2);
  shape.closePath();
  const material = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide, depthWrite: false, transparent: true, opacity: 0.85 });
  const arrow = new THREE.Mesh(new THREE.ShapeGeometry(shape), material);
  const letter = textSprite(messages.northLetter, "#000000", { metres: length * 0.4 }, [0.5, 0]);
  letter.position.set(0, length * 0.6, 0);
  const group = new THREE.Group();
  group.name = "north_arrow";
  group.add(arrow, letter);
  group.rotation.z = -northDegrees * DEGREES;       // clockwise
  group.userData.applyTheme = (theme: ViewportTheme) => {
    const ink = colourToken(theme === "dark" ? "ink-on-dark" : "ink");
    material.color.set(ink);
    recolourTextSprite(letter, ink);
  };
  return group;
}

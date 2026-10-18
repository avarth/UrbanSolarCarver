// Text in the 3D scene (grid distances, hour labels, the N of the north arrow): a sprite that faces the camera, with its text
// drawn on a canvas in the interface font. Its height is given in metres, so it scales with the model like the geometry, or in
// pixels, so it stays readable at any zoom (the scene then sizes it for the view with fitTextSpritesToView).
import * as THREE from "three";

const CANVAS_TEXT_PIXELS = 64;
const CANVAS_PADDING_PIXELS = 8;

export type TextHeight = { metres: number } | { pixels: number };

export interface TextSprite extends THREE.Sprite {
  material: THREE.SpriteMaterial;
}

function drawText(text: string, colour: string): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d")!;
  const font = `600 ${CANVAS_TEXT_PIXELS}px ${getComputedStyle(document.documentElement).getPropertyValue("--font-family") || "sans-serif"}`;
  context.font = font;
  canvas.width = Math.ceil(context.measureText(text).width) + 2 * CANVAS_PADDING_PIXELS;
  canvas.height = CANVAS_TEXT_PIXELS + 2 * CANVAS_PADDING_PIXELS;
  context.font = font;       // a resized canvas forgets its font
  context.fillStyle = colour;
  context.textBaseline = "middle";
  context.fillText(text, CANVAS_PADDING_PIXELS, canvas.height / 2);
  return canvas;
}

/** A sprite showing *text* in *colour* at *height*; *anchor* is the point of the sprite placed at its position. */
export function textSprite(text: string, colour: string, height: TextHeight, anchor: [number, number] = [0.5, 0.5]): TextSprite {
  const material = new THREE.SpriteMaterial({ transparent: true, depthWrite: false, sizeAttenuation: "metres" in height });
  const sprite = new THREE.Sprite(material) as TextSprite;
  sprite.center.set(anchor[0], anchor[1]);
  sprite.userData.text = text;
  sprite.userData.textHeight = height;
  recolourTextSprite(sprite, colour);
  return sprite;
}

/** Draws the sprite's text again in another colour (the viewport theme changed). */
export function recolourTextSprite(sprite: TextSprite, colour: string): void {
  const canvas = drawText(sprite.userData.text, colour);
  sprite.material.map?.dispose();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  sprite.material.map = texture;
  sprite.material.needsUpdate = true;
  sprite.userData.aspect = canvas.width / canvas.height;
  const height: TextHeight = sprite.userData.textHeight;
  if ("metres" in height) sprite.scale.set(height.metres * sprite.userData.aspect, height.metres, 1);
}

/**
 * Sizes the pixel-high text sprites under *root* for a view *viewHeightPixels* tall. A sprite without size attenuation keeps
 * the size it would have one unit in front of the camera, where the view is 2 tan(fov / 2) units tall.
 */
export function fitTextSpritesToView(root: THREE.Object3D, viewHeightPixels: number, fieldOfViewDegrees: number): void {
  const viewHeightAtOneUnit = 2 * Math.tan((fieldOfViewDegrees * Math.PI) / 360);
  root.traverse((object) => {
    const height: TextHeight | undefined = object.userData.textHeight;
    if (!height || !("pixels" in height)) return;
    const scale = (height.pixels / viewHeightPixels) * viewHeightAtOneUnit;
    object.scale.set(scale * object.userData.aspect, scale, 1);
  });
}

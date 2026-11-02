// The layers of the 3D view as ViewerPane wants them, one entry per layer, put in the scene by one effect: each render, only what
// changed since the scene was last told goes to it. A new scene is told everything.
import { useEffect, useRef } from "react";
import type * as THREE from "three";
import type { LayerName, ViewerScene } from "../viewer/scene";

export interface SceneLayer {
  name: LayerName;
  /** The object in the layer's slot, null for none. A new object replaces the old one, which the scene disposes. */
  object: THREE.Object3D | null;
  /** Shown or hidden; null leaves the slot as it is (a layer the layers menu does not list, which keeps its last state). */
  visible: boolean | null;
  dimmed: boolean;
}

type LayerSlots = Pick<ViewerScene, "setLayer" | "setLayerVisible" | "setLayerDimmed">;

export function useSceneLayers(scene: LayerSlots | null, layers: readonly SceneLayer[]): void {
  const told = useRef<{ scene: LayerSlots | null; layers: Map<LayerName, SceneLayer> }>({ scene: null, layers: new Map() });
  useEffect(() => {
    if (scene === null) return;
    if (told.current.scene !== scene) told.current = { scene, layers: new Map() };
    const before = told.current.layers;
    const changed = (layer: SceneLayer, field: "object" | "visible" | "dimmed") =>
      !before.has(layer.name) || before.get(layer.name)![field] !== layer[field];
    // The objects first: the first one placed frames the view while every slot is still shown, as before the menu's choices apply.
    for (const layer of layers) if (changed(layer, "object")) scene.setLayer(layer.name, layer.object);
    for (const layer of layers) if (layer.visible !== null && changed(layer, "visible")) scene.setLayerVisible(layer.name, layer.visible);
    for (const layer of layers) if (changed(layer, "dimmed")) scene.setLayerDimmed(layer.name, layer.dimmed);
    for (const layer of layers) before.set(layer.name, layer);
  });
}

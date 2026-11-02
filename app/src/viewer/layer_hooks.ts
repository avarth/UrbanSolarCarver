// What a layer's three.js object offers the scene and the view beside its meshes, kept in its userData. The builders (layers.ts,
// ground_grid.ts, compass_ring.ts) set these and the scene and ViewerPane call them, both through layerHooks, so each is typed
// where it is written and where it is read.
import type * as THREE from "three";
import type { ViewportTheme } from "./colour_scales";
import type { StudyView } from "./study_values";

export interface LayerHooks {
  /** Colours that follow the viewport theme (edges, labels, the accent colour). */
  applyTheme?: (theme: ViewportTheme) => void;
  /** Called after every camera move, for edges that depend on where the camera is (the carved voxels' outline). */
  followCamera?: (cameraPosition: THREE.Vector3) => void;
  /** What the view's accessible name says of the layer: a count of its voxels, storeys, patches or points. */
  summary?: string;
  /** The envelope: drawn see-through, for the building massing inside it or the study's values on it. */
  setSeeThrough?: (seeThrough: boolean) => void;
  /** The building massing: the label shown at the pointer for a hit on it, or null. */
  hoverLabel?: (intersection: THREE.Intersection) => string | null;
  storeyCount?: number;
  /** The study's values: paints the patches for *view*, which has the values and the points the layer was made for. */
  recolour?: (view: StudyView) => void;
  /** Inspect's surface orientation: the file and the surface a hit on one of its meshes landed on, or null. */
  fileAndSurfaceOf?: (intersection: THREE.Intersection) => { fileName: string; surface: number } | null;
  arrowCount?: number;
}

export function layerHooks(object: THREE.Object3D): LayerHooks {
  return object.userData as LayerHooks;
}

import { afterEach, expect, test } from "vitest";
import * as THREE from "three";
import type { LayerName } from "../viewer/scene";
import { renderForTest, type RenderedOverlay } from "./render_for_test";
import { useSceneLayers, type SceneLayer } from "./use_scene_layers";

/** A scene that writes down each call, as "setLayer max_volume". */
function recordingScene() {
  const calls: string[] = [];
  return {
    calls,
    setLayer: (name: LayerName) => { calls.push(`setLayer ${name}`); },
    setLayerVisible: (name: LayerName, visible: boolean) => { calls.push(`visible ${name} ${visible}`); },
    setLayerDimmed: (name: LayerName, dimmed: boolean) => { calls.push(`dimmed ${name} ${dimmed}`); },
  };
}

type RecordingScene = ReturnType<typeof recordingScene>;

function Layers({ scene, layers }: { scene: RecordingScene | null; layers: SceneLayer[] }) {
  useSceneLayers(scene, layers);
  return null;
}

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const box = new THREE.Object3D();
const entry = (name: LayerName, extra: Partial<SceneLayer> = {}): SceneLayer => ({ name, object: null, visible: true, dimmed: false, ...extra });

test("a new scene is given every layer: the objects first, then which are shown, then which are dimmed", () => {
  const scene = recordingScene();
  rendered = renderForTest(<Layers scene={scene} layers={[entry("max_volume", { object: box }), entry("envelope", { visible: false, dimmed: true })]} />);
  expect(scene.calls).toEqual(["setLayer max_volume", "setLayer envelope", "visible max_volume true", "visible envelope false",
                               "dimmed max_volume false", "dimmed envelope true"]);
});

test("afterwards only what changed goes to the scene, and nothing when nothing changed", () => {
  const scene = recordingScene();
  const layers = [entry("max_volume", { object: box }), entry("envelope")];
  rendered = renderForTest(<Layers scene={scene} layers={layers} />);
  scene.calls.length = 0;
  rendered.rerender(<Layers scene={scene} layers={[entry("max_volume", { object: box }), entry("envelope")]} />);
  expect(scene.calls).toEqual([]);
  rendered.rerender(<Layers scene={scene} layers={[entry("max_volume", { object: new THREE.Object3D() }), entry("envelope", { dimmed: true })]} />);
  expect(scene.calls).toEqual(["setLayer max_volume", "dimmed envelope true"]);
});

test("a layer whose visibility is null keeps its slot as it is", () => {
  const scene = recordingScene();
  rendered = renderForTest(<Layers scene={scene} layers={[entry("sun_study", { object: box, visible: null })]} />);
  expect(scene.calls).toEqual(["setLayer sun_study", "dimmed sun_study false"]);
});

test("nothing is asked of a scene that is not there yet; a scene that replaces another is given everything again", () => {
  const layers = [entry("max_volume", { object: box })];
  rendered = renderForTest(<Layers scene={null} layers={layers} />);
  const first = recordingScene();
  rendered.rerender(<Layers scene={first} layers={layers} />);
  const second = recordingScene();
  rendered.rerender(<Layers scene={second} layers={layers} />);
  expect(second.calls).toEqual(first.calls);
  expect(second.calls).toHaveLength(3);
});

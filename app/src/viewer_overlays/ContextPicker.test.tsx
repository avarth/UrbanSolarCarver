// Picking test surfaces on the surroundings (design/test-surfaces-on-context.md): a click on the context layer picks the flat piece
// under it, a click on a picked piece drops it, the pieces are drawn over the view, and the bar sends the picks (in the input files'
// coordinates, with the click's ray) to a new set, to a picked set, or back to the set being edited.
import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import * as THREE from "three";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { ViewerScene } from "../viewer/scene";
import type { Point3 } from "../viewer/local_origin";
import { ContextPicker, type PickTarget, type SurfacePick } from "./ContextPicker";
import { byRole, click, press, renderForTest, type, type RenderedOverlay } from "./render_for_test";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

// The corner of a box: a floor of two triangles (faces 0 and 1, z = 0) and a wall of two (faces 2 and 3, x = 0), in local coordinates
const CORNER = [
  [[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]],
  [[0, 0, 0], [0, 1, 0], [0, 1, 1]], [[0, 0, 0], [0, 1, 1], [0, 0, 1]],
];
const ORIGIN: Point3 = [1000, 2000, 5];

function cornerGeometry(): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(CORNER.flat(2), 3));
  return geometry;
}

interface Opened {
  scene: FakeViewerScene;
  onUse: ReturnType<typeof vi.fn<(picks: SurfacePick[], target: PickTarget) => void>>;
  onCancel: ReturnType<typeof vi.fn<() => void>>;
}

function openPicker(props: Partial<Parameters<typeof ContextPicker>[0]> = {}): Opened {
  const scene = new FakeViewerScene(document.createElement("div"));
  const onUse = vi.fn<(picks: SurfacePick[], target: PickTarget) => void>();
  const onCancel = vi.fn<() => void>();
  rendered = renderForTest(
    <ContextPicker scene={scene as unknown as ViewerScene} origin={ORIGIN} geometry={cornerGeometry()} colour="#ee6677" pickedSets={[]}
                   newSetName="Picked 3" busy={false} problem={null} onUse={onUse} onCancel={onCancel} {...props} />,
  );
  return { scene, onUse, onCancel };
}

const bar = () => rendered!.container.querySelector<HTMLFormElement>("form.context-picker-bar")!;
const useButton = () => bar().querySelector<HTMLButtonElement>('button[type="submit"]')!;
const polygons = () => [...rendered!.container.querySelectorAll(".context-picker-pieces polygon")].map((polygon) => polygon.getAttribute("points"));
const nameField = () => bar().querySelector<HTMLInputElement>('input[aria-label="Name of the new set"]');
const targetSelect = () => bar().querySelector<HTMLSelectElement>('select[aria-label="Where the picked faces go"]');

function clickFace(scene: FakeViewerScene, faceIndex: number, point: Point3) {
  act(() => scene.clickLayer("context", { faceIndex, point: new THREE.Vector3(...point), distance: 1, object: new THREE.Object3D() } as THREE.Intersection));
}

test("a click picks the flat piece under it, a second click on the piece drops it; the button counts the picks", () => {
  const { scene } = openPicker();
  expect(bar().getAttribute("aria-label")).toBe("Picking test surfaces on the surroundings");
  expect(bar().querySelector(".site-editor-steps")!.textContent).toBe(
    "Click the facades and roofs of the surroundings to protect. Click a picked face again to drop it.");
  expect(useButton().textContent).toBe("Use 0 faces");
  expect(useButton().disabled).toBe(true);
  expect(polygons()).toEqual([]);

  clickFace(scene, 0, [0.8, 0.2, 0]);
  // The floor's two triangles, drawn where the scene puts them on the screen (10 pixels a metre around pixel 400, 300)
  expect(polygons()).toEqual(["400,300 410,300 410,290", "400,300 410,290 400,290"]);
  expect(useButton().textContent).toBe("Use 1 face");
  expect(useButton().disabled).toBe(false);
  expect(rendered!.container.querySelector<SVGGElement>(".context-picker-pieces")!.style.fill).toBe("rgb(238, 102, 119)");

  clickFace(scene, 3, [0, 0.2, 0.8]);
  expect(polygons()).toHaveLength(4);
  expect(useButton().textContent).toBe("Use 2 faces");

  clickFace(scene, 1, [0.2, 0.8, 0]);            // the other triangle of the floor: the floor is dropped
  expect(polygons()).toEqual(["400,300 400,290 400,290", "400,300 400,290 400,300"]);
  expect(useButton().textContent).toBe("Use 1 face");
});

test("a click with no face does nothing", () => {
  const { scene } = openPicker();
  act(() => scene.clickLayer("context", { point: new THREE.Vector3(), distance: 1, object: new THREE.Object3D() } as THREE.Intersection));
  expect(useButton().textContent).toBe("Use 0 faces");
});

test("Use sends each pick as the point clicked in the input files' coordinates and the click's ray, normalised, to a new set", () => {
  const { scene, onUse } = openPicker();
  clickFace(scene, 2, [0, 0.5, 0.5]);
  clickFace(scene, 0, [0.5, 0.25, 0]);
  expect(nameField()!.value).toBe("Picked 3");
  click(useButton());
  expect(onUse).toHaveBeenCalledOnce();
  const [picks, target] = onUse.mock.calls[0];
  expect(target).toEqual({ kind: "new", name: "Picked 3" });
  expect(picks.map((pick) => pick.point)).toEqual([[1000, 2000.5, 5.5], [1000.5, 2000.25, 5]]);
  // The camera stands at (100, 0, 0) in local coordinates: each ray runs from it to the local point clicked
  const expected = (point: Point3) => {
    const ray = [point[0] - 100, point[1], point[2]];
    const length = Math.hypot(...ray);
    return ray.map((value) => value / length);
  };
  picks.forEach((pick, index) => {
    const want = expected(index === 0 ? [0, 0.5, 0.5] : [0.5, 0.25, 0]);
    pick.ray.forEach((value, axis) => expect(value).toBeCloseTo(want[axis], 12));
    expect(Math.hypot(...pick.ray)).toBeCloseTo(1, 12);
  });
});

test("the new set's name can be changed; without a name Use is off", () => {
  const { scene, onUse } = openPicker();
  clickFace(scene, 0, [0.5, 0.25, 0]);
  type(nameField()!, "   ");
  expect(useButton().disabled).toBe(true);
  type(nameField()!, "South facades");
  expect(useButton().disabled).toBe(false);
  click(useButton());
  expect(onUse.mock.calls[0][1]).toEqual({ kind: "new", name: "South facades" });
});

test("the picks can go to a picked set instead: the name field goes and Use names the set's file", () => {
  const { scene, onUse } = openPicker({ pickedSets: [{ file: "picked_1.ply", name: "Roofs" }, { file: "picked_2.ply", name: "Courtyard" }] });
  expect([...targetSelect()!.options].map((option) => option.textContent)).toEqual(["New set", "Add to Roofs", "Add to Courtyard"]);
  type(targetSelect()!, "picked_2.ply");
  expect(nameField()).toBeNull();
  clickFace(scene, 0, [0.5, 0.25, 0]);
  click(useButton());
  expect(onUse.mock.calls[0][1]).toEqual({ kind: "add", file: "picked_2.ply" });
});

test("Edit picks starts from the set's picks, says which set it edits, and Save picks sends what is left", () => {
  const roof: SurfacePick = { point: [1000.5, 2000.25, 5], ray: [0, 0, -1] };
  const wall: SurfacePick = { point: [1000, 2000.5, 5.5], ray: [-1, 0, 0] };
  const gone: SurfacePick = { point: [1050, 2000, 5], ray: [-1, 0, 0] };          // on no face of the surroundings now
  const { scene, onUse } = openPicker({ editing: { name: "Roofs", picks: [roof, wall, gone] } });
  expect(bar().querySelector(".context-picker-target")!.textContent).toBe("Editing Roofs");
  expect(targetSelect()).toBeNull();
  expect(nameField()).toBeNull();
  expect(polygons()).toHaveLength(4);
  expect(useButton().textContent).toBe("Save picks");
  clickFace(scene, 3, [0, 0.2, 0.8]);             // drops the wall
  expect(polygons()).toHaveLength(2);
  click(useButton());
  expect(onUse).toHaveBeenCalledExactlyOnceWith([roof], { kind: "new", name: "Picked 3" });
});

test("Save picks with every pick dropped is off", () => {
  const { scene } = openPicker({ editing: { name: "Roofs", picks: [{ point: [1000.5, 2000.25, 5], ray: [0, 0, -1] }] } });
  clickFace(scene, 0, [0.5, 0.25, 0]);
  expect(useButton().disabled).toBe(true);
});

test("Esc and Cancel cancel; while busy neither does, clicks pick nothing and the buttons are off", () => {
  const { onCancel } = openPicker();
  press(document.body, "Escape");
  expect(onCancel).toHaveBeenCalledOnce();
  click(byRole(bar(), "button", "Cancel"));
  expect(onCancel).toHaveBeenCalledTimes(2);
  rendered!.unmount();

  const busy = openPicker({ busy: true });
  clickFace(busy.scene, 0, [0.5, 0.25, 0]);
  expect(polygons()).toEqual([]);
  press(document.body, "Escape");
  expect(busy.onCancel).not.toHaveBeenCalled();
  expect(byRole<HTMLButtonElement>(bar(), "button", "Cancel").disabled).toBe(true);
  expect(useButton().disabled).toBe(true);
});

test("a refusal is shown in the bar", () => {
  openPicker({ problem: "The pick 1 is on no face of the surroundings." });
  expect(bar().querySelector('[role="alert"]')!.textContent).toBe("The pick 1 is on no face of the surroundings.");
});

test("the picker stops listening to the view's clicks once it closes", () => {
  const { scene } = openPicker();
  expect(scene.clickListenerCount("context")).toBe(1);
  rendered!.unmount();
  rendered = null;
  expect(scene.clickListenerCount("context")).toBe(0);
});

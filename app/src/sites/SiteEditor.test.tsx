// The site editor on its own: with flatElevation (a test surface drawn on the ground), a vertex's elevation moves the whole outline.
import { act } from "react";
import { afterEach, expect, test } from "vitest";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { SiteEditor } from "./SiteEditor";
import type { Site } from "./site_geometry";

let rendered: RenderedOverlay | null = null;
afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const GROUND: Site = { name: "Ground 1", points: [[0, 0, 2], [20, 0, 2], [20, 10, 2], [0, 10, 2]], height: 10, holes: [[[5, 3, 2], [8, 3, 2], [8, 6, 2]]] };

function typeElevation(container: HTMLElement, label: string, value: string) {
  const handle = container.querySelector(`[aria-label="${label}"]`)!;
  act(() => {
    handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: 600, clientY: 300 }));
    handle.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, clientX: 600, clientY: 300 }));
  });
  const field = container.querySelector<HTMLInputElement>(`[aria-label="${label}: Elevation"]`)!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => { field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
}

function render(flatElevation: boolean, changes: Site[]) {
  const scene = new FakeViewerScene(document.createElement("div"));
  rendered = renderForTest(
    <SiteEditor scene={scene as never} origin={[0, 0, 0]} sites={[GROUND]} tool={{ kind: "edit", index: 0 }} level={2} newSiteName="Ground 2"
                onFinishDrawing={() => {}} onChangeSite={(_, site) => changes.push(site)} onClose={() => {}} onUndo={() => {}} onRedo={() => {}}
                canUndo={false} canRedo={false} refusal={null} flatElevation={flatElevation} />,
  );
  return rendered.container;
}

test("with flatElevation a vertex's elevation moves every vertex of the outline and its holes", () => {
  const changes: Site[] = [];
  typeElevation(render(true, changes), "Vertex 2", "4.5");
  expect(changes).toHaveLength(1);
  expect([...changes[0].points, ...(changes[0].holes ?? []).flat()].map((point) => point[2])).toEqual([4.5, 4.5, 4.5, 4.5, 4.5, 4.5, 4.5]);
});

test("without it only that vertex moves", () => {
  const changes: Site[] = [];
  typeElevation(render(false, changes), "Vertex 2", "4.5");
  expect(changes[0].points.map((point) => point[2])).toEqual([2, 4.5, 2, 2]);
});

// Drawn context blocks in the workspace (design/context-blocks.md): read from the service, drawn in the Context layer with the
// context files, drawn and edited in the Site step with the site editor, saved whole.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { FakeService, NOTHING_RUN, buttonIn, container, endWorkspaceTest, openWorkspace, project, settle, startWorkspaceTest } from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const BLOCK = { name: "Block 1", points: [[100, 100, 0], [110, 100, 0], [110, 110, 0], [100, 110, 0]], height: 12, holes: [] };

/** The triangles of the geometry the Context layer was given, 0 without one. */
function contextTriangles(): number {
  const layer = FakeViewerScene.latest!.layers.get("context");
  let triangles = 0;
  layer?.traverse((object) => {
    if (object.type !== "Mesh") return;         // the layer's edges are line segments
    const geometry = (object as unknown as { geometry: { attributes: { position: { count: number } }; index: { count: number } | null } }).geometry;
    triangles += (geometry.index?.count ?? geometry.attributes.position.count) / 3;
  });
  return triangles;
}

test("a project with blocks and no context file draws the blocks in the Context layer", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [BLOCK];
  await openWorkspace(service, project(NOTHING_RUN));
  expect(service.count("GET /context-blocks")).toBeGreaterThan(0);
  expect(service.count("GET /context-blocks/mesh")).toBe(1);
  expect(FakeViewerScene.latest!.layersWithObjects()).toContain("context");
});

test("blocks and context files are drawn together in the Context layer", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [BLOCK];
  const opened = project(NOTHING_RUN);
  await openWorkspace(service, { ...opened, inputs: { ...opened.inputs, context: [{ name: "town.obj", triangle_count: 1 }] } });
  expect(contextTriangles()).toBe(2);           // the file's triangle and the blocks' (one each in the fake service)
});

// --- Drawing and editing in the Site step

const panel = () => container().querySelector(".workspace-panel")!;
const editor = () => container().querySelector(".site-editor");
const rows = () => [...panel().querySelectorAll<HTMLElement>(".context-block-row")];
const key = async (name: string, options: KeyboardEventInit = {}) => {
  act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, ...options })); });
  await settle();
};
/** Clicks the fake top view at the plan point (x, y) in metres (10 pixels a metre about pixel (400, 300)). */
const clickAt = async (x: number, y: number) => {
  act(() => { FakeViewerScene.latest!.clickView(400 + x * 10, 300 - y * 10); });
  await settle();
};
const typeAndEnter = async (field: HTMLInputElement, value: string) => {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => { field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await settle();
};
async function drawSquare(service: FakeService) {
  act(() => { buttonIn(panel(), "Draw block").click(); });
  await settle();
  expect(editor()!.textContent).toContain("Drawing Block 1");
  for (const [x, y] of [[0, 0], [10, 0], [10, 10], [0, 10]]) await clickAt(x, y);
  await clickAt(0.2, 0.1);                    // within 10 pixels of the first point: closes the outline
  return service.savedContextBlocks.at(-1)!;
}
/** A project with no maximum volume yet, on mesh files. */
function newProject() {
  const detail = project(NOTHING_RUN);
  return { ...detail, inputs: { ...detail.inputs, max_volume: [] }, joined_bounds: null };
}

test("Draw block in the Context box draws a block in a project whose maximum volume comes from files; it is saved 10 m high and its height field takes the focus", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  const saved = await drawSquare(service);
  expect(saved).toEqual([{ name: "Block 1", points: [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], height: 10 }]);
  expect(rows().map((row) => row.querySelector<HTMLInputElement>(".context-block-name")!.value)).toEqual(["Block 1"]);
  expect(document.activeElement).toBe(rows()[0].querySelector(".context-block-height"));
  expect(service.count("GET /context-blocks/mesh")).toBeGreaterThan(0);
});

test("a block drawn before any maximum volume exists is saved and drawn", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, newProject());
  expect(await drawSquare(service)).toHaveLength(1);
  expect(FakeViewerScene.latest!.layersWithObjects()).toContain("context");
});

test("a block's height typed in its row is saved; Edit reopens its outline and a vertex elevation typed there is saved", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  await typeAndEnter(rows()[0].querySelector<HTMLInputElement>(".context-block-height")!, "18");
  expect(service.savedContextBlocks.at(-1)![0].height).toBe(18);
  act(() => { buttonIn(rows()[0], "Edit").click(); });
  await settle();
  expect(editor()!.textContent).toContain("Editing Block 1");
  const handle = container().querySelector('[aria-label="Vertex 2"]')!;
  act(() => {
    handle.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, clientX: 0, clientY: 0 }));
    handle.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, clientX: 0, clientY: 0 }));
  });
  await settle();
  await typeAndEnter(container().querySelector<HTMLInputElement>('[aria-label="Vertex 2: Elevation"]')!, "2");
  expect(service.savedContextBlocks.at(-1)![0].points[1]).toEqual([110, 100, 2]);
});

test("Remove takes a block out; a refused change shows its reason and keeps the block as it was", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  service.contextBlocksRefusal = "Block 1: the outline crosses itself.";
  await typeAndEnter(rows()[0].querySelector<HTMLInputElement>(".context-block-height")!, "20");
  expect(panel().textContent).toContain("Block 1: the outline crosses itself.");
  expect(rows()[0].querySelector<HTMLInputElement>(".context-block-height")!.value).toBe("12");
  service.contextBlocksRefusal = null;
  act(() => { buttonIn(rows()[0], "Remove").click(); });
  await settle();
  expect(service.savedContextBlocks.at(-1)).toEqual([]);
  expect(rows()).toHaveLength(0);
});

test("renaming a block to another block's name shows the service's refusal and keeps the old name", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }, { ...BLOCK, name: "Block 2", points: BLOCK.points.map(([x, y, z]) => [x + 50, y, z]), holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  service.contextBlocksRefusal = "Two blocks are named block 1.";
  await typeAndEnter(rows()[1].querySelector<HTMLInputElement>(".context-block-name")!, "block 1");
  expect(panel().textContent).toContain("Two blocks are named block 1.");
  expect(rows()[1].querySelector<HTMLInputElement>(".context-block-name")!.value).toBe("Block 2");
});

test("drawing a block snaps to a site's vertex", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [{ name: "Site 1", points: [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 10, 0]], height: 30 }];
  await openWorkspace(service, newProject());
  act(() => { buttonIn(panel(), "Draw block").click(); });
  await settle();
  for (const [x, y] of [[20.3, 0.2], [30, 0], [30, 10]]) await clickAt(x, y);
  await key("Enter");
  expect(service.savedContextBlocks.at(-1)![0].points[0]).toEqual([20, 0, 0]);
});

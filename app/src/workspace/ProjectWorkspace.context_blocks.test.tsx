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
const heightOf = (row: Element) => row.querySelector<HTMLInputElement>(".site-row-height")!;
const nameOf = (row: Element) => row.querySelector<HTMLElement>(".site-row-name")!.textContent;
/** The items of a row's menu, opened first when it is closed. */
function menuOf(row: Element) {
  const button = row.querySelector<HTMLButtonElement>(".action-menu-button")!;
  if (button.getAttribute("aria-expanded") !== "true") act(() => { button.click(); });
  return [...row.querySelectorAll<HTMLButtonElement>("[role='menuitem']")];
}
async function choose(row: Element, label: string) {
  const item = menuOf(row).find((candidate) => candidate.textContent === label)!;
  await act(async () => { item.click(); });
  await settle();
}
/** Renames a row's block: a double click on its name, the name typed and Enter. */
async function rename(row: Element, name: string) {
  act(() => { row.querySelector(".site-row-name")!.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); });
  await typeAndEnter(row.querySelector<HTMLInputElement>(".site-row-name input")!, name);
}
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
  expect(rows().map(nameOf)).toEqual(["Block 1"]);
  expect(document.activeElement).toBe(heightOf(rows()[0]));
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
  await typeAndEnter(heightOf(rows()[0]), "18");
  expect(service.savedContextBlocks.at(-1)![0].height).toBe(18);
  await choose(rows()[0], "Edit");
  expect(editor()!.textContent).toContain("Editing Block 1");
  expect(rows()[0].classList).toContain("site-row-editing");
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
  await typeAndEnter(heightOf(rows()[0]), "20");
  expect(panel().textContent).toContain("Block 1: the outline crosses itself.");
  expect(heightOf(rows()[0]).value).toBe("12");
  service.contextBlocksRefusal = null;
  await choose(rows()[0], "Remove");
  expect(service.savedContextBlocks.at(-1)).toEqual([]);
  expect(rows()).toHaveLength(0);
});

test("renaming a block to another block's name shows the service's refusal and keeps the old name", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }, { ...BLOCK, name: "Block 2", points: BLOCK.points.map(([x, y, z]) => [x + 50, y, z]), holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  service.contextBlocksRefusal = "Two blocks are named block 1.";
  await rename(rows()[1], "block 1");
  expect(panel().textContent).toContain("Two blocks are named block 1.");
  expect(nameOf(rows()[1])).toBe("Block 2");
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

test("a block removed by mistake comes back with Undo under the rows, without the editor open", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  await choose(rows()[0], "Remove");
  expect(editor()).toBeNull();
  act(() => { buttonIn(panel().querySelector(".context-blocks")!, "Undo").click(); });
  await settle();
  expect(service.savedContextBlocks.at(-1)).toEqual([{ ...BLOCK, holes: [] }]);
  expect(rows()).toHaveLength(1);
});

// --- The rows' menu, picking a block in the view, and the lists scrolling to the row edited

test("a block's row has a name renamed by a double click, a height column and a menu of Edit, Draw hole and Remove; Place on terrain only with a terrain", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  expect(rows()[0].classList).toContain("site-row");
  expect(rows()[0].querySelector(".action-menu-button")!.getAttribute("aria-label")).toBe("Actions for Block 1");
  expect(menuOf(rows()[0]).map((item) => item.textContent)).toEqual(["Edit", "Draw hole", "Remove"]);
  expect(rows()[0].querySelector(".link-button")).toBeNull();     // no loose links any more
  await rename(rows()[0], "Kiosk");
  expect(service.savedContextBlocks.at(-1)![0].name).toBe("Kiosk");
  expect(nameOf(rows()[0])).toBe("Kiosk");
});

test("with a terrain file a block's menu offers Place on terrain", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }];
  const opened = project(NOTHING_RUN);
  await openWorkspace(service, { ...opened, inputs: { ...opened.inputs, terrain: [{ name: "ground.obj", triangle_count: 1 }] } });
  expect(menuOf(rows()[0]).map((item) => item.textContent)).toEqual(["Edit", "Draw hole", "Place on terrain", "Remove"]);
});

test("Draw hole in a block's menu draws a hole of that block", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.contextBlocks = [{ ...BLOCK, holes: [] }];
  await openWorkspace(service, project(NOTHING_RUN));
  await choose(rows()[0], "Draw hole");
  expect(rows()[0].classList).toContain("site-row-editing");
  for (const [x, y] of [[102, 102], [108, 102], [108, 108]]) await clickAt(x, y);
  await clickAt(102, 102);
  expect(service.savedContextBlocks.at(-1)![0].holes).toEqual([[[102, 102, 0], [108, 102, 0], [108, 108, 0]]]);
});

test("a click inside a block in the view edits it, in a project whose maximum volume comes from files; its row scrolls into view", async () => {
  const scrolled: Element[] = [];
  const scrollIntoView = vi.fn(function (this: Element) { scrolled.push(this); });
  Element.prototype.scrollIntoView = scrollIntoView;
  try {
    const service = new FakeService(NOTHING_RUN, null);
    service.contextBlocks = [{ ...BLOCK, holes: [] }, { ...BLOCK, name: "Block 2", points: BLOCK.points.map(([x, y, z]) => [x + 50, y, z]), holes: [] }];
    await openWorkspace(service, project(NOTHING_RUN));
    expect(editor()).toBeNull();
    await clickAt(155, 105);
    expect(editor()!.textContent).toContain("Editing Block 2");
    expect(rows()[1].classList).toContain("site-row-editing");
    expect(scrolled).toContain(rows()[1]);
    await key("Escape");
    expect(editor()).toBeNull();
    await clickAt(50, 50);                        // in no block: nothing opens
    expect(editor()).toBeNull();
  } finally {
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  }
});

test("a click inside both a site and a block edits the smaller of the two", async () => {
  const service = new FakeService(NOTHING_RUN, null);
  service.siteSource = "sites";
  service.sites = [
    { name: "Large plot", points: [[0, 0, 0], [200, 0, 0], [200, 200, 0], [0, 200, 0]], height: 30 },
    { name: "Small plot", points: [[300, 0, 0], [304, 0, 0], [304, 4, 0], [300, 4, 0]], height: 30 },
  ];
  service.contextBlocks = [{ ...BLOCK, holes: [] }, { ...BLOCK, name: "Large block", points: [[290, -10, 0], [320, -10, 0], [320, 20, 0], [290, 20, 0]], holes: [] }];
  await openWorkspace(service, newProject());
  await clickAt(105, 105);                        // the block inside the large site
  expect(editor()!.textContent).toContain("Editing Block 1");
  await key("Escape");
  await clickAt(50, 50);                          // the large site only
  expect(editor()!.textContent).toContain("Editing Large plot");
  await key("Escape");
  await clickAt(302, 2);                          // the small site inside the large block
  expect(editor()!.textContent).toContain("Editing Small plot");
  await key("Escape");
  await clickAt(315, 15);                         // the large block only
  expect(editor()!.textContent).toContain("Editing Large block");
});

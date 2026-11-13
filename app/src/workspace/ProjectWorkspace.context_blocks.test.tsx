// Drawn context blocks in the workspace (design/context-blocks.md): read from the service, drawn in the Context layer with the
// context files, drawn and edited in the Site step with the site editor, saved whole.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { FakeService, NOTHING_RUN, endWorkspaceTest, openWorkspace, project, startWorkspaceTest } from "./project_workspace_for_test";

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

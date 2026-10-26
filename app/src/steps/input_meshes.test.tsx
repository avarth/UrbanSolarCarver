import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { joinedGeometryOf, useInputGeometry, type InputGeometry } from "./input_meshes";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.unstubAllGlobals();
});

const TRIANGLE_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";
const TRUNCATED_ASCII_PLY = ["ply", "format ascii 1.0", "element vertex 3", "property float x", "property float y", "property float z",
                             "element face 1", "property list uchar uint vertex_indices", "end_header", "0 0 0", ""].join("\n");

function InputGeometryProbe({ files, onServiceProblem }: { files: InputFileInfo[]; onServiceProblem: (error: unknown) => void }) {
  const { geometry, drawingProblems } = useInputGeometry("t", "p", "test_surfaces", files, [0, 0, 0], 0, () => {}, onServiceProblem);
  return (
    <div data-vertex-count={geometry === null ? "none" : geometry.getAttribute("position").count}>
      {drawingProblems.map((problem) => <p key={problem}>{problem}</p>)}
    </div>
  );
}

async function settle() {
  for (let round = 0; round < 5; round++) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

test("a file the service accepted that the view cannot parse is named with the reason, and the other files are still drawn", async () => {
  vi.stubGlobal("fetch", vi.fn(async (address: string) => new Response(address.includes("broken.ply") ? TRUNCATED_ASCII_PLY : TRIANGLE_OBJ)));
  const onServiceProblem = vi.fn();
  const files = [{ name: "broken.ply", triangle_count: 1 }, { name: "good.obj", triangle_count: 1 }];
  rendered = renderForTest(<InputGeometryProbe files={files} onServiceProblem={onServiceProblem} />);
  await settle();
  const probe = rendered.container.firstElementChild!;
  expect([...probe.querySelectorAll("p")].map((paragraph) => paragraph.textContent))
    .toEqual([messages.fileProblem("broken.ply", messages.meshCannotBeDrawn)]);
  expect(probe.getAttribute("data-vertex-count")).toBe("3");
  expect(onServiceProblem).not.toHaveBeenCalled();
});

test("a request that never got a reply is a service problem for the app to check, not a file problem", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  const onServiceProblem = vi.fn();
  rendered = renderForTest(<InputGeometryProbe files={[{ name: "good.obj", triangle_count: 1 }]} onServiceProblem={onServiceProblem} />);
  await settle();
  expect(onServiceProblem).toHaveBeenCalledOnce();
  expect(rendered.container.querySelector("p")).toBeNull();
  expect(rendered.container.firstElementChild!.getAttribute("data-vertex-count")).toBe("none");
});

const TWO_TRIANGLES_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nf 1 2 3\nf 2 4 3\n";

test("each file's mesh is kept by name, and any of them can be joined again", async () => {
  vi.stubGlobal("fetch", vi.fn(async (address: string) => new Response(address.includes("pair.obj") ? TWO_TRIANGLES_OBJ : TRIANGLE_OBJ)));
  let loaded: InputGeometry | null = null;
  function Probe() {
    loaded = useInputGeometry("t", "p", "test_surfaces", [{ name: "single.obj", triangle_count: 1 }, { name: "pair.obj", triangle_count: 2 }], [0, 0, 0], 0, () => {}, () => {});
    return null;
  }
  rendered = renderForTest(<Probe />);
  await settle();
  expect(Object.keys(loaded!.byFile).sort()).toEqual(["pair.obj", "single.obj"]);
  expect(loaded!.geometry!.getAttribute("position").count).toBe(9);              // all three triangles, as before
  const vertexCount = (names: string[]) => joinedGeometryOf(loaded!.byFile, names)?.getAttribute("position").count;
  expect(vertexCount(["pair.obj"])).toBe(6);
  expect(vertexCount(["single.obj", "pair.obj", "not-there.obj"])).toBe(9);      // a name without a mesh is left out
  expect(joinedGeometryOf(loaded!.byFile, ["not-there.obj"])).toBeNull();
  expect(joinedGeometryOf(loaded!.byFile, [])).toBeNull();
});

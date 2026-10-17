import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { useInputGeometry } from "./input_meshes";

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

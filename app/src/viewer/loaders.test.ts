import { afterEach, expect, test, vi } from "vitest";
import { loadMesh } from "./loaders";

afterEach(() => {
  vi.unstubAllGlobals();
});

function answerWith(body: BodyInit) {
  const fetchStub = vi.fn(async (_address: string, _options?: RequestInit) => new Response(body));
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

const ORIGIN: [number, number, number] = [500000.25, 4200000.5, 10];

function firstVertex(positions: ArrayLike<number>): number[] {
  return [positions[0], positions[1], positions[2]];
}

test("a mesh is fetched with the token header", async () => {
  const fetchStub = answerWith("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
  await loadMesh("/api/projects/p/run/files/envelope.obj", "secret", "obj");
  const [address, options] = fetchStub.mock.calls[0];
  expect(address).toBe("/api/projects/p/run/files/envelope.obj");
  expect(new Headers(options!.headers).get("X-USC-Token")).toBe("secret");
});

test("OBJ coordinates are shifted to the local origin before they become float32", async () => {
  answerWith("v 500012.345 4200007.891 12.5\nv 500013.345 4200007.891 12.5\nv 500012.345 4200008.891 12.5\nf 1 2 3\n");
  const geometry = await loadMesh("/m.obj", "t", "obj", ORIGIN);
  const [x, y, z] = firstVertex(geometry.getAttribute("position").array);
  expect(x).toBeCloseTo(12.095, 3); expect(y).toBeCloseTo(7.391, 3); expect(z).toBeCloseTo(2.5, 3);
});

test("ASCII PLY coordinates are shifted before they become float32, whatever the other vertex properties", async () => {
  const ply = ["ply", "format ascii 1.0", "comment exported", "element vertex 3", "property float nx", "property float x", "property float y",
               "property float z", "property uchar red", "element face 1", "property list uchar uint vertex_indices", "end_header",
               "0 500012.345 4200007.891 12.5 250", "0 500013.345 4200007.891 12.5 250", "0 500012.345 4200008.891 12.5 250", "3 0 1 2", ""].join("\n");
  answerWith(ply);
  const geometry = await loadMesh("/m.ply", "t", "ply", ORIGIN);
  const [x, y, z] = firstVertex(geometry.getAttribute("position").array);
  expect(x).toBeCloseTo(12.095, 3); expect(y).toBeCloseTo(7.391, 3); expect(z).toBeCloseTo(2.5, 3);
});

test("ASCII STL coordinates are shifted before they become float32", async () => {
  const stl = ["solid s", "facet normal 0 0 1", "outer loop", "vertex 500012.345 4200007.891 12.5", "vertex 500013.345 4200007.891 12.5",
               "vertex 500012.345 4200008.891 12.5", "endloop", "endfacet", "endsolid s", ""].join("\n");
  answerWith(stl);
  const geometry = await loadMesh("/m.stl", "t", "stl", ORIGIN);
  const [x, y] = firstVertex(geometry.getAttribute("position").array);
  expect(x).toBeCloseTo(12.095, 3); expect(y).toBeCloseTo(7.391, 3);
});

test("a binary mesh is shifted after parsing", async () => {
  const triangleCount = 1;
  const buffer = new ArrayBuffer(84 + 50 * triangleCount);
  const view = new DataView(buffer);
  view.setUint32(80, triangleCount, true);
  const corners = [[110, 20, 30], [111, 20, 30], [110, 21, 30]];
  corners.forEach((corner, cornerIndex) => corner.forEach((value, axis) => view.setFloat32(84 + 12 + cornerIndex * 12 + axis * 4, value, true)));
  answerWith(buffer);
  const geometry = await loadMesh("/m.stl", "t", "stl", [100, 20, 25]);
  expect(firstVertex(geometry.getAttribute("position").array)).toEqual([10, 0, 5]);
});

test("an empty OBJ gives an empty geometry", async () => {
  answerWith("");
  const geometry = await loadMesh("/plates.obj", "t", "obj");
  expect(geometry.getAttribute("position").count).toBe(0);
  expect(geometry.userData.partNames).toEqual([]);
});

test("the parts of an OBJ stay apart as groups with their names", async () => {
  answerWith(["o floor_0_plate_0", "v 0 0 0", "v 1 0 0", "v 0 1 0", "f 1 2 3",
              "o floor_1_plate_0", "v 0 0 3", "v 1 0 3", "v 0 1 3", "f 4 5 6", ""].join("\n"));
  const geometry = await loadMesh("/plates.obj", "t", "obj");
  expect(geometry.groups).toHaveLength(2);
  expect(geometry.userData.partNames).toEqual(["floor_0_plate_0", "floor_1_plate_0"]);
});

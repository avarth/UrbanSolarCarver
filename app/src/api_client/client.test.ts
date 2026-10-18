import { afterEach, expect, test, vi } from "vitest";
import {
  ApiError, addInput, chooseProjectsFolder, deleteProject, getHealth, getProjectsFolder, getScorePoints, openProjectFolder, projectDownloadUrl, putConfig,
  readTokenFromLaunchUrl, renameProject, resetProjectToExample, runFileUrl, serviceProblemOf, startRun,
} from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

function answerWith(body: BodyInit | null, status = 200) {
  const fetchStub = vi.fn(async (_address: string, _options?: RequestInit) => new Response(body, { status }));
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

test("readTokenFromLaunchUrl takes the token and clears it from the address", () => {
  window.history.replaceState(null, "", "/?token=abc");
  expect(readTokenFromLaunchUrl()).toBe("abc");
  expect(window.location.search).toBe("");
});

test("readTokenFromLaunchUrl keeps the other parameters and gives an empty token when there is none", () => {
  window.history.replaceState(null, "", "/?token=abc&view=dark");
  readTokenFromLaunchUrl();
  expect(window.location.search).toBe("?view=dark");
  window.sessionStorage.clear();
  expect(readTokenFromLaunchUrl()).toBe("");
});

test("the token survives a reload: it is kept for the tab and read back when the address has none", () => {
  window.history.replaceState(null, "", "/?token=abc");
  readTokenFromLaunchUrl();
  window.history.replaceState(null, "", "/");
  expect(readTokenFromLaunchUrl()).toBe("abc");
});

test("a token in the address replaces the one kept for the tab", () => {
  window.history.replaceState(null, "", "/?token=old");
  readTokenFromLaunchUrl();
  window.history.replaceState(null, "", "/?token=new");
  readTokenFromLaunchUrl();
  window.history.replaceState(null, "", "/");
  expect(readTokenFromLaunchUrl()).toBe("new");
});

test("the token is still read when session storage cannot be used", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  window.history.replaceState(null, "", "/?token=abc");
  expect(readTokenFromLaunchUrl()).toBe("abc");
  window.history.replaceState(null, "", "/");
  expect(readTokenFromLaunchUrl()).toBe("");
  vi.restoreAllMocks();
});

test("a 401 means the page lost its access, a failed connection means the engine stopped", () => {
  expect(serviceProblemOf(new ApiError(401, { detail: "The access token is missing or wrong." }))).toBe("access_lost");
  expect(serviceProblemOf(new TypeError("Failed to fetch"))).toBe("engine_stopped");
  expect(serviceProblemOf(new ApiError(500, "oops"))).toBe("other");
});

test("a request carries the token in X-USC-Token", async () => {
  const fetchStub = answerWith(JSON.stringify({ version: "1.0", warm_up: { state: "ready" } }));
  expect(await getHealth("secret")).toEqual({ version: "1.0", warm_up: { state: "ready" } });
  const [address, options] = fetchStub.mock.calls[0];
  expect(address).toBe("/api/health");
  expect(new Headers(options!.headers).get("X-USC-Token")).toBe("secret");
});

test("a JSON body is sent with its content type", async () => {
  const fetchStub = answerWith(JSON.stringify({ settings: {}, grid_plan: null }));
  await putConfig("secret", "my project", { voxel_size: 1 });
  const [address, options] = fetchStub.mock.calls[0];
  expect(address).toBe("/api/projects/my%20project/config");
  expect(options!.method).toBe("PUT");
  expect(new Headers(options!.headers).get("Content-Type")).toBe("application/json");
  expect(JSON.parse(options!.body as string)).toEqual({ values: { voxel_size: 1 } });
});

test("a run starts with the stages asked for, or with the service's default", async () => {
  const fetchStub = answerWith(JSON.stringify({ status: "started", run_id: "r1", stages: [] }));
  await startRun("secret", "demo", ["thresholding"]);
  await startRun("secret", "demo");
  const bodies = fetchStub.mock.calls.map((call) => JSON.parse(call[1]!.body as string));
  expect(bodies).toEqual([{ produce: ["thresholding"] }, {}]);
});

test("a file goes up as multipart form data in the field named file", async () => {
  const fetchStub = answerWith(JSON.stringify({ role: "max_volume", files: [] }));
  await addInput("secret", "demo", "max_volume", new File(["o"], "block.obj"));
  const [address, options] = fetchStub.mock.calls[0];
  expect(address).toBe("/api/projects/demo/inputs/max_volume");
  const form = options!.body as FormData;
  expect((form.get("file") as File).name).toBe("block.obj");
  expect(new Headers(options!.headers).has("Content-Type")).toBe(false);   // the browser adds the boundary
});

test("a reply that is not 2xx throws an ApiError with the status and the body", async () => {
  answerWith(JSON.stringify({ detail: "There is no project 'x'." }), 404);
  const error = await getHealth("secret").catch((caught) => caught);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.status).toBe(404);
  expect(error.body).toEqual({ detail: "There is no project 'x'." });
});

test("an error reply that is not JSON keeps its text as the body", async () => {
  answerWith("Bad gateway", 502);
  const error = await getHealth("secret").catch((caught) => caught);
  expect(error.body).toBe("Bad gateway");
});

test("score points arrive as bytes", async () => {
  answerWith(new Uint8Array([1, 2, 3, 4]));
  expect(new Uint8Array(await getScorePoints("secret", "demo"))).toEqual(new Uint8Array([1, 2, 3, 4]));
});

test("file and download addresses encode each part of the path", () => {
  expect(runFileUrl("my project", "exporting/mesh 1.obj")).toBe("/api/projects/my%20project/run/files/exporting/mesh%201.obj");
  expect(projectDownloadUrl("my project")).toBe("/api/projects/my%20project/download");
});

test("the projects folder and the project management requests go to their routes", async () => {
  const fetchStub = vi.fn(async (_address: string, options?: RequestInit) =>
    options?.method === "DELETE" || _address.endsWith("/open-folder") ? new Response(null, { status: 204 }) : new Response("{}"));
  vi.stubGlobal("fetch", fetchStub);
  await getProjectsFolder("secret");
  await chooseProjectsFolder("secret");
  await renameProject("secret", "Plot 7", "Plot 8");
  await deleteProject("secret", "Plot 7", "Plot 7");
  await resetProjectToExample("secret", "Plot 7");
  await openProjectFolder("secret", "Plot 7");
  expect(fetchStub.mock.calls.map(([address, options]) => `${options?.method ?? "GET"} ${address}`)).toEqual([
    "GET /api/projects-folder",
    "POST /api/projects-folder/choose",
    "POST /api/projects/Plot%207/rename",
    "DELETE /api/projects/Plot%207?confirm_name=Plot%207",
    "POST /api/projects/Plot%207/reset-to-example",
    "POST /api/projects/Plot%207/open-folder",
  ]);
  expect(JSON.parse(fetchStub.mock.calls[2][1]!.body as string)).toEqual({ new_name: "Plot 8" });
});

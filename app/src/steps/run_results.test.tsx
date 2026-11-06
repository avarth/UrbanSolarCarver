import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "../api_client/client";
import { inProjectSession } from "../api_client/project_session_for_test";
import { MeshNotReadableError } from "../viewer/loaders";
import { renderForTest, settle } from "../viewer_overlays/render_for_test";
import { useRunResults, type RunResults } from "./run_results";

const mocks = vi.hoisted(() => ({ getRunSummary: vi.fn(), getScorePoints: vi.fn(), getSkyPatches: vi.fn(), loadMesh: vi.fn() }));

vi.mock("../api_client/client", async (original) => ({
  ...(await original<typeof import("../api_client/client")>()),
  getRunSummary: mocks.getRunSummary, getScorePoints: mocks.getScorePoints, getSkyPatches: mocks.getSkyPatches,
}));
vi.mock("../viewer/loaders", async (original) => ({ ...(await original<typeof import("../viewer/loaders")>()), loadMesh: mocks.loadMesh }));
vi.mock("../viewer/score_points_decoder", () => ({ decodeScorePoints: (blob: unknown) => blob }));

/** A reply the test hands out when it chooses, in any order. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((onResolved, onRejected) => { resolve = onResolved; reject = onRejected; });
  return { promise, resolve, reject };
}

let latest: { results: RunResults; reload: (stages: readonly string[]) => Promise<void> };

function Probe() {
  const [results, reload] = useRunResults({ origin: [0, 0, 0], stagesWithResults: [] });
  latest = { results, reload };
  return null;
}


beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.getRunSummary.mockResolvedValue({ envelope: { mesh_file: "export.ply" } });
});
afterEach(() => { vi.restoreAllMocks(); });

test("the last request wins: a reply that comes after a newer one is dropped", async () => {
  const first = deferred<unknown>();
  const second = deferred<unknown>();
  mocks.getScorePoints.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  renderForTest(inProjectSession(<Probe />));
  await settle();
  act(() => { void latest.reload(["thresholding"]); });
  act(() => { void latest.reload(["thresholding"]); });
  second.resolve("newer");
  await settle();
  first.resolve("older");
  await settle();
  expect(latest.results.scorePoints).toBe("newer");
});

test("an older failure does not mark a newer result unreadable", async () => {
  const first = deferred<unknown>();
  const second = deferred<unknown>();
  mocks.getScorePoints.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  renderForTest(inProjectSession(<Probe />));
  await settle();
  act(() => { void latest.reload(["thresholding"]); });
  act(() => { void latest.reload(["thresholding"]); });
  second.resolve("newer");
  await settle();
  first.reject(new ApiError(500, null));
  await settle();
  expect(latest.results.scorePoints).toBe("newer");
  expect(latest.results.unreadable).toEqual([]);
});

test("a result the stage has not written stays null and is not unreadable", async () => {
  mocks.getScorePoints.mockRejectedValue(new ApiError(404, null));
  renderForTest(inProjectSession(<Probe />));
  await settle();
  await act(async () => { await latest.reload(["thresholding"]); });
  expect(latest.results.scorePoints).toBeNull();
  expect(latest.results.unreadable).toEqual([]);
});

test.each([
  ["a refused request", new ApiError(500, null)],
  ["a mesh the view cannot read", new MeshNotReadableError("not a mesh")],
])("%s marks the result unreadable, and a later reply clears it", async (_case, error) => {
  mocks.loadMesh.mockRejectedValueOnce(error).mockResolvedValueOnce("mesh");
  renderForTest(inProjectSession(<Probe />));
  await settle();
  await act(async () => { await latest.reload(["exporting"]); });
  expect(latest.results.envelope).toBeNull();
  expect(latest.results.unreadable).toEqual(["envelope"]);
  await act(async () => { await latest.reload(["exporting"]); });
  expect(latest.results.envelope).toBe("mesh");
  expect(latest.results.unreadable).toEqual([]);
});

test.each([
  ["access lost", new ApiError(401, null)],
  ["a request that got no reply", new TypeError("Failed to fetch")],
])("%s goes to the app and does not mark the result unreadable", async (_case, error) => {
  mocks.loadMesh.mockRejectedValue(error);
  renderForTest(inProjectSession(<Probe />));
  await settle();
  await act(async () => { await latest.reload(["exporting"]); });
  expect(latest.results.unreadable).toEqual([]);
});

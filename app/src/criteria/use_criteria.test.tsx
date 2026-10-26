import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, type CriterionEntry, type ProjectDetail } from "../api_client/client";
import { renderForTest } from "../viewer_overlays/render_for_test";
import { useCriteria, type CriteriaHook } from "./use_criteria";

function entry(id: string, overrides: Partial<CriterionEntry> = {}): CriterionEntry {
  return { id, name: `Criterion ${id}`, named_by_user: false, colour: "#336699", bypassed: false, test_surface_files: [], settings: {}, ...overrides };
}

function projectWith(criteria: CriterionEntry[] | undefined): ProjectDetail {
  return { name: "p", criteria } as unknown as ProjectDetail;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/** Renders the hook against a fetch that answers with *reply* and records "METHOD address" of each request. */
function renderedHook(project: ProjectDetail, reply: (method: string, address: string, body: unknown) => Response) {
  const requests: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (address: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    requests.push(`${method} ${address}`);
    return reply(method, address, typeof options?.body === "string" ? JSON.parse(options.body) : options?.body);
  }));
  let latest: CriteriaHook | null = null;
  function Probe() {
    latest = useCriteria("token", project);
    return null;
  }
  const rendered = renderForTest(createElement(Probe));
  return { hook: () => latest!, requests, unmount: rendered.unmount };
}

afterEach(() => vi.unstubAllGlobals());

test("the criteria start from the project and the first one is selected", () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1"), entry("2")]), () => json({}));
  expect(hook().criteria.map((criterion) => criterion.id)).toEqual(["1", "2"]);
  expect(hook().selectedId).toBe("1");
  unmount();
});

test("a project that lists no criteria has none and nothing selected", () => {
  const { hook, unmount } = renderedHook(projectWith(undefined), () => json({}));
  expect(hook().criteria).toEqual([]);
  expect(hook().selectedId).toBe("");
  unmount();
});

test("select changes the selected card", () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1"), entry("2")]), () => json({}));
  act(() => hook().select("2"));
  expect(hook().selectedId).toBe("2");
  unmount();
});

test("add puts the new criterion last and selects it", async () => {
  const { hook, requests, unmount } = renderedHook(projectWith([entry("1")]), (_method, _address, body) => json(entry("2", { name: String((body as { mode: string }).mode) })));
  await act(async () => { await hook().add("daylight"); });
  expect(requests).toEqual(["POST /api/projects/p/criteria"]);
  expect(hook().criteria.map((criterion) => `${criterion.id}:${criterion.name}`)).toEqual(["1:Criterion 1", "2:daylight"]);
  expect(hook().selectedId).toBe("2");
  unmount();
});

test("rename and bypass replace the entry the service returns, by id", async () => {
  const { hook, requests, unmount } = renderedHook(projectWith([entry("1"), entry("2")]), (_method, _address, body) => {
    const sent = body as { name?: string; bypassed?: boolean };
    return json(entry("2", { name: sent.name ?? "Roofs", named_by_user: sent.name !== undefined, bypassed: sent.bypassed ?? false }));
  });
  await act(async () => { await hook().rename("2", "Roofs"); });
  expect(hook().criteria.map((criterion) => criterion.name)).toEqual(["Criterion 1", "Roofs"]);
  await act(async () => { await hook().setBypassed("2", true); });
  expect(hook().criteria[1].bypassed).toBe(true);
  expect(requests).toEqual(["PATCH /api/projects/p/criteria/2", "PATCH /api/projects/p/criteria/2"]);
  unmount();
});

test("duplicate adds the copy the service returns and selects it", async () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1")]), () => json(entry("2", { name: "Criterion 1 copy" })));
  await act(async () => { await hook().duplicate("1"); });
  expect(hook().criteria.map((criterion) => criterion.id)).toEqual(["1", "2"]);
  expect(hook().selectedId).toBe("2");
  unmount();
});

test("reorder takes the list the service returns", async () => {
  const { hook, requests, unmount } = renderedHook(projectWith([entry("1"), entry("2"), entry("3")]), () => json([entry("3"), entry("1"), entry("2")]));
  await act(async () => { await hook().reorder(["3", "1", "2"]); });
  expect(requests).toEqual(["PUT /api/projects/p/criteria/order"]);
  expect(hook().criteria.map((criterion) => criterion.id)).toEqual(["3", "1", "2"]);
  unmount();
});

test("removing the selected criterion selects the next card, else the previous one", async () => {
  const { hook, requests, unmount } = renderedHook(projectWith([entry("1"), entry("2"), entry("3")]), () => new Response(null, { status: 204 }));
  act(() => hook().select("2"));
  await act(async () => { await hook().remove("2"); });
  expect(requests).toEqual(["DELETE /api/projects/p/criteria/2"]);
  expect(hook().criteria.map((criterion) => criterion.id)).toEqual(["1", "3"]);
  expect(hook().selectedId).toBe("3");
  await act(async () => { await hook().remove("3"); });
  expect(hook().selectedId).toBe("1");
  unmount();
});

test("the criterion left after a remove keeps its switch: one that is off stays off", async () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1", { bypassed: true }), entry("2")]), () => new Response(null, { status: 204 }));
  await act(async () => { await hook().remove("2"); });
  expect(hook().criteria.map((criterion) => [criterion.id, criterion.bypassed])).toEqual([["1", true]]);
  unmount();
});

test("removing another criterion keeps the selection", async () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1"), entry("2")]), () => new Response(null, { status: 204 }));
  await act(async () => { await hook().remove("2"); });
  expect(hook().selectedId).toBe("1");
  unmount();
});

test("test surfaces go up one by one, each reply replacing the entry, and a stored file is reused or removed", async () => {
  let uploaded = 0;
  const { hook, requests, unmount } = renderedHook(projectWith([entry("1")]), (method) => {
    if (method === "POST") {
      uploaded += 1;
      return json(entry("1", { test_surface_files: Array.from({ length: uploaded }, (_, index) => `f${index + 1}.obj`) }));
    }
    return json(entry("1", { test_surface_files: method === "PUT" ? ["a.obj"] : [] }));
  });
  await act(async () => { await hook().addTestSurfaces("1", [new File(["o"], "f1.obj"), new File(["o"], "f2.obj")]); });
  expect(hook().criteria[0].test_surface_files).toEqual(["f1.obj", "f2.obj"]);
  await act(async () => { await hook().reuseFile("1", "a.obj"); });
  expect(hook().criteria[0].test_surface_files).toEqual(["a.obj"]);
  await act(async () => { await hook().removeFile("1", "a.obj"); });
  expect(hook().criteria[0].test_surface_files).toEqual([]);
  expect(requests).toEqual([
    "POST /api/projects/p/criteria/1/test-surfaces",
    "POST /api/projects/p/criteria/1/test-surfaces",
    "PUT /api/projects/p/criteria/1/test-surfaces/a.obj",
    "DELETE /api/projects/p/criteria/1/test-surfaces/a.obj",
  ]);
  unmount();
});

test("applyReply replaces the entry that has the reply's id", () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1"), entry("2")]), () => json({}));
  act(() => hook().applyReply(entry("1", { name: "Renamed" })));
  expect(hook().criteria.map((criterion) => criterion.name)).toEqual(["Renamed", "Criterion 2"]);
  unmount();
});

test("calls that overlap keep each other's changes: a rename lands while an upload is under way, and two adds in a row", async () => {
  let finishUpload: (reply: Response) => void = () => {};
  const { hook, unmount } = renderedHook(projectWith([entry("1"), entry("2")]), (method, address, body) => {
    if (method === "POST" && address.endsWith("/test-surfaces")) return new Promise<Response>((resolve) => { finishUpload = resolve; }) as unknown as Response;
    if (method === "PATCH") return json(entry("2", { name: (body as { name: string }).name }));
    return json(entry(`new${(body as { mode: string }).mode}`));
  });
  let upload: Promise<void> = Promise.resolve();
  act(() => { upload = hook().addTestSurfaces("1", [new File(["o"], "f1.obj")]); });
  await act(async () => { await hook().rename("2", "Roofs"); });
  await act(async () => { finishUpload(json(entry("1", { test_surface_files: ["f1.obj"] }))); await upload; });
  expect(hook().criteria.map((criterion) => `${criterion.id}:${criterion.name}:${criterion.test_surface_files?.length}`)).toEqual(["1:Criterion 1:1", "2:Roofs:0"]);
  await act(async () => { await Promise.all([hook().add("a"), hook().add("b")]); });
  expect(hook().criteria.map((criterion) => criterion.id)).toEqual(["1", "2", "newa", "newb"]);
  unmount();
});

test("a refused call rejects with the ApiError and leaves the list as it was", async () => {
  const { hook, unmount } = renderedHook(projectWith([entry("1")]), () => json({ detail: "A run of this project is active." }, 409));
  let failure: unknown = null;
  await act(async () => { failure = await hook().rename("1", "x").catch((error: unknown) => error); });
  expect(failure).toBeInstanceOf(ApiError);
  expect((failure as ApiError).status).toBe(409);
  expect(hook().criteria[0].name).toBe("Criterion 1");
  unmount();
});

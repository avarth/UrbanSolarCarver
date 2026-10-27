import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { StudyEntry, StudyWithState } from "../api_client/client";
import { renderForTest } from "../viewer_overlays/render_for_test";
import { useStudies, type StudiesHook } from "./use_studies";

function study(id: string): StudyWithState {
  const entry: StudyEntry = { id, name: `Study ${id}`, named_by_user: false, colour: "#336699", metric: "sky_view", settings: {}, target: null, test_surface_files: [] };
  return { entry, state: "not_run", reason: null, geometries: [] };
}

const listOf = (...ids: string[]) => ({ studies: ids.map(study), metrics: [] });

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/**
 * Renders the hook against a fetch whose reads of the studies are answered by *reads*, one after the other, each a promise the test
 * settles when it likes; DELETE and PUT order answer at once. Records "METHOD path".
 */
function renderedHook(reads: (() => Promise<Response>)[], writeReply: (method: string, path: string) => Response) {
  const requests: string[] = [];
  let read = 0;
  vi.stubGlobal("fetch", vi.fn(async (address: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    const path = address.replace("/api/projects/p", "");
    requests.push(`${method} ${path}`);
    return method === "GET" && path === "/studies" ? reads[read++]() : writeReply(method, path);
  }));
  let latest: StudiesHook | null = null;
  function Probe() {
    latest = useStudies("token", "p");
    return null;
  }
  const rendered = renderForTest(createElement(Probe));
  return { hook: () => latest!, requests, unmount: rendered.unmount };
}

/** A read of the studies that answers when the test calls *answer*. */
function lateRead() {
  let answer: (reply: Response) => void = () => {};
  const read = () => new Promise<Response>((resolve) => { answer = resolve; });
  return { read, answer: (body: unknown) => answer(json(body)) };
}

afterEach(() => vi.unstubAllGlobals());

test("a read asked for before a delete, answered after it, does not bring the study back", async () => {
  const early = lateRead();
  const { hook, requests, unmount } = renderedHook([early.read, async () => json(listOf("2"))], () => new Response(null, { status: 204 }));
  await act(async () => { void hook().refresh(); });                        // asked for, not answered yet
  await act(async () => { await hook().remove("1"); });                       // the delete is answered; its own read follows
  await act(async () => { early.answer(listOf("1", "2")); });                // the early read answers last, with the old list
  expect(requests).toEqual(["GET /studies", "DELETE /studies/1", "GET /studies"]);
  expect(hook().studies.map((each) => each.entry.id)).toEqual(["2"]);
  unmount();
});

test("a read asked for before a new order, answered after it, does not bring the old order back", async () => {
  const early = lateRead();
  const { hook, unmount } = renderedHook([early.read, async () => json(listOf("2", "1"))], () => json([study("2").entry, study("1").entry]));
  await act(async () => { void hook().refresh(); });
  await act(async () => { await hook().reorder(["2", "1"]); });
  await act(async () => { early.answer(listOf("1", "2")); });
  expect(hook().studies.map((each) => each.entry.id)).toEqual(["2", "1"]);
  unmount();
});

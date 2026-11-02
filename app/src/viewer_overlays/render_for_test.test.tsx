// settle, which every test that talks to a fake service waits with: it must wait as long as the page is busy (so a test that says a
// request was not sent means it), not wait for a reply a test holds on purpose or for a timer with a delay, and say so when the page
// never settles. Also byRole, which finds an element by its role and accessible name.
import { useEffect, useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { accessibleName, byRole, holdReply, renderForTest, settle, SETTLE_ROUNDS_AT_MOST, type RenderedOverlay } from "./render_for_test";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** A page that asks for /step/1, and for the next step once each reply is shown, up to *steps*; then, when *thenRun*, starts a run. */
function Chain({ steps, thenRun = false }: { steps: number; thenRun?: boolean }) {
  const [done, setDone] = useState(0);
  useEffect(() => {
    if (done < steps) void fetch(`/step/${done + 1}`).then((reply) => reply.json()).then(() => setDone(done + 1));
    else if (thenRun) void fetch("/runs", { method: "POST" });
  }, [done, steps, thenRun]);
  return <p>{done} done</p>;
}

/** A page that counts to 12, one zero-delay timer per number, each set once the number before is shown. */
function Ticks() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (count === 12) return undefined;
    const timer = setTimeout(() => setCount(count + 1), 0);
    return () => clearTimeout(timer);
  }, [count]);
  return <p>{count} ticks</p>;
}

const asked = (fetchStub: { mock: { calls: unknown[][] } }) => fetchStub.mock.calls.map((call) => String(call[0]));

test("one settle waits for a chain of zero-delay timers, each shown before the next is set, with fake timers or real ones", async () => {
  // The settle of five fixed rounds this one replaced got to 1 in both cases (measured).
  for (const fakeTimers of [true, false]) {
    if (fakeTimers) vi.useFakeTimers();
    rendered = renderForTest(<Ticks />);
    await settle();
    expect(rendered.container.textContent).toBe("12 ticks");
    rendered.unmount();
    rendered = null;
    vi.useRealTimers();
  }
});

test("with fake timers, a zero-delay timer set by another timer runs too, although the fake clock gives it 1 ms", async () => {
  vi.useFakeTimers();
  const fetchStub = vi.fn(async () => new Response("{}"));
  vi.stubGlobal("fetch", fetchStub);
  // Eight timers, each set by the one before, then a run: as a page that defers its work a few times would.
  const later = (hops: number): unknown => setTimeout(() => (hops === 0 ? void fetch("/runs", { method: "POST" }) : later(hops - 1)), 0);
  later(8);
  await settle();
  expect(asked(fetchStub)).toEqual(["/runs"]);
});

test("a run the page starts after a slow reply is seen, so a test that says no run started means it", async () => {
  // The reply comes after twenty macrotasks (a reply read in parts), then the page starts a run: the settle of five fixed rounds
  // returned before the run, so "no run started" would have passed (measured: it saw ["/step/1"] for 10 and 20 macrotasks).
  const fetchStub = vi.fn(async () => {
    for (let hop = 0; hop < 20; hop++) await new Promise((resolve) => setTimeout(resolve, 0));
    return new Response("{}");
  });
  vi.stubGlobal("fetch", fetchStub);
  rendered = renderForTest(<Chain steps={1} thenRun />);
  await settle();
  expect(asked(fetchStub)).toEqual(["/step/1", "/runs"]);
});

test("one settle waits for a chain of requests, each sent once the reply before is shown", async () => {
  vi.useFakeTimers();
  const fetchStub = vi.fn(async () => new Response("{}"));
  vi.stubGlobal("fetch", fetchStub);
  rendered = renderForTest(<Chain steps={12} thenRun />);
  await settle();
  expect(rendered.container.textContent).toBe("12 done");
  expect(asked(fetchStub)).toHaveLength(13);
  expect(asked(fetchStub).at(-1)).toBe("/runs");
});

test("settle does not wait for a reply held with holdReply, and waits for it once it is let go", async () => {
  vi.useFakeTimers();
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (address: string) => {
    if (address === "/step/2") await holdReply(held);
    return new Response("{}");
  }));
  rendered = renderForTest(<Chain steps={4} />);
  await settle();
  expect(rendered.container.textContent).toBe("1 done");       // the second reply is held
  release();
  await settle();
  expect(rendered.container.textContent).toBe("4 done");
});

test("settle leaves a timer with a delay waiting, as a save delay: the test moves the clock for it", async () => {
  vi.useFakeTimers();
  let saved = false;
  setTimeout(() => { saved = true; }, 400);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
  rendered = renderForTest(<Chain steps={1} />);
  await settle();
  expect(rendered.container.textContent).toBe("1 done");
  expect(saved).toBe(false);
  await vi.advanceTimersByTimeAsync(400);
  expect(saved).toBe(true);
});

test("a reply that never comes and is not held makes settle throw, naming the request", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
  rendered = renderForTest(<Chain steps={1} />);
  await expect(settle()).rejects.toThrow(`still busy after ${SETTLE_ROUNDS_AT_MOST} rounds; requests not answered: ["/step/1"] (0 of them held`);
});

test("a role is found by its accessible name, from aria-label, aria-labelledby or the text, and a missing one is named in the error", () => {
  rendered = renderForTest(
    <div>
      <span id="caption">Daylight</span>
      <div role="radio" aria-checked="false" aria-labelledby="caption" />
      <div role="radio" aria-checked="true" aria-label="Solar energy">sun</div>
      <button type="button"> Run analysis </button>
    </div>,
  );
  expect(byRole(rendered.container, "radio", "Daylight").getAttribute("aria-checked")).toBe("false");
  expect(accessibleName(byRole(rendered.container, "radio", "Solar energy"))).toBe("Solar energy");
  expect(byRole(rendered.container, "button", "Run analysis").tagName).toBe("BUTTON");
  expect(() => byRole(rendered!.container, "radio", "Night cooling")).toThrow('no radio named "Night cooling"; the radios here are named ["Daylight","Solar energy"]');
});

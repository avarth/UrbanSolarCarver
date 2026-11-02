// Rendering an overlay into the jsdom document for a test, with React's act so effects and updates have run; the events a user
// sends (a click, a key, typing), finding an element by its role and accessible name, and settle, which waits until the page and
// its fake service have nothing left to do. Shared by every test file of the app (a file here imports nothing above this folder).
import { readFileSync } from "node:fs";
import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

export interface RenderedOverlay {
  container: HTMLElement;
  rerender: (element: ReactElement) => void;
  unmount: () => void;
}

export function renderForTest(element: ReactElement): RenderedOverlay {
  const container = document.createElement("div");
  document.body.appendChild(container);
  let root: Root;
  act(() => {
    root = createRoot(container);
    root.render(element);
  });
  return {
    container,
    rerender: (next) => act(() => root.render(next)),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

export function click(element: Element): void {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

/**
 * Presses *key* on *element* (a keydown that bubbles and can be cancelled), focusing the element first when *focus* is set, as a
 * widget that reads the focused element needs; returns whether the page took the key (it called preventDefault).
 */
export function press(element: Element, key: string, { focus = false }: { focus?: boolean } = {}): boolean {
  if (focus) act(() => (element as HTMLElement).focus());
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
  act(() => {
    element.dispatchEvent(event);
  });
  return event.defaultPrevented;
}

/**
 * Types *text* into a field the way the browser does, so React's change handler runs: the value is set through the element's own
 * setter (React ignores a plain assignment), then an input event, or a change event for a select.
 */
export function type(field: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, text: string): void {
  const prototype = field instanceof HTMLSelectElement ? HTMLSelectElement.prototype
    : field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  act(() => {
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}

/** Types *text* into a field, then leaves it (focusout), which is when a field the user typed into commits its value. */
export function typeAndLeave(field: HTMLInputElement, text: string): void {
  type(field, text);
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
}

/** The accessible name of *element* as a screen reader gives it: its aria-label, else the text of the elements its aria-labelledby names, else its text. */
export function accessibleName(element: Element): string {
  const label = element.getAttribute("aria-label");
  if (label !== null) return label.trim();
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy !== null) {
    return labelledBy.split(/\s+/).map((id) => element.ownerDocument.getElementById(id)?.textContent ?? "").join(" ").trim();
  }
  return (element.textContent ?? "").trim();
}

/**
 * The element under *root* with this ARIA role (its role attribute, or a button's own) and accessible name; it throws, naming both,
 * when there is none, so a change of markup fails with what was looked for rather than with "Cannot read properties of null".
 */
export function byRole<Found extends HTMLElement = HTMLElement>(root: Element, role: string, name: string): Found {
  const selector = role === "button" ? 'button:not([role]), [role="button"]' : `[role="${role}"]`;
  const candidates = [...root.querySelectorAll<Found>(selector)];
  const found = candidates.find((candidate) => accessibleName(candidate) === name);
  if (found === undefined) {
    throw new Error(`no ${role} named "${name}"; the ${role}s here are named ${JSON.stringify(candidates.map(accessibleName))}`);
  }
  return found;
}

// ---- settle: waiting until nothing is pending ----

/** The replies a fake service holds on purpose (a test's hold point, see holdReply), counted by the fetch stub that was asked. */
const repliesHeld = new WeakMap<object, number>();

/**
 * For a fake service: its reply waits for *until* (a test's hold point, such as runStartsWaitFor), and settle does not wait for it
 * meanwhile. Without this, settle takes a reply held on purpose for a page that is still busy, and throws.
 */
export async function holdReply(until: Promise<unknown> | null | undefined): Promise<void> {
  const asked = globalThis.fetch;
  repliesHeld.set(asked, (repliesHeld.get(asked) ?? 0) + 1);
  try {
    await until;
  } finally {
    repliesHeld.set(asked, repliesHeld.get(asked)! - 1);
  }
}

/** The addresses of the requests the stubbed fetch has not answered yet, and how many of them a fake holds on purpose. */
function repliesOutstanding(): { addresses: string[]; held: number } {
  const stub = globalThis.fetch;
  if (!vi.isMockFunction(stub)) return { addresses: [], held: 0 };
  const addresses = stub.mock.settledResults.flatMap((result, index) => (result.type === "incomplete" ? [String(stub.mock.calls[index][0])] : []));
  return { addresses, held: repliesHeld.get(stub) ?? 0 };
}

function requestsAsked(): number {
  const stub = globalThis.fetch;
  return vi.isMockFunction(stub) ? stub.mock.calls.length : 0;
}

/** A fake timer as @sinonjs/fake-timers (behind vi.useFakeTimers) keeps it: the delay asked for and the time it is due. */
interface FakeTimer { delay?: unknown; callAt: number }
interface FakeClock { now: number; timers?: Map<number, FakeTimer> }

/**
 * With fake timers, how long until the first zero-delay timer (setTimeout(..., 0), setImmediate) is due, or null when there is none.
 * The fake clock gives a zero-delay timer made while timers run 1 ms, so vi.advanceTimersByTimeAsync(0) alone would leave it waiting.
 * The clock is read through the handle fake-timers puts on the faked setTimeout; without it, only the timers due now are run.
 */
function zeroDelayTimerIn(): number | null {
  const clock = (globalThis.setTimeout as { clock?: FakeClock }).clock;
  if (clock?.timers === undefined) return null;
  const due = [...clock.timers.values()].filter((timer) => !(Number.parseInt(String(timer.delay)) > 0)).map((timer) => timer.callAt - clock.now);
  return due.length === 0 ? null : Math.max(0, Math.min(...due));
}

/** The rounds settle waits at most before it says the page never settles. */
export const SETTLE_ROUNDS_AT_MOST = 50;
/** The rounds in a row with nothing happening that make the page settled: two, so work that takes one macrotask more is seen. */
const QUIET_ROUNDS = 2;

/**
 * Lets the page and its fake service finish what they are doing: rounds of act around one macrotask (with fake timers, the
 * zero-delay timers are run, moving the clock by the 1 ms the fake clock gives one made while timers run), until two rounds in a row
 * change nothing: no reply of the stubbed fetch outstanding (other than those held with holdReply), no request asked, no change in
 * the document, no zero-delay fake timer waiting. A request that the page sends late, after several replies or timers, is therefore
 * seen before a test says it was not sent. Throws when the page is still busy after SETTLE_ROUNDS_AT_MOST rounds, naming the requests
 * not answered. Timers with a delay (a save delay, a poll) are not waited for: a test moves the clock for those.
 */
export async function settle(): Promise<void> {
  // The observer's records reach its callback in a microtask, before a takeRecords after the round would see them.
  let documentChanged: boolean;
  const changes = new MutationObserver(() => { documentChanged = true; });
  changes.observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  try {
    let quietRounds = 0;
    for (let round = 0; round < SETTLE_ROUNDS_AT_MOST; round++) {
      const askedBefore = requestsAsked();
      documentChanged = false;
      await act(async () => {
        if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(zeroDelayTimerIn() ?? 0);
        else await new Promise((resolve) => setTimeout(resolve, 0));
      });
      const outstanding = repliesOutstanding();
      const busy = changes.takeRecords().length > 0 || documentChanged || requestsAsked() !== askedBefore
        || outstanding.addresses.length > outstanding.held || (vi.isFakeTimers() && zeroDelayTimerIn() !== null);
      quietRounds = busy ? 0 : quietRounds + 1;
      if (quietRounds === QUIET_ROUNDS) return;
    }
    const { addresses, held } = repliesOutstanding();
    const timers = vi.isFakeTimers() && zeroDelayTimerIn() !== null ? "; a zero-delay timer is still waiting" : "";
    throw new Error(`settle: the page is still busy after ${SETTLE_ROUNDS_AT_MOST} rounds; requests not answered: ${JSON.stringify(addresses)}`
      + ` (${held} of them held with holdReply)${timers}. A reply a test holds on purpose goes through holdReply.`);
  } finally {
    changes.disconnect();
  }
}

/**
 * Adds a style sheet of the app (a path from app/, such as "src/theme/panels.css") to the jsdom document, so getComputedStyle
 * reports what its rules declare (jsdom applies the cascade but resolves no var() and computes no layout); returns its removal.
 */
export function addStyleSheetForTest(path: string): () => void {
  const style = document.createElement("style");
  style.textContent = readFileSync(path, "utf8");
  document.head.appendChild(style);
  return () => style.remove();
}

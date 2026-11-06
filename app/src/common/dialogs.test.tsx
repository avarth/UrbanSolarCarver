import { act } from "react";
import { afterEach, expect, test } from "vitest";
import { press, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { DialogFrame } from "./dialogs";

let rendered: RenderedOverlay | null = null;
afterEach(() => { rendered?.unmount(); rendered = null; });

function pressShiftTab(element: Element) {
  act(() => { element.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true })); });
}

test("Tab goes round every kind of control of a dialog: select, textarea and link too", () => {
  rendered = renderForTest(
    <DialogFrame title="Kinds" busy={false} onClose={() => {}}>
      <button type="button">First</button>
      <select aria-label="Choice"><option>One</option></select>
      <textarea aria-label="Text" />
      <a href="#there">Last</a>
    </DialogFrame>);
  const last = rendered.container.querySelector("a")!;
  press(last, "Tab", { focus: true });
  expect(document.activeElement!.textContent).toBe("First");
  pressShiftTab(document.activeElement!);
  expect(document.activeElement).toBe(last);
});

test("a disabled control and a link without an address are not in the round", () => {
  rendered = renderForTest(
    <DialogFrame title="Kinds" busy={false} onClose={() => {}}>
      <button type="button">First</button>
      <button type="button">Last</button>
      <select disabled aria-label="Off"><option>One</option></select>
      <a>Not a link</a>
    </DialogFrame>);
  const buttons = rendered.container.querySelectorAll("button");
  press(buttons[1], "Tab", { focus: true });
  expect(document.activeElement).toBe(buttons[0]);
});

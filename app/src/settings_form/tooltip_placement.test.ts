// Where a tooltip opens: under its anchor, or over it when under would cover the pinned run bar or leave the window.
import { afterEach, expect, test } from "vitest";
import { placedTooltipStyle, placementUnder } from "./SettingTooltip";

const added: HTMLElement[] = [];

afterEach(() => {
  for (const element of added.splice(0)) element.remove();
});

function element(rect: { left: number; top: number; width: number; height: number }, attributes: Record<string, string> = {}): HTMLElement {
  const made = document.createElement("div");
  for (const [name, value] of Object.entries(attributes)) made.setAttribute(name, value);
  made.getBoundingClientRect = () => ({ ...rect, right: rect.left + rect.width, bottom: rect.top + rect.height, x: rect.left, y: rect.top, toJSON() {} }) as DOMRect;
  Object.defineProperty(made, "offsetWidth", { value: rect.width });
  Object.defineProperty(made, "offsetHeight", { value: rect.height });
  document.body.append(made);
  added.push(made);
  return made;
}

test("a tooltip opens under its anchor when it fits above the pinned run bar", () => {
  element({ left: 0, top: 800, width: 340, height: 100 }, { "data-tooltips-stay-clear": "" });
  const placement = placementUnder(element({ left: 100, top: 300, width: 16, height: 16 }), element({ left: 0, top: 0, width: 260, height: 120 }));
  expect(placement.above).toBe(false);
  expect(placement.top).toBe(324);
});

test("a tooltip that would cover the pinned run bar opens over its anchor, its arrow at its foot", () => {
  element({ left: 0, top: 800, width: 340, height: 100 }, { "data-tooltips-stay-clear": "" });
  const placement = placementUnder(element({ left: 100, top: 720, width: 16, height: 16 }), element({ left: 0, top: 0, width: 260, height: 120 }));
  expect(placement.above).toBe(true);
  expect(placement.top).toBe(720 - 8 - 120);
  expect(placedTooltipStyle(placement)).toMatchObject({ "--setting-tooltip-arrow-top": "calc(100% - 5px)", "--setting-tooltip-arrow-turn": "225deg" });
});

test("a bar beside the tooltip, not under it, does not move it", () => {
  element({ left: 600, top: 400, width: 300, height: 100 }, { "data-tooltips-stay-clear": "" });
  const placement = placementUnder(element({ left: 100, top: 300, width: 16, height: 16 }), element({ left: 0, top: 0, width: 260, height: 120 }));
  expect(placement.above).toBe(false);
});

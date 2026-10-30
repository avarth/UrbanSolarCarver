// Where a tooltip opens: under its anchor, or over it when under would cover the pinned run bar or leave the window. jsdom's
// window is 1024 x 768; the bar is placed inside it, so a flip comes from the bar, not from the window's edge.
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

const runBar = () => element({ left: 0, top: 500, width: 340, height: 100 }, { "data-tooltips-stay-clear": "" });
const tooltip = () => element({ left: 0, top: 0, width: 260, height: 120 });

test("a tooltip opens under its anchor when it ends above the pinned run bar", () => {
  runBar();
  const placement = placementUnder(element({ left: 100, top: 100, width: 16, height: 16 }), tooltip());
  expect(placement).toMatchObject({ above: false, top: 124 });
});

test("a tooltip that would cover the pinned run bar, inside the window, opens over its anchor with its arrow at its foot", () => {
  runBar();
  const anchor = element({ left: 100, top: 400, width: 16, height: 16 });
  expect(placementUnder(anchor, tooltip())).toMatchObject({ above: true, top: 400 - 8 - 120 });
  expect(placedTooltipStyle(placementUnder(anchor, tooltip()))).toMatchObject({ "--setting-tooltip-arrow-top": "calc(100% - 5px)", "--setting-tooltip-arrow-turn": "225deg" });
  for (const element of added.filter((each) => each.hasAttribute("data-tooltips-stay-clear"))) element.remove();
  expect(placementUnder(anchor, tooltip()).above).toBe(false);          // without the bar it fits under
});

test("a bar beside the tooltip, not under it, does not move it", () => {
  element({ left: 600, top: 500, width: 300, height: 100 }, { "data-tooltips-stay-clear": "" });
  expect(placementUnder(element({ left: 100, top: 400, width: 16, height: 16 }), tooltip()).above).toBe(false);
});

test("with no room over the anchor either, the tooltip stays under it", () => {
  element({ left: 0, top: 150, width: 340, height: 100 }, { "data-tooltips-stay-clear": "" });
  expect(placementUnder(element({ left: 100, top: 60, width: 16, height: 16 }), tooltip()).above).toBe(false);
});

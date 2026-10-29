import { readFileSync } from "node:fs";
import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { CriterionEntry } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriterionCard, type CriterionCardProps } from "./CriterionCard";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const DAYLIGHT: CriterionEntry = {
  id: "2", name: "Daylight on windows", named_by_user: true, colour: "#cc6677", bypassed: false, energy_weighted: false, test_surface_files: ["windows.obj"],
  settings: { mode: "daylight" },
};

function cardProps(overrides: Partial<CriterionCardProps> = {}): CriterionCardProps {
  return {
    entry: DAYLIGHT, line: "70 % of the score carved, 18 400 m³ removed", selected: false, reorderable: true, deleteDisabledReason: null, disabledReason: null,
    onSelect: () => {}, onMove: () => {}, onSetBypassed: () => {}, onChoose: () => {}, ...overrides,
  };
}

function renderCard(overrides: Partial<CriterionCardProps> = {}) {
  rendered = renderForTest(<ol><CriterionCard {...cardProps(overrides)} /></ol>);
}

const card = () => rendered!.container.querySelector<HTMLElement>(".criterion-card")!;
const handle = () => card().querySelector<HTMLElement>(".criterion-card-handle")!;

function press(element: Element, key: string) {
  act(() => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

test("a card shows the criterion's colour, name, mode symbol and its line", () => {
  renderCard();
  expect(card().querySelector<HTMLElement>(".criterion-card-swatch")!.style.background).toBe("rgb(204, 102, 119)");
  expect(card().querySelector(".criterion-card-name")!.textContent).toBe("Daylight on windows");
  expect(card().querySelector(".mode-tile-symbol")).not.toBeNull();
  expect(card().querySelector(".criterion-card-line")!.textContent).toBe("70 % of the score carved, 18 400 m³ removed");
  expect(card().getAttribute("aria-current")).toBeNull();
});

/** The name a button is given by its content: its text without the parts hidden from screen readers. */
function nameFromContent(element: Element): string {
  return [...element.childNodes].map((node) => (node.nodeType === Node.TEXT_NODE ? node.textContent
    : node instanceof Element && node.getAttribute("aria-hidden") !== "true" ? nameFromContent(node) : "")).join("");
}

const EIGHTY_CHARACTERS = "Solar usefulness on alatini_testSrfs_solargains_with_a_long_tail_of_eighty_chars";

test("a card shows its whole name on up to two lines in a row of its own, its line under it, and a chevron that says it opens", () => {
  expect(EIGHTY_CHARACTERS).toHaveLength(80);
  for (const name of [EIGHTY_CHARACTERS, "Daylight on alatini_testSrfs_daylight"]) {
    renderCard({ entry: { ...DAYLIGHT, name } });
    const nameElement = card().querySelector(".criterion-card-name")!;
    expect(nameElement.textContent).toBe(name);
    expect(nameElement.getAttribute("title")).toBe(name);
    expect(nameFromContent(card().querySelector(".criterion-card-select")!)).toBe(name);        // the one control that opens the card
    expect(card().querySelector(".criterion-card-chevron")!.getAttribute("aria-hidden")).toBe("true");
    rendered!.unmount();
    rendered = null;
  }
  const css = readFileSync("src/steps/steps.css", "utf8");
  const rule = (selector: string) => css.match(new RegExp(`\\n${selector.replace(/[.>]/g, "\\$&")}\\s*{([^}]*)}`))![1];
  expect(rule(".criterion-card-name")).toMatch(/-webkit-line-clamp:\s*2/);
  expect(rule(".criterion-card-name")).toMatch(/overflow-wrap:\s*anywhere/);
  expect(rule(".criterion-card-name")).not.toMatch(/white-space:\s*nowrap/);
  // The name has the second row across the card; the chevron is in the last column, after the switch and the menu.
  expect(rule(".criterion-card-name")).toMatch(/grid-column:\s*1\s*\/\s*-1;\s*grid-row:\s*2/);
  expect(rule(".criterion-card-chevron")).toMatch(/grid-column:\s*-2\s*\/\s*-1/);
  expect(rule(".criterion-card > .criterion-card-switch")).toMatch(/grid-column:\s*-4\s*\/\s*-3/);
  expect(rule(".criterion-card > .action-menu")).toMatch(/grid-column:\s*-3\s*\/\s*-2/);
  expect(rule(".criterion-card-select")).toMatch(/grid-row:\s*1\s*\/\s*3/);
});

test("the running criterion's card says Running and is marked busy; the others are not", () => {
  renderCard({ line: "Running", running: true });
  expect(card().querySelector(".criterion-card-line")!.textContent).toBe("Running");
  expect(card().classList.contains("criterion-card-running")).toBe(true);
  expect(card().getAttribute("aria-busy")).toBe("true");
  rendered!.unmount();
  renderCard();
  expect(card().classList.contains("criterion-card-running")).toBe(false);
  expect(card().getAttribute("aria-busy")).toBeNull();
});

test("the selected card is marked", () => {
  renderCard({ selected: true });
  expect(card().getAttribute("aria-current")).toBe("true");
  expect(card().classList.contains("criterion-card-selected")).toBe(true);
});

test("a press on the card selects it", () => {
  const onSelect = vi.fn();
  renderCard({ onSelect });
  click(card().querySelector(".criterion-card-select")!);
  expect(onSelect).toHaveBeenCalledOnce();
});

test("the handle is dragged, and the arrow keys on it move the card one place", () => {
  const onMove = vi.fn();
  renderCard({ onMove });
  expect(handle().getAttribute("draggable")).toBe("true");
  expect(handle().getAttribute("aria-label")).toBe("Move Daylight on windows");
  expect(document.getElementById(handle().getAttribute("aria-describedby")!)!.textContent).toBe("Drag to reorder, or press the up and down arrow keys");
  press(handle(), "ArrowUp");
  press(handle(), "ArrowDown");
  press(handle(), "ArrowLeft");
  expect(onMove.mock.calls).toEqual([[-1], [1]]);
});

test("the switch is named after the criterion and is on for a criterion the chain uses", () => {
  const onSetBypassed = vi.fn();
  renderCard({ onSetBypassed });
  const toggle = card().querySelector<HTMLInputElement>('[role="switch"]')!;
  expect(toggle.getAttribute("aria-label")).toBe("Use Daylight on windows");
  expect(toggle.checked).toBe(true);
  click(toggle);
  expect(onSetBypassed).toHaveBeenCalledExactlyOnceWith(true);
});

test("a criterion switched off is greyed, its switch is off and its line reads Off; switching it on asks for it to be used", () => {
  const onSetBypassed = vi.fn();
  renderCard({ entry: { ...DAYLIGHT, bypassed: true }, line: "Off", onSetBypassed });
  expect(card().classList.contains("criterion-card-bypassed")).toBe(true);
  const toggle = card().querySelector<HTMLInputElement>('[role="switch"]')!;
  expect(toggle.checked).toBe(false);
  expect(card().querySelector(".criterion-card-line")!.textContent).toBe("Off");
  click(toggle);
  expect(onSetBypassed).toHaveBeenCalledExactlyOnceWith(false);
});

test("a card that cannot be reordered has no drag handle", () => {
  renderCard({ reorderable: false });
  expect(card().querySelector(".criterion-card-handle")).toBeNull();
  expect(card().querySelector("[draggable='true']")).toBeNull();
});

test("the card's menu offers Rename, Duplicate and Delete, Delete waiting with its reason on the only criterion", () => {
  const onChoose = vi.fn();
  renderCard({ onChoose, deleteDisabledReason: "A project needs at least one criterion." });
  const menuButton = card().querySelector<HTMLButtonElement>(".action-menu-button")!;
  expect(menuButton.getAttribute("aria-label")).toBe("Actions for Daylight on windows");
  click(menuButton);
  const items = [...card().querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
  expect(items.map((item) => item.textContent)).toEqual(["Rename", "Duplicate", "Delete"]);
  expect(items[2].getAttribute("aria-disabled")).toBe("true");
  expect(document.getElementById(items[2].getAttribute("aria-describedby")!)!.textContent).toBe("A project needs at least one criterion.");
  click(items[1]);
  expect(onChoose).toHaveBeenCalledExactlyOnceWith("duplicate");
});

test("during a run the card's controls wait", () => {
  renderCard({ disabledReason: "A run is in progress" });
  expect(card().querySelector<HTMLInputElement>('[role="switch"]')!.disabled).toBe(true);
  expect(handle().getAttribute("draggable")).toBe("false");
  expect(handle().getAttribute("aria-disabled")).toBe("true");
});

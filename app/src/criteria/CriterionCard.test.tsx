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
  id: "2", name: "Daylight on windows", named_by_user: true, colour: "#cc6677", bypassed: false, test_surface_files: ["windows.obj"],
  settings: { mode: "daylight" },
};

function cardProps(overrides: Partial<CriterionCardProps> = {}): CriterionCardProps {
  return {
    entry: DAYLIGHT, line: "70 % of the score carved, 18 400 m³ removed", selected: false, deleteDisabledReason: null, disabledReason: null,
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

test("the bypass switch is named after the criterion; a bypassed card is greyed and reads Bypassed", () => {
  const onSetBypassed = vi.fn();
  renderCard({ onSetBypassed });
  const toggle = card().querySelector<HTMLInputElement>('[role="switch"]')!;
  expect(toggle.getAttribute("aria-label")).toBe("Bypass Daylight on windows");
  expect(toggle.checked).toBe(false);
  click(toggle);
  expect(onSetBypassed).toHaveBeenCalledExactlyOnceWith(true);
  rendered!.unmount();
  renderCard({ entry: { ...DAYLIGHT, bypassed: true }, line: "Bypassed" });
  expect(card().classList.contains("criterion-card-bypassed")).toBe(true);
  expect(card().querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  expect(card().querySelector(".criterion-card-line")!.textContent).toBe("Bypassed");
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

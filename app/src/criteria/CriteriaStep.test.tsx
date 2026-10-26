import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { CriterionEntry } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriteriaStep } from "./CriteriaStep";
import type { CriterionListProps } from "./CriterionList";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function entry(id: string, name: string): CriterionEntry {
  return { id, name, named_by_user: false, colour: "#336699", bypassed: false, test_surface_files: ["windows.ply"], settings: { mode: "daylight" } };
}

function listProps(criteria: CriterionEntry[], overrides: Partial<CriterionListProps> = {}): CriterionListProps {
  return {
    criteria, selectedId: criteria[0].id, lineOf: () => "", disabledReason: null, onSelect: () => {}, onReorder: async () => null,
    onSetBypassed: async () => null, onRename: async () => null, onDuplicate: async () => null, onDelete: async () => null, onAdd: async () => null,
    ...overrides,
  };
}

const PANEL = <div className="criterion-panel">Daylight on windows.ply</div>;
const step = () => rendered!.container.querySelector<HTMLElement>(".criteria-step")!;
const buttonNamed = (label: string) => [...step().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label);

test("one criterion shows its row in the list, then Add criterion under it, then its panel", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")])} />);
  const list = step().querySelector(".criterion-list")!;
  const cards = list.querySelectorAll(".criterion-card");
  expect(cards).toHaveLength(1);
  expect(cards[0].querySelector(".criterion-card-name")!.textContent).toBe("Daylight on windows");
  expect(cards[0].querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  expect(step().querySelector("[draggable='true']")).toBeNull();                                       // one card: no drag handle
  const add = buttonNamed("Add criterion")!;
  expect(add.classList.contains("link-button")).toBe(true);
  expect(list.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(add.compareDocumentPosition(step().querySelector(".criterion-panel")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(step().textContent).not.toContain("Add another criterion");
  expect(step().querySelector(".chain-summary")).toBeNull();
});

test("Add criterion opens the mode tiles; a tile adds a criterion of that mode", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null);
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")], { onAdd })} />);
  click(buttonNamed("Add criterion")!);
  const tiles = [...step().querySelectorAll<HTMLElement>(".add-criterion [role='radio']")];
  await act(async () => tiles.find((tile) => tile.textContent === "Solar usefulness")!.click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith("benefit");
});

test("the mode tiles of a new criterion take the focus, are named for it, and close with Cancel, which gives the focus back to the link", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")])} />);
  click(buttonNamed("Add criterion")!);
  const chooser = step().querySelector<HTMLElement>(".add-criterion-open")!;
  expect(document.activeElement).toBe(chooser);
  expect(document.getElementById(chooser.getAttribute("aria-labelledby")!)!.textContent).toBe("Mode of the new criterion");
  const group = chooser.querySelector('[role="radiogroup"]')!;
  expect(document.getElementById(group.getAttribute("aria-labelledby")!)!.textContent).toBe("Mode of the new criterion");
  click(buttonNamed("Cancel")!);
  expect(step().querySelector(".add-criterion [role='radio']")).toBeNull();
  expect(document.activeElement).toBe(buttonNamed("Add criterion"));
});

test("after a duplicate with one card, the focus goes to the card selected then", async () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")])} />);
  const select = () => step().querySelector<HTMLElement>('.criterion-card[aria-current="true"] .criterion-card-select')!;
  click(step().querySelector(".action-menu-button")!);
  await act(async () => click([...step().querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "Duplicate")!));
  expect(document.activeElement).toBe(select());
});

test("while the selected criterion's settings are on their way the panel waits; a refusal is said there", () => {
  const criteria = [entry("1", "Daylight on windows"), entry("2", "Night cooling")];
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps(criteria, { selectedId: "2" })} load={{ state: "loading" }} />);
  expect(step().querySelector(".criterion-panel")).toBeNull();
  expect(step().querySelector('.criterion-panel-frame [role="status"]')!.textContent).toBe("Loading the settings of Night cooling");
  rendered.rerender(<CriteriaStep panel={PANEL} list={listProps(criteria, { selectedId: "2" })} load={{ state: "failed", problem: "Not found." }} />);
  expect(step().querySelector('.criterion-panel-frame [role="alert"]')!.textContent).toBe("Not found.");
});

test("two criteria show their cards, then Add criterion, then the selected criterion's panel", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows"), entry("2", "Night cooling")])} />);
  const list = step().querySelector(".criterion-list")!;
  const add = buttonNamed("Add criterion")!;
  const panel = step().querySelector(".criterion-panel")!;
  expect(list.querySelectorAll(".criterion-card")).toHaveLength(2);
  expect(list.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(add.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(step().textContent).not.toContain("Add another criterion");
});

test("the chain summary line comes under the cards, before the panel; a step given none shows none", () => {
  const criteria = [entry("1", "Daylight on windows"), entry("2", "Night cooling")];
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps(criteria)} chainLine="Kept 480 m³, 48 % of the maximum volume" />);
  const line = step().querySelector(".chain-summary")!;
  expect(line.textContent).toBe("Kept 480 m³, 48 % of the maximum volume");
  expect(step().querySelector(".criterion-list")!.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(line.compareDocumentPosition(step().querySelector(".criterion-panel")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  rendered.rerender(<CriteriaStep panel={PANEL} list={listProps(criteria)} />);
  expect(step().querySelector(".chain-summary")).toBeNull();
});

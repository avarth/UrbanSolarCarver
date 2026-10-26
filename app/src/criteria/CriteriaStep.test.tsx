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

test("one criterion shows no list chrome, only a quiet Add another criterion link after its panel", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")])} />);
  expect(step().querySelector(".criterion-panel")!.textContent).toBe("Daylight on windows.ply");      // the panel open at once
  expect(step().querySelector(".criterion-list, .criterion-card, [role='list'], [role='listitem']")).toBeNull();
  expect(step().querySelector("[role='switch'], [draggable='true']")).toBeNull();                      // no bypass toggle, no drag handle
  expect(step().textContent).not.toContain("Add criterion");
  const link = buttonNamed("Add another criterion")!;
  expect(link.classList.contains("link-button")).toBe(true);
  expect(step().querySelector(".criterion-panel")!.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("Add another criterion opens the mode tiles; a tile adds a criterion of that mode", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null);
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")], { onAdd })} />);
  click(buttonNamed("Add another criterion")!);
  const tiles = [...step().querySelectorAll<HTMLElement>(".add-criterion [role='radio']")];
  await act(async () => tiles.find((tile) => tile.textContent === "Solar usefulness")!.click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith("benefit");
});

test("the mode tiles of a new criterion close with Cancel", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} list={listProps([entry("1", "Daylight on windows")])} />);
  click(buttonNamed("Add another criterion")!);
  click(buttonNamed("Cancel")!);
  expect(step().querySelector(".add-criterion [role='radio']")).toBeNull();
  expect(buttonNamed("Add another criterion")).toBeDefined();
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

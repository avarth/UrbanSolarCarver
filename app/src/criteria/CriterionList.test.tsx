import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { CriterionEntry } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriterionList, type CriterionListProps } from "./CriterionList";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function entry(id: string, name: string, mode: string): CriterionEntry {
  return { id, name, named_by_user: false, colour: "#336699", bypassed: false, test_surface_files: ["roofs.obj"], settings: { mode } };
}

const THREE_CRITERIA = [entry("1", "Daylight on windows", "daylight"), entry("4", "Solar usefulness on facades", "benefit"), entry("2", "Night cooling", "radiative_cooling")];

function listProps(overrides: Partial<CriterionListProps> = {}): CriterionListProps {
  return {
    criteria: THREE_CRITERIA, selectedId: "1", lineOf: (criterion) => `line of ${criterion.id}`, disabledReason: null, onSelect: () => {},
    onReorder: async () => null, onSetBypassed: async () => null, onRename: async () => null, onDuplicate: async () => null, onDelete: async () => null,
    onAdd: async () => null, ...overrides,
  };
}

const cards = () => [...rendered!.container.querySelectorAll<HTMLElement>(".criterion-card")];
const card = (name: string) => cards().find((candidate) => candidate.querySelector(".criterion-card-name")!.textContent === name)!;
const dialog = () => rendered!.container.querySelector<HTMLElement>('[role="dialog"]');
const buttonNamed = (root: Element, label: string) => [...root.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label)!;

function press(element: Element, key: string) {
  act(() => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

function chooseFromMenu(cardName: string, label: string) {
  click(card(cardName).querySelector(".action-menu-button")!);
  click([...card(cardName).querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === label)!);
}

function dragEvent(type: string): DragEvent {
  const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  Object.defineProperty(event, "dataTransfer", { value: { setData: () => {}, setDragImage: () => {}, effectAllowed: "", dropEffect: "" } });
  return event;
}

test("two criteria show cards in order, the selected one marked, and a press selects another", () => {
  const onSelect = vi.fn();
  rendered = renderForTest(<CriterionList {...listProps({ onSelect })} />);
  expect(rendered.container.querySelector("ol.criterion-list")).not.toBeNull();
  expect(cards().map((each) => each.querySelector(".criterion-card-name")!.textContent))
    .toEqual(["Daylight on windows", "Solar usefulness on facades", "Night cooling"]);
  expect(cards().map((each) => each.querySelector(".criterion-card-line")!.textContent)).toEqual(["line of 1", "line of 4", "line of 2"]);
  expect(cards().map((each) => each.getAttribute("aria-current"))).toEqual(["true", null, null]);
  click(card("Night cooling").querySelector(".criterion-card-select")!);
  expect(onSelect).toHaveBeenCalledExactlyOnceWith("2");
});

test("reordering with the keyboard sends the new order", async () => {
  const onReorder = vi.fn(async (_ids: string[]) => null as string | null);
  rendered = renderForTest(<CriterionList {...listProps({ onReorder })} />);
  const handle = card("Solar usefulness on facades").querySelector<HTMLElement>(".criterion-card-handle")!;
  await act(async () => press(handle, "ArrowUp"));
  expect(onReorder).toHaveBeenLastCalledWith(["4", "1", "2"]);
  await act(async () => press(card("Daylight on windows").querySelector(".criterion-card-handle")!, "ArrowUp"));     // the first card goes no higher
  expect(onReorder).toHaveBeenCalledOnce();
  await act(async () => press(card("Daylight on windows").querySelector(".criterion-card-handle")!, "ArrowDown"));
  expect(onReorder).toHaveBeenLastCalledWith(["4", "1", "2"]);
});

test("a card dragged by its handle and dropped on another takes its place", async () => {
  const onReorder = vi.fn(async (_ids: string[]) => null as string | null);
  rendered = renderForTest(<CriterionList {...listProps({ onReorder })} />);
  act(() => card("Daylight on windows").querySelector(".criterion-card-handle")!.dispatchEvent(dragEvent("dragstart")));
  const target = card("Night cooling");
  const over = dragEvent("dragover");
  act(() => target.dispatchEvent(over));
  expect(over.defaultPrevented).toBe(true);               // a drop is allowed there
  await act(async () => target.dispatchEvent(dragEvent("drop")));
  expect(onReorder).toHaveBeenCalledExactlyOnceWith(["4", "2", "1"]);
});

test("the only criterion cannot be deleted", () => {
  rendered = renderForTest(<CriterionList {...listProps({ criteria: [THREE_CRITERIA[0]] })} />);
  click(card("Daylight on windows").querySelector(".action-menu-button")!);
  const deleteItem = [...rendered.container.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "Delete")!;
  expect(deleteItem.getAttribute("aria-disabled")).toBe("true");
  expect(document.getElementById(deleteItem.getAttribute("aria-describedby")!)!.textContent).toBe("A project needs at least one criterion.");
  click(deleteItem);
  expect(dialog()).toBeNull();
});

test("Delete asks first, then deletes; Rename opens its dialog with the name; Duplicate goes at once", async () => {
  const onDelete = vi.fn(async (_id: string) => null as string | null);
  const onRename = vi.fn(async (_id: string, _name: string) => null as string | null);
  const onDuplicate = vi.fn(async (_id: string) => null as string | null);
  rendered = renderForTest(<CriterionList {...listProps({ onDelete, onRename, onDuplicate })} />);
  chooseFromMenu("Night cooling", "Delete");
  expect(dialog()!.textContent).toContain("Delete Night cooling?");
  await act(async () => click(buttonNamed(dialog()!, "Delete")));
  expect(onDelete).toHaveBeenCalledExactlyOnceWith("2");
  expect(dialog()).toBeNull();
  chooseFromMenu("Solar usefulness on facades", "Rename");
  const field = dialog()!.querySelector<HTMLInputElement>("input")!;
  expect(field.value).toBe("Solar usefulness on facades");
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, "Winter sun");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => dialog()!.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(onRename).toHaveBeenCalledExactlyOnceWith("4", "Winter sun");
  chooseFromMenu("Daylight on windows", "Duplicate");
  await act(async () => {});
  expect(onDuplicate).toHaveBeenCalledExactlyOnceWith("1");
});

test("a refused change is said under the cards", async () => {
  rendered = renderForTest(<CriterionList {...listProps({ onSetBypassed: async () => "A run of this project is in progress." })} />);
  await act(async () => click(card("Night cooling").querySelector('[role="switch"]')!));
  expect(rendered.container.querySelector('.criterion-list-problem[role="alert"]')!.textContent).toBe("A run of this project is in progress.");
});

test("Add criterion under the last card opens the mode tiles; a tile adds a criterion of its mode", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null);
  rendered = renderForTest(<CriterionList {...listProps({ onAdd })} />);
  const addButton = buttonNamed(rendered.container, "Add criterion");
  expect(addButton.compareDocumentPosition(cards()[2]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  click(addButton);
  const tiles = [...rendered.container.querySelectorAll<HTMLElement>(".add-criterion [role='radio']")];
  expect(tiles).toHaveLength(6);
  expect(tiles.some((tile) => tile.getAttribute("aria-checked") === "true")).toBe(false);
  await act(async () => tiles.find((tile) => tile.textContent === "Daylight")!.click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith("daylight");
  expect(rendered.container.querySelector(".add-criterion [role='radio']")).toBeNull();     // closed once added
});

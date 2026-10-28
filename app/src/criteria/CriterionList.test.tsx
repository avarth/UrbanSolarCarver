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
  return { id, name, named_by_user: false, colour: "#336699", bypassed: false, energy_weighted: false, test_surface_files: ["roofs.obj"], settings: { mode } };
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
  expect(target.classList.contains("criterion-card-drop-target")).toBe(true);
  act(() => target.dispatchEvent(dragEvent("dragleave")));
  expect(target.classList.contains("criterion-card-drop-target")).toBe(false);      // the mark goes when the card is left
  act(() => target.dispatchEvent(dragEvent("dragover")));
  await act(async () => target.dispatchEvent(dragEvent("drop")));
  expect(onReorder).toHaveBeenCalledExactlyOnceWith(["4", "2", "1"]);
});

test("one criterion shows its row with the switch on and no drag handle; Add criterion sits under it", () => {
  rendered = renderForTest(<CriterionList {...listProps({ criteria: [THREE_CRITERIA[0]] })} />);
  expect(cards()).toHaveLength(1);
  const only = card("Daylight on windows");
  expect(only.querySelector(".criterion-card-swatch")).not.toBeNull();
  expect(only.querySelector(".criterion-card-line")!.textContent).toBe("line of 1");
  expect(only.querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  expect(only.querySelector(".criterion-card-handle, [draggable='true']")).toBeNull();
  expect(only.compareDocumentPosition(buttonNamed(rendered.container, "Add criterion")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("two or more criteria each have a drag handle", () => {
  rendered = renderForTest(<CriterionList {...listProps()} />);
  expect(rendered.container.querySelectorAll(".criterion-card-handle")).toHaveLength(3);
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

const menuItems = () => [...rendered!.container.querySelectorAll<HTMLElement>('.add-criterion [role="menuitem"]')];
const itemNamed = (name: string) => menuItems().find((item) => item.querySelector(".mode-menu-name")!.textContent === name)!;

test("Add criterion under the last card opens a menu of the modes: six items in the order of the tiles, each with its one line", () => {
  rendered = renderForTest(<CriterionList {...listProps()} />);
  const addButton = buttonNamed(rendered.container, "Add criterion");
  expect(addButton.compareDocumentPosition(cards()[2]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  expect(menuItems()).toEqual([]);
  expect(addButton.hasAttribute("aria-controls")).toBe(false);
  click(addButton);
  expect(addButton.getAttribute("aria-expanded")).toBe("true");
  expect(document.getElementById(addButton.getAttribute("aria-controls")!)!.getAttribute("role")).toBe("menu");
  expect(rendered.container.querySelector('.add-criterion [role="radio"]')).toBeNull();     // no tile grid
  expect(menuItems().map((item) => [item.querySelector(".mode-menu-name")!.textContent, item.querySelector(".mode-menu-line")!.textContent])).toEqual([
    ["Angle rule", "A fixed plane from each facade"],
    ["Solar time-based", "Direct sun in a chosen period"],
    ["Solar energy", "Sun and sky energy over a season"],
    ["Solar usefulness", "Sun in hours that need heating"],
    ["Daylight", "Light from an overcast sky"],
    ["Night cooling", "View of the cold night sky"],
  ]);
  expect(document.activeElement).toBe(menuItems()[0]);
});

test("choosing a mode adds a criterion of it and closes the menu", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null);
  rendered = renderForTest(<CriterionList {...listProps({ onAdd })} />);
  click(buttonNamed(rendered.container, "Add criterion"));
  await act(async () => itemNamed("Daylight").click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith("daylight");
  expect(menuItems()).toEqual([]);     // closed once added
});

test("a refused add closes the menu and is said under Add criterion, which has the focus", async () => {
  rendered = renderForTest(<CriterionList {...listProps({ onAdd: async () => "A run of this project is in progress." })} />);
  click(buttonNamed(rendered.container, "Add criterion"));
  await act(async () => itemNamed("Daylight").click());
  expect(menuItems()).toEqual([]);
  expect(rendered.container.querySelector('.add-criterion [role="alert"]')!.textContent).toBe("A run of this project is in progress.");
  expect(document.activeElement).toBe(buttonNamed(rendered.container, "Add criterion"));
});

test("Escape closes the menu and the focus goes back to Add criterion", () => {
  rendered = renderForTest(<CriterionList {...listProps()} />);
  click(buttonNamed(rendered.container, "Add criterion"));
  press(document.activeElement!, "Escape");
  expect(menuItems()).toEqual([]);
  expect(document.activeElement).toBe(buttonNamed(rendered.container, "Add criterion"));
  expect(buttonNamed(rendered.container, "Add criterion").getAttribute("aria-expanded")).toBe("false");
});

test("Escape while Add criterion waits for a run puts the focus on the selected card, not on the page", () => {
  rendered = renderForTest(<CriterionList {...listProps()} />);
  click(buttonNamed(rendered.container, "Add criterion"));
  rendered.rerender(<CriterionList {...listProps({ disabledReason: "A run is in progress." })} />);
  press(document.activeElement!, "Escape");
  expect(menuItems()).toEqual([]);
  expect(document.activeElement).toBe(card("Daylight on windows").querySelector(".criterion-card-select"));
});

test("a refused add does not take the focus back when the user has moved on", async () => {
  let refuse = (_reason: string) => {};
  const onAdd = vi.fn(() => new Promise<string | null>((resolve) => { refuse = resolve; }));
  rendered = renderForTest(<CriterionList {...listProps({ onAdd })} />);
  click(buttonNamed(rendered.container, "Add criterion"));
  await act(async () => itemNamed("Daylight").click());
  const elsewhere = card("Night cooling").querySelector<HTMLElement>(".criterion-card-select")!;
  elsewhere.focus();
  await act(async () => refuse("A run of this project is in progress."));
  expect(menuItems()).toEqual([]);
  expect(rendered.container.querySelector('.add-criterion [role="alert"]')).not.toBeNull();
  expect(document.activeElement).toBe(elsewhere);
});

test("the menu waits while a run is in progress: its items are disabled with the run's reason", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null);
  rendered = renderForTest(<CriterionList {...listProps({ onAdd })} />);
  click(buttonNamed(rendered.container, "Add criterion"));
  rendered.rerender(<CriterionList {...listProps({ onAdd, disabledReason: "A run is in progress." })} />);
  expect(menuItems()).toHaveLength(6);
  expect(menuItems().every((item) => item.getAttribute("aria-disabled") === "true")).toBe(true);
  expect(rendered.container.querySelector(".add-criterion .action-menu-reason")!.textContent).toBe("A run is in progress.");
  await act(async () => itemNamed("Daylight").click());
  expect(onAdd).not.toHaveBeenCalled();
});

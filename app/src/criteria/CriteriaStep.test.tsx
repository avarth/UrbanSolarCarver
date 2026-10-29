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
  return { id, name, named_by_user: false, colour: "#336699", bypassed: false, energy_weighted: false, test_surface_files: ["windows.ply"], settings: { mode: "daylight" } };
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
/** A button of the step by its text or, for an icon button, its label. */
const buttonNamed = (label: string) =>
  [...step().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label || button.getAttribute("aria-label") === label);
const menuItem = (name: string) => [...step().querySelectorAll<HTMLElement>('.add-criterion [role="menuitem"]')].find((item) => item.querySelector(".mode-menu-name")!.textContent === name)!;

test("the list view shows the cards, Add criterion and the chain line, and no panel", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={() => {}} chainLine="Kept 188 073 m³, 19 % of the maximum volume"
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")])} />);
  expect(step().querySelectorAll(".criterion-card")).toHaveLength(2);
  expect(step().querySelector(".chain-summary")!.textContent).toBe("Kept 188 073 m³, 19 % of the maximum volume");
  expect(buttonNamed("Add criterion")!.classList.contains("link-button")).toBe(true);
  expect(step().querySelector(".criterion-panel-frame")).toBeNull();
  expect(step().querySelector(".criterion-editor-header")).toBeNull();
});

test("one criterion shows its card and Add criterion, no drag handle, and no chain line when none is given", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={() => {}} list={listProps([entry("1", "Daylight on windows")])} />);
  expect(step().querySelectorAll(".criterion-card")).toHaveLength(1);
  expect(step().querySelector("[draggable='true']")).toBeNull();
  expect(step().querySelector(".chain-summary")).toBeNull();
  expect(step().textContent).not.toContain("Add another criterion");
});

test("a press on a card selects it and asks for the editor", () => {
  const onSelect = vi.fn(), onShowsChange = vi.fn();
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={onShowsChange}
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")], { onSelect })} />);
  click(step().querySelectorAll<HTMLButtonElement>(".criterion-card-select")[1]);
  expect(onSelect).toHaveBeenCalledWith("2");
  expect(onShowsChange).toHaveBeenCalledWith("editor");
});

test("the editor view shows the header and the panel, not the cards; the focus goes to the criterion's name", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}}
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")], { selectedId: "2" })} />);
  expect(step().querySelector(".criterion-card")).toBeNull();
  expect(step().querySelector(".criterion-editor-name")!.textContent).toBe("Solar energy on roofs");
  expect(step().querySelector(".criterion-editor-position")!.textContent).toBe("2 of 2");
  expect(step().querySelector(".criterion-panel-frame")).not.toBeNull();
  expect(document.activeElement).toBe(step().querySelector(".criterion-editor-name"));
});

test("All criteria asks for the list; previous and next select the neighbours in carving order", () => {
  const onSelect = vi.fn(), onShowsChange = vi.fn();
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={onShowsChange}
                                         list={listProps([entry("1", "A"), entry("2", "B"), entry("3", "C")], { selectedId: "2", onSelect })} />);
  click(buttonNamed("Previous criterion")!);
  expect(onSelect).toHaveBeenLastCalledWith("1");
  click(buttonNamed("Next criterion")!);
  expect(onSelect).toHaveBeenLastCalledWith("3");
  click(buttonNamed("All criteria")!);
  expect(onShowsChange).toHaveBeenLastCalledWith("list");
});

test("with one criterion the header has no position and no previous or next", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}} list={listProps([entry("1", "A")])} />);
  expect(step().querySelector(".criterion-editor-position")).toBeNull();
  expect(buttonNamed("Previous criterion")).toBeUndefined();
  expect(buttonNamed("Next criterion")).toBeUndefined();
});

test("Add criterion and Duplicate open the new criterion's editor; Delete returns to the list with the focus on the card selected", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null), onDuplicate = vi.fn(async (_id: string) => null as string | null);
  const onDelete = vi.fn(async (_id: string) => null as string | null), onShowsChange = vi.fn();
  const criteria = [entry("1", "A"), entry("2", "B")];
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={onShowsChange} list={listProps(criteria, { onAdd })} />);
  click(buttonNamed("Add criterion")!);
  await act(async () => menuItem("Solar usefulness").click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith("benefit");
  expect(onShowsChange).toHaveBeenLastCalledWith("editor");

  rendered.rerender(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={onShowsChange} list={listProps(criteria, { onDuplicate, onDelete, selectedId: "2" })} />);
  onShowsChange.mockClear();
  const choose = async (label: string) => {
    click(step().querySelector(".criterion-editor-header .action-menu-button")!);
    await act(async () => click([...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === label)!));
  };
  await choose("Duplicate");
  expect(onDuplicate).toHaveBeenCalledExactlyOnceWith("2");
  expect(onShowsChange).toHaveBeenLastCalledWith("editor");

  onShowsChange.mockClear();
  await choose("Delete");
  const confirm = [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((button) => button.textContent === "Delete")!;
  await act(async () => click(confirm));
  expect(onDelete).toHaveBeenCalledExactlyOnceWith("2");
  expect(onShowsChange).toHaveBeenLastCalledWith("list");
  rendered.rerender(<CriteriaStep panel={PANEL} shows="list" onShowsChange={onShowsChange} list={listProps([criteria[0]], { selectedId: "1" })} />);
  expect(document.activeElement).toBe(step().querySelector('.criterion-card[aria-current="true"] .criterion-card-select'));
});

test("a refusal of the header's switch is said under the header", async () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}}
                                         list={listProps([entry("1", "A")], { onSetBypassed: async () => "A run is in progress." })} />);
  await act(async () => click(step().querySelector('.criterion-editor-header [role="switch"]')!));
  expect(step().querySelector(".criterion-editor-problem")!.textContent).toBe("A run is in progress.");
});

test("Add criterion opens the menu of the modes; an item adds a criterion of that mode and asks for its editor", async () => {
  const onAdd = vi.fn(async (_mode: string) => null as string | null), onShowsChange = vi.fn();
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={onShowsChange} list={listProps([entry("1", "Daylight on windows")], { onAdd })} />);
  click(buttonNamed("Add criterion")!);
  await act(async () => menuItem("Solar usefulness").click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith("benefit");
  expect(step().querySelector('.add-criterion [role="menu"]')).toBeNull();
  expect(onShowsChange).toHaveBeenLastCalledWith("editor");
});

test("the menu of a new criterion's mode takes the focus, is named for it, and closes with Escape, which gives the focus back to Add criterion", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={() => {}} list={listProps([entry("1", "Daylight on windows")])} />);
  click(buttonNamed("Add criterion")!);
  const menu = step().querySelector<HTMLElement>('.add-criterion [role="menu"]')!;
  expect(menu.getAttribute("aria-label")).toBe("Mode of the new criterion");
  expect(document.activeElement).toBe(menu.querySelector('[role="menuitem"]'));
  act(() => { document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
  expect(step().querySelector('.add-criterion [role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(buttonNamed("Add criterion"));
});

test("while the selected criterion's settings are on their way the panel waits and the header names the criterion; a refusal is said there", () => {
  const criteria = [entry("1", "Daylight on windows"), entry("2", "Night cooling")];
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}} list={listProps(criteria, { selectedId: "2" })} load={{ state: "loading" }} />);
  expect(step().querySelector(".criterion-panel")).toBeNull();
  expect(step().querySelector(".criterion-editor-name")!.textContent).toBe("Night cooling");
  expect(step().querySelector('.criterion-panel-frame [role="status"]')!.textContent).toBe("Loading the settings of Night cooling");
  rendered.rerender(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}} list={listProps(criteria, { selectedId: "2" })} load={{ state: "failed", problem: "Not found." }} />);
  expect(step().querySelector('.criterion-panel-frame [role="alert"]')!.textContent).toBe("Not found.");
});

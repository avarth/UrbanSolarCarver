import { act, useState } from "react";
import { flushSync } from "react-dom";
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

test("the editor view shows the header and the panel, not the cards; the step opening on the editor leaves the focus where it was", () => {
  const stepHeader = document.body.appendChild(document.createElement("button"));      // the step's header button, pressed to open it
  stepHeader.focus();
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}}
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")], { selectedId: "2" })} />);
  expect(step().querySelector(".criterion-card")).toBeNull();
  expect(step().querySelector(".criterion-editor-name")!.textContent).toBe("Solar energy on roofs");
  expect(step().querySelector(".criterion-editor-position")!.textContent).toBe("2 of 2");
  expect(step().querySelector(".criterion-panel-frame")).not.toBeNull();
  expect(document.activeElement).toBe(stepHeader);
  stepHeader.remove();
});

/** The step with its parent's state: the criteria, the one selected and what the step shows. Delete selects the next card first. */
function StepWithState({ start, selected, shows: startShows, onSelect }: { start: CriterionEntry[]; selected: string; shows: "list" | "editor"; onSelect?: (id: string) => void }) {
  const [criteria, setCriteria] = useState(start);
  const [selectedId, setSelectedId] = useState(selected);
  const [shows, setShows] = useState(startShows);
  const onDelete = async (id: string) => {
    const index = criteria.findIndex((criterion) => criterion.id === id), left = criteria.filter((criterion) => criterion.id !== id);
    // As criteria.remove does: the next criterion is selected, and drawn, before the request resolves.
    flushSync(() => { setCriteria(left); setSelectedId(left[Math.min(index, left.length - 1)].id); });
    return null;
  };
  return <CriteriaStep panel={PANEL} shows={shows} onShowsChange={setShows}
                       list={listProps(criteria, { selectedId, onDelete, onSelect: (id) => { onSelect?.(id); setSelectedId(id); } })} />;
}

test("a press on a card opens its editor with the focus on the name; Next then keeps the focus on Next and the live region says the criterion", () => {
  const onSelect = vi.fn();
  rendered = renderForTest(<StepWithState start={[entry("1", "A"), entry("2", "B"), entry("3", "C")]} selected="1" shows="list" onSelect={onSelect} />);
  click(step().querySelectorAll<HTMLButtonElement>(".criterion-card-select")[1]);
  expect(document.activeElement).toBe(step().querySelector(".criterion-editor-name"));
  const next = buttonNamed("Next criterion")!;
  const region = step().querySelector<HTMLElement>('.criterion-editor-header [role="status"]')!;
  next.focus();
  click(next);
  expect(step().querySelector(".criterion-editor-name")!.textContent).toBe("C");
  expect(document.activeElement).toBe(next);
  expect(region.textContent).toBe("C, 3 of 3");
  // At the last criterion Next waits, keeps the focus, and a press does nothing.
  expect(next.getAttribute("aria-disabled")).toBe("true");
  onSelect.mockClear();
  click(next);
  expect(onSelect).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(next);
  expect(step().querySelector(".criterion-editor-name")!.textContent).toBe("C");
});

test("Delete from the editor's menu ends on the list with the focus on the card selected then, never in the next criterion's editor", async () => {
  rendered = renderForTest(<StepWithState start={[entry("1", "A"), entry("2", "B"), entry("3", "C")]} selected="2" shows="editor" />);
  const focused: Element[] = [];
  const keep = (event: FocusEvent) => focused.push(event.target as Element);
  document.addEventListener("focusin", keep);
  click(step().querySelector(".criterion-editor-header .action-menu-button")!);
  await act(async () => click([...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "Delete")!));
  await act(async () => click([...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((button) => button.textContent === "Delete")!));
  document.removeEventListener("focusin", keep);
  expect(step().querySelector(".criterion-editor-header")).toBeNull();
  const selectedCard = step().querySelector<HTMLElement>('.criterion-card[aria-current="true"]')!;
  expect(selectedCard.querySelector(".criterion-card-name")!.textContent).toBe("C");
  expect(document.activeElement).toBe(selectedCard.querySelector(".criterion-card-select"));
  expect(focused.some((element) => element.classList.contains("criterion-editor-name"))).toBe(false);
  expect(focused.length).toBeGreaterThan(0);                                // focusin is heard
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

test("All criteria gives the focus to the selected card once the list shows; a later change of the selection on the list does not move it", () => {
  const criteria = [entry("1", "A"), entry("2", "B")];
  const onShowsChange = vi.fn();
  const view = (shows: "list" | "editor", selectedId: string) =>
    <CriteriaStep panel={PANEL} shows={shows} onShowsChange={onShowsChange} list={listProps(criteria, { selectedId })} />;
  rendered = renderForTest(view("editor", "2"));
  click(buttonNamed("All criteria")!);
  expect(onShowsChange).toHaveBeenLastCalledWith("list");
  rendered.rerender(view("list", "2"));
  expect(document.activeElement).toBe(step().querySelectorAll(".criterion-card-select")[1]);
  buttonNamed("Add criterion")!.focus();
  rendered.rerender(view("list", "1"));
  expect(document.activeElement).toBe(buttonNamed("Add criterion"));
});

test("after a Delete, a later change of the selection on the list does not move the focus", async () => {
  const criteria = [entry("1", "A"), entry("2", "B"), entry("3", "C")], left = [criteria[0], criteria[2]];
  const view = (selectedId: string, shown = criteria, onDelete?: () => Promise<string | null>) =>
    <CriteriaStep panel={PANEL} shows="list" onShowsChange={() => {}} list={listProps(shown, { selectedId, onDelete })} />;
  // The parent has the next criterion selected when the request is answered.
  rendered = renderForTest(view("2", criteria, async () => { rendered!.rerender(view("3", left)); return null; }));
  await act(async () => click(step().querySelectorAll(".action-menu-button")[1]));
  await act(async () => click([...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "Delete")!));
  await act(async () => click([...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((button) => button.textContent === "Delete")!));
  expect(document.activeElement).toBe(step().querySelectorAll(".criterion-card-select")[1]);
  buttonNamed("Add criterion")!.focus();
  rendered.rerender(view("1", left));
  expect(document.activeElement).toBe(buttonNamed("Add criterion"));
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

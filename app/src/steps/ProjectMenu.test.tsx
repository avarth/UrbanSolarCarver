// The project menu and its dialogs (R2 7.2), against fake actions: what each item opens, the name rule of Rename, the typed name
// of Delete, Reset only for an example's project, the items that wait while a run is active, and the keyboard.
import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { projectFolderPath, projectNameProblem } from "./ProjectDialogs";
import { ProjectMenu, type ProjectActions } from "./ProjectMenu";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function fakeActions(overrides: Partial<ProjectActions> = {}): ProjectActions {
  return {
    openFolder: vi.fn(async () => null), rename: vi.fn(async () => null), delete: vi.fn(async () => null),
    resetToExample: vi.fn(async () => null), ...overrides,
  };
}

function renderMenu(actions: ProjectActions, { exampleTitle = null as string | null, runActive = false } = {}) {
  rendered = renderForTest(<ProjectMenu projectName="Plot 7" exampleTitle={exampleTitle} projectFolderPath={"D:\\USC projects\\Plot 7"}
                                        runActive={runActive} actions={actions} placement="project_row" />);
}

const menuButton = () => rendered!.container.querySelector<HTMLButtonElement>(".project-menu-button")!;
const menuItems = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
const menuItem = (label: string) => menuItems().find((item) => item.textContent === label)!;
const dialog = () => rendered!.container.querySelector<HTMLElement>('[role="dialog"]');
const dialogButton = (label: string) => [...dialog()!.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label)!;

function type(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function press(element: Element, key: string) {
  act(() => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

async function submit(form: HTMLFormElement) {
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

test("the menu offers Open folder, Rename and Delete; Reset to the example only for a project made from an example", () => {
  renderMenu(fakeActions());
  expect(menuButton().getAttribute("aria-label")).toBe("Actions for Plot 7");
  click(menuButton());
  expect(menuItems().map((item) => item.textContent)).toEqual(["Open folder", "Rename", "Delete"]);
  rendered!.unmount();
  renderMenu(fakeActions(), { exampleTitle: "Perimeter block" });
  click(menuButton());
  expect(menuItems().map((item) => item.textContent)).toEqual(["Open folder", "Rename", "Delete", "Reset to the example"]);
});

test("the menu works with the keyboard: it opens on its first item, the arrows move, Escape closes it and gives the focus back", () => {
  renderMenu(fakeActions(), { exampleTitle: "Perimeter block" });
  menuButton().focus();
  press(menuButton(), "ArrowDown");
  expect(menuButton().getAttribute("aria-expanded")).toBe("true");
  expect(document.activeElement).toBe(menuItem("Open folder"));
  press(document.activeElement!, "ArrowDown");
  expect(document.activeElement).toBe(menuItem("Rename"));
  press(document.activeElement!, "ArrowUp");
  press(document.activeElement!, "ArrowUp");
  expect(document.activeElement).toBe(menuItem("Reset to the example"));    // from the first item up to the last
  press(document.activeElement!, "Home");
  expect(document.activeElement).toBe(menuItem("Open folder"));
  press(document.activeElement!, "Escape");
  expect(menuItems()).toEqual([]);
  expect(document.activeElement).toBe(menuButton());
});

test("Open folder asks the service at once; a refusal is said in a dialog", async () => {
  const actions = fakeActions({ openFolder: vi.fn(async () => "The folder D:\\USC projects\\Plot 7 could not be opened: no file manager.") });
  renderMenu(actions);
  click(menuButton());
  await act(async () => click(menuItem("Open folder")));
  expect(actions.openFolder).toHaveBeenCalledWith("Plot 7");
  expect(dialog()!.textContent).toContain("could not be opened: no file manager.");
  click(dialogButton("Close"));
  expect(dialog()).toBeNull();
  expect(document.activeElement).toBe(menuButton());
});

test("the rename dialog refuses an invalid name before sending it", async () => {
  const actions = fakeActions();
  renderMenu(actions);
  click(menuButton());
  click(menuItem("Rename"));
  const field = dialog()!.querySelector<HTMLInputElement>("input")!;
  expect(field.value).toBe("Plot 7");
  expect(document.activeElement).toBe(field);
  type(field, "Plot/7");
  await submit(dialog()!.querySelector("form")!);
  expect(actions.rename).not.toHaveBeenCalled();
  expect(dialog()!.querySelector('[role="alert"]')!.textContent)
    .toBe("Use up to 64 letters, numbers, spaces, hyphens or underscores, starting with a letter or number.");
});

test("the rename dialog sends the new name without its surrounding spaces, shows a refusal, and closes once renamed", async () => {
  const rename = vi.fn<ProjectActions["rename"]>().mockResolvedValueOnce("A project named 'Plot 8' already exists (project names ignore letter case).")
    .mockResolvedValueOnce(null);
  renderMenu(fakeActions({ rename }));
  click(menuButton());
  click(menuItem("Rename"));
  const field = dialog()!.querySelector<HTMLInputElement>("input")!;
  type(field, "Plot 7");
  expect(dialogButton("Rename").disabled).toBe(true);        // the name it has
  type(field, " Plot 8 ");
  await submit(dialog()!.querySelector("form")!);
  expect(rename).toHaveBeenLastCalledWith("Plot 7", "Plot 8");
  expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain("already exists");
  await submit(dialog()!.querySelector("form")!);
  expect(dialog()).toBeNull();
  expect(document.activeElement).toBe(menuButton());
});

test("the delete dialog names the project and its folder, and deletes only once the name typed matches", async () => {
  const actions = fakeActions();
  renderMenu(actions);
  click(menuButton());
  click(menuItem("Delete"));
  expect(dialog()!.textContent).toContain("Plot 7");
  expect(dialog()!.textContent).toContain("D:\\USC projects\\Plot 7");
  const description = dialog()!.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent).join(" ");
  expect(description).toBe("The project Plot 7 and everything in its folder go to the recycle bin or trash, where you can restore them. " +
                           "Folder: D:\\USC projects\\Plot 7");
  const field = dialog()!.querySelector<HTMLInputElement>("input")!;
  expect(dialogButton("Delete project").disabled).toBe(true);
  type(field, "plot 7");
  expect(dialogButton("Delete project").disabled).toBe(true);    // the name exactly as it is written
  type(field, "Plot 7");
  expect(dialogButton("Delete project").disabled).toBe(false);
  await act(async () => click(dialogButton("Delete project")));
  expect(actions.delete).toHaveBeenCalledExactlyOnceWith("Plot 7", "Plot 7");
  expect(dialog()).toBeNull();
});

test("a refused delete keeps the dialog open with the service's reason", async () => {
  const reason = "D:\\USC projects\\Plot 7 is on a network drive, which has no recycle bin. Delete it in the file manager.";
  renderMenu(fakeActions({ delete: vi.fn(async () => reason) }));
  click(menuButton());
  click(menuItem("Delete"));
  type(dialog()!.querySelector<HTMLInputElement>("input")!, "Plot 7");
  await act(async () => click(dialogButton("Delete project")));
  expect(dialog()!.querySelector('[role="alert"]')!.textContent).toBe(reason);
});

test("Reset to the example asks first, names the example, and resets on the confirmation", async () => {
  const actions = fakeActions();
  renderMenu(actions, { exampleTitle: "Perimeter block" });
  click(menuButton());
  click(menuItem("Reset to the example"));
  expect(dialog()!.textContent).toContain("Perimeter block");
  expect(document.getElementById(dialog()!.getAttribute("aria-describedby")!)!.textContent).toContain("a fresh copy of the example Perimeter block");
  expect(document.activeElement).toBe(dialogButton("Cancel"));
  await act(async () => click(dialogButton("Reset project")));
  expect(actions.resetToExample).toHaveBeenCalledExactlyOnceWith("Plot 7");
  expect(dialog()).toBeNull();
});

test("a dialog closes with Escape and gives the focus back to the menu button", () => {
  renderMenu(fakeActions());
  click(menuButton());
  click(menuItem("Delete"));
  press(dialog()!.querySelector("input")!, "Escape");
  expect(dialog()).toBeNull();
  expect(document.activeElement).toBe(menuButton());
});

test("Tab stays inside a dialog: from the last button it goes to the first field", () => {
  renderMenu(fakeActions());
  click(menuButton());
  click(menuItem("Rename"));
  const field = dialog()!.querySelector<HTMLInputElement>("input")!;
  type(field, "Plot 8");
  dialogButton("Rename").focus();
  press(dialogButton("Rename"), "Tab");
  expect(document.activeElement).toBe(field);
});

test("while a run of the project is active, Rename, Delete and Reset wait and say why; Open folder still works", async () => {
  const actions = fakeActions();
  renderMenu(actions, { exampleTitle: "Perimeter block", runActive: true });
  click(menuButton());
  expect(menuItems().filter((item) => item.getAttribute("aria-disabled") === "true").map((item) => item.textContent))
    .toEqual(["Rename", "Delete", "Reset to the example"]);
  const reasonId = menuItem("Rename").getAttribute("aria-describedby")!;
  expect(document.getElementById(reasonId)!.textContent).toBe("A run of this project is in progress. Rename, delete and reset wait until it has ended.");
  click(menuItem("Delete"));
  expect(dialog()).toBeNull();
  await act(async () => click(menuItem("Open folder")));
  expect(actions.openFolder).toHaveBeenCalledWith("Plot 7");
});

test("the menu opens under its button, and above it near the bottom of the window", () => {
  renderMenu(fakeActions());
  const menuHeight = vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(150);
  const buttonPlace = vi.spyOn(menuButton(), "getBoundingClientRect").mockReturnValue(new DOMRect(500, 100, 30, 30));
  click(menuButton());
  const popup = () => rendered!.container.querySelector<HTMLElement>(".project-menu-popup")!;
  expect(popup().style.top).toBe("134px");
  click(menuButton());
  buttonPlace.mockReturnValue(new DOMRect(500, window.innerHeight - 60, 30, 30));
  click(menuButton());
  expect(popup().style.top).toBe(`${window.innerHeight - 60 - 4 - 150}px`);
  menuHeight.mockRestore();
  buttonPlace.mockRestore();
});

test("the project-name rule of the service, and the folder of a project in the projects folder", () => {
  expect(projectNameProblem("Plot 7")).toBeNull();
  expect(projectNameProblem("  Plot_7-b  ")).toBeNull();
  expect(projectNameProblem("")).not.toBeNull();
  expect(projectNameProblem("-Plot")).not.toBeNull();
  expect(projectNameProblem("x".repeat(65))).not.toBeNull();
  expect(projectNameProblem("Plaza é")).not.toBeNull();
  expect(projectNameProblem("com1")).toBe("Windows does not allow 'com1' as a folder name. Choose another name.");
  expect(projectFolderPath("D:\\USC projects", "Plot 7")).toBe("D:\\USC projects\\Plot 7");
  expect(projectFolderPath("D:\\", "Plot 7")).toBe("D:\\Plot 7");
  expect(projectFolderPath("/home/ana/USC projects", "Plot 7")).toBe("/home/ana/USC projects/Plot 7");
});

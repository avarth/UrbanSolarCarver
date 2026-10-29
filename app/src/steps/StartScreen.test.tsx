import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { HealthReply, ProjectsFolderReply } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { ProjectActions } from "./ProjectMenu";
import { exampleTitleOf, newestFirst, StartScreen, type ProjectsFolderChange } from "./StartScreen";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const WARMING_UP: HealthReply = { version: "1.4.0", warm_up: { state: "running" } };
const PROJECTS = [
  { name: "Older", created: "2026-10-01T09:00:00", modified: "2026-10-02T09:00:00", mode: "time-based" },
  { name: "Newer", created: "2026-10-01T09:00:00", modified: "2026-10-16T14:05:00", mode: "irradiance" },
];
const EXAMPLES = [{ name: "new_building", title: "New building among neighbors", description: "A plot of about 18 by 17 m." }];
const FOLDER: ProjectsFolderReply = { path: "D:\\USC projects", source: "default", can_change: true };
const NO_ACTIONS: ProjectActions = {
  openFolder: async () => null, rename: async () => null, delete: async () => null, resetToExample: async () => null,
};

function startScreen(health: HealthReply | null, handlers: Partial<Parameters<typeof StartScreen>[0]> = {}) {
  return (
    <StartScreen health={health} projects={PROJECTS} examples={EXAMPLES} projectsFolder={FOLDER} activeRunProject={null} projectActions={NO_ACTIONS}
                 onCreateProject={async () => null} onOpenProject={async () => null} onTryExample={async () => null}
                 onChangeProjectsFolder={async () => ({ status: "cancelled" })} {...handlers} />
  );
}

const folderLine = () => rendered!.container.querySelector<HTMLElement>(".start-projects-folder")!;
const changeFolderButton = () => [...folderLine().querySelectorAll("button")].find((button) => button.textContent === "Change folder");

async function changeFolderTo(outcome: ProjectsFolderChange) {
  const onChangeProjectsFolder = vi.fn(async () => outcome);
  rendered = renderForTest(startScreen(WARMING_UP, { onChangeProjectsFolder }));
  await act(async () => click(changeFolderButton()!));
  expect(onChangeProjectsFolder).toHaveBeenCalledOnce();
}

test("while the GPU warms up, the device notice has the spinner, Preparing the GPU and the warm-up line", () => {
  rendered = renderForTest(startScreen(WARMING_UP));
  const card = rendered.container.querySelector(".start-device-card")!;
  expect(card.querySelector(".spinner")).not.toBeNull();
  expect(card.textContent).toBe("Preparing the GPU. You can open a project and add files now. The run buttons wait until the GPU is ready.");
  expect(rendered.container.querySelector(".start-footer")!.textContent).toBe("Version 1.4.0");     // the device line waits for the warm-up
});

test("the page heading is Projects; the version is in the footer, not under the heading", () => {
  rendered = renderForTest(startScreen({ version: "1.4.0", warm_up: { state: "ready", device_name: "NVIDIA RTX 4070" } }));
  expect(rendered.container.querySelector("h1")!.textContent).toBe("Projects");
  expect(rendered.container.querySelector(".start-cards")!.textContent).not.toContain("Version");
  expect(rendered.container.querySelector(".start-footer")!.textContent).toBe("Version 1.4.0NVIDIA RTX 4070");
});

test("after the warm-up the footer's device line names the GPU, the CPU, or the engine's reason", () => {
  rendered = renderForTest(startScreen({ version: "1.4.0", warm_up: { state: "ready", device_name: "NVIDIA RTX 4070" } }));
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toBe("NVIDIA RTX 4070");     // the top bar says GPU ready
  rendered.rerender(startScreen({ version: "1.4.0", warm_up: { state: "ready" } }));
  expect(rendered.container.querySelector(".start-device-line")).toBeNull();
  rendered.rerender(startScreen({ version: "1.4.0", warm_up: { state: "cpu", cuda_available: false } }));
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toBe("No CUDA-enabled GPU found. USC runs on the CPU, which is slower.");
  rendered.rerender(startScreen({ version: "1.4.0", warm_up: { state: "cpu", cuda_available: true } }));      // usc ui --device cpu
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toBe("CPU mode, chosen at launch.");
  rendered.rerender(startScreen({ version: "1.4.0", warm_up: { state: "failed", problem: "Warp cannot run. Repair the environment with `python setup_env.py`." } }));
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toContain("setup_env.py");
});

test("three cards: a new project with the name hint, the projects newest first, the examples with their descriptions", () => {
  rendered = renderForTest(startScreen(WARMING_UP));
  const cards = [...rendered.container.querySelectorAll(".start-card")];
  expect(cards.map((card) => card.querySelector("h2")!.textContent)).toEqual(["New project", "Open a project", "Try an example"]);
  expect(cards.every((card) => card.querySelector(".start-card-icon svg[aria-hidden='true']") !== null)).toBe(true);
  expect(cards[1].querySelector(".start-card-foot .start-projects-folder")).not.toBeNull();       // the folder at the foot of the list
  expect(cards[1].querySelector<HTMLElement>(".start-projects-folder-line")!.title).toBe(FOLDER.path);
  expect(cards[0].textContent).toContain("Up to 64 letters, numbers, spaces, hyphens or underscores.");
  expect([...cards[1].querySelectorAll(".start-choice-name")].map((name) => name.textContent)).toEqual(["Newer", "Older"]);
  expect(cards[1].querySelector(".start-choice-detail")!.textContent).toBe("16 Oct 2026, 14:05");
  expect(cards[2].textContent).toContain("New building among neighborsA plot of about 18 by 17 m.");
});

test("Create project sends the name; a refusal is shown under the field", async () => {
  const onCreateProject = vi.fn(async () => "A project named 'Plot 7' already exists.");
  rendered = renderForTest(startScreen(WARMING_UP, { onCreateProject }));
  const field = rendered.container.querySelector<HTMLInputElement>(".start-name-field")!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, " Plot 7 ");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    rendered!.container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(onCreateProject).toHaveBeenCalledWith("Plot 7");
  expect(rendered.container.querySelector('[role="alert"]')!.textContent).toBe("A project named 'Plot 7' already exists.");
});

test("choosing an example or a project opens it", async () => {
  const onTryExample = vi.fn(async () => null);
  const onOpenProject = vi.fn(async () => null);
  rendered = renderForTest(startScreen(WARMING_UP, { onTryExample, onOpenProject }));
  await act(async () => click(rendered!.container.querySelectorAll(".start-card")[2].querySelector(".start-choice")!));
  expect(onTryExample).toHaveBeenCalledWith(EXAMPLES[0]);
  await act(async () => click(rendered!.container.querySelectorAll(".start-card")[1].querySelector(".start-choice")!));
  expect(onOpenProject).toHaveBeenCalledWith("Newer");
  expect(newestFirst(PROJECTS).map((project) => project.name)).toEqual(["Newer", "Older"]);
});

test("the projects folder is shown under Open a project, with Change folder", () => {
  rendered = renderForTest(startScreen(WARMING_UP));
  const card = rendered.container.querySelectorAll(".start-card")[1];
  expect(card.querySelector(".start-projects-folder")!.textContent).toContain("Projects folder: D:\\USC projects");
  expect(changeFolderButton()).toBeDefined();
});

test("a changed folder or a cancelled picker shows no problem", async () => {
  await changeFolderTo({ status: "changed" });
  expect(folderLine().querySelector('[role="alert"]')).toBeNull();
  rendered!.unmount();
  await changeFolderTo({ status: "cancelled" });
  expect(folderLine().querySelector('[role="alert"]')).toBeNull();
  expect(folderLine().querySelector('[role="status"]')).toBeNull();     // the hint about the picker window is gone too
});

test("a folder picker that cannot open says why and names the way that always works", async () => {
  await changeFolderTo({ status: "unavailable", problem: "There is no display to show the folder picker on." });
  expect(folderLine().querySelector('[role="alert"]')!.textContent)
    .toBe("There is no display to show the folder picker on. To use another folder, start USC with usc ui --projects-folder <folder>.");
  expect(folderLine().querySelector('[role="alert"] code')!.textContent).toBe("usc ui --projects-folder <folder>");
});

test("a refused change shows the service's reason", async () => {
  await changeFolderTo({ status: "refused", reason: "The folder picker is already open on this computer." });
  expect(folderLine().querySelector('[role="alert"]')!.textContent).toBe("The folder picker is already open on this computer.");
});

test("while the picker is open, the button waits and the page says where the picker is", async () => {
  let answer: (outcome: ProjectsFolderChange) => void = () => {};
  rendered = renderForTest(startScreen(WARMING_UP, { onChangeProjectsFolder: () => new Promise((resolve) => { answer = resolve; }) }));
  click(changeFolderButton()!);
  expect(changeFolderButton()!.disabled).toBe(true);
  expect(folderLine().querySelector('[role="status"]')!.textContent).toBe("Choose a folder in the window that opened on this computer. It may be behind the browser.");
  await act(async () => answer({ status: "cancelled" }));
  expect(changeFolderButton()!.disabled).toBe(false);
});

test("without can_change the button is hidden and the line says why: the command line, or a run", () => {
  rendered = renderForTest(startScreen(WARMING_UP, { projectsFolder: { path: "D:\\USC projects", source: "command_line", can_change: false } }));
  expect(changeFolderButton()).toBeUndefined();
  expect(folderLine().textContent).toContain("This folder was given with --projects-folder. To change it here, start usc ui without it.");
  rendered.rerender(startScreen(WARMING_UP, { projectsFolder: { path: "D:\\USC projects", source: "preference", can_change: false } }));
  expect(changeFolderButton()).toBeUndefined();
  expect(folderLine().textContent).toContain("The projects folder can be changed once the run has ended.");
});

test("each project has its menu; the run of a project makes its own menu wait, not the others'", () => {
  rendered = renderForTest(startScreen(WARMING_UP, { activeRunProject: "older" }));
  const card = rendered.container.querySelectorAll(".start-card")[1];
  const menuButtons = [...card.querySelectorAll<HTMLButtonElement>(".project-menu-button")];
  expect(menuButtons.map((button) => button.getAttribute("aria-label"))).toEqual(["Actions for Newer", "Actions for Older"]);
  click(menuButtons[1]);
  expect(card.querySelector('[role="menuitem"][aria-disabled="true"]')).not.toBeNull();
  click(menuButtons[1]);
  click(menuButtons[0]);
  expect(card.querySelector('[role="menuitem"][aria-disabled="true"]')).toBeNull();
});

test("while the folder picker is open, every choice of the start screen waits, described by the line about the picker", async () => {
  let answer: (outcome: ProjectsFolderChange) => void = () => {};
  rendered = renderForTest(startScreen(WARMING_UP, { onChangeProjectsFolder: () => new Promise((resolve) => { answer = resolve; }) }));
  const field = rendered.container.querySelector<HTMLInputElement>(".start-name-field")!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, "Plot 9");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  click(changeFolderButton()!);
  const pickerLineId = folderLine().querySelector('[role="status"]')!.id;
  const waiting = [
    ...rendered.container.querySelectorAll<HTMLButtonElement>(".start-choice"),
    ...rendered.container.querySelectorAll<HTMLButtonElement>(".project-menu-button"),
    rendered.container.querySelector<HTMLButtonElement>(".start-new-project button[type=submit]")!,
  ];
  expect(waiting).toHaveLength(2 + 1 + 2 + 1);       // two projects, one example, two menus, Create project
  for (const button of waiting) {
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-describedby")).toBe(pickerLineId);
  }
  await act(async () => answer({ status: "cancelled" }));
  expect(waiting.every((button) => !button.disabled)).toBe(true);
});

test("after a rename the focus goes to the renamed project's menu once the list shows it", async () => {
  const projectActions: ProjectActions = { ...NO_ACTIONS, rename: vi.fn(async () => null) };
  rendered = renderForTest(startScreen(WARMING_UP, { projectActions }));
  const menuOf = (name: string) => rendered!.container.querySelector<HTMLButtonElement>(`[aria-label="Actions for ${name}"]`);
  click(menuOf("Older")!);
  click([...rendered.container.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === "Rename")!);
  const dialogField = rendered.container.querySelector<HTMLInputElement>('[role="dialog"] input')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(dialogField, "Oldest");
    dialogField.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    rendered!.container.querySelector('[role="dialog"] form')!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  rendered.rerender(startScreen(WARMING_UP, { projectActions, projects: [PROJECTS[1], { ...PROJECTS[0], name: "Oldest" }] }));
  expect(document.activeElement).toBe(menuOf("Oldest"));
});

test("after a delete the focus goes to the projects heading once the project is gone from the list", async () => {
  const projectActions: ProjectActions = { ...NO_ACTIONS, delete: vi.fn(async () => null) };
  rendered = renderForTest(startScreen(WARMING_UP, { projectActions }));
  click(rendered.container.querySelector('[aria-label="Actions for Older"]')!);
  click([...rendered.container.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === "Delete")!);
  const dialogField = rendered.container.querySelector<HTMLInputElement>('[role="dialog"] input')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(dialogField, "Older");
    dialogField.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    rendered!.container.querySelector('[role="dialog"] form')!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  rendered.rerender(startScreen(WARMING_UP, { projectActions, projects: [PROJECTS[1]] }));
  expect(document.activeElement).toBe(rendered.container.querySelectorAll(".start-card h2")[1]);
});

test("Reset to the example is offered only once the examples are read, and names the example by its title", () => {
  const fromExample = [{ ...PROJECTS[1], example: "new_building" }];
  rendered = renderForTest(startScreen(WARMING_UP, { projects: fromExample, examples: null }));
  const menuItems = () => [...rendered!.container.querySelectorAll('[role="menuitem"]')].map((item) => item.textContent);
  click(rendered.container.querySelector(".project-menu-button")!);
  expect(menuItems()).not.toContain("Reset to the example");
  click(rendered.container.querySelector(".project-menu-button")!);
  expect(exampleTitleOf("new_building", null)).toBeNull();
  expect(exampleTitleOf("unknown_example", EXAMPLES)).toBeNull();
  expect(exampleTitleOf("new_building", EXAMPLES)).toBe("New building among neighbors");
  rendered.rerender(startScreen(WARMING_UP, { projects: fromExample }));
  click(rendered.container.querySelector(".project-menu-button")!);
  expect(menuItems()).toContain("Reset to the example");
});

test("a rename the next list does not show gives up on the focus: a later list does not take it from where the user is", async () => {
  const projectActions: ProjectActions = { ...NO_ACTIONS, rename: vi.fn(async () => null) };
  rendered = renderForTest(startScreen(WARMING_UP, { projectActions }));
  const menuOf = (name: string) => rendered!.container.querySelector<HTMLButtonElement>(`[aria-label="Actions for ${name}"]`);
  click(menuOf("Older")!);
  click([...rendered.container.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === "Rename")!);
  const dialogField = rendered.container.querySelector<HTMLInputElement>('[role="dialog"] input')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(dialogField, "Oldest");
    dialogField.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    rendered!.container.querySelector('[role="dialog"] form')!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  rendered.rerender(startScreen(WARMING_UP, { projectActions, projects: [...PROJECTS] }));
  const nameField = rendered.container.querySelector<HTMLInputElement>(".start-name-field")!;
  nameField.focus();
  rendered.rerender(startScreen(WARMING_UP, { projectActions, projects: [PROJECTS[1], { ...PROJECTS[0], name: "Oldest" }] }));
  expect(document.activeElement).toBe(nameField);
});

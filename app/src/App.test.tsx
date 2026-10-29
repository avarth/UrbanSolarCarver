import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  ApiError, type ExampleInfo, type HealthReply, type ProjectDetail, type ProjectsFolderReply, type ProjectSummary,
} from "./api_client/client";
import { App, DeviceStatus, freeProjectName, pollHealth } from "./App";
import type { WorkspaceSteps } from "./steps/ProjectWorkspace";
import type { RunLoop } from "./steps/run_state";
import { click, renderForTest, type RenderedOverlay } from "./viewer_overlays/render_for_test";

// The open project stands in for the workspace here: the page's own part is which project it opens, when it opens it afresh,
// and what its settings saver sends around a rename, reset or delete. The stand-in saves as the settings form does: with the
// config saver of the project, flushed when the workspace closes, and handed to the page.
const workspaceMounts = vi.hoisted(() => [] as string[]);
const workspaceSettings = vi.hoisted(() => ({
  saver: null as { schedule: (values: Record<string, unknown>) => void } | null, delay: 0,
  /** While set, the uploads and removals of input files under way end only once this promise resolves. */
  inputChangesEndWhen: null as Promise<void> | null,
}));
// The steps each mount of the workspace started with, and the latest workspace's way to say which step is open and its run loop.
const workspaceSteps = vi.hoisted(() => ({
  startedWith: [] as (WorkspaceSteps | undefined)[], report: null as ((steps: WorkspaceSteps) => void) | null, runs: null as RunLoop | null,
}));
vi.mock("./steps/ProjectWorkspace", async () => {
  const { useEffect } = await import("react");
  const { createConfigSaver } = await import("./settings_form/form_state");
  const { putSharedSettings } = await import("./api_client/client");
  return {
    ProjectWorkspace: ({ token, project, runs, criterionKeys, mode, startSteps, onStepsChange, onSettingsSaverReady }: {
      token: string; project: ProjectDetail; runs: RunLoop; criterionKeys: ReadonlySet<string>; mode: string; startSteps?: WorkspaceSteps; onStepsChange?: (steps: WorkspaceSteps) => void;
      onSettingsSaverReady?: (saver: { flush: () => Promise<string>; cancel: () => void; waitForInputChanges: () => Promise<void> } | null) => void;
    }) => {
      workspaceSteps.runs = runs;
      workspaceSteps.report = onStepsChange ?? null;
      useEffect(() => {
        workspaceSteps.startedWith.push(startSteps);
        workspaceMounts.push(project.name);
        const saver = createConfigSaver((values) => putSharedSettings(token, project.name, values), () => {}, workspaceSettings.delay);
        workspaceSettings.saver = saver;
        onSettingsSaverReady?.({ flush: saver.flush, cancel: saver.cancel, waitForInputChanges: async () => { await workspaceSettings.inputChangesEndWhen; } });
        return () => {
          onSettingsSaverReady?.(null);
          void saver.flush();
        };
      }, []);
      return <div className="fake-workspace" data-run-refusal={runs.current?.refusal ?? ""} data-criterion-keys={[...criterionKeys].join(",")} data-mode={mode}>{project.modified}</div>;
    },
  };
});

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  rendered?.unmount();
  rendered = null;
  workspaceMounts.length = 0;
  workspaceSteps.startedWith.length = 0;
  workspaceSteps.report = null;
  workspaceSteps.runs = null;
  workspaceSettings.saver = null;
  workspaceSettings.delay = 0;
  workspaceSettings.inputChangesEndWhen = null;
  window.localStorage.clear();
});

const RUNNING: HealthReply = { version: "1", warm_up: { state: "running" } };
const READY: HealthReply = { version: "1", warm_up: { state: "ready", device_name: "GPU" } };
const NO_REPLY = new TypeError("Failed to fetch");

function polling(replies: (HealthReply | Error)[]) {
  const ask = vi.fn(async () => {
    const next = replies.shift()!;
    if (next instanceof Error) throw next;
    return next;
  });
  const onReply = vi.fn();
  const onProblem = vi.fn();
  const stop = pollHealth({ ask, onReply, onProblem, askAgainAfter: (reply) => reply.warm_up.state === "running", intervalMilliseconds: 1000,
                            failuresBeforeStopped: 3 });
  return { ask, onReply, onProblem, stop };
}

test("one failed health poll does not end polling: the warm-up is still followed", async () => {
  vi.useFakeTimers();
  const { ask, onReply, onProblem } = polling([RUNNING, NO_REPLY, RUNNING, READY]);
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(4);
  expect(onReply).toHaveBeenLastCalledWith(READY);
  expect(onProblem).not.toHaveBeenCalled();
});

test("the engine is said to be stopped only after three failed polls in a row", async () => {
  vi.useFakeTimers();
  const { ask, onProblem } = polling([NO_REPLY, NO_REPLY, NO_REPLY, READY]);
  await vi.advanceTimersByTimeAsync(1500);
  expect(onProblem).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(3);
  expect(onProblem).toHaveBeenCalledExactlyOnceWith("engine_stopped");
});

test("a lost token is said at once", async () => {
  vi.useFakeTimers();
  const { ask, onProblem } = polling([new ApiError(401, { detail: "token" })]);
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(1);
  expect(onProblem).toHaveBeenCalledExactlyOnceWith("access_lost");
});

test("stopping ends the polling", async () => {
  vi.useFakeTimers();
  const { ask, stop } = polling([RUNNING, RUNNING, RUNNING]);
  await vi.advanceTimersByTimeAsync(0);
  stop();
  await vi.advanceTimersByTimeAsync(5000);
  expect(ask).toHaveBeenCalledTimes(1);
});

test("an example's project is named after its title, numbered when that name is taken", () => {
  expect(freeProjectName("Perimeter block", ["Other"])).toBe("Perimeter block");
  expect(freeProjectName("Perimeter block", ["perimeter block", "Perimeter block 2"])).toBe("Perimeter block 3");
  expect(freeProjectName("x".repeat(70), ["x".repeat(64)])).toBe(`${"x".repeat(62)} 2`);
});

test("the top bar in CPU mode: on a computer without a CUDA device it says CPU mode with the no-GPU sentence as its title", () => {
  rendered = renderForTest(<DeviceStatus warmUp={{ state: "cpu", cuda_available: false }} />);
  const status = rendered.container.querySelector(".device-status")!;
  expect(status.textContent).toBe("CPU mode");
  expect(status.getAttribute("title")).toBe("No CUDA-enabled GPU found. USC runs on the CPU, which is slower.");
});

test("the top bar in CPU mode chosen at launch (--device cpu on a computer with a CUDA device) says so, never that no GPU was found", () => {
  rendered = renderForTest(<DeviceStatus warmUp={{ state: "cpu", cuda_available: true }} />);
  const status = rendered.container.querySelector(".device-status")!;
  expect(status.textContent).toBe("CPU mode, chosen at launch.");
  expect(rendered.container.innerHTML).not.toContain("No CUDA-enabled GPU found");
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function projectDetail(name: string, modified = "2026-10-17T09:00:00", example: string | null = null): ProjectDetail {
  return {
    name, created: "2026-10-17T09:00:00", modified, example, settings: { mode: "time-based" },
    inputs: { max_volume: [], test_surfaces: [], weather: [] }, joined_bounds: null, weather_location: null, weather_latitude: null,
    stage_status: { stages: { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing" } }, grid_plan: null,
  };
}

/** The local service as the start screen and the top bar use it; it notes every request as "METHOD address". */
class FakeService {
  readonly requests: string[] = [];
  projects: ProjectSummary[] = [
    { name: "Plot 7", created: "2026-10-17T09:00:00", modified: "2026-10-17T09:00:00", mode: "time-based", example: "perimeter_block" },
  ];
  examples: ExampleInfo[] = [{ name: "perimeter_block", title: "Perimeter block", description: "A closed block.", project: null }];
  folder: ProjectsFolderReply = { path: "D:\\USC projects", source: "default", can_change: true };
  /** Settings saves are refused with 409 (a run the page does not know of); false: they are stored. */
  refuseConfigSaves = false;
  /** While set, the folder picker stays open until this promise resolves. */
  pickerClosesWhen: Promise<void> | null = null;
  /** While set, the examples are answered only once this promise resolves. */
  examplesAnswerWhen: Promise<void> | null = null;
  /** The projects of the folder the picker changes to. */
  projectsOfOtherFolder: ProjectSummary[] = [
    { name: "Elsewhere", created: "2026-10-18T09:00:00", modified: "2026-10-18T09:00:00", mode: "daylight" },
  ];
  /** The reply to Open folder; null: the request does not reach the engine. */
  openFolderReply: (() => Response) | null = null;
  /** The reply to the criterion keys; null: the keys are answered. */
  criterionKeysReply: (() => Response) | null = null;

  answer = async (address: string, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    this.requests.push(`${method} ${address}`);
    const [path, query] = address.split("?");
    if (path === "/api/health") return json({ version: "1.4.0", warm_up: { state: "ready", device_name: "GPU" } });
    if (path === "/api/schema") return json({ properties: {} });
    if (path === "/api/modes") return json([]);
    if (path === "/api/criterion-keys") return this.criterionKeysReply?.() ?? json(["mode", "threshold"]);
    if (path === "/api/examples") {
      await this.examplesAnswerWhen;
      return json(this.examples);
    }
    if (method === "GET" && path === "/api/projects") return json(this.projects);
    if (method === "POST" && path === "/api/projects") return json(projectDetail(JSON.parse(String(init!.body)).name));
    if (path === "/api/projects-folder") return json(this.folder);
    if (method === "POST" && path === "/api/projects-folder/choose") {
      await this.pickerClosesWhen;
      this.folder = { ...this.folder, path: "E:\\Other projects", source: "preference" };
      this.projects = this.projectsOfOtherFolder;
      return json({ status: "changed", path: this.folder.path, problem: null });
    }
    const projectRoute = /^\/api\/projects\/([^/]+)(\/.*)?$/.exec(path);
    if (projectRoute === null) return json({ detail: "Not found" }, 404);
    const name = decodeURIComponent(projectRoute[1]);
    const rest = projectRoute[2] ?? "";
    if (method === "GET" && rest === "") return json(projectDetail(name, "2026-10-17T09:00:00", "perimeter_block"));
    if (method === "PUT" && rest === "/shared-settings") {
      if (this.refuseConfigSaves) return json({ detail: "A run of this project is in progress." }, 409);
      return json({ settings: JSON.parse(String(init!.body)).values, grid_plan: null });
    }
    if (method === "POST" && rest === "/open-folder") {
      if (this.openFolderReply !== null) return this.openFolderReply();
      throw new TypeError("Failed to fetch");      // the engine is not reached
    }
    if (method === "POST" && rest === "/runs") return json({ detail: "The maximum volume is missing." }, 422);
    if (method === "POST" && rest === "/rename") return json(projectDetail(JSON.parse(String(init!.body)).new_name));
    if (method === "POST" && rest === "/reset-to-example") return json(projectDetail(name, "2026-10-18T10:30:00", "perimeter_block"));
    if (method === "POST" && rest.startsWith("/examples/")) return json(projectDetail(name, "2026-10-18T10:30:00", "perimeter_block"));
    if (method === "DELETE" && rest === "" && query === `confirm_name=${encodeURIComponent(name)}`) {
      this.projects = this.projects.filter((project) => project.name !== name);
      return new Response(null, { status: 204 });
    }
    return json({ detail: "Not found" }, 404);
  };

  count(request: string): number {
    return this.requests.filter((made) => made === request).length;
  }
}

const settle = () => act(async () => {
  for (let tick = 0; tick < 5; tick++) await new Promise((resolve) => setTimeout(resolve, 0));
});

async function renderApp(service: FakeService) {
  vi.stubGlobal("fetch", vi.fn(service.answer));
  rendered = renderForTest(<App />);
  await settle();
}

const page = () => rendered!.container;
const buttonNamed = (text: string, within: Element = page()) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === text)!;
const startChoice = (name: string) =>
  [...page().querySelectorAll<HTMLButtonElement>(".start-choice")].find((button) => button.querySelector(".start-choice-name")!.textContent === name);
const topBarMenuButton = () => page().querySelector<HTMLButtonElement>(".top-bar .project-menu-button");
const dialog = () => page().querySelector<HTMLElement>('[role="dialog"]')!;

function type(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function chooseFromTopBarMenu(item: string) {
  click(topBarMenuButton()!);
  click(buttonNamed(item, page().querySelector('[role="menu"]')!));
  await settle();
}

async function openPlot7() {
  await act(async () => click(startChoice("Plot 7")!));
  await settle();
  expect(topBarMenuButton()!.textContent).toContain("Plot 7");
}

test("a criterion keys request that fails goes the way a failed schema or modes request does", async () => {
  const service = new FakeService();
  service.criterionKeysReply = () => json({ detail: "The access token is missing or wrong." }, 401);
  await renderApp(service);
  expect(page().querySelector(".service-problem-overlay")!.textContent).toContain("This page has lost its access to the engine.");
});

test("the one-time setup loads the criterion keys and passes them to the open project", async () => {
  const service = new FakeService();
  await renderApp(service);
  expect(service.requests).toContain("GET /api/criterion-keys");
  await openPlot7();
  expect(page().querySelector(".fake-workspace")!.getAttribute("data-criterion-keys")).toBe("mode,threshold");
});

test("Try an example opens the project made from that example, and creates none", async () => {
  const service = new FakeService();
  service.examples = [{ ...service.examples[0], project: "My block" }];
  await renderApp(service);
  await act(async () => click(startChoice("Perimeter block")!));
  await settle();
  expect(service.requests).toContain("GET /api/projects/My%20block");
  expect(service.requests.filter((request) => request.startsWith("POST"))).toEqual([]);
  expect(topBarMenuButton()!.textContent).toContain("My block");
});

test("Try an example creates the project the first time; the examples are read again on the way back to the start screen", async () => {
  const service = new FakeService();
  await renderApp(service);
  await act(async () => click(startChoice("Perimeter block")!));
  await settle();
  expect(service.requests).toContain("POST /api/projects/Perimeter%20block/examples/perimeter_block");
  const examplesAsked = service.count("GET /api/examples");
  click(buttonNamed("UrbanSolarCarver"));
  await settle();
  expect(service.count("GET /api/examples")).toBe(examplesAsked + 1);
});

test("renaming the open project from the top bar keeps it open under the new name", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(service.requests).toContain("POST /api/projects/Plot%207/rename");
  expect(topBarMenuButton()!.textContent).toContain("Plot 8");
  expect(workspaceMounts).toEqual(["Plot 7", "Plot 8"]);
  expect(page().querySelector('[role="dialog"]')).toBeNull();
});

test("deleting the open project from the top bar returns to the start screen, whose list no longer has it", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  await chooseFromTopBarMenu("Delete");
  expect(dialog().textContent).toContain("D:\\USC projects\\Plot 7");
  type(dialog().querySelector("input")!, "Plot 7");
  await act(async () => click(buttonNamed("Delete project", dialog())));
  await settle();
  expect(service.requests).toContain("DELETE /api/projects/Plot%207?confirm_name=Plot%207");
  expect(topBarMenuButton()).toBeNull();
  expect(page().querySelector(".start-screen")!.textContent).toContain("No projects yet.");
  expect(document.activeElement).toBe(page().querySelector("h1.start-heading"));
});

function savedChanges(service: FakeService) {
  return service.requests.filter((request) => request.startsWith("PUT"));
}

test("a rename of the open project sends its waiting settings first, under the old name, and nothing after", async () => {
  const service = new FakeService();
  workspaceSettings.delay = 60_000;       // the change waits for the rename's flush
  await renderApp(service);
  await openPlot7();
  workspaceSettings.saver!.schedule({ voxel_size: 2 });
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  const putAt = service.requests.indexOf("PUT /api/projects/Plot%207/shared-settings");
  expect(putAt).toBeGreaterThan(-1);
  expect(putAt).toBeLessThan(service.requests.indexOf("POST /api/projects/Plot%207/rename"));
  expect(savedChanges(service)).toEqual(["PUT /api/projects/Plot%207/shared-settings"]);
  expect(topBarMenuButton()!.textContent).toContain("Plot 8");
});

test("a rename whose settings cannot be saved first is not sent, and the dialog says why", async () => {
  const service = new FakeService();
  service.refuseConfigSaves = true;
  await renderApp(service);
  await openPlot7();
  workspaceSettings.saver!.schedule({ voxel_size: 2 });
  await settle();                          // the save fails: a run the page does not know of
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(service.requests.some((request) => request.includes("/rename"))).toBe(false);
  expect(dialog().querySelector('[role="alert"]')!.textContent)
    .toBe("The last change to the settings was not saved, so the project was not renamed. Save the settings again, then rename it.");
});

test("with a failed save outstanding, a reset of the open project sends no settings after the reset", async () => {
  const service = new FakeService();
  service.refuseConfigSaves = true;
  await renderApp(service);
  await openPlot7();
  workspaceSettings.saver!.schedule({ voxel_size: 2 });
  await settle();
  await chooseFromTopBarMenu("Reset to the example");
  await act(async () => click(buttonNamed("Reset project", dialog())));
  await settle();
  const resetAt = service.requests.indexOf("POST /api/projects/Plot%207/reset-to-example");
  expect(resetAt).toBeGreaterThan(-1);
  expect(service.requests.slice(resetAt).filter((request) => request.startsWith("PUT"))).toEqual([]);
  expect(workspaceMounts).toEqual(["Plot 7", "Plot 7"]);
});

test("with a failed save outstanding, a delete of the open project sends no settings after the delete", async () => {
  const service = new FakeService();
  service.refuseConfigSaves = true;
  await renderApp(service);
  await openPlot7();
  workspaceSettings.saver!.schedule({ voxel_size: 2 });
  await settle();
  await chooseFromTopBarMenu("Delete");
  type(dialog().querySelector("input")!, "Plot 7");
  await act(async () => click(buttonNamed("Delete project", dialog())));
  await settle();
  const deleteAt = service.requests.indexOf("DELETE /api/projects/Plot%207?confirm_name=Plot%207");
  expect(deleteAt).toBeGreaterThan(-1);
  expect(service.requests.slice(deleteAt).filter((request) => request.startsWith("PUT"))).toEqual([]);
});

test("the carving's auto-update choice follows a rename and goes with a delete", async () => {
  const service = new FakeService();
  window.localStorage.setItem("usc.autoUpdate.Plot 7", "off");
  await renderApp(service);
  await openPlot7();
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(window.localStorage.getItem("usc.autoUpdate.Plot 7")).toBeNull();
  expect(window.localStorage.getItem("usc.autoUpdate.Plot 8")).toBe("off");
  await chooseFromTopBarMenu("Delete");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => click(buttonNamed("Delete project", dialog())));
  await settle();
  expect(window.localStorage.getItem("usc.autoUpdate.Plot 8")).toBeNull();
});

test("a request that does not reach the engine is said in words, not as the browser's error", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  await chooseFromTopBarMenu("Open folder");
  expect(dialog().textContent).toContain("The request did not reach the USC engine. Check that it is still running, then try again.");
  expect(dialog().textContent).not.toContain("TypeError");
});

test("on the way back to the start screen, the examples wait to be read again before they can be chosen", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  let answerExamples: () => void = () => {};
  service.examplesAnswerWhen = new Promise((resolve) => { answerExamples = resolve; });
  service.examples = [{ ...service.examples[0], project: "Plot 7" }];
  click(buttonNamed("UrbanSolarCarver"));
  await settle();
  expect(startChoice("Perimeter block")).toBeUndefined();
  await act(async () => answerExamples());
  await settle();
  await act(async () => click(startChoice("Perimeter block")!));
  await settle();
  expect(service.requests.filter((request) => request.includes("/examples/"))).toEqual([]);     // opened, not made again
});

test("a project opened while the folder picker is open is closed when the folder changes", async () => {
  const service = new FakeService();
  let closePicker: () => void = () => {};
  service.pickerClosesWhen = new Promise((resolve) => { closePicker = resolve; });
  await renderApp(service);
  click(buttonNamed("Change folder"));
  await settle();
  // The start screen waits while the picker is open; a project is opened past it here, as nothing in the page can.
  type(page().querySelector<HTMLInputElement>(".start-name-field")!, "Plot 9");
  await act(async () => page().querySelector(".start-new-project")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(topBarMenuButton()!.textContent).toContain("Plot 9");
  await act(async () => closePicker());
  await settle();
  expect(topBarMenuButton()).toBeNull();
  expect(startChoice("Elsewhere")).toBeDefined();
});

test("resetting the open project to its example opens it afresh", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  await chooseFromTopBarMenu("Reset to the example");
  expect(dialog().textContent).toContain("Perimeter block");
  await act(async () => click(buttonNamed("Reset project", dialog())));
  await settle();
  expect(service.requests).toContain("POST /api/projects/Plot%207/reset-to-example");
  expect(workspaceMounts).toEqual(["Plot 7", "Plot 7"]);
  expect(page().querySelector(".fake-workspace")!.textContent).toBe("2026-10-18T10:30:00");
});

test("a changed projects folder shows its path and reads the project list again", async () => {
  const service = new FakeService();
  await renderApp(service);
  expect(page().querySelector(".start-projects-folder")!.textContent).toContain("D:\\USC projects");
  await act(async () => click(buttonNamed("Change folder")));
  await settle();
  expect(page().querySelector(".start-projects-folder")!.textContent).toContain("E:\\Other projects");
  expect(startChoice("Elsewhere")).toBeDefined();
  expect(startChoice("Plot 7")).toBeUndefined();
});

test("a refusal without a reason is said in a sentence with its status, not as the error's name", async () => {
  const service = new FakeService();
  service.openFolderReply = () => new Response("Internal Server Error", { status: 500 });
  await renderApp(service);
  await openPlot7();
  await chooseFromTopBarMenu("Open folder");
  expect(dialog().textContent).toContain("The USC engine refused the request and gave no reason (status 500). Try again.");
  expect(dialog().textContent).not.toContain("ApiError");
});

test("a changed projects folder forgets the last run's record: a project of the same name there shows no run of the old one", async () => {
  const service = new FakeService();
  service.projectsOfOtherFolder = [{ name: "Plot 7", created: "2026-10-18T09:00:00", modified: "2026-10-18T09:00:00", mode: "time-based" }];
  await renderApp(service);
  await openPlot7();
  await act(async () => { await workspaceSteps.runs!.start("Plot 7", ["thresholding"], "settings_run_analysis"); });
  await settle();
  expect(page().querySelector(".fake-workspace")!.getAttribute("data-run-refusal")).toBe("The maximum volume is missing.");
  click(buttonNamed("UrbanSolarCarver"));
  await settle();
  await act(async () => click(buttonNamed("Change folder")));
  await settle();
  await openPlot7();
  expect(page().querySelector(".fake-workspace")!.getAttribute("data-run-refusal")).toBe("");
});

test("renaming the open project keeps the open step; opening a project and resetting it start at Inputs", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  act(() => workspaceSteps.report!({ open: "export", view: "export" }));
  await chooseFromTopBarMenu("Reset to the example");
  await act(async () => click(buttonNamed("Reset project", dialog())));
  await settle();
  act(() => workspaceSteps.report!({ open: "criteria", view: "criteria" }));
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(workspaceMounts).toEqual(["Plot 7", "Plot 7", "Plot 8"]);
  expect(workspaceSteps.startedWith).toEqual([undefined, undefined, { open: "criteria", view: "criteria" }]);
  click(buttonNamed("UrbanSolarCarver"));
  await settle();
  await openPlot7();
  expect(workspaceSteps.startedWith).toHaveLength(4);
  expect(workspaceSteps.startedWith.at(-1)).toBeUndefined();
});

test("after a rename on the start screen, the examples wait to be read again: their project may be the old name", async () => {
  const service = new FakeService();
  service.examples = [{ ...service.examples[0], project: "Plot 7" }];
  await renderApp(service);
  let answerExamples: () => void = () => {};
  service.examplesAnswerWhen = new Promise((resolve) => { answerExamples = resolve; });
  service.examples = [{ ...service.examples[0], project: "Plot 8" }];
  click(page().querySelector<HTMLButtonElement>(".start-screen .project-menu-button")!);
  click(buttonNamed("Rename", page().querySelector('[role="menu"]')!));
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(service.requests).toContain("POST /api/projects/Plot%207/rename");
  expect(startChoice("Perimeter block")).toBeUndefined();
  await act(async () => answerExamples());
  await settle();
  await act(async () => click(startChoice("Perimeter block")!));
  await settle();
  expect(service.requests).toContain("GET /api/projects/Plot%208");
});

test("a rename or delete of the open project waits for its uploads under way, so none reaches the project after it", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  let endInputChanges: () => void = () => {};
  workspaceSettings.inputChangesEndWhen = new Promise((resolve) => { endInputChanges = resolve; });
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(service.requests.some((request) => request.includes("/rename"))).toBe(false);
  await act(async () => endInputChanges());
  await settle();
  expect(service.requests).toContain("POST /api/projects/Plot%207/rename");

  workspaceSettings.inputChangesEndWhen = new Promise((resolve) => { endInputChanges = resolve; });
  await chooseFromTopBarMenu("Delete");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => click(buttonNamed("Delete project", dialog())));
  await settle();
  expect(service.requests.some((request) => request.startsWith("DELETE"))).toBe(false);
  await act(async () => endInputChanges());
  await settle();
  expect(service.requests).toContain("DELETE /api/projects/Plot%208?confirm_name=Plot%208");
});

test("the product name in the top bar goes back to the start screen once a project is open; on the start screen it is plain text", async () => {
  const service = new FakeService();
  await renderApp(service);
  const product = () => page().querySelector<HTMLElement>(".top-bar-product")!;
  expect(product().tagName).toBe("SPAN");
  expect(page().querySelector(".top-bar")!.textContent).not.toContain("Projects");
  await openPlot7();
  expect(product().tagName).toBe("BUTTON");
  expect(product().textContent).toBe("UrbanSolarCarver");
  expect(product().getAttribute("title")).toBe("Back to the projects");
  click(product());
  await settle();
  expect(page().querySelector(".fake-workspace")).toBeNull();
  expect(page().querySelector(".start-screen h1")!.textContent).toBe("Projects");
});

test("the theme button at the right of the top bar switches the whole page to dark and back, and the choice is remembered", async () => {
  const service = new FakeService();
  await renderApp(service);
  const themeButton = () => page().querySelector<HTMLButtonElement>(".top-bar .top-bar-icon-button")!;
  expect(page().querySelector(".top-bar")!.lastElementChild).toBe(themeButton());
  expect(document.body.dataset.theme).toBe("light");
  expect(themeButton().getAttribute("aria-label")).toBe("Dark theme");
  expect(themeButton().getAttribute("aria-pressed")).toBe("false");
  expect(themeButton().title).toBe("Switch to the dark theme");
  click(themeButton());
  expect(document.body.dataset.theme).toBe("dark");
  expect(themeButton().getAttribute("aria-pressed")).toBe("true");
  expect(themeButton().title).toBe("Switch to the light theme");
  expect(window.localStorage.getItem("usc.theme")).toBe("dark");
  rendered!.unmount();
  rendered = null;
  await renderApp(service);           // the next visit opens in the theme chosen last
  expect(document.body.dataset.theme).toBe("dark");
  click(themeButton());
  expect(document.body.dataset.theme).toBe("light");
});

test("the top bar names the GPU on hover once it is ready", () => {
  rendered = renderForTest(<DeviceStatus warmUp={{ state: "ready", device_name: "NVIDIA RTX 4070" }} />);
  const status = rendered.container.querySelector(".device-status")!;
  expect(status.textContent).toBe("GPU ready");
  expect(status.getAttribute("title")).toBe("GPU ready: NVIDIA RTX 4070");
});

const modeSwitch = () => page().querySelector<HTMLElement>(".top-bar .workspace-mode-switch");
const modeButton = (name: string) => buttonNamed(name, modeSwitch()!);
const workspaceMode = () => page().querySelector(".fake-workspace")!.getAttribute("data-mode");
const modePressed = () => [...modeSwitch()!.querySelectorAll("button")].map((button) => [button.textContent, button.getAttribute("aria-pressed")]);

test("the Design | Simulate | Inspect switch shows only with an open project and sets the workspace's mode", async () => {
  const service = new FakeService();
  await renderApp(service);
  expect(modeSwitch()).toBeNull();
  await openPlot7();
  expect(modeSwitch()!.getAttribute("role")).toBe("group");
  expect(modeSwitch()!.getAttribute("aria-label")).toBe("Workspace mode");
  expect(modePressed()).toEqual([["Design", "true"], ["Simulate", "false"], ["Inspect", "false"]]);
  expect(workspaceMode()).toBe("design");
  click(modeButton("Simulate"));
  expect(workspaceMode()).toBe("simulate");
  expect(modePressed()).toEqual([["Design", "false"], ["Simulate", "true"], ["Inspect", "false"]]);
  click(modeButton("Inspect"));
  expect(workspaceMode()).toBe("inspect");
  expect(modePressed()).toEqual([["Design", "false"], ["Simulate", "false"], ["Inspect", "true"]]);
  click(buttonNamed("UrbanSolarCarver"));
  await settle();
  expect(modeSwitch()).toBeNull();
});

test("another project opens in Design, whatever mode the last one was left in", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  click(modeButton("Simulate"));
  click(buttonNamed("UrbanSolarCarver"));
  await settle();
  await openPlot7();
  expect(workspaceMode()).toBe("design");
  expect(modePressed()).toEqual([["Design", "true"], ["Simulate", "false"], ["Inspect", "false"]]);
});

test("the mode survives renaming the project", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  click(modeButton("Simulate"));
  await chooseFromTopBarMenu("Rename");
  type(dialog().querySelector("input")!, "Plot 8");
  await act(async () => dialog().querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(workspaceMounts).toEqual(["Plot 7", "Plot 8"]);
  expect(workspaceMode()).toBe("simulate");
  expect(modePressed()).toEqual([["Design", "false"], ["Simulate", "true"], ["Inspect", "false"]]);
});

test("a reset of the open project to its example opens it in Design, as it opens at the first step", async () => {
  const service = new FakeService();
  await renderApp(service);
  await openPlot7();
  click(modeButton("Simulate"));
  await chooseFromTopBarMenu("Reset to the example");
  await act(async () => click(buttonNamed("Reset project", dialog())));
  await settle();
  expect(workspaceMounts).toEqual(["Plot 7", "Plot 7"]);
  expect(workspaceMode()).toBe("design");
  expect(modePressed()).toEqual([["Design", "true"], ["Simulate", "false"], ["Inspect", "false"]]);
});

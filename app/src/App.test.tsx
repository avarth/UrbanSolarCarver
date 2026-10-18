import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  ApiError, type ExampleInfo, type HealthReply, type ProjectDetail, type ProjectsFolderReply, type ProjectSummary,
} from "./api_client/client";
import { App, DeviceStatus, freeProjectName, pollHealth } from "./App";
import { click, renderForTest, type RenderedOverlay } from "./viewer_overlays/render_for_test";

// The open project stands in for the workspace here: the page's own part is which project it opens, and when it opens it afresh.
const workspaceMounts = vi.hoisted(() => [] as string[]);
vi.mock("./steps/ProjectWorkspace", async () => {
  const { useEffect } = await import("react");
  return {
    ProjectWorkspace: ({ project }: { project: ProjectDetail }) => {
      useEffect(() => { workspaceMounts.push(project.name); }, []);
      return <div className="fake-workspace">{project.modified}</div>;
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
    inputs: { max_volume: [], test_surfaces: [], weather: [] }, joined_bounds: null, weather_location: null,
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

  answer = async (address: string, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    this.requests.push(`${method} ${address}`);
    const [path, query] = address.split("?");
    if (path === "/api/health") return json({ version: "1.4.0", warm_up: { state: "ready", device_name: "GPU" } });
    if (path === "/api/schema") return json({ properties: {} });
    if (path === "/api/modes") return json([]);
    if (path === "/api/examples") return json(this.examples);
    if (path === "/api/projects") return json(this.projects);
    if (path === "/api/projects-folder") return json(this.folder);
    if (method === "POST" && path === "/api/projects-folder/choose") {
      this.folder = { ...this.folder, path: "E:\\Other projects", source: "preference" };
      this.projects = [{ name: "Elsewhere", created: "2026-10-18T09:00:00", modified: "2026-10-18T09:00:00", mode: "daylight" }];
      return json({ status: "changed", path: this.folder.path, problem: null });
    }
    const projectRoute = /^\/api\/projects\/([^/]+)(\/.*)?$/.exec(path);
    if (projectRoute === null) return json({ detail: "Not found" }, 404);
    const name = decodeURIComponent(projectRoute[1]);
    const rest = projectRoute[2] ?? "";
    if (method === "GET" && rest === "") return json(projectDetail(name, "2026-10-17T09:00:00", "perimeter_block"));
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
  click(buttonNamed("Projects"));
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

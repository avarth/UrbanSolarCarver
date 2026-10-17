import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { HealthReply } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { newestFirst, StartScreen } from "./StartScreen";

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

function startScreen(health: HealthReply | null, handlers: Partial<Parameters<typeof StartScreen>[0]> = {}) {
  return (
    <StartScreen health={health} projects={PROJECTS} examples={EXAMPLES} onCreateProject={async () => null} onOpenProject={async () => null}
                 onTryExample={async () => null} {...handlers} />
  );
}

test("while the GPU warms up, the device card has the spinner, Preparing the GPU and the warm-up line", () => {
  rendered = renderForTest(startScreen(WARMING_UP));
  const card = rendered.container.querySelector(".start-device-card")!;
  expect(card.querySelector(".spinner")).not.toBeNull();
  expect(card.textContent).toBe("Preparing the GPUYou can open a project and add files now. The run buttons wait until the GPU is ready.");
  expect(rendered.container.textContent).toContain("Version 1.4.0");
});

test("after the warm-up the device line names the GPU, the CPU, or the engine's reason", () => {
  rendered = renderForTest(startScreen({ version: "1.4.0", warm_up: { state: "ready", device_name: "NVIDIA RTX 4070" } }));
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toBe("GPU ready: NVIDIA RTX 4070");
  rendered.rerender(startScreen({ version: "1.4.0", warm_up: { state: "cpu" } }));
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toBe("No CUDA-enabled GPU found. USC runs on the CPU, which is slower.");
  rendered.rerender(startScreen({ version: "1.4.0", warm_up: { state: "failed", problem: "Warp cannot run. Repair the environment with `python setup_env.py`." } }));
  expect(rendered.container.querySelector(".start-device-line")!.textContent).toContain("setup_env.py");
});

test("three cards: a new project with the name hint, the projects newest first, the examples with their descriptions", () => {
  rendered = renderForTest(startScreen(WARMING_UP));
  const cards = [...rendered.container.querySelectorAll(".start-card")];
  expect(cards.map((card) => card.querySelector("h2")!.textContent)).toEqual(["New project", "Open a project", "Try an example"]);
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
  await act(async () => click(rendered!.container.querySelectorAll(".start-card")[2].querySelector("button")!));
  expect(onTryExample).toHaveBeenCalledWith(EXAMPLES[0]);
  await act(async () => click(rendered!.container.querySelectorAll(".start-card")[1].querySelector("button")!));
  expect(onOpenProject).toHaveBeenCalledWith("Newer");
  expect(newestFirst(PROJECTS).map((project) => project.name)).toEqual(["Newer", "Older"]);
});

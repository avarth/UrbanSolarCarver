import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { InputFileInfo } from "../api_client/client";
import { byRole, click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { SurfaceSetSwitches } from "./SurfaceSetSwitches";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const SETS: InputFileInfo[] = [
  { name: "picked_1.ply", triangle_count: 6, shown_name: "South facades", picked: true },
  { name: "roofs.ply", triangle_count: 1 },
];
const root = () => rendered!.container.querySelector<HTMLElement>(".surface-set-switches")!;
const switches = () => [...root().querySelectorAll<HTMLInputElement>('[role="switch"]')];

test("one switch per set of the project, under the mode's hint, on for the sets the criterion uses", () => {
  rendered = renderForTest(<SurfaceSetSwitches sets={SETS} chosen={["roofs.ply"]} mode="daylight" onToggle={async () => null} onOpenSite={() => {}}
                                               disabledReason={null} />);
  expect(root().querySelector(".input-box-hint")!.textContent).toBe("Windows or facades that need daylight. Flat panels; a curved or folded one is skipped.");
  expect(switches().map((input) => [input.getAttribute("aria-label"), input.checked])).toEqual([["Use South facades", false], ["Use roofs.ply", true]]);
  expect([...root().querySelectorAll(".input-file-detail")].map((detail) => detail.textContent)).toEqual(["6 triangles", "1 triangle"]);
  expect(root().textContent).not.toContain("Open the Site step");
});

test("a switch calls onToggle with the stored file and whether it is now on; a refusal is said under the list", async () => {
  const onToggle = vi.fn(async (_fileName: string, on: boolean) => (on ? "A run is in progress" : null));
  rendered = renderForTest(<SurfaceSetSwitches sets={SETS} chosen={["roofs.ply"]} mode="daylight" onToggle={onToggle} onOpenSite={() => {}}
                                               disabledReason={null} />);
  await act(async () => click(byRole(root(), "switch", "Use roofs.ply")));
  expect(onToggle).toHaveBeenLastCalledWith("roofs.ply", false);
  expect(root().querySelector(".input-box-problem")).toBeNull();
  await act(async () => click(byRole(root(), "switch", "Use South facades")));
  expect(onToggle).toHaveBeenLastCalledWith("picked_1.ply", true);
  expect([...root().querySelectorAll(".input-box-problem")].map((line) => line.textContent)).toEqual(["A run is in progress"]);
});

test("during a run the switches are off", () => {
  rendered = renderForTest(<SurfaceSetSwitches sets={SETS} chosen={[]} mode="daylight" onToggle={async () => null} onOpenSite={() => {}}
                                               disabledReason="A run is in progress" />);
  expect(switches().map((input) => input.disabled)).toEqual([true, true]);
});

test("a project without sets says so, with a link that opens the Site step", () => {
  const onOpenSite = vi.fn();
  rendered = renderForTest(<SurfaceSetSwitches sets={[]} chosen={[]} mode="daylight" onToggle={async () => null} onOpenSite={onOpenSite}
                                               disabledReason={null} />);
  expect(switches()).toEqual([]);
  expect(root().querySelector(".surface-set-note")!.textContent).toBe(
    "The project has no test surfaces yet. Import files or pick them on the context in the Site step. Open the Site step");
  click(byRole(root(), "button", "Open the Site step"));
  expect(onOpenSite).toHaveBeenCalledOnce();
});

import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ProtectsBox } from "./ProtectsBox";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const box = () => rendered!.container.querySelector<HTMLElement>(".input-box")!;

test("a criterion without test surfaces says what to add", () => {
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} />);
  expect(box().getAttribute("aria-label")).toBe("Test surfaces");
  expect(box().classList.contains("input-box-empty")).toBe(true);
  expect(box().querySelector(".input-box-hint")!.textContent).toBe("Windows or facades that need daylight.");
  expect(box().querySelector(".input-box-actions")!.textContent).toBe("Add test surfacesor drop them here");
  expect(box().querySelector(".input-box-required")!.textContent).toBe("Required");
});

test("the hint follows the criterion's mode", () => {
  rendered = renderForTest(<ProtectsBox files={[]} mode="irradiance" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} />);
  expect(box().querySelector(".input-box-hint")!.textContent).toBe("Roofs or facades that collect sun and sky energy, for example for solar panels.");
});

test("the criterion's files are listed with their triangle counts; dropped files are added to it and a remove button takes one out", async () => {
  const onAddFiles = vi.fn(async (_files: File[]) => [] as string[]);
  const onRemoveFile = vi.fn(async (_fileName: string) => null);
  rendered = renderForTest(<ProtectsBox files={[{ name: "roofs.ply", triangle_count: 2040 }, { name: "windows.ply", triangle_count: 12 }]} mode="daylight"
                                        onAddFiles={onAddFiles} onRemoveFile={onRemoveFile} disabledReason={null} />);
  expect([...box().querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["roofs.ply", "windows.ply"]);
  expect(box().querySelector(".input-file-detail")!.textContent).toBe("2 040 triangles");
  expect(box().querySelector(".input-box-hint")).toBeNull();
  const file = new File(["solid"], "facade.obj");
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  await act(async () => {
    box().dispatchEvent(drop);
  });
  expect(onAddFiles).toHaveBeenCalledWith([file]);
  await act(async () => click(box().querySelector('[aria-label="Remove windows.ply"]')!));
  expect(onRemoveFile).toHaveBeenCalledWith("windows.ply");
});

test("during a run the files cannot be added or removed; the panel's Run analysis says why, not the box", () => {
  rendered = renderForTest(<ProtectsBox files={[{ name: "roofs.ply", triangle_count: 2 }]} mode="daylight" onAddFiles={async () => []}
                                        onRemoveFile={async () => null} disabledReason="A run is in progress" />);
  expect(box().querySelector<HTMLButtonElement>(".input-add")!.disabled).toBe(true);
  expect(box().querySelector<HTMLButtonElement>(".input-remove")!.disabled).toBe(true);
  expect(box().textContent).not.toContain("A run is in progress");
});

test("use a file from another criterion: the stored files other criteria use are offered, each with a Use button", async () => {
  const onUseFile = vi.fn(async (_fileName: string) => null as string | null);
  rendered = renderForTest(<ProtectsBox files={[{ name: "roofs.ply", triangle_count: 2 }]} mode="daylight" onAddFiles={async () => []}
                                        onRemoveFile={async () => null} disabledReason={null} otherFiles={["windows.ply", "courtyard.obj"]}
                                        onUseFile={onUseFile} />);
  const reuse = rendered.container.querySelector<HTMLElement>(".protects-reuse")!;
  expect(reuse.querySelector(".protects-reuse-title")!.textContent).toBe("Use a file from another criterion");
  expect([...reuse.querySelectorAll(".protects-reuse-name")].map((name) => name.textContent)).toEqual(["windows.ply", "courtyard.obj"]);
  const useButton = reuse.querySelector<HTMLButtonElement>('[aria-label="Use windows.ply"]')!;
  expect(useButton.textContent).toBe("Use");
  await act(async () => click(useButton));
  expect(onUseFile).toHaveBeenCalledExactlyOnceWith("windows.ply");
});

test("with no file of another criterion to use, nothing more is offered", () => {
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null}
                                        otherFiles={[]} onUseFile={async () => null} />);
  expect(rendered.container.querySelector(".protects-reuse")).toBeNull();
});

test("a file the criterion could not use is said under the list", async () => {
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null}
                                        otherFiles={["windows.ply"]} onUseFile={async () => "A run is in progress"} />);
  await act(async () => click(rendered!.container.querySelector('[aria-label="Use windows.ply"]')!));
  expect(rendered.container.querySelector('.protects-reuse [role="alert"]')!.textContent).toBe("A run is in progress");
});

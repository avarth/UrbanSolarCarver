import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { byRole, click, renderForTest, type, type RenderedOverlay } from "../viewer_overlays/render_for_test";
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
  expect(box().querySelector(".input-box-hint")!.textContent).toBe("Windows or facades that need daylight. Flat panels; a curved or folded one is skipped.");
  expect(box().querySelector(".input-box-title-row button")!.textContent).toBe("Add test surfaces");
  expect(box().querySelector(".input-box-drop-hint")!.textContent).toBe("Or drop the files here.");
  expect(box().querySelector(".input-box-subtitle")).toBeNull();     // not optional: no muted line
});

test("the hint follows the criterion's mode", () => {
  rendered = renderForTest(<ProtectsBox files={[]} mode="irradiance" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} />);
  expect(box().querySelector(".input-box-hint")!.textContent).toBe("Roofs or facades that collect sun and sky energy, for example for solar panels. Flat panels; a curved or folded one is skipped.");
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

// Surface sets (design/test-surfaces-on-context.md): picking on the surroundings, a set's shown name, Rename and Edit picks.
const menuItems = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
const renameDialog = () => rendered!.container.querySelector<HTMLElement>('[role="dialog"]');

test("From surroundings sits beside the add button when the criterion can pick on the surroundings, and opens picking", () => {
  const onPick = vi.fn();
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null}
                                        onPickFromSurroundings={onPick} />);
  const actions = box().querySelector(".input-box-title-row .site-box-actions")!;
  expect([...actions.querySelectorAll("button")].map((button) => button.textContent)).toEqual(["Add test surfaces", "From surroundings"]);
  click(byRole(actions, "button", "From surroundings"));
  expect(onPick).toHaveBeenCalledOnce();
});

test("without surroundings there is no From surroundings; during a run it is off", () => {
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} />);
  expect(box().querySelector(".site-box-actions")).toBeNull();
  expect(box().textContent).not.toContain("From surroundings");
  rendered.unmount();
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null}
                                        disabledReason="A run is in progress" onPickFromSurroundings={() => {}} />);
  expect(byRole<HTMLButtonElement>(box(), "button", "From surroundings").disabled).toBe(true);
});

test("a set is listed by its shown name, with its stored name as the title; a picked set says so, and how many picks are gone", () => {
  rendered = renderForTest(<ProtectsBox files={[
    { name: "picked_1.ply", triangle_count: 6, shown_name: "South facades", picked: true, picks_lost: 2 },
    { name: "roofs.ply", triangle_count: 4, shown_name: "roofs.ply" },
    { name: "windows.ply", triangle_count: 1, shown_name: "Windows", picked: true, picks_lost: 1 },
  ]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} />);
  const names = [...box().querySelectorAll<HTMLElement>(".input-file-name")];
  expect(names.map((name) => name.textContent)).toEqual(["South facades", "roofs.ply", "Windows"]);
  expect(names.map((name) => name.getAttribute("title"))).toEqual(["picked_1.ply", null, "windows.ply"]);
  expect([...box().querySelectorAll(".input-file-detail")].map((detail) => detail.textContent)).toEqual([
    "6 triangles, picked on the surroundings", "4 triangles", "1 triangle, picked on the surroundings",
  ]);
  expect([...box().querySelectorAll(".input-file-row .input-box-problem")].map((line) => line.textContent)).toEqual([
    "2 picked faces are gone from the surroundings", "1 picked face is gone from the surroundings",
  ]);
  // The remove button still names the stored file
  expect(box().querySelector('[aria-label="Remove picked_1.ply"]')).not.toBeNull();
});

test("a set's menu offers Rename, and Edit picks only for a picked set", () => {
  const onEditPicks = vi.fn();
  rendered = renderForTest(<ProtectsBox files={[
    { name: "picked_1.ply", triangle_count: 6, shown_name: "South facades", picked: true },
    { name: "roofs.ply", triangle_count: 4 },
  ]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} onRenameSet={async () => null}
                                        onEditPicks={onEditPicks} />);
  const roofsMenu = byRole<HTMLButtonElement>(box(), "button", "Actions for roofs.ply");
  expect(roofsMenu.textContent).toBe("⋯");
  click(roofsMenu);
  expect(menuItems().map((item) => item.textContent)).toEqual(["Rename"]);
  click(roofsMenu);
  click(byRole(box(), "button", "Actions for South facades"));
  expect(menuItems().map((item) => item.textContent)).toEqual(["Rename", "Edit picks"]);
  click(menuItems()[1]);
  expect(onEditPicks).toHaveBeenCalledExactlyOnceWith("picked_1.ply");
});

test("without renaming there is no menu", () => {
  rendered = renderForTest(<ProtectsBox files={[{ name: "picked_1.ply", triangle_count: 6, picked: true }]} mode="daylight"
                                        onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} onEditPicks={() => {}} />);
  expect(box().querySelector(".action-menu-button")).toBeNull();
});

test("Rename asks for the set's new name and renames the stored file; the same name or none cannot be confirmed", async () => {
  const onRenameSet = vi.fn(async (_fileName: string, _name: string) => null as string | null);
  rendered = renderForTest(<ProtectsBox files={[{ name: "picked_1.ply", triangle_count: 6, shown_name: "Picked 1", picked: true }]} mode="daylight"
                                        onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} onRenameSet={onRenameSet} />);
  click(byRole(box(), "button", "Actions for Picked 1"));
  click(menuItems().find((item) => item.textContent === "Rename")!);
  const dialog = renameDialog()!;
  expect(dialog.querySelector("h2")!.textContent).toBe("Rename Picked 1");
  const field = dialog.querySelector<HTMLInputElement>('input[aria-label="Name of the new set"]')!;
  expect(field.value).toBe("Picked 1");
  const confirm = byRole<HTMLButtonElement>(dialog, "button", "Rename");
  expect(confirm.disabled).toBe(true);
  type(field, "  ");
  expect(confirm.disabled).toBe(true);
  type(field, "South facades");
  expect(confirm.disabled).toBe(false);
  await act(async () => click(confirm));
  expect(onRenameSet).toHaveBeenCalledExactlyOnceWith("picked_1.ply", "South facades");
  expect(renameDialog()).toBeNull();
});

test("a refused rename is said in the dialog, which stays open", async () => {
  rendered = renderForTest(<ProtectsBox files={[{ name: "roofs.ply", triangle_count: 4 }]} mode="daylight" onAddFiles={async () => []}
                                        onRemoveFile={async () => null} disabledReason={null} onRenameSet={async () => "Another set is named Roofs."} />);
  click(byRole(box(), "button", "Actions for roofs.ply"));
  click(menuItems()[0]);
  type(renameDialog()!.querySelector<HTMLInputElement>("input")!, "Roofs");
  await act(async () => click(byRole(renameDialog()!, "button", "Rename")));
  expect(renameDialog()!.querySelector('[role="alert"]')!.textContent).toBe("Another set is named Roofs.");
});

test("the files of other criteria are listed by their sets' names; Use still names the stored file", async () => {
  const onUseFile = vi.fn(async (_fileName: string) => null as string | null);
  rendered = renderForTest(<ProtectsBox files={[]} mode="daylight" onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null}
                                        otherFiles={["picked_1.ply", "windows.ply"]} onUseFile={onUseFile} setNames={{ "picked_1.ply": "South facades" }} />);
  const reuse = rendered.container.querySelector<HTMLElement>(".protects-reuse")!;
  expect([...reuse.querySelectorAll(".protects-reuse-name")].map((name) => name.textContent)).toEqual(["South facades", "windows.ply"]);
  await act(async () => click(reuse.querySelector('[aria-label="Use picked_1.ply"]')!));
  expect(onUseFile).toHaveBeenCalledExactlyOnceWith("picked_1.ply");
});

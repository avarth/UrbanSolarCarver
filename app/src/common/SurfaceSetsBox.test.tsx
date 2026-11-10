import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { InputFileInfo } from "../api_client/client";
import { byRole, click, renderForTest, type, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { listed, protectsHintOf, SurfaceSetsBox } from "./SurfaceSetsBox";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const box = () => rendered!.container.querySelector<HTMLElement>(".input-box")!;
const menuItems = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
const renameDialog = () => rendered!.container.querySelector<HTMLElement>('[role="dialog"]');

interface BoxOptions {
  files?: InputFileInfo[];
  onAddFiles?: (role: string, files: File[]) => Promise<string[]>;
  onRemoveFile?: (role: string, fileName: string) => Promise<string | null>;
  disabledReason?: string | null;
  onPickFromSurroundings?: () => void;
  onRenameSet?: (fileName: string, name: string) => Promise<string | null>;
  onEditPicks?: (fileName: string) => void;
}

function renderBox({ files = [], onAddFiles = async () => [], onRemoveFile = async () => null, disabledReason = null, onPickFromSurroundings,
                     onRenameSet = async () => null, onEditPicks = () => {} }: BoxOptions = {}) {
  rendered = renderForTest(<SurfaceSetsBox files={files} onAddFiles={onAddFiles} onRemoveFile={onRemoveFile} disabledReason={disabledReason}
                                           onPickFromSurroundings={onPickFromSurroundings} onRenameSet={onRenameSet} onEditPicks={onEditPicks} />);
}

test("an empty box says what test surfaces are, with Add files and, given context, From context", () => {
  const onPick = vi.fn();
  renderBox({ onPickFromSurroundings: onPick });
  expect(box().getAttribute("aria-labelledby")).not.toBeNull();
  expect(box().querySelector(".input-box-title")!.textContent).toBe("Test surfaces");
  expect(box().classList.contains("input-box-empty")).toBe(true);
  expect(box().querySelector(".input-box-hint")!.textContent).toBe(
    "Windows, facades or roofs whose sun or sky the carving protects, as files or as faces picked on the context. Each criterion and study chooses which of them to use.");
  expect(box().querySelector(".input-box-drop-hint")!.textContent).toBe("You can also drag files onto this box.");
  const actions = box().querySelector(".input-box-title-row .site-box-actions")!;
  expect([...actions.querySelectorAll("button")].map((button) => button.textContent)).toEqual(["Add files", "From context"]);
  click(byRole(actions, "button", "From context"));
  expect(onPick).toHaveBeenCalledOnce();
});

test("without context there is no From context; during a run neither button can be used", () => {
  renderBox();
  expect(box().querySelector(".site-box-actions")).toBeNull();
  expect(box().textContent).not.toContain("From context");
  expect(box().querySelector(".input-add")!.textContent).toBe("Add files");
  rendered!.unmount();
  renderBox({ disabledReason: "A run is in progress", onPickFromSurroundings: () => {} });
  expect(byRole<HTMLButtonElement>(box(), "button", "From context").disabled).toBe(true);
  expect(byRole<HTMLButtonElement>(box(), "button", "Add files").disabled).toBe(true);
});

test("dropped files are added as test surfaces; a set no one uses is removed by its button", async () => {
  const onAddFiles = vi.fn(async (_role: string, _files: File[]) => [] as string[]);
  const onRemoveFile = vi.fn(async (_role: string, _fileName: string) => null as string | null);
  renderBox({ files: [{ name: "roofs.ply", triangle_count: 2040, used_by: [] }], onAddFiles, onRemoveFile });
  const file = new File(["solid"], "facade.obj");
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  await act(async () => {
    box().dispatchEvent(drop);
  });
  expect(onAddFiles).toHaveBeenCalledExactlyOnceWith("test_surfaces", [file]);
  const remove = byRole<HTMLButtonElement>(box(), "button", "Remove roofs.ply");
  expect(remove.disabled).toBe(false);
  expect(remove.title).toBe("Remove roofs.ply from the project. The file is kept in the project folder, under inputs/removed\n2 040 triangles");
  await act(async () => click(remove));
  expect(onRemoveFile).toHaveBeenCalledExactlyOnceWith("test_surfaces", "roofs.ply");
});

test("the sets are listed by their shown names, with the stored name as the title, what picked them and who uses them", () => {
  renderBox({ files: [
    { name: "picked_1.ply", triangle_count: 6, shown_name: "South facades", picked: true, picks_lost: 2, used_by: ["Daylight on windows", "Shade study"] },
    { name: "roofs.ply", triangle_count: 4, shown_name: "roofs.ply", used_by: null },
  ] });
  const names = [...box().querySelectorAll<HTMLElement>(".input-file-name")];
  expect(names.map((name) => name.textContent)).toEqual(["South facades", "roofs.ply"]);
  expect(names.map((name) => name.getAttribute("title"))).toEqual(["picked_1.ply", null]);
  // What picked them and who uses them are in the remove button's title, under what the button does
  expect(box().querySelectorAll(".input-file-detail")).toHaveLength(0);
  expect(byRole<HTMLButtonElement>(box(), "button", "Remove South facades").title.split("\n")).toEqual([
    "Used by Daylight on windows and Shade study: switch it off there to remove it", "6 triangles, picked on the context",
  ]);
  expect(byRole<HTMLButtonElement>(box(), "button", "Remove roofs.ply").title.split("\n").slice(1)).toEqual(["4 triangles"]);
  expect([...box().querySelectorAll(".input-file-row .input-box-problem")].map((line) => line.textContent)).toEqual([
    "2 picked faces are gone from the context",
  ]);
});

test("a set in use cannot be removed: its remove button is off and says who uses it", async () => {
  const onRemoveFile = vi.fn(async (_role: string, _fileName: string) => null as string | null);
  renderBox({ files: [
    { name: "picked_1.ply", triangle_count: 6, shown_name: "South facades", used_by: ["Daylight on windows", "Solar heating", "Shade study"] },
    { name: "roofs.ply", triangle_count: 4, used_by: ["Solar heating"] },
  ], onRemoveFile });
  const southFacades = byRole<HTMLButtonElement>(box(), "button", "Remove South facades");
  expect(southFacades.disabled).toBe(true);
  expect(southFacades.title.split("\n")[0]).toBe("Used by Daylight on windows, Solar heating and Shade study: switch it off there to remove it");
  expect(byRole<HTMLButtonElement>(box(), "button", "Remove roofs.ply").title).toBe(
    "Used by Solar heating: switch it off there to remove it\n4 triangles");
  await act(async () => click(southFacades));
  expect(onRemoveFile).not.toHaveBeenCalled();
});

test("names are listed as A, A and B, A, B and C", () => {
  expect(listed([])).toBe("");
  expect(listed(["A"])).toBe("A");
  expect(listed(["A", "B"])).toBe("A and B");
  expect(listed(["A", "B", "C"])).toBe("A, B and C");
});

test("a set's menu offers Rename, and Edit picks only for a picked set while picking is possible", () => {
  const onEditPicks = vi.fn();
  const files: InputFileInfo[] = [{ name: "picked_1.ply", triangle_count: 6, shown_name: "South facades", picked: true }, { name: "roofs.ply", triangle_count: 4 }];
  renderBox({ files, onEditPicks, onPickFromSurroundings: () => {} });
  const roofsMenu = byRole<HTMLButtonElement>(box(), "button", "Actions for roofs.ply");
  expect(roofsMenu.textContent).toBe("⋯");
  click(roofsMenu);
  expect(menuItems().map((item) => item.textContent)).toEqual(["Rename"]);
  click(roofsMenu);
  click(byRole(box(), "button", "Actions for South facades"));
  expect(menuItems().map((item) => item.textContent)).toEqual(["Rename", "Edit picks"]);
  click(menuItems()[1]);
  expect(onEditPicks).toHaveBeenCalledExactlyOnceWith("picked_1.ply");
  // Without context (or outside Carve) a picked set cannot be edited
  rendered!.unmount();
  renderBox({ files, onEditPicks });
  click(byRole(box(), "button", "Actions for South facades"));
  expect(menuItems().map((item) => item.textContent)).toEqual(["Rename"]);
});

test("Rename asks for the set's new name and renames the stored file; the same name or none cannot be confirmed", async () => {
  const onRenameSet = vi.fn(async (_fileName: string, _name: string) => null as string | null);
  renderBox({ files: [{ name: "picked_1.ply", triangle_count: 6, shown_name: "Picked 1", picked: true }], onRenameSet });
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
  renderBox({ files: [{ name: "roofs.ply", triangle_count: 4 }], onRenameSet: async () => "Another set is named Roofs." });
  click(byRole(box(), "button", "Actions for roofs.ply"));
  click(menuItems()[0]);
  type(renameDialog()!.querySelector<HTMLInputElement>("input")!, "Roofs");
  await act(async () => click(byRole(renameDialog()!, "button", "Rename")));
  expect(renameDialog()!.querySelector('[role="alert"]')!.textContent).toBe("Another set is named Roofs.");
});

test("a mode's hint of what it protects ends with the note on flat panels", () => {
  expect(protectsHintOf("daylight")).toBe("Windows or facades that need daylight. Flat panels; a curved or folded one is skipped.");
  expect(protectsHintOf("irradiance")).toBe("Roofs or facades that collect sun and sky energy, for example for solar panels. Flat panels; a curved or folded one is skipped.");
});

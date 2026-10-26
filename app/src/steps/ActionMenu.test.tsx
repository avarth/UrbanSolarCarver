// The menu of actions behind a small button (a project's, a criterion card's): its items, an item that waits with its reason, the
// choice it reports and the keyboard. ProjectMenu.test.tsx covers its placement in the window and the project's dialogs.
import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const ITEMS: ActionMenuItem[] = [
  { key: "rename", label: "Rename" },
  { key: "duplicate", label: "Duplicate" },
  { key: "delete", label: "Delete", disabledReason: "A project needs at least one criterion." },
];

const menuButton = () => rendered!.container.querySelector<HTMLButtonElement>(".action-menu-button")!;
const menuItems = () => [...rendered!.container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
const menuItem = (label: string) => menuItems().find((item) => item.textContent === label)!;

function press(element: Element, key: string) {
  act(() => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

test("the menu lists its items, reports the one chosen and closes", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ActionMenu label="Actions for Daylight" symbol="⋯" items={ITEMS} onChoose={onChoose} />);
  expect(menuButton().getAttribute("aria-label")).toBe("Actions for Daylight");
  expect(menuButton().textContent).toBe("⋯");
  click(menuButton());
  expect(menuItems().map((item) => item.textContent)).toEqual(["Rename", "Duplicate", "Delete"]);
  click(menuItem("Duplicate"));
  expect(onChoose).toHaveBeenCalledExactlyOnceWith("duplicate");
  expect(menuItems()).toEqual([]);
});

test("an item with a reason waits: it is marked, says why and reports nothing", () => {
  const onChoose = vi.fn();
  rendered = renderForTest(<ActionMenu label="Actions for Daylight" symbol="⋯" items={ITEMS} onChoose={onChoose} />);
  click(menuButton());
  expect(menuItems().filter((item) => item.getAttribute("aria-disabled") === "true").map((item) => item.textContent)).toEqual(["Delete"]);
  expect(document.getElementById(menuItem("Delete").getAttribute("aria-describedby")!)!.textContent).toBe("A project needs at least one criterion.");
  click(menuItem("Delete"));
  expect(onChoose).not.toHaveBeenCalled();
});

test("the keyboard opens the menu on its first item, the arrows, Home and End move, Escape closes it and gives the focus back", () => {
  rendered = renderForTest(<ActionMenu label="Actions for Daylight" symbol="⋯" items={ITEMS} onChoose={() => {}} />);
  menuButton().focus();
  press(menuButton(), "ArrowDown");
  expect(document.activeElement).toBe(menuItem("Rename"));
  press(document.activeElement!, "ArrowUp");
  expect(document.activeElement).toBe(menuItem("Delete"));
  press(document.activeElement!, "Home");
  expect(document.activeElement).toBe(menuItem("Rename"));
  press(document.activeElement!, "End");
  expect(document.activeElement).toBe(menuItem("Delete"));
  press(document.activeElement!, "Escape");
  expect(menuItems()).toEqual([]);
  expect(document.activeElement).toBe(menuButton());
});

test("the menu closes when the page scrolls or the window is resized", () => {
  rendered = renderForTest(<ActionMenu label="Actions for Daylight" symbol="⋯" items={ITEMS} onChoose={() => {}} />);
  click(menuButton());
  act(() => window.dispatchEvent(new Event("scroll")));
  expect(menuItems()).toEqual([]);
  click(menuButton());
  act(() => window.dispatchEvent(new Event("resize")));
  expect(menuItems()).toEqual([]);
});

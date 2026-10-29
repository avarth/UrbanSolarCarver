import { afterEach, expect, test, vi } from "vitest";
import type { CriterionEntry } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriterionEditorHeader, type CriterionEditorHeaderProps } from "./CriterionEditorHeader";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const DAYLIGHT: CriterionEntry = {
  id: "2", name: "Daylight on windows", named_by_user: true, colour: "#cc6677", bypassed: false, energy_weighted: false, test_surface_files: ["windows.obj"],
  settings: { mode: "daylight" },
};
const LINE = "70 % of the score carved, 18 400 m³ removed, more than fits the line of the header";

function headerProps(overrides: Partial<CriterionEditorHeaderProps> = {}): CriterionEditorHeaderProps {
  return {
    entry: DAYLIGHT, line: LINE, position: 2, count: 3, onShowList: () => {}, onPrevious: () => {}, onNext: () => {}, disabledReason: null,
    deleteDisabledReason: null, onSetBypassed: () => {}, onChoose: () => {}, ...overrides,
  };
}

function renderHeader(overrides: Partial<CriterionEditorHeaderProps> = {}) {
  rendered = renderForTest(<CriterionEditorHeader {...headerProps(overrides)} />);
}

const header = () => rendered!.container.querySelector<HTMLElement>(".criterion-editor-header")!;
const button = (label: string) => [...header().querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === label || item.getAttribute("aria-label") === label);

test("the header shows the colour, name, mode symbol and the line, with the whole line as its title", () => {
  renderHeader();
  expect(header().querySelector<HTMLElement>(".criterion-card-swatch")!.style.background).not.toBe("");
  expect(header().querySelector(".criterion-editor-name")!.textContent).toBe("Daylight on windows");
  expect(header().querySelector(".mode-tile-symbol")).not.toBeNull();
  const line = header().querySelector(".criterion-editor-line")!;
  expect(line.textContent).toBe(LINE);
  expect(line.getAttribute("title")).toBe(LINE);
});

test("All criteria asks for the list; the position and the neighbours' buttons show with several criteria", () => {
  const onShowList = vi.fn(), onPrevious = vi.fn(), onNext = vi.fn();
  renderHeader({ onShowList, onPrevious, onNext });
  expect(header().querySelector(".criterion-editor-position")!.textContent).toBe("2 of 3");
  click(button("All criteria")!);
  click(button("Previous criterion")!);
  click(button("Next criterion")!);
  expect(onShowList).toHaveBeenCalledOnce();
  expect(onPrevious).toHaveBeenCalledOnce();
  expect(onNext).toHaveBeenCalledOnce();
});

test("the first criterion has no previous and the last no next, both disabled", () => {
  renderHeader({ position: 1 });
  expect(button("Previous criterion")!.disabled).toBe(true);
  expect(button("Next criterion")!.disabled).toBe(false);
  rendered!.rerender(<CriterionEditorHeader {...headerProps({ position: 3 })} />);
  expect(button("Next criterion")!.disabled).toBe(true);
  expect(button("Previous criterion")!.disabled).toBe(false);
});

test("with one criterion there is no position and no previous or next", () => {
  renderHeader({ position: 1, count: 1 });
  expect(header().querySelector(".criterion-editor-position")).toBeNull();
  expect(button("Previous criterion")).toBeUndefined();
  expect(button("Next criterion")).toBeUndefined();
  expect(button("All criteria")).toBeDefined();
});

test("the switch is named for the criterion and turning it off reports the criterion as bypassed", () => {
  const onSetBypassed = vi.fn();
  renderHeader({ onSetBypassed });
  const switchInput = header().querySelector<HTMLInputElement>('[role="switch"]')!;
  expect(switchInput.getAttribute("aria-label")).toBe("Use Daylight on windows");
  expect(switchInput.checked).toBe(true);
  click(switchInput);
  expect(onSetBypassed).toHaveBeenCalledExactlyOnceWith(true);
});

test("the menu offers Rename, Duplicate and Delete, Delete waiting with its own reason", () => {
  const onChoose = vi.fn();
  renderHeader({ onChoose, deleteDisabledReason: "A project needs at least one criterion." });
  const menuButton = header().querySelector<HTMLButtonElement>(".action-menu-button")!;
  expect(menuButton.getAttribute("aria-label")).toBe("Actions for Daylight on windows");
  click(menuButton);
  const items = [...header().querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
  expect(items.map((item) => item.textContent)).toEqual(["Rename", "Duplicate", "Delete"]);
  expect(items[2].getAttribute("aria-disabled")).toBe("true");
  expect(document.getElementById(items[2].getAttribute("aria-describedby")!)!.textContent).toBe("A project needs at least one criterion.");
  click(items[0]);
  expect(onChoose).toHaveBeenCalledExactlyOnceWith("rename");
});

test("during a run the switch and the menu items wait", () => {
  renderHeader({ disabledReason: "A run is in progress" });
  expect(header().querySelector<HTMLInputElement>('[role="switch"]')!.disabled).toBe(true);
  click(header().querySelector(".action-menu-button")!);
  expect([...header().querySelectorAll('[role="menuitem"]')].every((item) => item.getAttribute("aria-disabled") === "true")).toBe(true);
});

import { readFileSync } from "node:fs";
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
const LINE = "Removes 70 % of the obstruction, 18 400 m³, more than fits the line of the header";

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

test("the first criterion's previous and the last one's next wait without leaving the focus: aria-disabled, and a press does nothing", () => {
  const onPrevious = vi.fn(), onNext = vi.fn();
  renderHeader({ position: 1, onPrevious, onNext });
  expect(button("Previous criterion")!.getAttribute("aria-disabled")).toBe("true");
  expect(button("Previous criterion")!.disabled).toBe(false);              // a disabled button would drop the focus it has
  expect(button("Next criterion")!.getAttribute("aria-disabled")).toBeNull();
  click(button("Previous criterion")!);
  expect(onPrevious).not.toHaveBeenCalled();
  rendered!.rerender(<CriterionEditorHeader {...headerProps({ position: 3, onPrevious, onNext })} />);
  expect(button("Next criterion")!.getAttribute("aria-disabled")).toBe("true");
  expect(button("Previous criterion")!.getAttribute("aria-disabled")).toBeNull();
  click(button("Next criterion")!);
  expect(onNext).not.toHaveBeenCalled();
});

test("the name is whole, on a row of its own under the colour, symbol, switch and menu, with the whole name as its title", () => {
  const name = "Solar usefulness on alatini_testSrfs_solargains_with_a_long_tail_of_eighty_chars";
  renderHeader({ entry: { ...DAYLIGHT, name } });
  const nameElement = header().querySelector(".criterion-editor-name")!;
  expect(nameElement.textContent).toBe(name);
  expect(nameElement.getAttribute("title")).toBe(name);
  const identity = header().querySelector(".criterion-editor-identity")!;
  expect([...identity.children].map((child) => child.classList[0])).toEqual(["criterion-card-swatch", "mode-tile-symbol", "setting-switch", "action-menu", "criterion-editor-name"]);
  const css = readFileSync("src/steps/steps.css", "utf8");
  const nameRule = css.match(/\n\.criterion-editor-name\s*{([^}]*)}/)![1];
  expect(nameRule).toMatch(/-webkit-line-clamp:\s*2/);
  expect(nameRule).toMatch(/overflow-wrap:\s*anywhere/);
  expect(nameRule).toMatch(/grid-column:\s*1\s*\/\s*-1;\s*grid-row:\s*2/);
});

test("a polite live region in the header says the criterion's name and position once previous or next has changed it", () => {
  renderHeader();
  const region = header().querySelector<HTMLElement>('.visually-hidden[role="status"]')!;
  expect(region.textContent).toBe("");                                     // nothing said when the editor opens
  click(button("Next criterion")!);
  rendered!.rerender(<CriterionEditorHeader {...headerProps({ entry: { ...DAYLIGHT, id: "3", name: "Night cooling" }, position: 3 })} />);
  expect(region.textContent).toBe("Night cooling, 3 of 3");
  rendered!.rerender(<CriterionEditorHeader {...headerProps({ entry: { ...DAYLIGHT, id: "1", name: "Winter sun" }, position: 1 })} />);
  expect(region.textContent).toBe("Night cooling, 3 of 3");                // not a change made by previous or next
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

test("the sticky header stays over the controls that scroll under it, the period control's bubbles included", () => {
  const zIndexOf = (css: string, selector: string) => {
    const start = css.indexOf(`${selector} {`);
    return Number(/z-index:\s*(\d+)/.exec(css.slice(start, css.indexOf("}", start)))![1]);
  };
  const header = zIndexOf(readFileSync("src/steps/steps.css", "utf8"), ".criterion-editor-header");
  const bubble = zIndexOf(readFileSync("src/settings_form/settings_form.css", "utf8"), ".scale-strip-bubble");
  expect(header).toBeGreaterThan(bubble);
});

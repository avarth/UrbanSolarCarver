import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { StudyWithState } from "../api_client/client";
import { addStyleSheetForTest, click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { StudiesPanel, type StudiesPanelProps } from "./StudiesPanel";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function study(id: string, name: string, files: string[], state: StudyWithState["state"], reason: string | null = null,
               settings: Record<string, unknown> = {}): StudyWithState {
  return { entry: { id, name, named_by_user: false, colour: "#336699", metric: "sun_hours", settings, target: null, test_surface_files: files },
           state, reason, geometries: [] };
}

const STUDIES = [
  study("1", "Sun hours, 21 Dec", ["facades.obj", "windows.obj"], "current"),
  study("2", "Sky view factor", ["roofs.obj"], "not_run"),
  study("3", "Solar energy, 21 Jun", ["facades.obj"], "out_of_date"),
  study("4", "Overcast sky component", [], "refused", "Add study surfaces"),
];

function panelProps(overrides: Partial<StudiesPanelProps> = {}): StudiesPanelProps {
  return {
    studies: STUDIES, selectedId: "1", criteria: [], metrics: [], runDisabledReason: null, editDisabledReason: null, popoverStudyId: null,
    onSelect: () => {}, onToggleSettings: () => {}, onAdd: async () => null, onRun: () => {}, shownOnView: true, onShownOnViewChange: () => {}, ...overrides,
  };
}

const container = () => rendered!.container;
const rows = () => [...container().querySelectorAll<HTMLElement>(".study-row")];
const toggle = () => container().querySelector<HTMLButtonElement>(".studies-panel-toggle")!;

test("a study's whole name shows on up to two lines, and on hover, not cut on one line", async () => {
  const { readFileSync } = await import("node:fs");
  rendered = renderForTest(<StudiesPanel {...panelProps()} />);
  expect(rows().map((row) => row.querySelector<HTMLElement>(".study-row-name")!.title))
    .toEqual(["Sun hours, 21 Dec", "Sky view factor", "Solar energy, 21 Jun", "Overcast sky component"]);
  const nameRule = readFileSync("src/simulate/simulate.css", "utf8").match(/\.study-row-name\s*{([^}]*)}/)![1];
  expect(nameRule).toMatch(/-webkit-line-clamp: 2/);
  expect(nameRule).not.toMatch(/white-space: nowrap/);
});

test("a study row shows its files, Not run yet, Out of date or the reason it cannot run", () => {
  const onSelect = vi.fn();
  rendered = renderForTest(<StudiesPanel {...panelProps({ onSelect })} />);
  expect(rows().map((row) => row.querySelector(".study-row-name")!.textContent))
    .toEqual(["Sun hours, 21 Dec", "Sky view factor", "Solar energy, 21 Jun", "Overcast sky component"]);
  expect(rows().map((row) => row.querySelector(".study-row-line")!.textContent))
    .toEqual(["facades.obj, windows.obj", "Not run yet", "Out of date", "Add study surfaces"]);
  expect(rows().map((row) => (row.querySelector<HTMLElement>(".study-row-swatch")!.style.background))).toEqual(Array(4).fill("rgb(51, 102, 153)"));
  expect(rows().map((row) => row.getAttribute("aria-current"))).toEqual(["true", null, null, null]);
  click(rows()[1].querySelector(".study-row-select")!);
  expect(onSelect).toHaveBeenCalledExactlyOnceWith("2");
});

test("the line of a current study names the project's surfaces it samples after its files", () => {
  rendered = renderForTest(<StudiesPanel {...panelProps({ studies: [
    study("1", "Sun hours, 21 Dec", ["facades.obj"], "current", null, { surfaces_from: ["context", "ground"] }),
    study("2", "Sky view factor", [], "current", null, { surfaces_from: ["terrain"] }),
  ] })} />);
  expect(rows().map((row) => row.querySelector(".study-row-line")!.textContent))
    .toEqual(["facades.obj, the surroundings, the ground", "the terrain"]);
});

test("each row's settings button opens its popover, and says whether it is open", () => {
  const onToggleSettings = vi.fn();
  rendered = renderForTest(<StudiesPanel {...panelProps({ onToggleSettings, popoverStudyId: "2", popover: <div id="the-popover" /> })} />);
  const settingsButtons = rows().map((row) => row.querySelector<HTMLButtonElement>(".study-row-settings")!);
  expect(settingsButtons.map((button) => button.getAttribute("aria-label"))).toEqual([
    "Settings of Sun hours, 21 Dec", "Settings of Sky view factor", "Settings of Solar energy, 21 Jun", "Settings of Overcast sky component",
  ]);
  expect(settingsButtons.map((button) => button.getAttribute("aria-expanded"))).toEqual(["false", "true", "false", "false"]);
  expect(container().querySelector("#the-popover")).not.toBeNull();
  click(settingsButtons[0]);
  expect(onToggleSettings).toHaveBeenCalledExactlyOnceWith("1");
});

test("the panel collapses to an icon and opens again", () => {
  rendered = renderForTest(<StudiesPanel {...panelProps({ popoverStudyId: "1", popover: <div id="the-popover" /> })} />);
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  expect(toggle().getAttribute("aria-label")).toBe("Studies");
  expect(document.getElementById(toggle().getAttribute("aria-controls")!)).not.toBeNull();
  click(toggle());
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  expect(toggle().hasAttribute("aria-controls")).toBe(false);
  expect(rows()).toEqual([]);
  expect(container().querySelector("#the-popover")).toBeNull();
  expect(container().textContent).not.toContain("Add study");
  click(toggle());
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  expect(rows()).toHaveLength(4);
});

test("Run waits with its reason; Add study and the studies wait while a run of the project goes on", () => {
  rendered = renderForTest(<StudiesPanel {...panelProps({ runDisabledReason: "A carving run is in progress", editDisabledReason: "A carving run is in progress" })} />);
  const run = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Run")!;
  expect(run.disabled).toBe(true);
  expect(document.getElementById(run.getAttribute("aria-describedby")!)!.textContent).toBe("A carving run is in progress");
  const add = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Add study")!;
  expect(add.disabled).toBe(true);
});

test("an Add study the service refuses says why", async () => {
  const onAdd = vi.fn(async () => "There is no criterion '9'.");
  rendered = renderForTest(<StudiesPanel {...panelProps({ studies: [], criteria: [], metrics: [
    { name: "sky_view", label: "Sky view factor", unit: "%", needs_epw: false, available: true, default_settings: {} },
  ], onAdd })} />);
  const add = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Add study")!;
  click(add);
  await act(async () => container().querySelector<HTMLButtonElement>('[role="menuitem"]')!.click());
  expect(onAdd).toHaveBeenCalledExactlyOnceWith({ metric: "sky_view" });
  expect(container().querySelector('[role="alert"]')!.textContent).toBe("There is no criterion '9'.");
});

test("a refused study's reason wraps in its row and is the row line's title, so its last words are read; other lines stay on one line", () => {
  const reason = "The test surfaces are too far from the maximum volume to sample the sky. A spacing of 2 m or more fits.";
  const removeStyles = addStyleSheetForTest("src/simulate/simulate.css");
  try {
    rendered = renderForTest(<StudiesPanel {...panelProps({ studies: [study("1", "Sky view factor", [], "refused", reason), study("2", "Sun hours, 21 Dec", ["facades.obj"], "current")] })} />);
    const [refused, current] = [...container().querySelectorAll<HTMLElement>(".study-row-line")];
    expect(refused.textContent).toBe(reason);
    expect(refused.title).toBe(reason);
    expect(getComputedStyle(refused).whiteSpace).toBe("normal");
    expect(getComputedStyle(current).whiteSpace).toBe("nowrap");
    expect(current.title).toBe("facades.obj");
  } finally {
    removeStyles();
  }
});

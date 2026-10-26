import { afterEach, expect, test, vi } from "vitest";
import { initialFormState, type FormState } from "../settings_form/form_state";
import { CRITERION_KEYS, MODES, SCHEMA } from "../steps/project_workspace_for_test";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriterionPanel, type CriterionPanelProps } from "./CriterionPanel";
import { usePanelSections } from "./PanelSection";
import { PANEL_SECTIONS, type PanelSectionId } from "./section_summaries";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function formFor(mode: string): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode }, gridPlan: null });
}

// The tests of the parts read every part of the panel: all four sections open.
function panelProps(overrides: Partial<CriterionPanelProps> = {}): CriterionPanelProps {
  return {
    openSections: new Set(PANEL_SECTIONS), onToggleSection: () => {}, onOpenSections: () => {},
    testSurfaces: [{ name: "windows.ply", triangle_count: 12 }], onAddTestSurfaces: async () => [], onRemoveTestSurface: async () => null,
    form: formFor("time-based"), stepErrors: [], criterionKeys: CRITERION_KEYS, onChange: () => {}, onChooseMode: () => {}, disabledReason: null,
    weatherDropZone: null, carvingRule: <div className="carving-rule-for-test">carving rule</div>,
    ...overrides,
  };
}

const find = (selector: string) => rendered!.container.querySelector<HTMLElement>(selector);
const follows = (earlier: Element, later: Element) => (earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

test("the panel holds the test surfaces, the mode tiles, the criterion's settings and the carving rule, in that order, and no Run analysis", () => {
  rendered = renderForTest(<CriterionPanel {...panelProps()} />);
  const parts = [find(".input-box"), find('[role="radiogroup"]'), find('[data-setting="start_month"]'), find(".carving-rule-for-test")];
  expect(parts.every((part) => part !== null)).toBe(true);
  expect([...rendered.container.querySelectorAll("button")].map((button) => button.textContent)).not.toContain("Run analysis");
  for (let index = 1; index < parts.length; index++) expect(follows(parts[index - 1]!, parts[index]!)).toBe(true);
  expect(find(".input-box h3")!.textContent).toBe("Test surfaces");
  expect(find(".input-file-name")!.textContent).toBe("windows.ply");
});

test("the criterion's settings leave out the shared ones, which Site and grid shows", () => {
  rendered = renderForTest(<CriterionPanel {...panelProps()} />);
  expect(find('[data-setting="start_month"]')).not.toBeNull();
  for (const shared of ["voxel_size", "north_deg", "ray_batch_size", "context_blocks_rays"]) expect(find(`[data-setting="${shared}"]`), shared).toBeNull();
});

test("a group with only folded settings in the panel is a fold that says it holds settings, not a bare heading", () => {
  rendered = renderForTest(<CriterionPanel {...panelProps({ form: formFor("daylight") })} />);
  expect([...rendered.container.querySelectorAll(".setting-group-title")].map((title) => title.textContent)).toEqual([]);
  expect([...rendered.container.querySelectorAll(".settings-step .setting-fold")].map((fold) => fold.textContent)).toEqual(["Detail settings"]);
});

test("a tile chooses the criterion's mode; a message of the criterion's save that names no setting is shown in the panel", () => {
  const onChooseMode = vi.fn();
  rendered = renderForTest(<CriterionPanel {...panelProps({ onChooseMode, stepErrors: ["Add a weather file to run this mode"] })} />);
  click([...rendered.container.querySelectorAll('[role="radio"]')][4]);
  expect(onChooseMode).toHaveBeenCalledWith("daylight");
  expect(find(".step-error")!.textContent).toBe("Add a weather file to run this mode");
  expect(rendered.container.textContent).toContain("Choosing a mode fills its starting values in the settings below.");
});

type PanelWithoutSections = Omit<CriterionPanelProps, "openSections" | "onToggleSection" | "onOpenSections">;

/** The panel with the open sections a step keeps (CriteriaStep keeps them with usePanelSections). */
function PanelInStep(props: PanelWithoutSections) {
  return <CriterionPanel {...props} {...usePanelSections(null)} />;
}

const sectionHeader = (id: PanelSectionId) => find(`.panel-section[data-section="${id}"] .panel-section-header`)!;
const sectionSummary = (id: PanelSectionId) => find(`.panel-section[data-section="${id}"] .panel-section-summary`);
const sectionOpen = (id: PanelSectionId) => sectionHeader(id).getAttribute("aria-expanded") === "true";
const isWarning = (element: Element) => element.classList.contains("panel-section-summary-problem");

test("the panel shows four sections with test surfaces and carving open", () => {
  rendered = renderForTest(<PanelInStep {...panelProps()} />);
  const headers = [...rendered.container.querySelectorAll<HTMLButtonElement>(".panel-section-header")];
  expect(headers.map((header) => header.querySelector(".panel-section-title")!.textContent)).toEqual(["Test surfaces", "Mode", "Settings", "Carving rule"]);
  expect(headers.map((header) => header.getAttribute("aria-expanded"))).toEqual(["true", "false", "false", "true"]);
  // An open section's header names its content; a closed section has none.
  expect(document.getElementById(sectionHeader("test_surfaces").getAttribute("aria-controls")!)!.querySelector(".input-box")).not.toBeNull();
  expect(sectionHeader("mode").hasAttribute("aria-controls")).toBe(false);
  expect(find('[role="radiogroup"]')).toBeNull();
  expect(find('[data-setting="start_month"]')).toBeNull();
  expect(find(".carving-rule-for-test")).not.toBeNull();
  click(sectionHeader("mode"));
  expect(sectionOpen("mode")).toBe(true);
  expect(find('[role="radiogroup"]')).not.toBeNull();
  click(sectionHeader("carving"));
  expect(sectionOpen("carving")).toBe(false);
  expect(find(".carving-rule-for-test")).toBeNull();
});

test("a closed section shows its summary", () => {
  const daylight = { ...formFor("daylight"), userValues: { carve_fraction: 0.7 } };
  rendered = renderForTest(<PanelInStep {...panelProps({ form: daylight })} />);
  expect(sectionSummary("test_surfaces")).toBeNull();                 // open: no summary
  expect(sectionSummary("mode")!.textContent).toBe("Daylight");
  expect(sectionSummary("settings")!.textContent).toBe("Starting values");
  click(sectionHeader("carving"));
  expect(sectionSummary("carving")!.textContent).toBe("Carve 70 %");
  click(sectionHeader("test_surfaces"));
  expect(sectionSummary("test_surfaces")!.textContent).toBe("windows.ply");
  expect(sectionHeader("mode").textContent).toBe("ModeDaylight");      // in the header, after the title
  rendered.unmount();
  const timeBased = { ...formFor("time-based"), userValues: { start_hour: 7, end_hour: 19 } };
  rendered = renderForTest(<PanelInStep {...panelProps({ form: timeBased })} />);
  expect(sectionSummary("settings")!.textContent).toBe("21 Dec, 7 to 19 h");
  expect(isWarning(sectionSummary("settings")!)).toBe(false);
});

test("a criterion without test surfaces opens its test surfaces section; closed, it says none yet in the warning style", () => {
  rendered = renderForTest(<PanelInStep {...panelProps()} />);
  click(sectionHeader("test_surfaces"));
  expect(sectionOpen("test_surfaces")).toBe(false);
  expect(isWarning(sectionSummary("test_surfaces")!)).toBe(false);
  rendered.rerender(<PanelInStep {...panelProps({ testSurfaces: [] })} />);       // the last file goes
  expect(sectionOpen("test_surfaces")).toBe(true);
  click(sectionHeader("test_surfaces"));                                         // the user may close it again
  expect(sectionOpen("test_surfaces")).toBe(false);
  expect(sectionSummary("test_surfaces")!.textContent).toBe("None yet");
  expect(isWarning(sectionSummary("test_surfaces")!)).toBe(true);
  expect(sectionSummary("test_surfaces")!.querySelector(".setting-error-icon")).not.toBeNull();       // a warning icon, not the colour alone
  expect(sectionSummary("mode")!.querySelector(".setting-error-icon")).toBeNull();
});

test("a criterion that is off needs no test surfaces: none is no problem, and the section stays as it is", () => {
  rendered = renderForTest(<PanelInStep {...panelProps({ testSurfacesNeeded: false })} />);
  click(sectionHeader("test_surfaces"));
  rendered.rerender(<PanelInStep {...panelProps({ testSurfacesNeeded: false, testSurfaces: [] })} />);
  expect(sectionOpen("test_surfaces")).toBe(false);
  expect(sectionSummary("test_surfaces")!.textContent).toBe("None yet");
  expect(isWarning(sectionSummary("test_surfaces")!)).toBe(false);
});

test("inside the sections the test surfaces box does not repeat the section's title, which names it for screen readers", () => {
  rendered = renderForTest(<PanelInStep {...panelProps()} />);
  const boxTitle = find('.panel-section[data-section="test_surfaces"] .input-box h3')!;
  expect(boxTitle.textContent).toBe("Test surfaces");
  expect(boxTitle.classList.contains("visually-hidden")).toBe(true);
  expect(find(".input-box .input-add")).not.toBeNull();              // its Add button stays
});

test("a field error of the criterion's save opens the section that holds the field; the weather box and the values reset open Mode", () => {
  rendered = renderForTest(<PanelInStep {...panelProps()} />);
  expect(sectionOpen("settings")).toBe(false);
  rendered.rerender(<PanelInStep {...panelProps({ form: { ...formFor("time-based"), fieldErrors: { end_hour: "Input should be less than 24" } } })} />);
  expect(sectionOpen("settings")).toBe(true);
  expect(sectionOpen("mode")).toBe(false);
  click(sectionHeader("settings"));
  expect(sectionSummary("settings")!.textContent).toBe("1 setting to fix");
  expect(isWarning(sectionSummary("settings")!)).toBe(true);
  rendered.rerender(<PanelInStep {...panelProps({ weatherDropZone: <div className="weather-box-for-test" /> })} />);
  expect(sectionOpen("mode")).toBe(true);
  expect(find('.panel-section[data-section="mode"] .weather-box-for-test')).not.toBeNull();
  click(sectionHeader("mode"));
  expect(isWarning(sectionSummary("mode")!)).toBe(true);
  rendered.unmount();
  rendered = renderForTest(<PanelInStep {...panelProps()} />);
  rendered.rerender(<PanelInStep {...panelProps({ form: { ...formFor("time-based"), valuesResetByModeChange: { settings: ["max_slope_deg"], mode: "time-based" } } })} />);
  expect(sectionOpen("mode")).toBe(true);
  expect(find('.panel-section[data-section="mode"] .mode-values-reset')).not.toBeNull();
});

test("a request to open a section (a link to a setting) opens it, once per request", () => {
  function PanelWithRequest(props: PanelWithoutSections & { request: { section: PanelSectionId } | null }) {
    const { request, ...panel } = props;
    return <CriterionPanel {...panel} {...usePanelSections(request)} />;
  }
  rendered = renderForTest(<PanelWithRequest {...panelProps()} request={{ section: "settings" }} />);
  expect(sectionOpen("settings")).toBe(true);                         // also asked for as the step opens
  click(sectionHeader("settings"));
  const request = { section: "settings" as const };
  rendered.rerender(<PanelWithRequest {...panelProps()} request={request} />);
  expect(sectionOpen("settings")).toBe(true);
  expect(find('[data-setting="start_month"]')).not.toBeNull();
  click(sectionHeader("settings"));
  rendered.rerender(<PanelWithRequest {...panelProps()} request={request} />);    // the same request again: done already
  expect(sectionOpen("settings")).toBe(false);
});

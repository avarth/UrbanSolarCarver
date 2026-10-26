import { afterEach, expect, test, vi } from "vitest";
import { initialFormState, type FormState } from "../settings_form/form_state";
import { CRITERION_KEYS, MODES, SCHEMA } from "../steps/project_workspace_for_test";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriterionPanel, type CriterionPanelProps } from "./CriterionPanel";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function formFor(mode: string): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode }, gridPlan: null });
}

function panelProps(overrides: Partial<CriterionPanelProps> = {}): CriterionPanelProps {
  return {
    testSurfaces: [{ name: "windows.ply", triangle_count: 12 }], onAddTestSurfaces: async () => [], onRemoveTestSurface: async () => null,
    form: formFor("time-based"), stepErrors: [], criterionKeys: CRITERION_KEYS, onChange: () => {}, onChooseMode: () => {}, disabledReason: null,
    weatherDropZone: null, carvingRule: <div className="carving-rule-for-test">carving rule</div>,
    runAnalysis: <button type="button">Run analysis</button>, ...overrides,
  };
}

const find = (selector: string) => rendered!.container.querySelector<HTMLElement>(selector);
const follows = (earlier: Element, later: Element) => (earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

test("the panel holds the test surfaces, the mode tiles, the criterion's settings, the carving rule and Run analysis, in that order", () => {
  rendered = renderForTest(<CriterionPanel {...panelProps()} />);
  const runButton = [...rendered.container.querySelectorAll("button")].find((button) => button.textContent === "Run analysis")!;
  const parts = [find(".input-box"), find('[role="radiogroup"]'), find('[data-setting="start_month"]'), find(".carving-rule-for-test"), runButton];
  expect(parts.every((part) => part !== null)).toBe(true);
  for (let index = 1; index < parts.length; index++) expect(follows(parts[index - 1]!, parts[index]!)).toBe(true);
  expect(find(".input-box h3")!.textContent).toBe("Protects");
  expect(find(".input-file-name")!.textContent).toBe("windows.ply");
});

test("the criterion's settings leave out the shared ones, which Site and grid shows", () => {
  rendered = renderForTest(<CriterionPanel {...panelProps()} />);
  expect(find('[data-setting="start_month"]')).not.toBeNull();
  for (const shared of ["voxel_size", "north_deg", "ray_batch_size", "context_blocks_rays"]) expect(find(`[data-setting="${shared}"]`), shared).toBeNull();
});

test("a tile chooses the criterion's mode; a message of the criterion's save that names no setting is shown in the panel", () => {
  const onChooseMode = vi.fn();
  rendered = renderForTest(<CriterionPanel {...panelProps({ onChooseMode, stepErrors: ["Add a weather file to run this mode"] })} />);
  click([...rendered.container.querySelectorAll('[role="radio"]')][4]);
  expect(onChooseMode).toHaveBeenCalledWith("daylight");
  expect(find(".step-error")!.textContent).toBe("Add a weather file to run this mode");
  expect(rendered.container.textContent).toContain("Choosing a mode fills its starting values in the settings below.");
});

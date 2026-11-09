import { afterEach, expect, test, vi } from "vitest";
import { initialFormState } from "../settings_form/form_state";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CRITERION_KEYS, MODES, SCHEMA } from "./project_workspace_for_test";
import { ProjectSettingsButton, ProjectSettingsDialog } from "./ProjectSettingsDialog";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const PLAN_WITHIN_BUDGET = { resolution: 62, voxel_size: 1, total_voxels: 238328, extent: 62, budget_voxels: 500000000 };
const form = initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based" }, gridPlan: PLAN_WITHIN_BUDGET });
// The window is drawn into the page's body, not into the container.
const dialog = () => document.body.querySelector<HTMLElement>("[role='dialog']");
const field = (setting: string) => dialog()!.querySelector<HTMLElement>(`[data-setting="${setting}"]`);

function renderDialog(overrides: Partial<Parameters<typeof ProjectSettingsDialog>[0]> = {}) {
  const props = { form, stepErrors: [], criterionKeys: CRITERION_KEYS, onChange: () => {}, disabledReason: null, inputRoles: [],
                  onClose: () => {}, ...overrides };
  rendered = renderForTest(<ProjectSettingsDialog {...props} />);
  return props;
}

test("the window shows only the shared settings, with the grid line under Voxel size", () => {
  renderDialog();
  expect(dialog()!.querySelector("h2")!.textContent).toBe("Project settings");
  expect(field("voxel_size")).not.toBeNull();
  expect(field("north_deg")).not.toBeNull();
  for (const ofTheCriterion of ["start_month", "time_basis", "sun_steps_per_hour", "rays_per_patch"]) expect(field(ofTheCriterion), ofTheCriterion).toBeNull();
  for (const ofAStep of ["floor_height", "final_mesh_format"]) expect(field(ofAStep), ofAStep).toBeNull();
  expect([...field("voxel_size")!.querySelectorAll(".setting-note")].map((note) => note.textContent))
    .toContain("62 voxels per side, 238 328 in total");
  expect(dialog()!.textContent).toContain("These settings apply to every criterion. A change puts every criterion out of date.");
});

test("the surroundings switch is greyed out with the reason until the project has surroundings or terrain", () => {
  renderDialog();
  expect(field("context_blocks_rays")!.querySelector<HTMLInputElement>("input")!.disabled).toBe(true);
  expect(field("context_blocks_rays")!.textContent).toContain("Add existing surroundings or terrain in Site to use this.");
  rendered!.unmount();
  renderDialog({ inputRoles: ["terrain"] });
  expect(field("context_blocks_rays")!.querySelector<HTMLInputElement>("input")!.disabled).toBe(false);
});

test("a message of the shared settings' save that names no setting is shown in the window", () => {
  renderDialog({ stepErrors: ["Add a weather file to run this mode"] });
  expect(dialog()!.querySelector(".step-error")!.textContent).toBe("Add a weather file to run this mode");
});

test("while a run is in progress the fields wait and say why", () => {
  renderDialog({ disabledReason: "A run is in progress" });
  expect(dialog()!.querySelector(".step-reason")!.textContent).toBe("A run is in progress");
  expect(field("north_deg")!.querySelector<HTMLInputElement>("input[type='number']")!.disabled).toBe(true);
});

test("Done and × close the window, which ends with the settings", () => {
  const onClose = vi.fn();
  renderDialog({ onClose });
  expect([...dialog()!.querySelectorAll("button")].map((button) => button.textContent)).not.toContain("Envelope and massing");
  click([...dialog()!.querySelectorAll("button")].find((button) => button.textContent === "Done")!);
  click(dialog()!.querySelector("button[aria-label='Close']")!);
  expect(onClose).toHaveBeenCalledTimes(2);
});

test("the Settings button gives the summary in its tooltip and the ! of a step row while a shared setting is to fix", () => {
  const onOpen = vi.fn();
  rendered = renderForTest(<ProjectSettingsButton summary="North 10°, 0.5 m voxels" settingsToFix={0} open={false} onOpen={onOpen} />);
  const button = rendered.container.querySelector("button")!;
  expect(button.textContent).toBe("Settings");
  expect(button.title).toBe("North 10°, 0.5 m voxels. Opens the settings every criterion shares.");
  expect(button.getAttribute("aria-label")).toBeNull();
  expect(button.querySelector(".step-mark-error")).toBeNull();
  click(button);
  expect(onOpen).toHaveBeenCalledOnce();
  rendered.rerender(<ProjectSettingsButton summary="North 10°, 0.5 m voxels" settingsToFix={2} open={false} onOpen={onOpen} />);
  expect(button.querySelector(".step-mark-error")!.textContent).toBe("!");
  expect(button.getAttribute("aria-label")).toBe("Settings, 2 settings to fix");
});

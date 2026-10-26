import { afterEach, expect, test } from "vitest";
import { initialFormState } from "../settings_form/form_state";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CRITERION_KEYS, MODES, SCHEMA } from "./project_workspace_for_test";
import { SiteAndGridStep } from "./SiteAndGridStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const PLAN_WITHIN_BUDGET = { resolution: 62, voxel_size: 1, total_voxels: 238328, extent: 62, budget_voxels: 500000000 };
const form = initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based" }, gridPlan: PLAN_WITHIN_BUDGET });
const field = (setting: string) => rendered!.container.querySelector<HTMLElement>(`[data-setting="${setting}"]`);

test("site and grid shows only shared settings", () => {
  rendered = renderForTest(<SiteAndGridStep form={form} stepErrors={[]} criterionKeys={CRITERION_KEYS} onChange={() => {}} disabledReason={null} />);
  expect(field("voxel_size")).not.toBeNull();
  expect(field("north_deg")).not.toBeNull();
  for (const ofTheCriterion of ["start_month", "time_basis", "sun_steps_per_hour"]) expect(field(ofTheCriterion), ofTheCriterion).toBeNull();
  // The grid budget line under Voxel size.
  expect([...field("voxel_size")!.querySelectorAll(".setting-note")].map((note) => note.textContent))
    .toContain("62 voxels per side, 238 328 in total");
});

test("a message of the shared settings' save that names no setting is shown in the step", () => {
  rendered = renderForTest(<SiteAndGridStep form={form} stepErrors={["Add a weather file to run this mode"]} criterionKeys={CRITERION_KEYS} onChange={() => {}}
                                            disabledReason={null} />);
  expect(rendered.container.querySelector(".step-error")!.textContent).toBe("Add a weather file to run this mode");
});

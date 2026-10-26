import { afterEach, expect, test } from "vitest";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriteriaStep } from "./CriteriaStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

test("one criterion shows no list chrome", () => {
  rendered = renderForTest(<CriteriaStep panel={<div className="criterion-panel">Daylight on windows.ply</div>} />);
  const step = rendered.container.querySelector(".criteria-step")!;
  expect(step.querySelector(".criterion-panel")!.textContent).toBe("Daylight on windows.ply");      // the panel open at once
  expect(step.querySelector(".criterion-list, .criterion-card, [role='list'], [role='listitem']")).toBeNull();
  expect(step.querySelector("[role='switch'], [draggable='true']")).toBeNull();                      // no bypass toggle, no drag handle
  expect(step.textContent).not.toContain("Add another criterion");
  expect(step.textContent).not.toContain("Add criterion");
});

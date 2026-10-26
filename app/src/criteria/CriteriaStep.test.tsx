import { afterEach, expect, test } from "vitest";
import type { CriterionEntry } from "../api_client/client";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { CriteriaStep } from "./CriteriaStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const DAYLIGHT: CriterionEntry = {
  id: "1", name: "Daylight on windows.ply", named_by_user: false, colour: "#4477aa", bypassed: false, test_surface_files: ["windows.ply"],
  settings: { mode: "daylight" },
};

test("one criterion shows no list chrome", () => {
  rendered = renderForTest(<CriteriaStep criteria={[DAYLIGHT]} selectedId="1"
                                         panelOf={(criterion) => <div className="criterion-panel">{criterion?.name}</div>} />);
  const step = rendered.container.querySelector(".criteria-step")!;
  expect(step.querySelector(".criterion-panel")!.textContent).toBe("Daylight on windows.ply");      // the panel open at once
  expect(step.querySelector(".criterion-list, .criterion-card, [role='list'], [role='listitem']")).toBeNull();
  expect(step.querySelector("[role='switch'], [draggable='true']")).toBeNull();                      // no bypass toggle, no drag handle
  expect(step.textContent).not.toContain("Add another criterion");
  expect(step.textContent).not.toContain("Add criterion");
});

test("a project that lists no criterion still shows a panel, for the settings it holds", () => {
  rendered = renderForTest(<CriteriaStep criteria={[]} selectedId="" panelOf={(criterion) => <div className="criterion-panel">{String(criterion)}</div>} />);
  expect(rendered.container.querySelector(".criterion-panel")!.textContent).toBe("null");
});

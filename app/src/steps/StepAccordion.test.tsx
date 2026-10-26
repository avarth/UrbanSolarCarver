import { afterEach, expect, test, vi } from "vitest";
import { addStyleSheetForTest, click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { StepAccordion, type AccordionStep } from "./StepAccordion";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const STEPS: AccordionStep[] = [
  { name: "inputs", title: "Inputs", summary: "1 volume, weather", mark: "done", notUsableYet: null, content: <p>inputs content</p> },
  { name: "site_and_grid", title: "Site and grid", summary: "1 setting to fix", mark: "error", notUsableYet: null, content: <p>site and grid content</p> },
  { name: "envelope_and_massing", title: "Envelope and massing", summary: "Not built yet", mark: "none", notUsableYet: "Run the analysis in Criteria before building the envelope and massing",
    content: <p>envelope content</p> },
];

function rowOf(container: HTMLElement, title: string): HTMLElement {
  return [...container.querySelectorAll<HTMLElement>(".step")].find((row) => row.querySelector(".step-title")?.textContent === title)!;
}

test("closed steps show their summary, the open one its content; a click opens another step", () => {
  const onOpenStep = vi.fn();
  rendered = renderForTest(<StepAccordion steps={STEPS} openStep="inputs" onOpenStep={onOpenStep} pinnedAction={null} />);
  const inputs = rowOf(rendered.container, "Inputs");
  expect(inputs.querySelector(".step-summary")).toBeNull();
  expect(inputs.textContent).toContain("inputs content");
  expect(inputs.querySelector("button")!.getAttribute("aria-expanded")).toBe("true");
  expect(rowOf(rendered.container, "Envelope and massing").textContent).toContain("Not built yet");
  expect(rendered.container.textContent).not.toContain("envelope content");
  click(rowOf(rendered.container, "Envelope and massing").querySelector("button")!);
  expect(onOpenStep).toHaveBeenCalledWith("envelope_and_massing");
});

test("each row starts with its state mark: a tick, a red !, an accent ring on the open step", () => {
  rendered = renderForTest(<StepAccordion steps={STEPS} openStep="envelope_and_massing" onOpenStep={() => {}} pinnedAction={null} />);
  expect(rowOf(rendered.container, "Inputs").querySelector(".step-mark-done svg")).not.toBeNull();
  expect(rowOf(rendered.container, "Site and grid").querySelector(".step-mark-error")!.textContent).toBe("!");
  expect(rowOf(rendered.container, "Envelope and massing").querySelector(".step-mark-open")).not.toBeNull();
});

test("a setting to fix stays in the summary while its step is open, in the error style", () => {
  rendered = renderForTest(<StepAccordion steps={STEPS} openStep="site_and_grid" onOpenStep={() => {}} pinnedAction={null} />);
  const summary = rowOf(rendered.container, "Site and grid").querySelector(".step-summary")!;
  expect(summary.textContent).toBe("1 setting to fix");
  expect(summary.classList.contains("step-summary-error")).toBe(true);
});

test("a step that cannot be used yet opens and says why", () => {
  rendered = renderForTest(<StepAccordion steps={STEPS} openStep="envelope_and_massing" onOpenStep={() => {}} pinnedAction={<button>Run analysis</button>} />);
  const envelope = rowOf(rendered.container, "Envelope and massing");
  expect(envelope.textContent).toContain("Run the analysis in Criteria before building the envelope and massing");
  expect(envelope.textContent).not.toContain("envelope content");
  expect(rendered.container.querySelector(".step-pinned-action")!.textContent).toBe("Run analysis");
});

test("the pinned action area takes at most half the panel and scrolls, so the step list keeps the other half (UX 12, 200 % zoom)", () => {
  const removeStyleSheet = addStyleSheetForTest("src/steps/steps.css");
  try {
    rendered = renderForTest(<StepAccordion steps={STEPS} openStep="inputs" onOpenStep={() => {}} pinnedAction={<p>A long list of warnings</p>} />);
    const pinned = getComputedStyle(rendered.container.querySelector(".step-pinned-action")!);
    expect(pinned.maxHeight).toBe("50%");
    expect(pinned.overflowY).toBe("auto");
    const stepList = getComputedStyle(rendered.container.querySelector(".step-list")!);
    expect(stepList.overflowY).toBe("auto");
  } finally {
    removeStyleSheet();
  }
});

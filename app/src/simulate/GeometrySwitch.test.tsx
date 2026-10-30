import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { GeometrySwitch } from "./GeometrySwitch";
import type { StudyGeometry } from "./study_values";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const container = () => rendered!.container;
const segment = (label: string) => [...container().querySelectorAll<HTMLButtonElement>(".geometry-switch-segment")].find((button) => button.textContent === label)!;
const changeToggle = () => container().querySelector<HTMLButtonElement>(".geometry-switch-change")!;
const describedBy = (element: HTMLElement) => (element.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean)
  .map((id) => document.getElementById(id)!.textContent);

function renderSwitch(available: StudyGeometry[], outOfDateInDesign: StudyGeometry[], value: StudyGeometry = "max_volume", change = false,
                      waitingForStudy: StudyGeometry[] = []) {
  const onChange = vi.fn(), onChangeToggle = vi.fn();
  rendered = renderForTest(<GeometrySwitch available={available} outOfDateInDesign={outOfDateInDesign} waitingForStudy={waitingForStudy} value={value}
                                           change={change} onChange={onChange} onChangeToggle={onChangeToggle} />);
  return { onChange, onChangeToggle };
}

test("a geometry built after the study last ran waits for a new run of the study, with the reason", () => {
  const { onChange } = renderSwitch(["max_volume", "envelope", "massing"], ["envelope"], "max_volume", false, ["envelope"]);
  expect(segment("Envelope").getAttribute("aria-disabled")).toBe("true");
  expect(segment("Envelope").title).toBe("Run the study again to see it on the envelope");
  expect(describedBy(segment("Envelope"))).toEqual(["Run the study again to see it on the envelope"]);
  expect(segment("Envelope").querySelector(".geometry-switch-stale")).toBeNull();      // the reason it waits says enough
  click(segment("Envelope"));
  expect(onChange).not.toHaveBeenCalled();
  expect(segment("Massing").getAttribute("aria-disabled")).toBeNull();
});

test("the geometry switch offers Envelope and Massing only once built and marks one out of date in Design", () => {
  const { onChange } = renderSwitch(["max_volume"], []);
  expect(container().querySelector('[role="group"]')!.getAttribute("aria-label")).toBe("Geometry");
  expect([...container().querySelectorAll(".geometry-switch-segment")].map((button) => button.textContent)).toEqual(["Max volume", "Envelope", "Massing"]);
  expect(segment("Max volume").getAttribute("aria-pressed")).toBe("true");
  for (const [label, reason] of [["Envelope", "Build the envelope first"], ["Massing", "Build the massing first"]]) {
    expect(segment(label).getAttribute("aria-disabled")).toBe("true");
    expect(segment(label).title).toBe(reason);
    expect(describedBy(segment(label))).toEqual([reason]);
  }
  click(segment("Envelope"));
  expect(onChange).not.toHaveBeenCalled();

  rendered!.unmount();
  const built = renderSwitch(["max_volume", "envelope", "massing"], ["massing"], "envelope");
  expect(segment("Envelope").getAttribute("aria-disabled")).toBeNull();
  expect(segment("Envelope").getAttribute("aria-pressed")).toBe("true");
  expect(describedBy(segment("Envelope"))).toEqual([]);
  expect(describedBy(segment("Massing"))).toEqual(["Out of date in Carve"]);
  expect(segment("Massing").title).toBe("Out of date in Carve");
  expect(segment("Massing").querySelector(".geometry-switch-stale")).not.toBeNull();
  click(segment("Massing"));
  expect(built.onChange).toHaveBeenCalledWith("massing");
});

test("Change colours by the change from the maximum volume, and waits on the maximum volume itself", () => {
  const { onChangeToggle } = renderSwitch(["max_volume", "envelope"], [], "max_volume");
  expect(changeToggle().textContent).toBe("Change");
  expect(changeToggle().getAttribute("aria-disabled")).toBe("true");
  expect(describedBy(changeToggle())).toEqual(["Choose Envelope or Massing"]);
  click(changeToggle());
  expect(onChangeToggle).not.toHaveBeenCalled();

  rendered!.unmount();
  const onEnvelope = renderSwitch(["max_volume", "envelope"], [], "envelope", true);
  expect(changeToggle().getAttribute("aria-pressed")).toBe("true");
  expect(changeToggle().title).toBe("Colours each point by its change from the maximum volume");
  click(changeToggle());
  expect(onEnvelope.onChangeToggle).toHaveBeenCalledWith(false);
});

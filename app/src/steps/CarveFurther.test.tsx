import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { messages } from "../messages";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { carvedByNote, CarveFurtherSection } from "./CarveFurther";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const buttonNamed = (name: string) =>
  [...rendered!.container.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === name);

async function settle() {
  await act(async () => {});
}

test("carving further asks first and replaces only after the confirmation", async () => {
  const onCarveFurther = vi.fn(async () => null);
  rendered = renderForTest(<CarveFurtherSection disabledReason={null} onCarveFurther={onCarveFurther} />);
  click(buttonNamed(messages.carveFurtherButton)!);
  expect(rendered.container.textContent).toContain(messages.carveFurtherQuestion);
  expect(onCarveFurther).not.toHaveBeenCalled();
  click(buttonNamed(messages.carveFurtherConfirm)!);
  await settle();
  expect(onCarveFurther).toHaveBeenCalledTimes(1);
});

test("cancelling the confirmation changes nothing", () => {
  const onCarveFurther = vi.fn(async () => null);
  rendered = renderForTest(<CarveFurtherSection disabledReason={null} onCarveFurther={onCarveFurther} />);
  click(buttonNamed(messages.carveFurtherButton)!);
  click(buttonNamed(messages.cancel)!);
  expect(rendered.container.textContent).not.toContain(messages.carveFurtherQuestion);
  expect(onCarveFurther).not.toHaveBeenCalled();
});

test("without a current envelope the button is disabled and says why", () => {
  rendered = renderForTest(<CarveFurtherSection disabledReason={messages.carveFurtherNeedsCurrentEnvelope} onCarveFurther={async () => null} />);
  expect(buttonNamed(messages.carveFurtherButton)!.disabled).toBe(true);
  expect(rendered.container.textContent).toContain(messages.carveFurtherNeedsCurrentEnvelope);
});

test("a refused request shows the service's reason", async () => {
  rendered = renderForTest(<CarveFurtherSection disabledReason={null} onCarveFurther={async () => "A run is in progress"} />);
  click(buttonNamed(messages.carveFurtherButton)!);
  click(buttonNamed(messages.carveFurtherConfirm)!);
  await settle();
  expect(rendered.container.textContent).toContain("A run is in progress");
});

test("the note names the modes in the order they carved the maximum volume", () => {
  expect(carvedByNote([])).toBeNull();
  expect(carvedByNote([{ mode: "daylight" }, { mode: "time-based" }])).toBe("Carved by Daylight, then Solar time-based. The earlier maximum volumes are kept in the project folder, in inputs/earlier_max_volumes.");
});

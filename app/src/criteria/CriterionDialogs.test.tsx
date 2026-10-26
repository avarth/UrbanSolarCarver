import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { DeleteCriterionDialog, RenameCriterionDialog } from "./CriterionDialogs";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const dialog = () => rendered!.container.querySelector<HTMLElement>('[role="dialog"]');
const dialogButton = (label: string) => [...dialog()!.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label)!;

function type(input: HTMLInputElement, text: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    dialog()!.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

test("the rename dialog refuses an empty name with the service's message, and sends a name without its surrounding spaces", async () => {
  const onRename = vi.fn(async (_name: string) => null as string | null);
  const onClose = vi.fn();
  rendered = renderForTest(<RenameCriterionDialog name="Daylight on windows" onRename={onRename} onClose={onClose} />);
  expect(dialog()!.querySelector("h2")!.textContent).toBe("Rename Daylight on windows");
  const field = dialog()!.querySelector<HTMLInputElement>("input")!;
  expect(field.value).toBe("Daylight on windows");
  type(field, "   ");
  await submit();
  expect(onRename).not.toHaveBeenCalled();
  expect(dialog()!.querySelector('[role="alert"]')!.textContent).toBe("A criterion needs a name.");
  type(field, " Daylight on the courtyard ");
  await submit();
  expect(onRename).toHaveBeenCalledExactlyOnceWith("Daylight on the courtyard");
  expect(onClose).toHaveBeenCalled();
});

test("a name with only white space around it is the name it has: nothing to send", () => {
  rendered = renderForTest(<RenameCriterionDialog name="Daylight" onRename={async () => null} onClose={() => {}} />);
  type(dialog()!.querySelector<HTMLInputElement>("input")!, "	Daylight ");
  expect(dialogButton("Rename").disabled).toBe(true);
});

test("a rename the service refuses keeps the dialog open with its reason", async () => {
  rendered = renderForTest(<RenameCriterionDialog name="Daylight" onRename={async () => "A run of this project is in progress."} onClose={() => {}} />);
  type(dialog()!.querySelector<HTMLInputElement>("input")!, "Daylight 2");
  await submit();
  expect(dialog()!.querySelector('[role="alert"]')!.textContent).toBe("A run of this project is in progress.");
});

test("the delete dialog says what goes, and deletes on the confirmation", async () => {
  const onDelete = vi.fn(async () => null as string | null);
  const onClose = vi.fn();
  rendered = renderForTest(<DeleteCriterionDialog name="Daylight on windows" onDelete={onDelete} onClose={onClose} />);
  expect(document.getElementById(dialog()!.getAttribute("aria-describedby")!)!.textContent).toBe(
    "Delete Daylight on windows? Its settings and results go; test surface files no other criterion uses go to the recycle bin.");
  expect(document.activeElement).toBe(dialogButton("Cancel"));
  await act(async () => click(dialogButton("Delete")));
  expect(onDelete).toHaveBeenCalledOnce();
  expect(onClose).toHaveBeenCalled();
});

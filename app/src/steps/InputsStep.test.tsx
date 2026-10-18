import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { InputBox, InputsStep, inputsSizeText, type AddInputFiles } from "./InputsStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const WEATHER_HINT = "Needed for Sun at set hours, Solar energy and Solar heat when cold.";
const NO_FILES = { max_volume: [], test_surfaces: [], weather: [] };
const SOME_FILES = {
  max_volume: [{ name: "max_volume.ply", triangle_count: 1152 }],
  test_surfaces: [{ name: "neighbor_roofs.ply", triangle_count: 2040 }, { name: "neighbor_windows.ply", triangle_count: 1730 }],
  weather: [{ name: "weather.epw", triangle_count: 0 }],
};

function boxTitled(title: string): HTMLElement {
  return [...rendered!.container.querySelectorAll<HTMLElement>(".input-box")].find((box) => box.querySelector("h3")!.textContent === title)!;
}

function inputsStep(files: typeof NO_FILES | typeof SOME_FILES, onAddFiles: AddInputFiles = async () => [], disabledReason: string | null = null) {
  return (
    <InputsStep files={files} weatherLocation={files.weather.length ? "Golden, CO, USA" : null} weatherHint={WEATHER_HINT}
                inputsBounds={files.max_volume.length ? [[0, 0, 0], [52.2, 44.4, 30]] : null} onAddFiles={onAddFiles}
                onRemoveFile={async () => null} disabledReason={disabledReason} />
  );
}

test("empty boxes: dashed, Required or .epw beside the title, the hint, Add files and or drop them here", () => {
  rendered = renderForTest(inputsStep(NO_FILES));
  const maxVolume = boxTitled("Maximum volume");
  expect(maxVolume.classList.contains("input-box-empty")).toBe(true);
  expect(maxVolume.querySelector(".input-box-required")!.textContent).toBe("Required");
  expect(maxVolume.textContent).toContain("The largest building you would allow, as one or more closed meshes.");
  expect(boxTitled("Test surfaces").textContent).toContain("The surfaces whose sun or sky the carving protects, such as neighbouring facades.");
  const weather = boxTitled("Weather file (optional)");
  expect(weather.querySelector(".input-box-required")!.textContent).toBe(".epw");
  expect(weather.textContent).toContain(WEATHER_HINT);
  expect(maxVolume.querySelector(".input-box-actions")!.textContent).toBe("Add filesor drop them here");
  expect(rendered.container.textContent).not.toContain("Size of all inputs together");
});

test("filled boxes: a row per file with its triangle count or location, a named remove button, Replace for the weather", () => {
  rendered = renderForTest(inputsStep(SOME_FILES));
  const testSurfaces = boxTitled("Test surfaces");
  expect(testSurfaces.classList.contains("input-box-filled")).toBe(true);
  expect(testSurfaces.querySelector(".input-box-title-row button")!.textContent).toBe("Add files");
  expect([...testSurfaces.querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["neighbor_roofs.ply", "neighbor_windows.ply"]);
  expect(testSurfaces.querySelector(".input-file-detail")!.textContent).toBe("2\u202f040 triangles");
  expect(testSurfaces.querySelector('[aria-label="Remove neighbor_windows.ply"]')).not.toBeNull();
  const weather = boxTitled("Weather file (optional)");
  expect(weather.querySelector(".input-box-title-row button")!.textContent).toBe("Replace");
  expect(weather.querySelector(".input-file-detail")!.textContent).toBe("Golden, CO, USA");
  expect(rendered.container.querySelector(".inputs-size")!.textContent).toBe("Size of all inputs together52 × 44 × 30\u00a0m");
});

test("files dropped on a box are added to its role, and a file that cannot be read is named in the box", async () => {
  const onAddFiles = vi.fn<AddInputFiles>(async () => ["No triangles found in facade_b.obj"]);
  rendered = renderForTest(inputsStep(NO_FILES, onAddFiles));
  const file = new File(["solid"], "facade_b.obj");
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  await act(async () => {
    boxTitled("Test surfaces").dispatchEvent(drop);
  });
  expect(onAddFiles).toHaveBeenCalledWith("test_surfaces", [file]);
  expect(boxTitled("Test surfaces").querySelector(".input-box-problem")!.textContent).toBe("No triangles found in facade_b.obj");
});

test("during a run adding and removing are disabled, with the reason", () => {
  const onAddFiles = vi.fn<AddInputFiles>(async () => []);
  rendered = renderForTest(inputsStep(SOME_FILES, onAddFiles, "A run is in progress"));
  const maxVolume = boxTitled("Maximum volume");
  expect(maxVolume.querySelector<HTMLButtonElement>(".input-add")!.disabled).toBe(true);
  expect(maxVolume.querySelector<HTMLButtonElement>(".input-remove")!.disabled).toBe(true);
  expect(maxVolume.textContent).toContain("A run is in progress");
  click(maxVolume.querySelector(".input-add")!);
  expect(onAddFiles).not.toHaveBeenCalled();
});

test("the size line rounds to whole metres from 10 m up", () => {
  expect(inputsSizeText([[0, 0, 0], [1250.4, 8.25, 0.5]])).toBe("1\u202f250 × 8.25 × 0.5\u00a0m");
});

test("the weather box where the chosen mode needs the file is not titled optional", () => {
  rendered = renderForTest(<InputBox role="weather" files={[]} weatherLocation={null} weatherHint={WEATHER_HINT} onAddFiles={async () => []}
                                     onRemoveFile={async () => null} disabledReason={null} weatherNeeded />);
  expect(rendered.container.querySelector("h3")!.textContent).toBe("Weather file");
});

test("a file the 3D view cannot draw is named in its box, next to the files, which stay", () => {
  const problem = "neighbor_windows.ply: The 3D view cannot read this file, so it is not drawn. Runs still use it.";
  rendered = renderForTest(
    <InputsStep files={SOME_FILES} weatherLocation="Golden, CO, USA" weatherHint={WEATHER_HINT} inputsBounds={null} onAddFiles={async () => []}
                onRemoveFile={async () => null} disabledReason={null} drawingProblems={{ max_volume: [], test_surfaces: [problem] }} />);
  const testSurfaces = boxTitled("Test surfaces");
  expect([...testSurfaces.querySelectorAll(".input-box-problem")].map((paragraph) => paragraph.textContent)).toEqual([problem]);
  expect([...testSurfaces.querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["neighbor_roofs.ply", "neighbor_windows.ply"]);
  expect(boxTitled("Maximum volume").querySelector(".input-box-problem")).toBeNull();
});

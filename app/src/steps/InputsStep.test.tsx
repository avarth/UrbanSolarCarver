import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { carvedByNote, InputsStep, inputsSizeText } from "./InputsStep";
import { InputBox, type AddInputFiles } from "../common/InputBox";
import { LastRemovalContext } from "../common/last_removal";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const WEATHER_HINT = "Needed for Sun hours, Solar energy and Solar heating.";
const NO_FILES = { max_volume: [], context: [] };
const SOME_FILES = {
  max_volume: [{ name: "max_volume.ply", triangle_count: 1152 }],
  context: [{ name: "neighbour_blocks.ply", triangle_count: 2040 }, { name: "neighbour_trees.ply", triangle_count: 1730 }],
};
const WEATHER_FILES = [{ name: "weather.epw", triangle_count: 0 }];
const CONTEXT_TITLE = "Existing surroundings";

function boxTitled(title: string): HTMLElement {
  return [...rendered!.container.querySelectorAll<HTMLElement>(".input-box")].find((box) => box.querySelector("h3")!.textContent === title)!;
}

function inputsStep(files: typeof NO_FILES | typeof SOME_FILES, onAddFiles: AddInputFiles = async () => [], disabledReason: string | null = null) {
  return (
    <InputsStep files={files} inputsBounds={files.max_volume.length ? [[0, 0, 0], [52.2, 44.4, 30]] : null} onAddFiles={onAddFiles}
                onRemoveFile={async () => null} disabledReason={disabledReason} />
  );
}

/** The weather box, as Settings draws it (weatherNeeded: as a criterion's editor does). */
function weatherBox(files: typeof WEATHER_FILES, weatherNeeded = false) {
  return (
    <InputBox role="weather" files={files} weatherLocation={files.length ? "Golden, CO, USA" : null} weatherHint={WEATHER_HINT}
              onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null} weatherNeeded={weatherNeeded} />
  );
}

test("empty boxes: dashed, Add files in the title row and no badge, the hint, then the drop line", () => {
  rendered = renderForTest(inputsStep(NO_FILES));
  const maxVolume = boxTitled("Maximum volume");
  expect(maxVolume.classList.contains("input-box-empty")).toBe(true);
  expect(maxVolume.querySelector(".input-box-required")).toBeNull();
  expect(maxVolume.querySelector(".input-box-subtitle")).toBeNull();
  expect(maxVolume.querySelector(".input-box-title-row button")!.textContent).toBe("Add files");
  expect(maxVolume.textContent).toContain("The largest building you would allow, as one or more closed meshes.");
  expect(maxVolume.querySelector(".input-box-actions")).toBeNull();
  expect(maxVolume.querySelector("p.input-box-drop-hint")!.textContent).toBe("Or drop the files here.");
  expect(rendered.container.textContent).not.toContain("Overall size");
  rendered.unmount();
  rendered = renderForTest(weatherBox([]));
  const weather = boxTitled("Weather file");
  expect(weather.querySelector(".input-box-required")).toBeNull();
  expect(weather.querySelector(".input-box-title-row button")!.textContent).toBe("Add files");
  expect(weather.textContent).toContain(WEATHER_HINT);
  expect(weather.querySelector("p.input-box-drop-hint")!.textContent).toBe("Or drop the .epw file here.");
});

test("filled boxes: a row per file with its triangle count or location, a named remove button, Replace for the weather", () => {
  rendered = renderForTest(inputsStep(SOME_FILES));
  const context = boxTitled(CONTEXT_TITLE);
  expect(context.classList.contains("input-box-filled")).toBe(true);
  expect(context.querySelector(".input-box-title-row button")!.textContent).toBe("Add files");
  expect(context.querySelector(".input-box-drop-hint")).toBeNull();
  expect([...context.querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["neighbour_blocks.ply", "neighbour_trees.ply"]);
  expect(context.querySelector(".input-file-detail")!.textContent).toBe("2 040 triangles");
  expect(context.querySelector('[aria-label="Remove neighbour_trees.ply"]')).not.toBeNull();
  expect(rendered.container.querySelector(".inputs-size")!.textContent).toBe("Overall size52 × 44 × 30 m");
  rendered.unmount();
  rendered = renderForTest(weatherBox(WEATHER_FILES));
  const weather = boxTitled("Weather file");
  expect(weather.querySelector(".input-box-title-row button")!.textContent).toBe("Replace");
  expect(weather.querySelector(".input-file-detail")!.textContent).toBe("Golden, CO, USA");
});

test("files dropped on a box are added to its role, and a file that cannot be read is named in the box", async () => {
  const onAddFiles = vi.fn<AddInputFiles>(async () => ["No triangles found in facade_b.obj"]);
  rendered = renderForTest(inputsStep(NO_FILES, onAddFiles));
  const file = new File(["solid"], "facade_b.obj");
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  await act(async () => {
    boxTitled(CONTEXT_TITLE).dispatchEvent(drop);
  });
  expect(onAddFiles).toHaveBeenCalledWith("context", [file]);
  expect(boxTitled(CONTEXT_TITLE).querySelector(".input-box-problem")!.textContent).toBe("No triangles found in facade_b.obj");
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
  expect(inputsSizeText([[0, 0, 0], [1250.4, 8.25, 0.5]])).toBe("1 250 × 8.25 × 0.5 m");
});

test("the weather box in a criterion's editor, where its mode needs the file, has Also in Settings under its title", () => {
  rendered = renderForTest(weatherBox([], true));
  expect(rendered.container.querySelector("h3")!.textContent).toBe("Weather file");
  expect(rendered.container.querySelector("p.input-box-subtitle")!.textContent).toBe("Also in Settings");
  rendered.unmount();
  rendered = renderForTest(weatherBox([]));
  expect(rendered.container.querySelector("h3")!.textContent).toBe("Weather file");
  expect(rendered.container.querySelector(".input-box-subtitle")).toBeNull();
});

test("a file the 3D view cannot draw is named in its box, next to the files, which stay", () => {
  const problem = "neighbour_trees.ply: The 3D view cannot read this file, so it is not drawn. Runs still use it.";
  rendered = renderForTest(
    <InputsStep files={SOME_FILES} inputsBounds={null} onAddFiles={async () => []}
                onRemoveFile={async () => null} disabledReason={null} drawingProblems={{ max_volume: [], context: [problem] }} />);
  const context = boxTitled(CONTEXT_TITLE);
  expect([...context.querySelectorAll(".input-box-problem")].map((paragraph) => paragraph.textContent)).toEqual([problem]);
  expect([...context.querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["neighbour_blocks.ply", "neighbour_trees.ply"]);
  expect(boxTitled("Maximum volume").querySelector(".input-box-problem")).toBeNull();
});

test("the Site step holds only the site's geometry: no test surfaces, no weather file", () => {
  rendered = renderForTest(inputsStep(NO_FILES));
  const titles = [...rendered.container.querySelectorAll(".input-box h3")].map((title) => title.textContent);
  expect(titles).toEqual(["Maximum volume", "Existing surroundings", "Terrain"]);
  expect(rendered.container.textContent).not.toContain("Test surfaces");
  expect(rendered.container.textContent).not.toContain("Weather file");
});

test("the optional boxes for the existing surroundings and the terrain follow the maximum volume, with Optional under their titles", () => {
  rendered = renderForTest(inputsStep(NO_FILES));
  const context = boxTitled("Existing surroundings");
  expect(context.querySelector(".input-box-required")).toBeNull();
  expect(context.querySelector("p.input-box-subtitle")!.textContent).toBe("Optional");
  expect(context.textContent).toContain("Buildings and large trees that stay. They block sun and sky, and nothing is built in their place.");
  const terrain = boxTitled("Terrain");
  expect(terrain.querySelector(".input-box-required")).toBeNull();
  expect(terrain.querySelector("p.input-box-subtitle")!.textContent).toBe("Optional");
  expect(terrain.textContent).toContain("The ground. It blocks sun and sky; the site stays buildable above it.");
  expect(terrain.querySelector(".input-box-title-row button")!.textContent).toBe("Add files");
  expect(terrain.querySelector("p.input-box-drop-hint")!.textContent).toBe("Or drop the files here.");
});

test("a project carved further with an earlier version keeps its note on the maximum volume", () => {
  const chain = [{ mode: "daylight" }, { mode: "time-based" }];
  const note = "Carved by Daylight, then Sun hours. The earlier maximum volumes are kept in the project folder, in inputs/earlier_max_volumes.";
  expect(carvedByNote([])).toBeNull();
  expect(carvedByNote(chain)).toBe(note);
  rendered = renderForTest(
    <InputsStep files={SOME_FILES} inputsBounds={null} onAddFiles={async () => []}
                onRemoveFile={async () => null} disabledReason={null} maxVolumeNote={carvedByNote(chain)} />);
  expect(boxTitled("Maximum volume").querySelector(".input-box-hint")!.textContent).toBe(note);
  expect(boxTitled(CONTEXT_TITLE).textContent).not.toContain("Carved by");
});

test("the box a file was removed from says so with Undo, and a failed undo shows its reason there", async () => {
  const undo = vi.fn(async () => "The file could not be added back");
  rendered = renderForTest(
    <LastRemovalContext.Provider value={{ role: "context", name: "neighbour_trees.ply", undo }}>{inputsStep(SOME_FILES)}</LastRemovalContext.Provider>,
  );
  expect(boxTitled("Maximum volume").querySelector(".input-box-removed")).toBeNull();
  const line = boxTitled(CONTEXT_TITLE).querySelector(".input-box-removed")!;
  expect(line.textContent).toBe("neighbour_trees.ply was removed. Undo");
  await act(async () => {
    click(line.querySelector("button")!);
  });
  expect(undo).toHaveBeenCalledOnce();
  expect(boxTitled(CONTEXT_TITLE).querySelector(".input-box-problem")!.textContent).toBe("The file could not be added back");
});

test("under the boxes, how many removed files the folder keeps, and Show opens it", async () => {
  const show = vi.fn(async () => null);
  rendered = renderForTest(
    <InputsStep files={SOME_FILES} inputsBounds={null} onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null}
                removedFiles={{ count: 3, show }} />,
  );
  const line = rendered.container.querySelector(".inputs-removed")!;
  expect(line.textContent).toBe("3 removed files are kept in the project folder. Show");
  await act(async () => {
    click(line.querySelector("button")!);
  });
  expect(show).toHaveBeenCalledOnce();
  rendered.unmount();
  rendered = renderForTest(
    <InputsStep files={SOME_FILES} inputsBounds={null} onAddFiles={async () => []} onRemoveFile={async () => null} disabledReason={null}
                removedFiles={{ count: 0, show }} />,
  );
  expect(rendered.container.querySelector(".inputs-removed")).toBeNull();
});

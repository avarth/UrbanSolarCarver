// The notice of a new weather file (weather_change_notice.ts) in the open project, against a fake service: when it comes, what its
// buttons save, and the heating season preset that follows the file. Which files and modes bring no notice is weather_change_notice.test.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../api_client/client";
import {
  FakeService, MODES, NOTHING_RUN, SCHEMA, buttonIn, container, endWorkspaceTest, openPanelSection, openStep, openWorkspace, pressRunAnalysis, project,
  settle, startWorkspaceTest, stepRow, waitForTheSave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let service: FakeService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const BENEFIT_SCHEMA = {
  properties: { ...SCHEMA.properties, balance_temperature: { default: 15, type: "number" }, balance_offset: { default: 2, minimum: 0, type: "number" } },
};
const COLD_SEASON = { start_month: 9, start_day: 30, start_hour: 0, end_month: 5, end_day: 15, end_hour: 23 };
const MODES_WITH_BENEFIT: ModeInfo[] = [...MODES, { name: "benefit", description: "", needs_epw: true, needs_period: true, experimental: false,
                                                     score_kind: "weighted_sum", weight_unit: "", score_unit: "", starting_values: COLD_SEASON }];
const BRISBANE = { location: "Brisbane, AUS", latitude: -27.38 };
const GOLDEN = { location: "Golden, CO, USA", latitude: 39.74 };

async function addWeatherFile() {
  if (!stepRow("Inputs").classList.contains("step-open")) openStep("Inputs");
  const weatherPicker = container().querySelector<HTMLInputElement>('input[type="file"][accept=".epw"]')!;
  Object.defineProperty(weatherPicker, "files", { value: [new File(["LOCATION"], "weather.epw")], configurable: true });
  act(() => weatherPicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  openStep("Criteria");
  openPanelSection("Settings");
}

/** Past the wait before the cold period is asked for, and its reply. */
const waitForTheColdPeriod = async () => {
  await act(async () => { await vi.advanceTimersByTimeAsync(450); });
  await settle();
};

const weatherNotice = () => container().querySelector<HTMLElement>(".weather-change-notice");
const noticeText = () => weatherNotice()!.querySelector("p")!.textContent;
const noticeRegion = () => container().querySelector<HTMLElement>(".weather-change-region");
const startDateHandle = () => container().querySelector<HTMLElement>('.period-control [role="slider"][aria-label="Start date"]');
const BRISBANE_SHIFT = "The new weather file (Brisbane, AUS) is in the southern hemisphere: winter there is June to August. " +
  "Shift the analysis period by six months, to 21 Jun, 10 to 14 h?";

test("a project opened with a weather file in the other hemisphere shows no notice: only a weather file added in this session does", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, { ...project(NOTHING_RUN), weather_location: BRISBANE.location, weather_latitude: BRISBANE.latitude });
  openStep("Criteria");
  expect(weatherNotice()).toBeNull();
});

test("a weather file in the other hemisphere: the notice offers the period six months on, which goes through the saver", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  expect(noticeText()).toBe(BRISBANE_SHIFT);
  expect(buttonIn(weatherNotice()!, "Keep").getAttribute("aria-label")).toBe("Keep the analysis period");
  act(() => buttonIn(weatherNotice()!, "Shift by six months").click());
  expect(weatherNotice()).toBeNull();
  expect(document.activeElement).toBe(startDateHandle());           // the focus goes to the period the button changed
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "time-based", start_month: 6, end_month: 6 }]);      // the settings changed, as the period control sends
});

test("a first weather file counts as after a northern one; the heating season preset follows the hemisphere of the file, northern in the tropics", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, { ...project(NOTHING_RUN), inputs: { ...project(NOTHING_RUN).inputs, weather: [] }, weather_location: null, weather_latitude: null });
  openStep("Criteria");
  openPanelSection("Settings");
  expect(buttonIn(container(), "Heating season, October to April")).toBeDefined();
  await addWeatherFile();
  expect(noticeText()).toContain("(Brisbane, AUS) is in the southern hemisphere");
  expect(buttonIn(container(), "Heating season, October to April")).toBeUndefined();
  expect(buttonIn(container(), "Heating season, April to October")).toBeDefined();
  service.uploadedWeather = { location: "Darwin, AUS", latitude: -12.46 };       // the preset follows this file, not the one before
  await addWeatherFile();
  expect(buttonIn(container(), "Heating season, October to April")).toBeDefined();
});

test("Keep dismisses the notice and saves nothing; a later weather file brings a notice again", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  act(() => buttonIn(weatherNotice()!, "Keep").click());
  expect(weatherNotice()).toBeNull();
  expect(document.activeElement).toBe(startDateHandle());
  await waitForTheSave();
  expect(service.savedValues).toEqual([]);
  service.uploadedWeather = GOLDEN;                 // back north, the period still northern: the notice asks about the change again
  await addWeatherFile();
  expect(noticeText()).toBe("The new weather file (Golden, CO, USA) is in the northern hemisphere: winter there is December to February. " +
    "Shift the analysis period by six months, to 21 Jun, 10 to 14 h?");
});

test("while a run is in progress the notice's buttons are disabled, as the settings are", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  await pressRunAnalysis();
  for (const name of ["Shift by six months", "Keep"]) expect(buttonIn(weatherNotice()!, name).disabled).toBe(true);
});

test("Solar usefulness: the notice waits for the cold period of the new file and offers it, keeping the hours", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN, { mode: "benefit" }), {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await waitForTheColdPeriod();                     // of the file the project opened with: none
  service.coldPeriodReply = { status: "found", period: { start_month: 5, start_day: 3, end_month: 9, end_day: 20 } };
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();               // waiting for the new file's answer
  await waitForTheColdPeriod();
  expect(noticeText()).toBe("The new weather file (Brisbane, AUS) has its cold period from 3 May to 20 Sep; the analysis period is 30 Sep to 15 May.");
  act(() => buttonIn(weatherNotice()!, "Use the cold period").click());
  expect(weatherNotice()).toBeNull();
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "benefit", start_month: 5, start_day: 3, end_month: 9, end_day: 20 }]);           // the hours kept
});

test("Solar usefulness, energy-weighted: a new file's cold period is not offered, as it belongs to the cold hours rule", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  const energyWeighted = project(NOTHING_RUN, { mode: "benefit" });
  energyWeighted.criteria = energyWeighted.criteria!.map((criterion) => ({ ...criterion, energy_weighted: true }));
  await openWorkspace(service, energyWeighted, {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await waitForTheColdPeriod();
  service.coldPeriodReply = { status: "found", period: { start_month: 5, start_day: 3, end_month: 9, end_day: 20 } };
  await addWeatherFile();
  await waitForTheColdPeriod();
  expect(weatherNotice()).toBeNull();
});

test("the notice is a live region kept on the page, empty until a notice fills it, so screen readers announce what comes", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  expect(noticeRegion()!.getAttribute("role")).toBe("status");
  expect(noticeRegion()!.textContent).toBe("");
  await addWeatherFile();                                           // through the Inputs step, back to Criteria
  const region = noticeRegion()!;
  expect(region.textContent).toContain(BRISBANE_SHIFT);
  act(() => buttonIn(weatherNotice()!, "Keep").click());
  expect(noticeRegion()).toBe(region);
  expect(region.textContent).toBe("");
});

test("a new weather file without a latitude keeps the hemisphere of the one before it", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  act(() => buttonIn(weatherNotice()!, "Keep").click());          // the period stays northern, the file southern
  service.uploadedWeather = { location: null, latitude: null } as unknown as typeof BRISBANE;
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();                               // nothing to say about a file without a latitude
  service.uploadedWeather = GOLDEN;
  await addWeatherFile();                                           // north after the southern file: the notice asks
  expect(noticeText()).toContain("(Golden, CO, USA) is in the northern hemisphere");
});

test("once the period is changed by hand the notice is gone, also when the period is set back", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  expect(noticeText()).toBe(BRISBANE_SHIFT);
  act(() => buttonIn(container(), "21 June").click());
  expect(weatherNotice()).toBeNull();
  act(() => buttonIn(container(), "21 December").click());          // the period the file came with, again
  await waitForTheSave();
  await settle();
  expect(weatherNotice()).toBeNull();
});

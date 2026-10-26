// The open project with several criteria, against a fake service of a chain: the cards in order, selecting, bypassing, deleting,
// adding and reordering criteria, where a pending save goes, test surface files shared by criteria, and the step summary.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  CURRENT, FACADES, OUT_OF_DATE, ROOFS, WINDOWS, card, cardLine, cardNames, cards, chooseFromMenu, criteriaSummary, deleteCriterion, expectNoProblemShown,
  expectResultsOfCriterion, keptTile, openChain, panel, panelFrame, periodFieldText, protectedFiles, select, selectButtonOf, selectedCardName, service,
  settingsSaves,
} from "./chain_service_for_test";
import {
  buttonIn, container, endWorkspaceTest, openStep, reasonOf, settle, startWorkspaceTest, stepRow, thresholdField, unmountWorkspace, waitForTheSave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

test("two criteria show cards in order, each with its result, and the first is selected with its panel below", async () => {
  await openChain([FACADES, WINDOWS]);
  expect(cardNames()).toEqual(["Winter sun on facades", "Spring sun on windows"]);
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(cardLine("Winter sun on facades")).toBe("39 % of the volume carved, 390 m³ removed");
  expect(cardLine("Spring sun on windows")).toBe("20 % of the volume carved, 200 m³ removed");
  expect(protectedFiles()).toEqual(["facades.obj"]);
  expect(buttonIn(stepRow("Criteria"), "Add criterion")).toBeDefined();
  expect(container().textContent).not.toContain("Add another criterion");
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Winter sun on facades 61 %, then Spring sun on windows 80 %");
});

test("selecting a card shows its settings, its test surfaces and its results", async () => {
  await openChain([FACADES, WINDOWS]);
  expect(periodFieldText()).toContain("21 Dec");
  expect(thresholdField().value).toBe("1.5");
  expect(keptTile()).toContain("61");
  await select("Spring sun on windows");
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(service.requests).toContain("GET /criteria/2/settings");
  expect(periodFieldText()).toContain("21 Mar");
  expect(thresholdField().value).toBe("3");
  expect(keptTile()).toContain("80");
  expect(protectedFiles()).toEqual(["windows.obj"]);
  expect(service.requests).toContain("GET /run/score-points?criterion=2");
  // A change now saves criterion 2's settings, not criterion 1's.
  act(() => buttonIn(container(), "21 June").click());
  await waitForTheSave();
  await settle();
  expect(service.patches.map((patch) => patch.id)).toEqual(["2"]);
  expect(service.entries[1].settings).toEqual({ mode: "time-based", start_month: 6, end_month: 6, start_day: 21, start_hour: 10, end_day: 21, end_hour: 14,
                                                threshold: { method: "cutoff", value: 3 } });
});

test("a pending save goes to the criterion it was typed in", async () => {
  await openChain([FACADES, WINDOWS]);
  act(() => buttonIn(container(), "21 June").click());           // a period for criterion 1, its save still waiting
  await select("Spring sun on windows");                           // before the save delay
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect((service.patches[0].body.values as Record<string, unknown>).start_month).toBe(6);
  expect(service.entries[1].settings!.start_month).toBe(3);       // criterion 2 kept its own period
  expect(periodFieldText()).toContain("21 Mar");
});

test("bypassing a card greys it and reads Bypassed", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Spring sun on windows").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(service.patches).toEqual([{ id: "2", body: { bypassed: true } }]);
  expect(card("Spring sun on windows").classList.contains("criterion-card-bypassed")).toBe(true);
  expect(cardLine("Spring sun on windows")).toBe("Bypassed");
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(service.count("GET /stage-status")).toBeGreaterThan(0);
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Winter sun on facades 61 %");       // the bypassed criterion is left out
});

test("bypassing the selected card selects the next one", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(periodFieldText()).toContain("21 Mar");
  expectResultsOfCriterion("2");
  expectNoProblemShown();
});

test("a bypass whose reply comes after another card was pressed moves the selection from the card pressed", async () => {
  await openChain([FACADES, WINDOWS, ROOFS]);
  let answerPatches = () => {};
  service.patchesAnswerWhen = new Promise((resolve) => { answerPatches = resolve; });
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await select("Daylight on roofs");                              // while the bypass is on its way
  await act(async () => answerPatches());
  await settle();
  expect(card("Winter sun on facades").classList.contains("criterion-card-bypassed")).toBe(true);
  expect(selectedCardName()).toBe("Daylight on roofs");           // not the card after the bypassed one
});

test("deleting the selected criterion selects the next one, and the last one the previous; settings and results follow", async () => {
  await openChain([FACADES, WINDOWS, ROOFS]);
  await deleteCriterion("Winter sun on facades");
  expect(service.requests).toContain("DELETE /criteria/1");
  expect(cardNames()).toEqual(["Spring sun on windows", "Daylight on roofs"]);
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(document.activeElement).toBe(selectButtonOf("Spring sun on windows"));     // the focus goes to the card selected now
  expect(periodFieldText()).toContain("21 Mar");
  expect(thresholdField().value).toBe("3");
  expect(keptTile()).toContain("80");
  expectResultsOfCriterion("2");
  expectNoProblemShown();
  await select("Daylight on roofs");
  await deleteCriterion("Daylight on roofs");
  expect(service.requests).toContain("DELETE /criteria/3");
  // One criterion left: no cards, its panel at once (with the focus), and Add another criterion.
  expect(cards()).toEqual([]);
  expect(document.activeElement).toBe(panelFrame());
  expectNoProblemShown();
  expect(periodFieldText()).toContain("21 Mar");
  expect(protectedFiles()).toEqual(["windows.obj"]);
  expect(buttonIn(stepRow("Criteria"), "Add another criterion")).toBeDefined();
});

test("a project left with one bypassed criterion offers Turn on in its panel, which turns it on", async () => {
  await openChain([{ ...FACADES, bypassed: true }], { 1: CURRENT });
  expect(cards()).toEqual([]);
  expect(panel().textContent).not.toContain("Bypassed: the chain skips this criterion.");
  expect(reasonOf(buttonIn(panel(), "Run analysis"))).toContain("Turn on a criterion");
  await act(async () => buttonIn(panel(), "Turn on").click());
  await settle();
  expect(service.patches).toEqual([{ id: "1", body: { bypassed: false } }]);
  expect(buttonIn(panel(), "Turn on")).toBeUndefined();
  expect(container().textContent).not.toContain("Turn on a criterion");
  expectNoProblemShown();
});

test("Add another criterion adds one of the chosen mode and selects it", async () => {
  await openChain([FACADES]);
  expect(cards()).toEqual([]);
  act(() => buttonIn(stepRow("Criteria"), "Add another criterion").click());
  await act(async () => [...container().querySelectorAll<HTMLElement>(".add-criterion [role='radio']")].find((tile) => tile.textContent === "Daylight")!.click());
  await settle();
  expect(service.requests).toContain("POST /criteria");
  expect(cardNames()).toEqual(["Winter sun on facades", "Daylight"]);
  expect(selectedCardName()).toBe("Daylight");
  expect(service.requests).toContain("GET /criteria/2/settings");
  expect(cardLine("Daylight")).toBe("Add test surfaces");
  expect(document.activeElement).toBe(selectButtonOf("Daylight"));
  expect(protectedFiles()).toEqual([]);
  expect(panel().querySelector('[role="radio"][aria-checked="true"]')!.textContent).toBe("Daylight");
  // It has not run: its score points and sky dome are not asked for (the service has none).
  expect(service.requests.filter((request) => request.includes("criterion=2") && request.includes("/run/"))).toEqual([]);
});

test("while a card's settings are on their way its panel waits, and a reply for a card pressed before is not used", async () => {
  await openChain([FACADES, WINDOWS, ROOFS]);
  let answerWindows = () => {};
  service.settingsAnswerWhen["2"] = new Promise((resolve) => { answerWindows = resolve; });
  await select("Spring sun on windows");
  expect(container().querySelector(".criterion-panel")).toBeNull();          // no settings of another criterion to type into
  expect(panelFrame().querySelector('[role="status"]')!.textContent).toBe("Loading the settings of Spring sun on windows");
  await select("Daylight on roofs");                              // before criterion 2's settings are in
  await act(async () => answerWindows());
  await settle();
  expect(selectedCardName()).toBe("Daylight on roofs");
  expect(protectedFiles()).toEqual(["roofs.obj"]);
  expect(panel().querySelector('[role="radio"][aria-checked="true"]')!.textContent).toBe("Daylight");
  act(() => panel().querySelector<HTMLElement>('[role="radio"][aria-checked="false"]')!.click());       // another mode for it
  await waitForTheSave();
  await settle();
  expect(service.patches.map((patch) => patch.id)).toEqual(["3"]);
});

test("settings that cannot be read are said in the panel; a press on the card asks again", async () => {
  await openChain([FACADES, WINDOWS]);
  service.settingsRefusedWith["2"] = 500;
  await select("Spring sun on windows");
  expect(panelFrame().querySelector('[role="alert"]')!.textContent).toBe("The settings of criterion 2 could not be read.");
  expect(container().querySelector(".criterion-panel")).toBeNull();
  delete service.settingsRefusedWith["2"];
  await select("Spring sun on windows");
  expect(periodFieldText()).toContain("21 Mar");
  expectNoProblemShown();
});

test("a card asked for again after its settings were refused waits for them without the old refusal", async () => {
  await openChain([FACADES, WINDOWS]);
  service.settingsRefusedWith["2"] = 500;
  await select("Spring sun on windows");
  expect(panelFrame().querySelector('[role="alert"]')).not.toBeNull();
  delete service.settingsRefusedWith["2"];
  let answerWindows = () => {};
  service.settingsAnswerWhen["2"] = new Promise((resolve) => { answerWindows = resolve; });
  await select("Winter sun on facades");
  await select("Spring sun on windows");
  expect(panelFrame().querySelector('[role="alert"]')).toBeNull();
  expect(panelFrame().querySelector('[role="status"]')!.textContent).toBe("Loading the settings of Spring sun on windows");
  await act(async () => answerWindows());
  await settle();
  expect(periodFieldText()).toContain("21 Mar");
});

test("turning a selected criterion that has results back on fetches its score points and sky dome", async () => {
  await openChain([FACADES, { ...WINDOWS, bypassed: true }], { 1: CURRENT });
  service.criterionStages["2"] = CURRENT;                          // its results from before it was bypassed
  await select("Spring sun on windows");
  expect(service.requests.filter((request) => request.includes("/run/") && request.includes("criterion=2"))).toEqual([]);
  expect(panel().textContent).toContain("Bypassed: the chain skips this criterion.");        // not that it needs an analysis
  expect(panel().textContent).not.toContain("Run the analysis to see the carving");
  await act(async () => card("Spring sun on windows").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(service.requests).toEqual(expect.arrayContaining(["GET /run/score-points?criterion=2", "GET /run/sky-patches?criterion=2"]));
});

test("reordering with the keyboard sends the new order and the cards follow it", async () => {
  await openChain([FACADES, WINDOWS]);
  const handle = card("Spring sun on windows").querySelector<HTMLElement>(".criterion-card-handle")!;
  handle.focus();
  await act(async () => handle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true })));
  await settle();
  expect(service.requests).toContain("PUT /criteria/order");
  expect(cardNames()).toEqual(["Spring sun on windows", "Winter sun on facades"]);
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(document.activeElement).toBe(card("Spring sun on windows").querySelector(".criterion-card-handle"));     // the focus stays on the handle moved
});

test("a file added to two criteria is stored once and replacing it dates both", async () => {
  await openChain([FACADES, WINDOWS]);
  // Criterion 1 takes criterion 2's file too, from the list of the other criteria's files.
  await act(async () => panel().querySelector<HTMLButtonElement>('[aria-label="Use windows.obj"]')!.click());
  await settle();
  expect(service.requests).toContain("PUT /criteria/1/test-surfaces/windows.obj");
  expect(protectedFiles()).toEqual(["facades.obj", "windows.obj"]);
  expect(service.storedFileCount("windows.obj")).toBe(1);
  service.criterionStages = { 1: CURRENT, 2: CURRENT };
  // A new windows.obj, uploaded to criterion 1, replaces the stored file both use.
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [new File(["v 0 0 1"], "windows.obj")] } });
  await act(async () => panel().querySelector(".input-box")!.dispatchEvent(drop));
  await settle();
  expect(service.storedFileCount("windows.obj")).toBe(1);
  expect(cardLine("Winter sun on facades")).toBe("Out of date");
  expect(cardLine("Spring sun on windows")).toBe("Out of date");
});

test("use a file from another criterion", async () => {
  await openChain([FACADES, WINDOWS]);
  const reuse = panel().querySelector<HTMLElement>(".protects-reuse")!;
  expect([...reuse.querySelectorAll(".protects-reuse-name")].map((name) => name.textContent)).toEqual(["windows.obj"]);
  await act(async () => reuse.querySelector<HTMLButtonElement>('[aria-label="Use windows.obj"]')!.click());
  await settle();
  expect(protectedFiles()).toEqual(["facades.obj", "windows.obj"]);
  expect(panel().querySelector(".protects-reuse")).toBeNull();            // nothing more to use
  expect(cardLine("Winter sun on facades")).toBe("Out of date");
});

test("renaming a card sends the new name and the card shows it", async () => {
  await openChain([FACADES, WINDOWS]);
  await chooseFromMenu("Spring sun on windows", "Rename");
  const field = container().querySelector<HTMLInputElement>('[role="dialog"] input')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, "Courtyard windows");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => field.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await settle();
  expect(service.patches).toEqual([{ id: "2", body: { name: "Courtyard windows" } }]);
  expect(cardNames()).toEqual(["Winter sun on facades", "Courtyard windows"]);
  expect(container().querySelector('[role="dialog"]')).toBeNull();
});

test("duplicating a card adds the copy after the last card and selects it", async () => {
  await openChain([FACADES, WINDOWS]);
  await chooseFromMenu("Winter sun on facades", "Duplicate");
  await settle();
  expect(service.requests).toContain("POST /criteria/1/duplicate");
  expect(cardNames()).toEqual(["Winter sun on facades", "Spring sun on windows", "Winter sun on facades copy"]);
  expect(selectedCardName()).toBe("Winter sun on facades copy");
  expect(document.activeElement).toBe(selectButtonOf("Winter sun on facades copy"));
  expect(service.requests).toContain("GET /criteria/3/settings");
});

const chainLine = () => container().querySelector(".chain-summary")?.textContent?.replace(/[  ]/g, " ") ?? null;

test("the chain summary line under the cards: the last volume and its share of the maximum volume", async () => {
  await openChain([FACADES, WINDOWS], undefined, (chain) => { chain.summaryChain = { volume_after_each_m3: [610, 480], share_of_max_volume_kept: 0.4813 }; });
  expect(chainLine()).toBe("Kept 480 m³, 48 % of the maximum volume");
  const list = container().querySelector(".criterion-list")!;
  expect(list.compareDocumentPosition(container().querySelector(".chain-summary")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(container().querySelector(".chain-summary")!.compareDocumentPosition(panel()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("the chain summary line says the volume alone when there is no share, and is not there while the summary has no chain", async () => {
  await openChain([FACADES, WINDOWS], undefined, (chain) => { chain.summaryChain = { volume_after_each_m3: [610, 1234], share_of_max_volume_kept: null }; });
  expect(chainLine()).toBe("Kept 1 234 m³");
  unmountWorkspace();
  await openChain([FACADES, WINDOWS]);
  expect(chainLine()).toBeNull();
});

test("the chain summary line is hidden while a criterion that is on is not current: its numbers are from the run before", async () => {
  const chain = { volume_after_each_m3: [610, 480], share_of_max_volume_kept: 0.4813 };
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE }, (service) => { service.summaryChain = chain; });
  expect(cardLine("Spring sun on windows")).toBe("Out of date");
  expect(chainLine()).toBeNull();
});

test("the chain summary line needs two criteria that are on", async () => {
  const chain = { volume_after_each_m3: [610], share_of_max_volume_kept: 0.61 };
  await openChain([FACADES], undefined, (service) => { service.summaryChain = chain; });
  expect(chainLine()).toBeNull();
  unmountWorkspace();
  await openChain([FACADES, { ...WINDOWS, bypassed: true }], undefined, (service) => { service.summaryChain = chain; });
  expect(chainLine()).toBeNull();
});

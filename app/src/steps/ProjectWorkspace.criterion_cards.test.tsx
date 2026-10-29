// The open project with several criteria, against a fake service of a chain: the cards in order, selecting, bypassing, deleting,
// adding and reordering criteria, where a pending save goes, test surface files shared by criteria, and the step summary.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  CURRENT, FACADES, OUT_OF_DATE, ROOFS, WINDOWS, card, cardLine, cardNames, chooseFromMenu, criteriaSummary, criterion, deleteCriterion, expectNoProblemShown,
  expectResultsOfCriterion, keptTile, openChain, panel, panelFrame, periodFieldText, protectedFiles, select, selectButtonOf, selectedCardName, service,
  settingsSaves,
} from "./chain_service_for_test";
import {
  buttonIn, container, endWorkspaceTest, openPanelSection, openPanelSections, openStep, pinnedBar, reasonOf, settle, showCriterionCards, startWorkspaceTest, stepRow, thresholdField,
  togglePanelSection,
  unmountWorkspace, waitForTheSave,
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
  showCriterionCards();
  expect(buttonIn(stepRow("Criteria"), "Add criterion")).toBeDefined();
  expect(container().textContent).not.toContain("Add another criterion");
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Winter sun on facades 61 %, then Spring sun on windows 80 %");
});

test("the step summary names a criterion the user did not name by its mode, without its test surface file", async () => {
  await openChain([{ ...FACADES, name: "Solar time-based on facades", named_by_user: false }, WINDOWS]);
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Solar time-based 61 %, then Spring sun on windows 80 %");
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

test("the open sections stay as the user left them when another criterion is selected; one without test surfaces opens them", async () => {
  const bare = criterion("3", "Daylight on roofs", { mode: "daylight" }, []);
  await openChain([FACADES, WINDOWS, bare]);
  expect(openPanelSections()).toEqual(["Test surfaces", "Carving rule"]);
  togglePanelSection("Mode");
  togglePanelSection("Carving rule");
  togglePanelSection("Test surfaces");
  expect(openPanelSections()).toEqual(["Mode"]);
  await select("Spring sun on windows");
  expect(openPanelSections()).toEqual(["Mode"]);
  await select("Daylight on roofs");                              // it protects nothing yet
  expect(openPanelSections()).toEqual(["Test surfaces", "Mode"]);
  await select("Winter sun on facades");
  expect(openPanelSections()).toEqual(["Test surfaces", "Mode"]);
  // The open sections are the workspace's: closing the step and opening it again keeps them.
  openStep("Inputs");
  openStep("Criteria");
  expect(openPanelSections()).toEqual(["Test surfaces", "Mode"]);
});

test("a pending save goes to the criterion it was typed in", async () => {
  await openChain([FACADES, WINDOWS]);
  openPanelSection("Settings");
  act(() => buttonIn(container(), "21 June").click());           // a period for criterion 1, its save still waiting
  await select("Spring sun on windows");                           // before the save delay
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect((service.patches[0].body.values as Record<string, unknown>).start_month).toBe(6);
  expect(service.entries[1].settings!.start_month).toBe(3);       // criterion 2 kept its own period
  expect(periodFieldText()).toContain("21 Mar");
});

test("switching a card off greys it and reads Off", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Spring sun on windows").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(service.patches).toEqual([{ id: "2", body: { bypassed: true } }]);
  expect(card("Spring sun on windows").classList.contains("criterion-card-bypassed")).toBe(true);
  expect(cardLine("Spring sun on windows")).toBe("Off");
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(service.count("GET /stage-status")).toBeGreaterThan(0);
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Winter sun on facades 61 %");       // the criterion that is off is left out
});

test("switching off the selected card keeps it selected; its panel says it is off", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(service.requests).not.toContain("GET /criteria/2/settings");
  expect(panel().textContent).toContain("Off: the chain skips this criterion");
  expect(periodFieldText()).toContain("21 Dec");
  expectNoProblemShown();
});

test("a switch-off whose reply comes after another card was pressed keeps the card pressed selected", async () => {
  await openChain([FACADES, WINDOWS, ROOFS]);
  let answerPatches = () => {};
  service.patchesAnswerWhen = new Promise((resolve) => { answerPatches = resolve; });
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await select("Daylight on roofs");                              // while the bypass is on its way
  await act(async () => answerPatches());
  await settle();
  expect(card("Winter sun on facades").classList.contains("criterion-card-bypassed")).toBe(true);
  expect(selectedCardName()).toBe("Daylight on roofs");
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
  // One criterion left: its row stays in the list (with the focus), with its switch on and Delete waiting, and Add criterion.
  expect(cardNames()).toEqual(["Spring sun on windows"]);
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(document.activeElement).toBe(selectButtonOf("Spring sun on windows"));
  expect(card("Spring sun on windows").querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  expect(card("Spring sun on windows").querySelector(".criterion-card-handle")).toBeNull();
  expectNoProblemShown();
  expect(periodFieldText()).toContain("21 Mar");
  expect(protectedFiles()).toEqual(["windows.obj"]);
  showCriterionCards();
  expect(buttonIn(stepRow("Criteria"), "Add criterion")).toBeDefined();
});

test("turning the only criterion off and on again: Run analysis waits while it is off, the carving rule comes back when it is on", async () => {
  await openChain([FACADES], { 1: CURRENT });
  expect(card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(service.patches).toEqual([{ id: "1", body: { bypassed: true } }]);
  expect(cardLine("Winter sun on facades")).toBe("Off");
  expect(card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(false);
  expect(panel().textContent).toContain("Off: the chain skips this criterion");
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toContain("Turn on a criterion to run");
  openStep("Inputs");
  expect(criteriaSummary()).toBe("Solar time-based, Off");
  openStep("Criteria");
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  expect(service.patches[1]).toEqual({ id: "1", body: { bypassed: false } });
  expect(panel().textContent).not.toContain("Off: the chain skips this criterion");
  expect(container().textContent).not.toContain("Turn on a criterion");
  expectNoProblemShown();
});

test("switch off the first of two criteria, delete the second: the one left stays off, and Run analysis says to turn it on", async () => {
  await openChain([FACADES, WINDOWS]);
  await act(async () => card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
  await deleteCriterion("Spring sun on windows");
  expect(cardNames()).toEqual(["Winter sun on facades"]);
  expect(card("Winter sun on facades").querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(false);
  expect(cardLine("Winter sun on facades")).toBe("Off");
  expect(service.entries.map((entry) => [entry.id, entry.bypassed])).toEqual([["1", true]]);      // as the service stores it
  expect(buttonIn(pinnedBar(), "Run analysis").disabled).toBe(true);
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Turn on a criterion to run");
});

test("Add criterion with one criterion opens a menu of the modes; choosing one adds a criterion of it, selected, its test surfaces open", async () => {
  await openChain([FACADES]);
  expect(cardNames()).toEqual(["Winter sun on facades"]);
  togglePanelSection("Test surfaces");                             // closed by the user; the new criterion has no files to show
  expect(openPanelSections()).toEqual(["Carving rule"]);
  showCriterionCards();
  act(() => buttonIn(stepRow("Criteria"), "Add criterion").click());
  expect(container().querySelector('.add-criterion [role="radio"]')).toBeNull();
  expect([...container().querySelectorAll('.add-criterion [role="menuitem"] .mode-menu-name')].map((name) => name.textContent))
    .toEqual(["Angle rule", "Solar time-based", "Solar energy", "Solar usefulness", "Daylight", "Night cooling"]);
  await act(async () => [...container().querySelectorAll<HTMLElement>('.add-criterion [role="menuitem"]')]
    .find((item) => item.querySelector(".mode-menu-name")!.textContent === "Daylight")!.click());
  await settle();
  expect(service.requests).toContain("POST /criteria");
  expect(container().querySelector('.add-criterion [role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(container().querySelector(".criterion-editor-name"));    // the new criterion's editor opens, the focus on its name
  expect(cardNames()).toEqual(["Winter sun on facades", "Daylight"]);
  expect(selectedCardName()).toBe("Daylight");
  expect(service.requests).toContain("GET /criteria/2/settings");
  expect(cardLine("Daylight")).toBe("Add test surfaces");
  expect(protectedFiles()).toEqual([]);
  expect(openPanelSections()).toEqual(["Test surfaces", "Carving rule"]);
  openPanelSection("Mode");
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
  openPanelSection("Mode");
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
  expect(panel().textContent).toContain("Off: the chain skips this criterion");        // not that it needs an analysis
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
  expect(document.activeElement).toBe(container().querySelector(".criterion-editor-name"));    // the copy's editor opens, the focus on its name
  expect(container().querySelector(".criterion-editor-name")!.textContent).toBe("Winter sun on facades copy");
  expect(cardNames()).toEqual(["Winter sun on facades", "Spring sun on windows", "Winter sun on facades copy"]);
  expect(selectedCardName()).toBe("Winter sun on facades copy");
  expect(service.requests).toContain("GET /criteria/3/settings");
});

const chainLine = () => (showCriterionCards(), container().querySelector(".chain-summary"))?.textContent?.replace(/[  ]/g, " ") ?? null;

test("the chain summary line under the cards: the last volume and its share of the maximum volume", async () => {
  await openChain([FACADES, WINDOWS], undefined, (chain) => { chain.summaryChain = { volume_after_each_m3: [610, 480], share_of_max_volume_kept: 0.4813 }; });
  expect(chainLine()).toBe("Kept 480 m³, 48 % of the maximum volume");
  const list = container().querySelector(".criterion-list")!;
  expect(list.compareDocumentPosition(container().querySelector(".chain-summary")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(container().querySelector(".criterion-panel")).toBeNull();                       // the list shows no panel
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

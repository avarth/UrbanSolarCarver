// The criteria's part of the open project (ProjectWorkspace): the selection of a card and the requests that change the criteria
// (use_criterion_selection.ts), a run refused for a criterion shown on that criterion (use_refusal_selection.ts), why Run analysis
// cannot start in Criteria and in Site and grid, what the results need to know about the criteria (useResultSteps), and the cards'
// lines and the chain line, which read the results (cardsOf).
import { useRef } from "react";
import { serviceProblemOf, updateCriterion, type CriterionEntry, type HealthReply, type ModeInfo } from "../api_client/client";
import { messages } from "../messages";
import type { FormStart, FormState, SettingsForm } from "../settings_form/form_state";
import { splitSettings, type StepFormAction } from "../settings_form/two_forms";
import type { ResultSteps, ResultStepsContext } from "../steps/result_steps";
import { criterionProgressOf, pipelineRecordOf, runningCriterion, type RunFailure, type RunLoop } from "../steps/run_state";
import { runAnalysisBlocker, stepOfSetting } from "../steps/SettingsStep";
import type { StageState, StepName } from "../steps/step_summaries";
import {
  activeCriteria, cardLineOf, chainSummaryLine, criteriaProtectingNothing, criterionStatus, stagesDuringRun, type StagesByCriterion,
} from "./criteria_state";
import type { CriterionListProps } from "./CriterionList";
import type { CriteriaHook } from "./use_criteria";
import { useCriterionSelection, type CriterionSelection } from "./use_criterion_selection";
import { useRefusalSelection } from "./use_refusal_selection";

type CriterionStages = Record<"preprocessing" | "thresholding", StageState>;
const NOT_RUN: CriterionStages = { preprocessing: "missing", thresholding: "missing" };

/** A criterion's stages that have output (none for a criterion the stage status does not list: bypassed, or new). */
function stagesWithOutputOf(stages: CriterionStages | undefined): string[] {
  return stages === undefined ? [] : (["preprocessing", "thresholding"] as const).filter((stage) => stages[stage] !== "missing");
}

export interface WorkspaceCriteriaSource {
  token: string;
  project: string;
  criteria: CriteriaHook;
  /** The criterion whose settings the criterion form holds (the workspace's state), and its setter. */
  shownCriterionId: string;
  setShownCriterionId: (id: string) => void;
  /** The shown criterion's entry; null when the project lists none. */
  criterion: CriterionEntry | null;
  /** The criterion whose results are shown; absent when the project lists none. */
  resultsCriterionId: string | undefined;
  sharedForm: SettingsForm;
  criterionForm: SettingsForm;
  /** The two forms as one (useBothForms): what the steps show and where their changes go. */
  form: FormState;
  dispatch: (action: StepFormAction) => void;
  currentForm: () => FormState;
  schema: Record<string, unknown>;
  modes: ModeInfo[];
  criterionKeys: ReadonlySet<string>;
  runs: RunLoop;
  warmUpState: HealthReply["warm_up"]["state"] | null;
  maxVolumeFiles: number;
  /** The stored test surface files (every criterion's). */
  testSurfaceFiles: number;
  hasWeatherFile: boolean;
  /** The mode the form shows needs a weather file. */
  modeNeedsWeatherFile: boolean;
  /** Each criterion's stages, as the stage status gives them. */
  criterionStages: StagesByCriterion;
  /** Stages as the steps show them: out of date while the form's analysis settings are not the stored ones. */
  shownAs: <Stage extends string>(stagesOf: Record<Stage, StageState>) => Record<Stage, StageState>;
  refreshStageStatus: () => void;
  /** Follows a request until its reply is in (the app waits for it before a rename, reset or delete of the project). */
  followed: <Reply>(request: Promise<Reply>) => Promise<Reply>;
  /** Asks for the stored test surface files again (after a delete). */
  reloadTestSurfaces: () => Promise<void>;
  /** Opens a step (and shows its layers). */
  openStep: (step: StepName) => void;
  /** Moves the focus to a setting's field in the panel. */
  focusSetting: (settingName: string) => void;
  /** A criterion is shown for a refused run or a link to one of its settings (showCriterion): the Criteria step shows its editor. */
  onShowCriterion: () => void;
  onServiceProblem: (error: unknown) => void;
}

/** The criteria's parts of the result steps' context (useResultSteps). */
export type CriteriaOfResults = Pick<ResultStepsContext,
  "criterionStagesWithResults" | "carvedByCriterionIds" | "carvedByCriterionWanted" | "carvedByCriterionOutOfDate" | "criterionStages" | "chainOrder"
  | "analysisWaitsFor" | "buildWaitReason" | "showRefusalOfCriterion" | "saveToCriterion" | "criterionBypassed" | "criterionNames">;

export interface WorkspaceCriteria {
  selection: CriterionSelection;
  /** The criteria that are on, in chain order. */
  active: CriterionEntry[];
  /** Why Run analysis cannot start, as Criteria says it and as Site and grid does; null when it can. */
  runBlocker: string | null;
  siteAndGridRunBlocker: string | null;
  /** The shown criterion's own analysis and carving stages, as shown; absent when the project lists none. */
  ownStages: CriterionStages | undefined;
  ofResults: CriteriaOfResults;
  /** A failed run's link to a setting (the criterion the run named, when it named one). */
  goToSetting: (settingName: string, criterionId?: string | null) => void;
  /** What the shown criterion's panel says over its settings about a refused start; null when nothing. */
  panelProblem: string | null;
  /** The cards and the chain line, from the results. */
  cardsOf: (resultSteps: Pick<ResultSteps, "results" | "criteriaAwaitingNumbers">, disabledReason: string | null) => {
    list: CriterionListProps; chainLine: string | null;
  };
}

export function useWorkspaceCriteria(source: WorkspaceCriteriaSource): WorkspaceCriteria {
  const { token, project, criteria, criterion, resultsCriterionId, criterionKeys, runs, criterionStages, shownAs, form, onServiceProblem } = source;
  const selection = useCriterionSelection({
    token, project, criteria, shownCriterionId: source.shownCriterionId, setShownCriterionId: source.setShownCriterionId, criterionForm: source.criterionForm,
    sharedForm: source.sharedForm, refreshStageStatus: source.refreshStageStatus, followed: source.followed, afterDelete: source.reloadTestSurfaces,
    onServiceProblem, onShowCriterion: source.onShowCriterion,
    criterionStartOf: (settings): FormStart => ({
      schema: source.schema, modes: source.modes, settings: splitSettings(settings, criterionKeys).criterion, gridPlan: null,
    }),
  });

  // A start refused for another criterion's settings marks them once that criterion's panel shows them, with the forms then.
  const latestForms = useRef({ dispatch: source.dispatch, currentForm: source.currentForm });
  latestForms.current = { dispatch: source.dispatch, currentForm: source.currentForm };
  const markRunErrors = (fieldErrors: RunFailure["field_errors"]) => {
    latestForms.current.dispatch({ type: "save_rejected", reply: { field_errors: fieldErrors, grid_plan: latestForms.current.currentForm().gridPlan } });
  };
  const showRefusalOfCriterion = (id: string, fieldErrors: RunFailure["field_errors"]) => selection.showCriterion(id, () => markRunErrors(fieldErrors));
  // A failed run's link to the setting it names: the step that holds the setting opens and the focus goes to its field. A setting
  // of the criterion the run named is focused in that criterion's panel, selected first, with the run's errors marked there again.
  const goToSetting = (settingName: string, criterionId: string | null = null) => {
    const step = stepOfSetting(settingName, criterionKeys);
    if (step === null) return;
    source.openStep(step);
    const focusField = () => source.focusSetting(settingName);
    const known = criteria.criteria.some((entry) => entry.id === criterionId);
    if (step !== "criteria" || criterionId === null || criterionId === source.shownCriterionId || !known) {
      focusField();
      return;
    }
    const failure = pipelineRecordOf(runs, project)?.state.failure ?? null;
    selection.showCriterion(criterionId, () => {
      if (failure?.criterion === criterionId) markRunErrors(failure.field_errors);
      focusField();
    });
  };

  // Run analysis is in Criteria and pinned in Site and grid: each names a setting to fix in another step with that step. Every
  // criterion that is on needs test surfaces (a bypassed one needs none), and a weather file when its mode reads one. With several
  // criteria every reason about a criterion names it, the shown one's too.
  const active = activeCriteria(criteria.criteria);
  const protectingNothing = criteriaProtectingNothing(criteria.criteria);
  const severalCriteria = criteria.criteria.length >= 2;
  const modeOf = (entry: CriterionEntry) => (entry.id === criterion?.id ? form.mode : entry.settings?.mode);
  const needingWeatherFile = active.filter((entry) => source.modes.find((mode) => mode.name === modeOf(entry))?.needs_epw);
  const runConditions = {
    runActive: runs.activeRun !== null, simulationActive: runs.activeRun?.origin === "simulate", maxVolumeFiles: source.maxVolumeFiles,
    testSurfaceFiles: criterion === null ? source.testSurfaceFiles : criterion.bypassed ? 1 : (criterion.test_surface_files ?? []).length,
    otherCriterionWithoutTestSurfaces: protectingNothing.find((entry) => entry.id !== criterion?.id)?.name ?? null,
    noCriterionOn: criteria.criteria.length > 0 && active.length === 0,
    modeNeedsWeatherFile: source.modeNeedsWeatherFile && !(criterion?.bypassed ?? false),
    otherCriterionNeedingWeatherFile: needingWeatherFile.find((entry) => entry.id !== criterion?.id)?.name ?? null,
    hasWeatherFile: source.hasWeatherFile, form, warmUpState: source.warmUpState, criterionKeys,
    shownCriterionName: severalCriteria ? criterion?.name ?? null : null,
    stepErrorsByStep: { site_and_grid: source.sharedForm.form.stepErrors, criteria: source.criterionForm.form.stepErrors },
  };
  const runBlocker = runAnalysisBlocker({ ...runConditions, shownIn: "criteria" });
  // Site and grid shows no criterion: with several, the one without test surfaces or that needs a weather file is named, the shown one too.
  const siteAndGridRunBlocker = runAnalysisBlocker(severalCriteria
    ? { ...runConditions, shownIn: "site_and_grid", testSurfaceFiles: 1, otherCriterionWithoutTestSurfaces: protectingNothing[0]?.name ?? null,
        modeNeedsWeatherFile: false, otherCriterionNeedingWeatherFile: needingWeatherFile[0]?.name ?? null }
    : { ...runConditions, shownIn: "site_and_grid" });

  // The shown criterion's own analysis and carving: its carving rule locks while its analysis is out of date; another criterion's
  // analysis out of date keeps a carving change from running (result_steps.tsx).
  const ownStages = resultsCriterionId === undefined ? undefined : shownAs(criterionStages[resultsCriterionId] ?? NOT_RUN);
  const waitedFor = active.find((entry) => entry.id !== resultsCriterionId && criterionStages[entry.id]?.preprocessing !== "current");
  const analysisWaitsFor = waitedFor === undefined ? null : { name: waitedFor.name, protectsNothing: protectingNothing.includes(waitedFor) };
  // With several criteria the builds name the first criterion that is on whose analysis is not current (the shown one as shown).
  const notAnalysed = active.find((entry) => (entry.id === resultsCriterionId ? ownStages : criterionStages[entry.id])?.preprocessing !== "current");
  const buildWaitReason = !severalCriteria || notAnalysed === undefined ? null
    : protectingNothing.includes(notAnalysed) ? messages.addTestSurfacesFirst(notAnalysed.name) : messages.carvingWaitsForAnalysisOf(notAnalysed.name);
  // A threshold value of another criterion, whose turn in the threshold queue came after this one was selected: its settings with
  // the value, while it is there with the mode the value was given in.
  const saveToCriterion = async (id: string, mode: string, values: Record<string, unknown>): Promise<boolean> => {
    const entry = criteria.current().criteria.find((candidate) => candidate.id === id);
    if (entry === undefined || entry.settings?.mode !== mode) return false;
    try {
      criteria.applyReply(await source.followed(updateCriterion(token, project, id, { values: { ...entry.settings, ...values } })));
      source.refreshStageStatus();
      return true;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return false;
    }
  };
  // Which criterion removed each voxel: asked for with two or more criteria on, once every one has thresholding output (the service
  // answers 404 before), and again whenever the criteria that are on change.
  const carvedByCriterionWanted = active.length >= 2;
  const everyOneCarved = active.every((entry) => stagesWithOutputOf(criterionStages[entry.id]).includes("thresholding"));
  const ofResults: CriteriaOfResults = {
    criterionStagesWithResults: resultsCriterionId === undefined ? undefined : stagesWithOutputOf(criterionStages[resultsCriterionId]),
    carvedByCriterionIds: carvedByCriterionWanted && everyOneCarved ? active.map((entry) => entry.id) : null,
    carvedByCriterionWanted,
    carvedByCriterionOutOfDate: active.some((entry) => shownAs(criterionStages[entry.id] ?? NOT_RUN).thresholding !== "current"),
    criterionStages: ownStages,
    chainOrder: criteria.criteria.map((entry) => entry.id),
    analysisWaitsFor, buildWaitReason, showRefusalOfCriterion, saveToCriterion,
    criterionBypassed: criterion?.bypassed ?? false,
    criterionNames: severalCriteria ? Object.fromEntries(criteria.criteria.map((entry) => [entry.id, entry.name])) : undefined,
  };

  // A start refused because criteria that are on protect nothing shows the first of them (the selected one when it is among them); its
// editor opens and its panel asks for test surfaces.
  const record = pipelineRecordOf(runs, project);
  const panelProblem = useRefusalSelection({
    record, criteria: criteria.criteria, selectedId: criteria.selectedId, shownCriterion: criterion, showCriterion: (id) => selection.showCriterion(id),
  });

  // The cards (CriteriaStep): their lines from the criteria's stages and the run summary. While a run of the project goes on, the
  // criterion it works on says Running and the stages it has done or still has to do count as current or out of date.
  const cardsOf: WorkspaceCriteria["cardsOf"] = (resultSteps, disabledReason) => {
    const runUnderWay = record !== null && record.state.final === null && record.refusal === null;
    const runningId = runUnderWay ? runningCriterion(record.state) : null;
    const cardStages = runUnderWay ? stagesDuringRun(criterionStages, criterionProgressOf(record.state)) : criterionStages;
    const summaryCriteria = resultSteps.results.summary?.criteria ?? [];
    const statusOf = (entry: CriterionEntry) => (resultSteps.criteriaAwaitingNumbers.has(entry.id) ? { kind: "running" as const }
      : criterionStatus(entry, criteria.criteria, cardStages, runningId));
    // What the chain kept, under the cards, only while every card that is on shows its current result: otherwise its numbers are
    // those of the run before.
    const chainCurrent = active.every((entry) => statusOf(entry).kind === "current");
    return {
      list: {
        criteria: criteria.criteria,
        selectedId: criteria.selectedId,
        lineOf: (entry) => cardLineOf(statusOf(entry), summaryCriteria.find((summary) => summary.id === entry.id)),
        runningId,
        disabledReason,
        ...selection.requests,
      },
      chainLine: chainCurrent ? chainSummaryLine(resultSteps.results.summary?.chain, active.length) : null,
    };
  };

  return {
    selection, active, runBlocker, siteAndGridRunBlocker, ownStages,
    ofResults, goToSetting, panelProblem, cardsOf,
  };
}

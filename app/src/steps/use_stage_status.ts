// The stage status of an open project (ProjectWorkspace): which pipeline stages are current, out of date or missing, in total and
// for each criterion, asked again after a save, a change of the input files or a run; and the stages as the steps show them.
import { useEffect, useRef, useState } from "react";
import { getStageStatus, type CriterionEntry, type ProjectDetail } from "../api_client/client";
import { activeCriteria, stagesByCriterionOf, type StagesByCriterion } from "../criteria/criteria_state";
import { analysisDiffersFromStored, type FormState } from "../settings_form/form_state";
import type { RunLoop } from "./run_state";
import type { PipelineStage, StageState } from "./step_summaries";

export interface StageStatusContext {
  token: string;
  project: ProjectDetail;
  criteria: CriterionEntry[];
  /** The two forms as one (useBothForms). */
  form: FormState;
  runs: RunLoop;
  onServiceProblem: (error: unknown) => void;
}

export interface StageStatus {
  /** The stages as the service last gave them. */
  stages: Record<PipelineStage, StageState>;
  /** Each criterion's stages, as the stage status gives them. */
  criterionStages: StagesByCriterion;
  /** Asks for the stage status again; *completedStages* are current at once, before the reply. */
  refreshStageStatus: (completedStages?: readonly string[]) => void;
  /** Stages as the steps show them: out of date while the form's analysis settings are not the stored ones. */
  shownAs: <Stage extends string>(stagesOf: Record<Stage, StageState>) => Record<Stage, StageState>;
  shownStages: Record<PipelineStage, StageState>;
  /** Every criterion that is on has a current carving. */
  everyCriterionCarved: boolean;
}

export function useStageStatus({ token, project, criteria, form, runs, onServiceProblem }: StageStatusContext): StageStatus {
  const [stages, setStages] = useState(project.stage_status.stages as Record<PipelineStage, StageState>);
  const [criterionStages, setCriterionStages] = useState<StagesByCriterion>(() => stagesByCriterionOf(project.criterion_status));
  // The stored analysis settings (FormState.storedAnalysisRevision) the last stage status used was asked for after.
  const [revisionOfStageStatus, setRevisionOfStageStatus] = useState(0);
  const storedAnalysisRevision = useRef(form.storedAnalysisRevision);
  storedAnalysisRevision.current = form.storedAnalysisRevision;

  // A stage status read across a run of this project says "missing" for results still on screen: such a reply is not used
  // (RunLoop.replyStillHolds), and the run's end asks again. *completedStages*: the stages a run just completed are current at
  // once, so their layers are not dimmed until the reply.
  const refreshStageStatus = (completedStages: readonly string[] = []) => {
    if (completedStages.length > 0) {
      const completed = Object.fromEntries(completedStages.map((stage) => [stage, "current"]));
      setStages((current) => ({ ...current, ...completed }));
      const completedOfCriteria = Object.fromEntries(completedStages.filter((stage) => stage === "preprocessing" || stage === "thresholding")
        .map((stage) => [stage, "current"]));
      setCriterionStages((current) => Object.fromEntries(Object.entries(current).map(([id, ofCriterion]) => [id, { ...ofCriterion, ...completedOfCriteria }])));
    }
    const replyStillHolds = runs.replyStillHolds(project.name);
    const revisionAsked = storedAnalysisRevision.current;
    getStageStatus(token, project.name).then((reply) => {
      if (!replyStillHolds()) return;
      setStages(reply.stages as Record<PipelineStage, StageState>);
      setCriterionStages(stagesByCriterionOf(reply.criteria));
      setRevisionOfStageStatus((revision) => Math.max(revision, revisionAsked));
    }).catch(onServiceProblem);
  };

  // The stage status describes the stored settings. While the form's mode or analysis settings are not those (a save waits or
  // was refused), or a save changed them and the stage status since is still to come, the analysis is out of date for the
  // settings shown: every stage counts as out of date, so the carving rule is locked and its results are dimmed (UX 5.5), and no
  // carving change can start the analysis of a mode the form does not show.
  const analysisOfOtherSettings = analysisDiffersFromStored(form) || revisionOfStageStatus < form.storedAnalysisRevision;
  const shownAs = <Stage extends string>(stagesOf: Record<Stage, StageState>): Record<Stage, StageState> => (analysisOfOtherSettings
    ? Object.fromEntries(Object.entries(stagesOf).map(([stage, state]) => [stage, state === "current" ? "out_of_date" : state])) as Record<Stage, StageState>
    : stagesOf);
  const shownStages = shownAs(stages);
  // Criteria's pinned Build envelope and massing waits until every criterion that is on has a current carving (disabled, with the reason,
  // while the settings shown differ from those it was made with).
  const everyCriterionCarved = activeCriteria(criteria).length > 0
    && activeCriteria(criteria).every((criterion) => criterionStages[criterion.id]?.thresholding === "current");

  // A save changes what the stages were run with; its reply is in once no save waits.
  useEffect(() => {
    if (form.changeCount > 0 && !form.pendingSave) refreshStageStatus();
  }, [form.pendingSave]);

  return { stages, criterionStages, refreshStageStatus, shownAs, shownStages, everyCriterionCarved };
}

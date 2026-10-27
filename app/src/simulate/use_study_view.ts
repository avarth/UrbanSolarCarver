// What Simulate shows of the selected study on the 3D view: its values (GET studies/{id}/values, read while Simulate is open, again
// after each run), the geometry shown and Change (kept across studies), the target (saved with the study), and what the view, the
// legend and the result card draw from them. One study at a time: the values of another study are not drawn once one is selected.
// The statistics are computed once per set of values and geometry; the share at the target once per target.
import { useEffect, useMemo, useState } from "react";
import { ApiError, getStudyValues, serviceProblemOf } from "../api_client/client";
import type { RunLoop } from "../steps/run_state";
import type { StageState } from "../steps/step_summaries";
import { changeOf, changeTolerance, distributionOf, highestOf, OPEN_COLUMN, shareAtOrAbove, type StudyGeometry, type StudyStatistics,
  type StudyView } from "./study_values";
import { decodeStudyValues, type StudyValues } from "./study_values_decoder";
import type { StudiesHook } from "./use_studies";

const NOT_FOUND = 404;

interface StudyViewSource {
  token: string;
  project: string;
  studies: StudiesHook;
  /** Simulate is open: the values are read only then. */
  active: boolean;
  runs: RunLoop;
  /** Design has built the envelope, the massing (their meshes are drawn). */
  envelopeBuilt: boolean;
  massingBuilt: boolean;
  /** The states of Design's envelope ("exporting") and massing stages. */
  envelopeStage: StageState;
  massingStage: StageState;
  /** The studies cannot be changed now (a run of the project): the target waits. */
  editDisabled: boolean;
  onServiceProblem: (error: unknown) => void;
}

export interface StudyViewHook {
  geometry: StudyGeometry;
  setGeometry: (geometry: StudyGeometry) => void;
  /** Colour by the change from the maximum volume (never on the maximum volume itself). */
  change: boolean;
  setChange: (change: boolean) => void;
  available: StudyGeometry[];
  outOfDateInDesign: StudyGeometry[];
  /** What the 3D view draws; null without a selected study whose values have the geometry shown. */
  view: StudyView | null;
  /** The legend and the result card; null when the view draws nothing. */
  legend: { label: string; unit: string; range: [number, number]; mode: "value" | "change"; hasLoss: boolean; target: number | null; disabled: boolean } | null;
  card: { geometry: StudyGeometry; unit: string; statistics: StudyStatistics; baseline: StudyStatistics | null } | null;
  /** Shows the target at once and saves it with the selected study. */
  setTarget: (target: number | null) => void;
}

export function useStudyView({ token, project, studies, active, runs, envelopeBuilt, massingBuilt, envelopeStage, massingStage, editDisabled,
                               onServiceProblem }: StudyViewSource): StudyViewHook {
  const [chosenGeometry, setGeometry] = useState<StudyGeometry>("max_volume");
  const [chosenChange, setChange] = useState(false);
  const [loaded, setLoaded] = useState<{ id: string; values: StudyValues } | null>(null);
  // A target being saved, shown until the study's entry has it.
  const [savingTarget, setSavingTarget] = useState<{ id: string; target: number | null } | null>(null);

  const selected = studies.studies.find((study) => study.entry.id === studies.selectedId) ?? null;
  const selectedId = selected?.entry.id ?? null;
  const hasResult = selected !== null && (selected.state === "current" || selected.state === "out_of_date");
  const running = runs.activeRun !== null;
  // Read when a study with a result is selected, and again when a run ends (a simulation writes new values); not during a run. They
  // are let go when Simulate closes (tens of megabytes on a district) and read again when it opens.
  useEffect(() => {
    if (!active) setLoaded(null);
    if (!active || !hasResult || running || selectedId === null) return;
    let wanted = true;
    getStudyValues(token, project, selectedId).then((buffer) => {
      if (wanted) setLoaded({ id: selectedId, values: decodeStudyValues(buffer) });
    }).catch((error: unknown) => {
      if (!wanted) return;
      setLoaded(null);
      if (!(error instanceof ApiError && error.status === NOT_FOUND) && serviceProblemOf(error) !== "other") onServiceProblem(error);
    });
    return () => { wanted = false; };
  }, [active, selectedId, hasResult, running]);

  const available: StudyGeometry[] = ["max_volume", ...(envelopeBuilt ? ["envelope" as const] : []), ...(massingBuilt ? ["massing" as const] : [])];
  const outOfDateInDesign: StudyGeometry[] = [...(envelopeStage === "out_of_date" ? ["envelope" as const] : []),
                                              ...(massingStage === "out_of_date" ? ["massing" as const] : [])];
  const geometry = available.includes(chosenGeometry) ? chosenGeometry : "max_volume";
  const change = chosenChange && geometry !== "max_volume";

  const values = hasResult && loaded !== null && loaded.id === selectedId ? loaded.values : null;
  const shown = values?.values[geometry] ?? null;
  const baselineValues = values?.values.max_volume ?? null;
  const target = selected === null ? null : savingTarget?.id === selectedId ? savingTarget.target : selected.entry.target ?? null;

  const distribution = useMemo(() => (shown === null ? null : distributionOf(shown)), [shown]);
  const baselineDistribution = useMemo(() => (baselineValues === null || geometry === "max_volume" ? null : distributionOf(baselineValues)),
                                       [baselineValues, geometry]);
  const share = useMemo(() => (shown === null ? null : shareAtOrAbove(shown, target)), [shown, target]);
  const baselineShare = useMemo(() => (baselineDistribution === null || baselineValues === null ? null : shareAtOrAbove(baselineValues, target)),
                                   [baselineDistribution, baselineValues, target]);
  const highest = useMemo(() => (shown === null ? 0 : highestOf(shown)), [shown]);
  // By change: the scale runs to the largest gain; a loss is a fall by more than the tolerance.
  const changeScale = useMemo(() => {
    if (!change || shown === null || values === null) return null;
    const changes = changeOf(shown, values.values.max_volume);
    const tolerance = changeTolerance(values.values[OPEN_COLUMN], values.values.max_volume);
    return { highest: highestOf(changes), hasLoss: changes.some((value) => value < -tolerance) };
  }, [change, shown, values]);

  const unit = values?.header.unit ?? "";
  const label = studies.metrics.find((metric) => metric.name === selected?.entry.metric)?.label ?? "";
  const drawn = values !== null && shown !== null && selected !== null;
  const setTarget = (next: number | null) => {
    if (selectedId === null) return;
    const id = selectedId;
    setSavingTarget({ id, target: next });
    const done = () => setSavingTarget((saving) => (saving?.id === id && saving.target === next ? null : saving));
    studies.update(id, { target: next }).then(done, (error: unknown) => {
      done();
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    });
  };

  return {
    geometry, setGeometry, change, setChange, available, outOfDateInDesign, setTarget,
    view: drawn ? { values, geometry, change, target, unit, dimmed: selected.state === "out_of_date" } : null,
    legend: drawn ? {
      label, unit, target, disabled: editDisabled, mode: change ? "change" : "value", hasLoss: changeScale?.hasLoss ?? false,
      range: [0, changeScale?.highest ?? highest],
    } : null,
    card: drawn && distribution !== null ? {
      geometry, unit, statistics: { ...distribution, shareAtTarget: share },
      baseline: baselineDistribution === null ? null : { ...baselineDistribution, shareAtTarget: baselineShare },
    } : null,
  };
}

// What Simulate shows of the selected study on the 3D view: its values (GET studies/{id}/values, read while Simulate is open, again
// after each run), the geometry shown, Change and the colouring (kept across studies), the colour range and palette, and what the
// view, the legend and the result card draw from them. One study at a time: the values of another study are not drawn once one is
// selected. The statistics are computed once per set of values and geometry; the share at the target once per target.
//
// The colour range (user, 2026-10-28): a low and a high end; the palette runs between them and values beyond either end take that
// end's colour. By value the ends are the study's target (the low end, which the result card's "at target" reads) and target_max,
// saved with the study, by default 0 and the highest value of the geometry shown. By share they are percentages of the open-site
// value, 0 and 100 by default, kept for each study while the app is open. The palette is the viewer's choice, kept in the browser.
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getStudyValues, serviceProblemOf, type StudyChange } from "../api_client/client";
import type { RunLoop } from "../steps/run_state";
import type { StageState } from "../steps/step_summaries";
import { isStudyPalette, STUDY_PALETTES, type StudyPalette } from "../viewer/study_palettes";
import { changeOf, changeTolerance, distributionOf, highestOf, keptShareOf, OPEN_COLUMN, shareAtOrAbove, type ColourBy, type StudyGeometry,
  type StudyStatistics, type StudyView } from "./study_values";
import { decodeStudyValues, type StudyValues } from "./study_values_decoder";
import type { StudiesHook } from "./use_studies";

const NOT_FOUND = 404;
const PALETTE_STORAGE_KEY = "usc.studyPalette";
const FULL_SHARE: [number, number] = [0, 100];

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
  /** The studies cannot be changed now (a run of the project): the saved ends wait. */
  editDisabled: boolean;
  onServiceProblem: (error: unknown) => void;
}

/** The legend's content: the scale the bar spans, the two ends of the colour range on it, and what it is coloured by. */
export interface StudyLegend {
  label: string;
  unit: string;
  mode: "share" | "value" | "change";
  /** The extent of the bar: 0 to 100 (%) by share, 0 to the highest value (or change) otherwise. */
  scale: [number, number];
  /** The two ends of the colour range (not by change, where the bar is the change ramp). */
  low: number;
  high: number;
  palette: StudyPalette;
  hasLoss: boolean;
  /** The ends cannot be moved now (a run of the project); by value they are saved with the study. */
  disabled: boolean;
}

export interface StudyViewHook {
  geometry: StudyGeometry;
  setGeometry: (geometry: StudyGeometry) => void;
  /** Colour by the change from the maximum volume (never on the maximum volume itself). */
  change: boolean;
  setChange: (change: boolean) => void;
  /** How the values are coloured when Change is off (kept across studies): share of the open-site value, or the value. */
  colourBy: ColourBy;
  setColourBy: (colourBy: ColourBy) => void;
  palette: StudyPalette;
  setPalette: (palette: StudyPalette) => void;
  available: StudyGeometry[];
  outOfDateInDesign: StudyGeometry[];
  /** Geometries Design has built that the selected study's last result does not have: they wait for a new run of the study. */
  waitingForStudy: StudyGeometry[];
  /** The selected study is out of date: the view's stamp says so. */
  studyOutOfDate: boolean;
  /** The selected study has a result whose values are not read during a run: the view says they are shown when it ends. */
  waitingForRun: boolean;
  /** What the 3D view draws; null without a selected study whose values have the geometry shown. */
  view: StudyView | null;
  /** The legend and the result card; null when the view draws nothing. */
  legend: StudyLegend | null;
  card: { geometry: StudyGeometry; unit: string; statistics: StudyStatistics; baseline: StudyStatistics | null } | null;
  /** Moves the low or the high end of the colour range (null: back to its default); by value it is saved with the selected study once
   * the gesture ends. */
  setRangeEnd: (end: "low" | "high", value: number | null) => void;
}

/** How long after the last change of a saved end it is saved: a held arrow key is one save, of the value it ended on. */
export const TARGET_SAVE_DELAY_MILLISECONDS = 300;

/** The palette kept in the browser, magma when there is none or the storage cannot be read. */
function storedPalette(): StudyPalette {
  try {
    const stored = window.localStorage.getItem(PALETTE_STORAGE_KEY);
    return isStudyPalette(stored) ? stored : STUDY_PALETTES[0];
  } catch {
    return STUDY_PALETTES[0];
  }
}

export function useStudyView({ token, project, studies, active, runs, envelopeBuilt, massingBuilt, envelopeStage, massingStage, editDisabled,
                               onServiceProblem }: StudyViewSource): StudyViewHook {
  const [chosenGeometry, setGeometry] = useState<StudyGeometry>("max_volume");
  const [chosenChange, setChange] = useState(false);
  const [colourBy, setColourBy] = useState<ColourBy>("share");
  const [palette, setPaletteState] = useState<StudyPalette>(storedPalette);
  const setPalette = (next: StudyPalette) => {
    setPaletteState(next);
    try { window.localStorage.setItem(PALETTE_STORAGE_KEY, next); } catch { /* the choice lasts this session */ }
  };
  // By share: each study's range, while the app is open.
  const [shareRanges, setShareRanges] = useState<Record<string, [number, number]>>({});
  const [loaded, setLoaded] = useState<{ id: string; values: StudyValues } | null>(null);
  // The saved ends being saved, shown until the study's entry has them.
  const [saving, setSaving] = useState<{ id: string; change: StudyChange } | null>(null);

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
  const values = hasResult && loaded !== null && loaded.id === selectedId ? loaded.values : null;
  // A geometry Design built after the study's last run has no values in it: its segment waits for a new run, and the view shows the
  // maximum volume meanwhile (the choice is kept for the studies that have it).
  const waitingForStudy = values === null ? [] : available.filter((each) => values.values[each] === undefined);
  const geometry = available.includes(chosenGeometry) && !waitingForStudy.includes(chosenGeometry) ? chosenGeometry : "max_volume";
  const change = chosenChange && geometry !== "max_volume";

  const shown = values?.values[geometry] ?? null;
  const baselineValues = values?.values.max_volume ?? null;
  const savedEnd = (key: "target" | "target_max"): number | null => {
    if (selected === null) return null;
    if (saving?.id === selectedId && key in saving.change) return saving.change[key] ?? null;
    return selected.entry[key] ?? null;
  };
  const target = savedEnd("target");
  const targetMax = savedEnd("target_max");

  const distribution = useMemo(() => (shown === null ? null : distributionOf(shown)), [shown]);
  const baselineDistribution = useMemo(() => (baselineValues === null || geometry === "max_volume" ? null : distributionOf(baselineValues)),
                                       [baselineValues, geometry]);
  const share = useMemo(() => (shown === null ? null : shareAtOrAbove(shown, target)), [shown, target]);
  const openValues = values?.values[OPEN_COLUMN] ?? null;
  const kept = useMemo(() => (shown === null || openValues === null ? null : keptShareOf(shown, openValues)), [shown, openValues]);
  const baselineKept = useMemo(() => (baselineValues === null || openValues === null || geometry === "max_volume" ? null
    : keptShareOf(baselineValues, openValues)), [baselineValues, openValues, geometry]);
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

  // The colour range on the scale shown.
  const byShare = colourBy === "share";
  const shareRange = (selectedId !== null ? shareRanges[selectedId] : undefined) ?? FULL_SHARE;
  const valueHigh = targetMax ?? highest;
  const [low, high]: [number, number] = byShare ? shareRange : [target ?? 0, valueHigh];
  const scale: [number, number] = change ? [0, changeScale?.highest ?? 0] : byShare ? FULL_SHARE : [0, Math.max(highest, valueHigh, target ?? 0)];

  const unit = values?.header.unit ?? "";
  const label = studies.metrics.find((metric) => metric.name === selected?.entry.metric)?.label ?? "";
  const drawn = values !== null && shown !== null && selected !== null;
  // A saved end shows at once; it is saved once a gesture ends: TARGET_SAVE_DELAY_MILLISECONDS after the last change (a drag gives
  // one change, at its release; held or repeated keys many). The saves go one after another, so the service applies them in order.
  const latestStudies = useRef(studies);
  latestStudies.current = studies;
  const pendingSave = useRef<{ id: string; change: StudyChange; timer: ReturnType<typeof setTimeout> } | null>(null);
  const saves = useRef<Promise<unknown>>(Promise.resolve());
  const save = (id: string, sent: StudyChange) => {
    const done = () => setSaving((current) => (current?.id === id && current.change === sent ? null : current));
    saves.current = saves.current.then(() => latestStudies.current.update(id, sent)).then(done, (error: unknown) => {
      done();
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    });
  };
  const flushSave = () => {
    const pending = pendingSave.current;
    if (pending === null) return;
    clearTimeout(pending.timer);
    pendingSave.current = null;
    save(pending.id, pending.change);
  };
  useEffect(() => flushSave, []);         // an end still waiting is saved when the workspace closes
  const saveEnd = (key: "target" | "target_max", next: number | null) => {
    if (selectedId === null) return;
    if (pendingSave.current !== null && pendingSave.current.id !== selectedId) flushSave();
    const earlier = pendingSave.current?.id === selectedId ? pendingSave.current.change : {};
    if (pendingSave.current !== null) clearTimeout(pendingSave.current.timer);
    const merged: StudyChange = { ...earlier, [key]: next };
    setSaving({ id: selectedId, change: merged });
    pendingSave.current = { id: selectedId, change: merged, timer: setTimeout(flushSave, TARGET_SAVE_DELAY_MILLISECONDS) };
  };
  const setRangeEnd = (end: "low" | "high", next: number | null) => {
    if (selectedId === null) return;
    if (byShare) {
      const [shareLow, shareHigh] = shareRange;
      const range: [number, number] = end === "low" ? [next ?? FULL_SHARE[0], shareHigh] : [shareLow, next ?? FULL_SHARE[1]];
      setShareRanges((ranges) => ({ ...ranges, [selectedId]: range }));
      return;
    }
    saveEnd(end === "low" ? "target" : "target_max", next);
  };

  return {
    geometry, setGeometry, change, setChange, colourBy, setColourBy, palette, setPalette, available, outOfDateInDesign, waitingForStudy,
    setRangeEnd,
    waitingForRun: active && running && hasResult && values === null,
    studyOutOfDate: active && selected?.state === "out_of_date",
    view: drawn ? { values, geometry, change, colourBy, range: [low, high], palette, unit, dimmed: selected.state === "out_of_date" } : null,
    legend: drawn ? {
      label, unit, mode: change ? "change" : colourBy, scale, low, high, palette, hasLoss: changeScale?.hasLoss ?? false,
      disabled: !byShare && editDisabled,
    } : null,
    card: drawn && distribution !== null ? {
      geometry, unit, statistics: { ...distribution, shareAtTarget: share, keptShare: kept },
      baseline: baselineDistribution === null ? null : { ...baselineDistribution, shareAtTarget: baselineShare, keptShare: baselineKept },
    } : null,
  };
}

// What Simulate shows of the selected study on the 3D view: its values (GET studies/{id}/values, read while Simulate is open, again
// after each run) with the geometry the study stands on the plot (its setting "geometry"), the colouring (kept across studies), the
// colour range and palette, and what the view, the legend and the result card draw from them. One study at a time: the values of
// another study are not drawn once one is selected. The statistics are computed once per set of values; the shares at the target once
// per target. The result card has the points on the study's geometry (the service puts them last) apart from the others, and those
// by the way they face.
//
// The colour range (user, 2026-10-28): a low and a high end; the palette runs between them and values beyond either end take that
// end's colour. By value the ends are the study's target (the low end, which the result card's "at target" reads) and target_max,
// saved with the study, by default 0 and the highest value shown. By share they are percentages of the no-build value, 0 and 100 by
// default, kept for each study while the app is open. The palettes are pinned (user, 2026-10-28): magma by value, viridis by share.
import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { ApiError, getStudySkyPatches, getStudyValues, reportServiceProblem, type SkyDome, type StudyChange } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import { useLatest } from "../hooks/use_latest";
import { messages } from "../messages";
import type { RunLoop } from "../common/run_state";
import type { StudyPalette } from "../viewer/study_palettes";
import { columnOf, distributionOf, FACING_GROUPS, facingGroups, highestOf, keptShareOf, OPEN_COLUMN, shareAtOrAbove, valuesAt, type ColourBy,
  type FacingGroup, type StudyGeometry, type StudyStand, type StudyStatistics, type StudyView } from "../viewer/study_values";
import { decodeStudyValues, type StudyValues } from "../viewer/study_values_decoder";
import type { StudiesHook } from "./use_studies";

const NOT_FOUND = 404;
const FULL_SHARE: [number, number] = [0, 100];

interface StudyViewSource {
  studies: StudiesHook;
  /** Simulate is open: the values are read only then. */
  active: boolean;
  runs: RunLoop;
  /** The studies cannot be changed now (a run of the project): the saved ends wait. */
  editDisabled: boolean;
  /** The project's north (degrees clockwise from +y): the facades of the study's geometry are grouped by the compass point they face. */
  northDegrees: number;
}

/** The legend's content: the scale the bar spans, the two ends of the colour range on it, and what it is coloured by. */
export interface StudyLegend {
  label: string;
  unit: string;
  mode: ColourBy;
  /** The extent of the bar: 0 to 100 (%) by share, 0 to the highest value otherwise. */
  scale: [number, number];
  /** The two ends of the colour range. */
  low: number;
  high: number;
  palette: StudyPalette;
  /** The ends cannot be moved now (a run of the project); by value they are saved with the study. */
  disabled: boolean;
}

/** The result card's content: the statistics of the points that are not on the study's geometry, and of those on it, whole and by facing. */
export interface StudyCard {
  unit: string;
  /** The study's files, the surroundings, the terrain and the ground; null when the study samples none of them. */
  surroundings: StudyStatistics | null;
  /** The faces of the study's geometry; null when the study does not sample them. */
  building: { stand: StudyGeometry; statistics: StudyStatistics; byFacing: Record<FacingGroup, StudyStatistics | null> } | null;
}

export interface StudyViewHook {
  /** What the selected study stands on the plot (max_volume without a selected study). */
  geometry: StudyStand;
  /** How the values are coloured (kept across studies): share of the no-build value, or the value. */
  colourBy: ColourBy;
  setColourBy: (colourBy: ColourBy) => void;
  /** The selected study is shown on the view (its values, legend and result card); off, nothing of it is drawn. */
  shownOnView: boolean;
  setShownOnView: (shown: boolean) => void;
  /** The selected study is out of date: the view's stamp says so. */
  studyOutOfDate: boolean;
  /** The selected study has a result whose values are not read during a run: the view says they are shown when it ends. */
  waitingForRun: boolean;
  /** What the 3D view draws; null without a selected study whose values have its geometry's column. */
  view: StudyView | null;
  /** The selected study's sky dome (the value each patch carried) and its legend title; null while nothing is drawn, for a sun
   * hours study, or for a result from before the patch values were kept. Design's dome is not shown in Simulate. */
  skyDome: SkyDome | null;
  skyDomeTitle: string;
  /** The selected study measures the sky but its result has no sky patches (run before they were kept): its dome needs a run. */
  skyDomeMissing: boolean;
  /** The legend and the result card; null when the view draws nothing. */
  legend: StudyLegend | null;
  card: StudyCard | null;
  /** Moves the low or the high end of the colour range (null: back to its default); by value it is saved with the selected study once
   * the gesture ends. */
  setRangeEnd: (end: "low" | "high", value: number | null) => void;
}

/** How long after the last change of a saved end it is saved: a held arrow key is one save, of the value it ended on. */
export const TARGET_SAVE_DELAY_MILLISECONDS = 300;

/** The palette of each colouring: magma by value, viridis by share of the no-build value. */
const PALETTE_OF: Record<ColourBy, StudyPalette> = { value: "magma", share: "viridis" };

/** What a study stands on the plot, from its settings: the maximum volume until one is chosen. */
export function standOf(settings: Record<string, unknown> | undefined): StudyStand {
  const stand = settings?.geometry;
  return stand === "none" || stand === "envelope" || stand === "massing" ? stand : "max_volume";
}

/** The part of the statistics that does not depend on the target, of *values* and of their no-build values *open*; null for no points. */
function partOf(values: Float32Array, open: Float32Array | null) {
  if (values.length === 0) return null;
  return { values, distribution: distributionOf(values), kept: open === null ? null : keptShareOf(values, open) };
}

type Part = ReturnType<typeof partOf>;

const withTarget = (part: Part, target: number | null): StudyStatistics | null =>
  part === null ? null : { ...part.distribution, shareAtTarget: shareAtOrAbove(part.values, target), keptShare: part.kept };

export function useStudyView({ studies, active, runs, editDisabled, northDegrees }: StudyViewSource): StudyViewHook {
  const { token, project, onServiceProblem } = useProjectSession();
  const [colourBy, setColourBy] = useState<ColourBy>("value");
  const [shownOnView, setShownOnView] = useState(true);
  const palette = PALETTE_OF[colourBy];
  // By share: each study's range, while the app is open.
  const [shareRanges, setShareRanges] = useState<Record<string, [number, number]>>({});
  const [loaded, setLoaded] = useState<{ id: string; values: StudyValues } | null>(null);
  const [loadedSky, setLoadedSky] = useState<{ id: string; dome: SkyDome | null } | null>(null);
  // The saved ends being saved, shown until the study's entry has them.
  const [saving, setSaving] = useState<{ id: string; change: StudyChange } | null>(null);

  const selected = studies.studies.find((study) => study.entry.id === studies.selectedId) ?? null;
  const selectedId = selected?.entry.id ?? null;
  // Made before the memos that read the study: the React Compiler takes a call given part of the study as one that may change it.
  const skyDomeTitle = messages.studySkyDomeLegend(selected?.entry.metric);
  const geometry = standOf(selected?.entry.settings);
  const hasResult = selected !== null && (selected.state === "current" || selected.state === "out_of_date");
  const running = runs.activeRun !== null;
  const reportReadProblem = useEffectEvent((error: unknown) => {
    if (!(error instanceof ApiError && error.status === NOT_FOUND)) reportServiceProblem(error, onServiceProblem);
  });
  // Read when a study with a result is selected, and again when a run ends (a simulation writes new values); not during a run. They
  // are let go when Simulate closes (tens of megabytes on a district) and read again when it opens.
  if (!active && (loaded !== null || loadedSky !== null)) {
    setLoaded(null);
    setLoadedSky(null);
  }
  useEffect(() => {
    if (!active || !hasResult || running || selectedId === null) return;
    let wanted = true;
    getStudyValues(token, project, selectedId).then((buffer) => {
      if (wanted) setLoaded({ id: selectedId, values: decodeStudyValues(buffer) });
    }).catch((error: unknown) => {
      if (!wanted) return;
      setLoaded(null);
      reportReadProblem(error);
    });
    // The sky dome is read beside the values; a result without one answers null (a sun hours study, or one from before it was kept).
    getStudySkyPatches(token, project, selectedId).then((dome) => {
      if (wanted) setLoadedSky({ id: selectedId, dome });
    }).catch((error: unknown) => {
      if (!wanted) return;
      setLoadedSky({ id: selectedId, dome: null });
      reportReadProblem(error);
    });
    return () => { wanted = false; };
  }, [active, token, project, selectedId, hasResult, running]);

  const values = hasResult && loaded !== null && loaded.id === selectedId ? loaded.values : null;
  const column = columnOf(geometry);
  // A result of another geometry than the study accounts for now (run before the study changed) is not drawn, even when it has the
  // column (every result has "open"): nothing is drawn until the study runs again, and the stamp says it is out of date.
  const resultGeometry = values?.header.geometry ?? geometry;
  const shown = resultGeometry === geometry ? values?.values[column] ?? null : null;
  const savedEnd = (key: "target" | "target_max"): number | null => {
    if (selected === null) return null;
    if (saving?.id === selectedId && key in saving.change) return saving.change[key] ?? null;
    return selected.entry[key] ?? null;
  };
  const target = savedEnd("target");
  const targetMax = savedEnd("target_max");

  // The points on the study's geometry are the last ones; the card has them apart, and by the way they face.
  const parts = useMemo(() => {
    if (shown === null || values === null) return null;
    const open = values.values[OPEN_COLUMN] ?? null;
    const count = shown.length;
    const onGeometry = geometry === "none" ? 0 : Math.min(count, Math.max(0, values.header.geometry_point_count ?? 0));
    const split = count - onGeometry;
    const facing = onGeometry === 0 ? null : facingGroups(values.quads, split, count, northDegrees);
    return {
      surroundings: partOf(shown.subarray(0, split), open === null ? null : open.subarray(0, split)),
      building: partOf(shown.subarray(split), open === null ? null : open.subarray(split)),
      byFacing: facing === null ? null : Object.fromEntries(FACING_GROUPS.map((group) =>
        [group, partOf(valuesAt(shown, facing[group]), open === null ? null : valuesAt(open, facing[group]))])) as Record<FacingGroup, Part>,
    };
  }, [shown, values, geometry, northDegrees]);
  const card = useMemo((): StudyCard | null => {
    if (parts === null) return null;
    const building = geometry === "none" ? null : withTarget(parts.building, target);
    return {
      unit: values?.header.unit ?? "",
      surroundings: withTarget(parts.surroundings, target),
      building: building === null || geometry === "none" || parts.byFacing === null ? null : {
        stand: geometry, statistics: building,
        byFacing: Object.fromEntries(FACING_GROUPS.map((group) => [group, withTarget(parts.byFacing![group], target)])) as Record<FacingGroup, StudyStatistics | null>,
      },
    };
  }, [parts, target, geometry, values]);
  const highest = useMemo(() => (shown === null ? 0 : highestOf(shown)), [shown]);

  // The colour range on the scale shown.
  const byShare = colourBy === "share";
  const shareRange = (selectedId !== null ? shareRanges[selectedId] : undefined) ?? FULL_SHARE;
  // A saved high end at or below the target (an earlier legend let the two meet) counts as none.
  const valueHigh = targetMax !== null && targetMax > (target ?? 0) ? targetMax : highest;
  const [low, high]: [number, number] = byShare ? shareRange : [target ?? 0, valueHigh];
  const scale: [number, number] = byShare ? FULL_SHARE : [0, Math.max(highest, valueHigh, target ?? 0)];

  const unit = values?.header.unit ?? "";
  const label = studies.metrics.find((metric) => metric.name === selected?.entry.metric)?.label ?? "";
  const drawn = shownOnView && values !== null && shown !== null && selected !== null;
  // A saved end shows at once; it is saved once a gesture ends: TARGET_SAVE_DELAY_MILLISECONDS after the last change (a drag gives
  // one change, at its release; held or repeated keys many). The saves go one after another, so the service applies them in order.
  const latestStudies = useLatest(studies);
  const pendingSave = useRef<{ id: string; change: StudyChange; timer: ReturnType<typeof setTimeout> } | null>(null);
  const saves = useRef<Promise<unknown>>(Promise.resolve());
  const save = (id: string, sent: StudyChange) => {
    const done = () => setSaving((current) => (current?.id === id && current.change === sent ? null : current));
    saves.current = saves.current.then(() => latestStudies.current.update(id, sent)).then(done, (error: unknown) => {
      done();
      reportServiceProblem(error, onServiceProblem);
    });
  };
  const flushSave = () => {
    const pending = pendingSave.current;
    if (pending === null) return;
    clearTimeout(pending.timer);
    pendingSave.current = null;
    save(pending.id, pending.change);
  };
  const flushOnClose = useEffectEvent(() => flushSave());
  useEffect(() => () => flushOnClose(), []);         // an end still waiting is saved when the workspace closes
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
    geometry, colourBy, setColourBy, shownOnView, setShownOnView, setRangeEnd,
    waitingForRun: active && running && hasResult && values === null,
    studyOutOfDate: active && shownOnView && selected?.state === "out_of_date",       // a hidden study shows no stamp
    skyDome: drawn && loadedSky?.id === selectedId ? loadedSky.dome : null,
    skyDomeMissing: drawn && loadedSky?.id === selectedId && loadedSky.dome === null && selected?.entry.metric !== "sun_hours",
    skyDomeTitle,
    view: drawn ? { values, column, colourBy, range: [low, high], palette, unit, dimmed: selected.state === "out_of_date" } : null,
    legend: drawn ? { label, unit, mode: colourBy, scale, low, high, palette, disabled: !byShare && editDisabled } : null,
    card: drawn ? card : null,
  };
}

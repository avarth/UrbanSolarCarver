// What Simulate puts over the 3D view: the studies panel (StudiesPanel) with the popover of a study's settings (StudyPopover) and
// Run; for the selected study the target legend along the bottom and the result card in
// the bottom right corner (use_study_view.ts; the view draws its values, ProjectWorkspace gives them to ViewerPane). The studies are read when Simulate opens and again whenever a run ends while it is open: a simulation's results, or a run of
// Design that changed what the studies trace. The simulation is a run of the app's run loop (origin "simulate"), one job at a time
// with the runs of Design: Run waits while one of those goes on, and the studies cannot be changed while a run of the project does.
import { useEffect, useEffectEvent, useId, useRef, useState, type ReactNode } from "react";
import { failureTextOf, reportServiceProblem, type CriterionEntry, type InputFileInfo, type StudySource } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import { messages } from "../messages";
import type { ViewportTheme } from "../viewer/colour_scales";
import type { RunLoop } from "../common/run_state";
import { RunProgress } from "../common/RunProgress";
import { TargetLegend } from "../viewer_overlays/TargetLegend";
import { ResultCard } from "./ResultCard";
import { StudiesPanel } from "./StudiesPanel";
import { StudyPopover } from "./StudyPopover";
import type { StudiesHook } from "./use_studies";
import type { StudyViewHook } from "./use_study_view";
import "./simulate.css";

interface SimulateViewProps {
  studies: StudiesHook;
  /** The criteria, which Add study offers as shortcuts. */
  criteria: CriterionEntry[];
  /** The test surface files the project stores, with their triangle counts. */
  storedTestSurfaces: InputFileInfo[];
  /** The project has surroundings files, and a terrain file: a study can sample them (the ground around the site without a terrain). */
  hasSurroundings: boolean;
  hasTerrain: boolean;
  /** Carve has built the envelope, the massing: a study can account for them. */
  envelopeBuilt: boolean;
  massingBuilt: boolean;
  /** Whether the project has a base height: a study can then stand its base volume. */
  hasBaseVolume?: boolean;
  /** The carving's test point spacing (m), which a study follows until it has its own. */
  carvingSpacing: number;
  runs: RunLoop;
  /** A study let a file go, which the project may then no longer store: the stored files are asked for again. */
  onStoredFilesChange: () => void;
  /** The selected study on the view: the target legend and the result card. */
  studyView: StudyViewHook;
  /** The viewport theme (the legend's palettes do not depend on it). */
  theme?: ViewportTheme;
  /** The notice of input files changed in the project folder or missing from it, at the top of the studies panel. */
  notice?: ReactNode;
}

export function SimulateView({ studies, criteria, storedTestSurfaces, hasSurroundings, hasTerrain, envelopeBuilt, massingBuilt, hasBaseVolume = false, carvingSpacing, runs,
                               onStoredFilesChange, studyView, notice }: SimulateViewProps) {
  const { project, onServiceProblem } = useProjectSession();
  const [popoverStudyId, setPopoverStudyId] = useState<string | null>(null);
  const view = useRef<HTMLDivElement>(null);
  const popoverId = useId();
  const runEnded = runs.activeRun === null;
  const opened = useRef(false);
  const refreshStudies = useEffectEvent(() => void studies.refresh());
  useEffect(() => refreshStudies(), []);
  useEffect(() => {
    if (opened.current && runEnded) refreshStudies();
    opened.current = true;
  }, [runEnded]);

  const active = runs.activeRun;
  const runDisabledReason = active === null ? null : active.origin === "simulate" ? messages.simulationInProgress : messages.designRunInProgress;
  const editDisabledReason = active !== null && active.project === project ? runDisabledReason : null;

  /** Sends a request; resolves with the reason it failed, or null. */
  const attempt = async (request: () => Promise<unknown>): Promise<string | null> => {
    try {
      await request();
      return null;
    } catch (error) {
      reportServiceProblem(error, onServiceProblem);
      return failureTextOf(error);
    }
  };
  const settingsButtonOf =(id: string) => [...view.current?.querySelectorAll<HTMLElement>(".study-row") ?? []]
    .find((row) => row.dataset.studyId === id)?.querySelector<HTMLButtonElement>(".study-row-settings") ?? null;
  const closePopover = () => {
    const id = popoverStudyId;
    setPopoverStudyId(null);
    if (id !== null) settingsButtonOf(id)?.focus();
  };
  const add = (source: StudySource) => attempt(async () => setPopoverStudyId((await studies.add(source)).id));

  const shown = studies.studies.find((study) => study.entry.id === popoverStudyId) ?? null;
  const popover = shown === null ? null : (
    <StudyPopover key={shown.entry.id} id={popoverId} study={shown} metrics={studies.metrics} storedFiles={storedTestSurfaces}
                  hasSurroundings={hasSurroundings} hasTerrain={hasTerrain} envelopeBuilt={envelopeBuilt} massingBuilt={massingBuilt} hasBaseVolume={hasBaseVolume}
                  carvingSpacing={carvingSpacing} disabledReason={editDisabledReason} onChange={(change) => attempt(() => studies.update(shown.entry.id, change))}
                  onUseFile={(fileName) => attempt(() => studies.useFile(shown.entry.id, fileName))}
                  onRemoveFile={(fileName) => attempt(async () => {
                    await studies.removeFile(shown.entry.id, fileName);
                    onStoredFilesChange();
                  })}
                  onDuplicate={() => attempt(async () => setPopoverStudyId((await studies.duplicate(shown.entry.id)).id))}
                  onDelete={() => attempt(async () => {
                    await studies.remove(shown.entry.id);
                    setPopoverStudyId(null);
                    view.current?.querySelector<HTMLButtonElement>(".study-add")?.focus();
                  })}
                  onClose={closePopover} />
  );
  const studyNames = Object.fromEntries(studies.studies.map((study) => [study.entry.id, study.entry.name]));

  const { legend, card } = studyView;
  return (
    <>
      <div ref={view} className="simulate-view" data-covers-view-left>
        <StudiesPanel studies={studies.studies} selectedId={studies.selectedId} criteria={criteria} metrics={studies.metrics}
                      runDisabledReason={runDisabledReason} editDisabledReason={editDisabledReason} popoverStudyId={shown === null ? null : popoverStudyId}
                      popoverId={popoverId} onSelect={studies.select} onAdd={add} onRun={() => void runs.startSimulation(project)}
                      onToggleSettings={(id) => {
                        if (popoverStudyId !== id) studies.select(id);       // the study whose settings are open is the one in the view
                        setPopoverStudyId(popoverStudyId === id ? null : id);
                      }} loadProblem={studies.loadProblem} popover={popover} notice={notice}
                      shownOnView={studyView.shownOnView} onShownOnViewChange={studyView.setShownOnView}
                      runFeedback={<RunProgress runs={runs} project={project} origin="simulate" mode="" onGoToSetting={() => {}} studyNames={studyNames} foldWarnings />} />
      </div>
      {studyView.waitingForRun && <p className="viewer-overlay study-view-note" role="status">{messages.studyShownWhenRunEnds}</p>}
      {legend !== null && (
        <TargetLegend label={legend.label} unit={legend.unit} mode={legend.mode} scale={legend.scale} low={legend.low} high={legend.high}
                      palette={legend.palette} disabled={legend.disabled} onRangeEndChange={studyView.setRangeEnd}
                      onColourByChange={studyView.setColourBy} />
      )}
      {card !== null && <ResultCard unit={card.unit} surroundings={card.surroundings} building={card.building} sunDayStep={card.sunDayStep} />}
    </>
  );
}

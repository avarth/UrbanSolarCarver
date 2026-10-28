// What Simulate puts over the 3D view: the studies panel (StudiesPanel) with the popover of a study's settings (StudyPopover) and
// Run; the geometry switch at the top centre, and for the selected study the target legend along the bottom and the result card in
// the bottom right corner (use_study_view.ts; the view draws its values, ProjectWorkspace gives them to ViewerPane). The studies are read when Simulate opens and again whenever a run ends while it is open: a simulation's results, or a run of
// Design that changed what the studies trace. The simulation is a run of the app's run loop (origin "simulate"), one job at a time
// with the runs of Design: Run waits while one of those goes on, and the studies cannot be changed while a run of the project does.
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { failureTextOf, serviceProblemOf, type CriterionEntry, type InputFileInfo, type StudySource } from "../api_client/client";
import { messages } from "../messages";
import type { ViewportTheme } from "../viewer/colour_scales";
import type { RunLoop } from "../steps/run_state";
import { inputProblemText } from "../steps/InputsStep";
import { RunProgress } from "../steps/RunProgress";
import { TargetLegend } from "../viewer_overlays/TargetLegend";
import { GeometrySwitch } from "./GeometrySwitch";
import { ResultCard } from "./ResultCard";
import { StudiesPanel } from "./StudiesPanel";
import { StudyPopover } from "./StudyPopover";
import type { StudiesHook } from "./use_studies";
import type { StudyViewHook } from "./use_study_view";
import "./simulate.css";

interface SimulateViewProps {
  project: string;
  studies: StudiesHook;
  /** The criteria, which Add study offers as shortcuts. */
  criteria: CriterionEntry[];
  /** The test surface files the project stores, with their triangle counts. */
  storedTestSurfaces: InputFileInfo[];
  runs: RunLoop;
  /** A study let a file go, which the project may then no longer store: the stored files are asked for again. */
  onStoredFilesChange: () => void;
  onServiceProblem: (error: unknown) => void;
  /** The selected study on the view: the geometry switch, the target legend and the result card. */
  studyView: StudyViewHook;
  /** The viewport theme (the legend's palettes do not depend on it). */
  theme?: ViewportTheme;
  /** The notice of input files changed in the project folder or missing from it, at the top of the studies panel. */
  notice?: ReactNode;
}

export function SimulateView({ project, studies, criteria, storedTestSurfaces, runs, onStoredFilesChange, onServiceProblem, studyView,
                               notice }: SimulateViewProps) {
  const [popoverStudyId, setPopoverStudyId] = useState<string | null>(null);
  const view = useRef<HTMLDivElement>(null);
  const popoverId = useId();
  const runEnded = runs.activeRun === null;
  const opened = useRef(false);
  useEffect(() => void studies.refresh(), []);
  useEffect(() => {
    if (opened.current && runEnded) void studies.refresh();
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
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return failureTextOf(error);
    }
  };
  /** Uploads the files one after another; resolves with a message per file that could not be added. The stored files are asked for
   *  again after one was added, since the reply lists names only (a file of a stored name may have replaced it for a criterion too). */
  const addFiles = async (id: string, files: File[]): Promise<string[]> => {
    const problems: string[] = [];
    let added = false;
    for (const file of files) {
      try {
        await studies.addFile(id, file);
        added = true;
      } catch (error) {
        if (serviceProblemOf(error) !== "other") {
          onServiceProblem(error);
          break;
        }
        problems.push(inputProblemText(error, file.name));
      }
    }
    if (added) onStoredFilesChange();
    return problems;
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
                  disabledReason={editDisabledReason} onChange={(change) => attempt(() => studies.update(shown.entry.id, change))}
                  onAddFiles={(files) => addFiles(shown.entry.id, files)}
                  onUseFile={(fileName) => attempt(() => studies.useFile(shown.entry.id, fileName))}
                  onRemoveFile={(fileName) => attempt(async () => {
                    await studies.removeFile(shown.entry.id, fileName);
                    onStoredFilesChange();
                  })}
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
      <div ref={view} className="simulate-view">
        <StudiesPanel studies={studies.studies} selectedId={studies.selectedId} criteria={criteria} metrics={studies.metrics}
                      runDisabledReason={runDisabledReason} editDisabledReason={editDisabledReason} popoverStudyId={shown === null ? null : popoverStudyId}
                      popoverId={popoverId} onSelect={studies.select} onAdd={add} onRun={() => void runs.startSimulation(project)}
                      onToggleSettings={(id) => {
                        if (popoverStudyId !== id) studies.select(id);       // the study whose settings are open is the one in the view
                        setPopoverStudyId(popoverStudyId === id ? null : id);
                      }} loadProblem={studies.loadProblem} popover={popover} notice={notice}
                      runFeedback={<RunProgress runs={runs} project={project} origin="simulate" mode="" onGoToSetting={() => {}} studyNames={studyNames} foldWarnings />} />
      </div>
      <div className={`simulate-geometry-bar${shown === null ? "" : " simulate-geometry-bar-beside-popover"}`}>
        <GeometrySwitch available={studyView.available} outOfDateInDesign={studyView.outOfDateInDesign} waitingForStudy={studyView.waitingForStudy}
                        value={studyView.geometry}
                        change={studyView.change} onChange={studyView.setGeometry} onChangeToggle={studyView.setChange} />
      </div>
      {studyView.waitingForRun && <p className="viewer-overlay study-view-note" role="status">{messages.studyShownWhenRunEnds}</p>}
      {legend !== null && (
        <TargetLegend label={legend.label} unit={legend.unit} mode={legend.mode} scale={legend.scale} low={legend.low} high={legend.high}
                      palette={legend.palette} hasLoss={legend.hasLoss} disabled={legend.disabled} onRangeEndChange={studyView.setRangeEnd}
                      onColourByChange={studyView.setColourBy} />
      )}
      {card !== null && <ResultCard geometry={card.geometry} unit={card.unit} statistics={card.statistics} baseline={card.baseline} />}
    </>
  );
}

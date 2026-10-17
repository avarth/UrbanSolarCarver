// The state of one run as its events arrive (UX 6.3): each stage waiting, running or done, the batch count of the ray tracing,
// the issues, and how the run ended. The engine reports progress 0 of 1 when a stage starts and 1 of 1 when it ends, and the
// batches of the ray tracing in between; a stage counts as done when a later stage starts or the run finishes, since the
// last batch of the ray tracing is not the end of its stage.
//
// useRunLoop runs one pipeline at a time, as the engine does: it starts a run, follows its events and keeps the last run's
// state, for any project, so a run goes on being followed while another project is open.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, cancelRun, refusalDetailOf, serviceProblemOf, startRun } from "../api_client/client";
import { subscribeToRunEvents, type RunEvent } from "../api_client/events";
import { messages } from "../messages";
import type { PipelineStage } from "./step_summaries";

export type StageRunState = "waiting" | "running" | "done";
export type RunEnding = "finished" | "failed" | "cancelled" | "connection_lost";

export interface StageProgress {
  state: StageRunState;
  done: number;
  total: number;
}

export interface RunIssue {
  /** The stage that raised it; null for an issue raised before any stage began (the config loading). */
  stage: string | null;
  code: string;
  message: string;
}

export interface RunFailure {
  error_type: string;
  message: string;
  field_errors: { field: string | null; message: string }[];
}

export interface RunState {
  /** The stages the run brings up to date, in pipeline order. */
  order: string[];
  stages: Record<string, StageProgress>;
  issues: RunIssue[];
  final: RunEnding | null;
  failure: RunFailure | null;
  /** The close code of a connection that ended before the run's last event. */
  lostConnectionCode: number | null;
  startedAt: number;
  endedAt: number | null;
}

const STAGE_DISPLAY_NAMES: Record<PipelineStage, string> = {
  preprocessing: "Sun analysis",
  thresholding: "Carving",
  exporting: "Envelope mesh",
  massing: "Building massing",
};

export function stageDisplayName(stage: string): string {
  return STAGE_DISPLAY_NAMES[stage as PipelineStage] ?? stage;
}

/** A run that has just started: its first stage running, the others waiting. */
export function initialRunState(stages: string[], startedAt = Date.now()): RunState {
  return {
    order: stages,
    stages: Object.fromEntries(stages.map((stage, index) => [stage, { state: index === 0 ? "running" : "waiting", done: 0, total: 0 }])),
    issues: [],
    final: null,
    failure: null,
    lostConnectionCode: null,
    startedAt,
    endedAt: null,
  };
}

function withEveryStageDone(stages: Record<string, StageProgress>): Record<string, StageProgress> {
  return Object.fromEntries(Object.entries(stages).map(([stage, progress]) => [stage, { ...progress, state: "done" }]));
}

export function runReducer(state: RunState, event: RunEvent, now = Date.now()): RunState {
  if (state.final !== null) return state;
  switch (event.type) {
    case "stage_progress": {
      const position = event.stage === null ? -1 : state.order.indexOf(event.stage);
      if (position < 0) return state;
      const stages = { ...state.stages };
      state.order.forEach((stage, index) => {
        if (index < position) stages[stage] = { ...stages[stage], state: "done" };
      });
      stages[event.stage!] = { state: "running", done: event.done, total: event.total };
      return { ...state, stages };
    }
    case "issue":
      return { ...state, issues: [...state.issues, { stage: event.stage, code: event.code, message: event.message }] };
    case "run_finished":
      return { ...state, stages: withEveryStageDone(state.stages), final: "finished", endedAt: now };
    case "run_failed":
      return { ...state, final: "failed", endedAt: now,
               failure: { error_type: event.error_type, message: event.message, field_errors: event.field_errors } };
    case "run_cancelled":
      return { ...state, final: "cancelled", endedAt: now };
    case "connection_lost":
      return { ...state, final: "connection_lost", lostConnectionCode: event.code, endedAt: now };
  }
}

/** The stages of the run that are done so far. */
export function stagesDone(state: RunState): string[] {
  return state.order.filter((stage) => state.stages[stage].state === "done");
}

/** How far the run is, 0 to 1, for the progress bar: the finished stages and the batch fraction of the running one. */
export function runProgressShare(state: RunState): number {
  if (state.order.length === 0) return 1;
  let share = 0;
  for (const stage of state.order) {
    const progress = state.stages[stage];
    if (progress.state === "done") share += 1;
    else if (progress.state === "running" && progress.total > 0) share += Math.min(1, progress.done / progress.total);
  }
  return share / state.order.length;
}

// The loop of runs -------------------------------------------------------------------------------------------------------

/** The button that started a run: its progress and outcome are shown under it (UX 6.3). */
export type RunOrigin = "settings_run_analysis" | "carving_run_analysis" | "carving_update" | "build" | "export_format";

export interface RunRecord {
  /** Counts the runs asked for in this page, so each one is followed once. */
  serial: number;
  project: string;
  origin: RunOrigin;
  runId: string | null;
  state: RunState;
  /** The service's reason when it refused to start the run (a run already active, inputs missing); null otherwise. */
  refusal: string | null;
  /**
   * Whether the user has left the value the run was started for (a threshold moved again while it ran): its results are then
   * neither fetched nor shown as current, since the run that follows brings the value the user is at. Absent: never.
   */
  isSuperseded?: () => boolean;
}

/** How a request to run ended: as the run ended, with nothing to run, or with no run started (refused, or a run active). */
export type RunOutcome = RunEnding | "up_to_date" | "not_started";

export interface RunLoop {
  /** The run in progress, or the last one, of any project. */
  current: RunRecord | null;
  /** The project and button of the run starting or in progress (the engine runs one at a time); null when none is. */
  activeRun: { project: string; origin: RunOrigin } | null;
  /**
   * A short message at a button, for three seconds: "Results are up to date" when the service had nothing to run, "A run is in
   * progress" when the button was pressed while a run was starting or under way.
   */
  notice: RunNotice | null;
  /** Brings *produce* up to date; resolves at the run's last event. *isSuperseded* goes into the run's record. */
  start: (project: string, produce: string[], origin: RunOrigin, isSuperseded?: () => boolean) => Promise<RunOutcome>;
  cancel: () => void;
  /**
   * Made before a request about *project* (its stage status), it tells when the reply comes whether the reply still holds: not
   * when it was asked for or answered while a run of the project was starting or under way, nor after one started since. A run
   * removes the records of its stages when it starts and writes them when it ends, so a status read across a run says
   * "missing" for results on screen.
   */
  replyStillHolds: (project: string) => () => boolean;
}

export interface RunNotice {
  project: string;
  origin: RunOrigin;
  message: string;
}

export const NOTICE_MILLISECONDS = 3000;
const WEBSOCKET_CLOSE_UNAUTHORIZED = 4401;

/** A refused start whose settings the service found invalid (ConfigError), as a failed run that names its fields. */
function refusedSettingsFailure(error: unknown): RunFailure | null {
  if (!(error instanceof ApiError) || error.status !== 422 || typeof error.body !== "object" || error.body === null) return null;
  const fieldErrors = (error.body as { field_errors?: RunFailure["field_errors"] }).field_errors;
  if (!Array.isArray(fieldErrors)) return null;
  return { error_type: "ConfigError", message: fieldErrors.map((fieldError) => fieldError.message).join(" "), field_errors: fieldErrors };
}

/** What a connection that ended before the run's last event says about the service, as a failed request would say it. */
function problemOfLostConnection(code: number): unknown {
  return code === WEBSOCKET_CLOSE_UNAUTHORIZED ? new ApiError(401, { detail: "The token was refused." }) : new TypeError("The engine closed the connection.");
}

export function useRunLoop(token: string, onServiceProblem: (error: unknown) => void): RunLoop {
  const [current, setCurrent] = useState<RunRecord | null>(null);
  const [activeRun, setActiveRun] = useState<RunLoop["activeRun"]>(null);
  const [notice, setNotice] = useState<RunNotice | null>(null);
  const latestRecord = useRef<RunRecord | null>(null);       // ahead of the render that shows it
  const busy = useRef(false);
  const busyProject = useRef<string | null>(null);
  const runsAskedFor = useRef(0);
  const runsAskedForByProject = useRef(new Map<string, number>());
  const stopEvents = useRef<(() => void) | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const reportProblem = useRef(onServiceProblem);
  reportProblem.current = onServiceProblem;

  useEffect(() => () => {
    stopEvents.current?.();
    clearTimeout(noticeTimer.current);
  }, []);

  const show = (record: RunRecord) => {
    latestRecord.current = record;
    setCurrent(record);
  };
  const release = () => {
    busy.current = false;
    busyProject.current = null;
    setActiveRun(null);
  };
  const showNotice = (project: string, origin: RunOrigin, message: string) => {
    clearTimeout(noticeTimer.current);
    setNotice({ project, origin, message });
    noticeTimer.current = setTimeout(() => setNotice(null), NOTICE_MILLISECONDS);
  };

  const start = useCallback(async (project: string, produce: string[], origin: RunOrigin, isSuperseded?: () => boolean): Promise<RunOutcome> => {
    if (busy.current) {
      showNotice(project, origin, messages.runInProgress);
      return "not_started";
    }
    busy.current = true;
    busyProject.current = project;
    setActiveRun({ project, origin });
    const serial = ++runsAskedFor.current;
    runsAskedForByProject.current.set(project, (runsAskedForByProject.current.get(project) ?? 0) + 1);
    let reply;
    try {
      reply = await startRun(token, project, produce);
    } catch (error) {
      release();
      if (serviceProblemOf(error) !== "other") {
        reportProblem.current(error);
        return "not_started";
      }
      const settingsFailure = refusedSettingsFailure(error);
      if (settingsFailure !== null) {
        show({ serial, project, origin, runId: null, refusal: null, isSuperseded,
               state: { ...initialRunState([]), final: "failed", failure: settingsFailure, endedAt: Date.now() } });
      } else {
        show({ serial, project, origin, runId: null, state: initialRunState([]), refusal: refusalDetailOf(error) ?? String(error), isSuperseded });
      }
      return "not_started";
    }
    if (reply.status === "up_to_date" || reply.run_id === null) {
      release();
      showNotice(project, origin, messages.resultsUpToDate);
      return "up_to_date";
    }
    const runId = reply.run_id;
    show({ serial, project, origin, runId, state: initialRunState(reply.stages), refusal: null, isSuperseded });
    return new Promise<RunOutcome>((resolve) => {
      stopEvents.current = subscribeToRunEvents(runId, token, (event) => {
        const record = latestRecord.current!;
        const state = runReducer(record.state, event);
        if (state === record.state) return;
        show({ ...record, state });
        if (state.final === null) return;
        stopEvents.current?.();
        stopEvents.current = null;
        release();
        if (event.type === "connection_lost") reportProblem.current(problemOfLostConnection(event.code));
        resolve(state.final);
      });
    });
  }, [token]);

  const cancel = useCallback(() => {
    const record = latestRecord.current;
    if (record?.runId == null || record.state.final !== null) return;
    cancelRun(token, record.runId).catch((error) => { if (serviceProblemOf(error) !== "other") reportProblem.current(error); });
  }, [token]);

  const replyStillHolds = useCallback((project: string) => {
    const runsBefore = runsAskedForByProject.current.get(project) ?? 0;
    const askedDuringARun = busyProject.current === project;
    return () => !askedDuringARun && busyProject.current !== project && (runsAskedForByProject.current.get(project) ?? 0) === runsBefore;
  }, []);

  return { current, activeRun, notice, start, cancel, replyStillHolds };
}

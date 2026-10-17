// The page (UX 4, 5.1, 6.1, 11): the top bar with the device status, then the start screen or the open project. The device
// status is polled every second while the GPU warms up. A request that finds no engine is checked against GET health a few
// times before the page says the engine stopped, so one lost request does not end the session. The runs are followed here, one
// at a time as the engine runs them, so a run goes on being followed while the start screen or another project is open.
import { useEffect, useRef, useState } from "react";
import {
  createProject, createProjectFromExample, getExamples, getHealth, getModes, getProject, getSchema, listProjects, readTokenFromLaunchUrl,
  refusalDetailOf, serviceProblemOf, type ExampleInfo, type HealthReply, type ModeInfo, type ProjectDetail, type ProjectSummary,
} from "./api_client/client";
import { messages, type MessagePart } from "./messages";
import { MessageParts } from "./settings_form/SettingTooltip";
import { ProjectWorkspace } from "./steps/ProjectWorkspace";
import { useRunLoop } from "./steps/run_state";
import { isWarmingUp, Spinner, StartScreen } from "./steps/StartScreen";
import "./App.css";

const accessToken = readTokenFromLaunchUrl();
const HEALTH_POLL_MILLISECONDS = 1000;
const FAILED_POLLS_BEFORE_ENGINE_STOPPED = 3;
const PROJECT_NAME_MAXIMUM_LENGTH = 64;
const NEW_PROJECT_MODE = "time-based";      // Sun at set hours (UX 3, 5.1)

type ServiceProblem = "access_lost" | "engine_stopped";

interface HealthPolling {
  ask: () => Promise<HealthReply>;
  onReply: (reply: HealthReply) => void;
  /** Called once when polling ends on a problem: at once for a lost token, after the last failed attempt for a stopped engine. */
  onProblem: (problem: ServiceProblem) => void;
  /** Whether to ask again after a reply. */
  askAgainAfter: (reply: HealthReply) => boolean;
  intervalMilliseconds?: number;
  failuresBeforeStopped?: number;
}

/** Asks for the health until *askAgainAfter* says stop, retrying failed requests; returns the function that stops it. */
export function pollHealth({ ask, onReply, onProblem, askAgainAfter, intervalMilliseconds = HEALTH_POLL_MILLISECONDS,
                             failuresBeforeStopped = FAILED_POLLS_BEFORE_ENGINE_STOPPED }: HealthPolling): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;          // a reply that arrives after the stop must start no new round
  let failures = 0;
  const askOnce = async () => {
    try {
      const reply = await ask();
      if (stopped) return;
      failures = 0;
      onReply(reply);
      if (askAgainAfter(reply)) timer = setTimeout(askOnce, intervalMilliseconds);
    } catch (error) {
      if (stopped) return;
      const kind = serviceProblemOf(error);
      if (kind === "access_lost") return onProblem(kind);
      failures += 1;
      if (failures < failuresBeforeStopped) timer = setTimeout(askOnce, intervalMilliseconds);
      else if (kind === "engine_stopped") onProblem(kind);
      // another refusal (a 500) repeated: polling ends, and the device status keeps its last state
    }
  };
  void askOnce();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

/** The title of an example as a project name, numbered when a project of that name exists ("Perimeter block 2"). */
export function freeProjectName(title: string, existingNames: string[]): string {
  const taken = new Set(existingNames.map((name) => name.toLowerCase()));
  const base = title.slice(0, PROJECT_NAME_MAXIMUM_LENGTH);
  if (!taken.has(base.toLowerCase())) return base;
  for (let number = 2; ; number++) {
    const suffix = ` ${number}`;
    const candidate = `${base.slice(0, PROJECT_NAME_MAXIMUM_LENGTH - suffix.length)}${suffix}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
}

function MessageText({ parts }: { parts: MessagePart[] }) {
  return <p><MessageParts parts={parts} /></p>;
}

function DeviceStatus({ warmUp }: { warmUp: HealthReply["warm_up"] }) {
  const [reasonOpen, setReasonOpen] = useState(false);
  if (isWarmingUp(warmUp)) return <span className="device-status"><Spinner />{messages.gpuPreparing}</span>;
  if (warmUp.state === "ready") return <span className="device-status"><span className="device-dot device-dot-ready" />{messages.gpuReady}</span>;
  if (warmUp.state === "cpu") {
    return <span className="device-status" title={messages.noCudaGpuFound}><span className="device-dot" />{messages.cpuMode}</span>;
  }
  return (
    <span className="device-status device-status-problem">
      <span className="device-dot device-dot-error" />
      <button type="button" className="link-button" aria-expanded={reasonOpen} onClick={() => setReasonOpen(!reasonOpen)}>{messages.gpuNotAvailable}</button>
      {reasonOpen && <span className="device-reason" role="status">{warmUp.problem ?? messages.gpuNotAvailable}</span>}
    </span>
  );
}

export function App() {
  const [health, setHealth] = useState<HealthReply | null>(null);
  const [problem, setProblem] = useState<ServiceProblem | null>(null);
  const [setup, setSetup] = useState<{ schema: Record<string, unknown>; modes: ModeInfo[] } | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [examples, setExamples] = useState<ExampleInfo[] | null>(null);
  const [openProject, setOpenProject] = useState<ProjectDetail | null>(null);
  const engineCheck = useRef<(() => void) | null>(null);
  const runs = useRunLoop(accessToken, (error) => handleServiceProblem(error));

  /** A failed request: a lost token is said at once; a missing engine only once GET health finds none either. */
  const handleServiceProblem = (error: unknown) => {
    const kind = serviceProblemOf(error);
    if (kind === "access_lost") setProblem(kind);
    if (kind !== "engine_stopped" || engineCheck.current !== null) return;
    engineCheck.current = pollHealth({
      ask: () => getHealth(accessToken),
      onReply: (reply) => {
        engineCheck.current = null;      // the engine answered: the next failed request is checked again
        setHealth(reply);
      },
      onProblem: setProblem,
      askAgainAfter: () => false,
    });
  };

  useEffect(() => {
    const stopPolling = pollHealth({
      ask: () => getHealth(accessToken), onReply: setHealth, onProblem: setProblem, askAgainAfter: (reply) => isWarmingUp(reply.warm_up),
    });
    Promise.all([getSchema(accessToken), getModes(accessToken)]).then(([schema, modes]) => setSetup({ schema, modes })).catch(handleServiceProblem);
    getExamples(accessToken).then(setExamples).catch(handleServiceProblem);
    return () => {
      stopPolling();
      engineCheck.current?.();
    };
  }, []);

  useEffect(() => {
    if (openProject === null) listProjects(accessToken).then(setProjects).catch(handleServiceProblem);
  }, [openProject === null]);

  /** Opens the project the request gives; resolves with the reason it failed, or null. */
  const openFrom = async (request: Promise<ProjectDetail>): Promise<string | null> => {
    try {
      setOpenProject(await request);
      return null;
    } catch (error) {
      handleServiceProblem(error);
      return refusalDetailOf(error);
    }
  };

  if (problem !== null) {
    return <div className="service-problem-overlay" role="alert"><MessageText parts={problem === "access_lost" ? messages.accessLost : messages.engineStopped} /></div>;
  }
  return (
    <div className="app">
      <header className="top-bar">
        <span className="top-bar-product">{messages.productName}</span>
        {openProject && (
          <>
            <span className="top-bar-project">{openProject.name}</span>
            <button type="button" className="link-button" onClick={() => setOpenProject(null)}>{messages.projectsLink}</button>
          </>
        )}
        <span className="top-bar-device">{health && <DeviceStatus warmUp={health.warm_up} />}</span>
      </header>
      {openProject === null && (
        <StartScreen health={health} projects={projects} examples={examples}
                     onCreateProject={(name) => openFrom(createProject(accessToken, name, NEW_PROJECT_MODE))}
                     onOpenProject={(name) => openFrom(getProject(accessToken, name))}
                     onTryExample={(example) => openFrom(createProjectFromExample(accessToken,
                       freeProjectName(example.title, (projects ?? []).map((project) => project.name)), example.name))} />
      )}
      {openProject !== null && setup !== null && (
        <ProjectWorkspace key={openProject.name} token={accessToken} project={openProject} schema={setup.schema} modes={setup.modes}
                          warmUpState={health?.warm_up.state ?? null} runs={runs} onServiceProblem={handleServiceProblem}
                          onShowProjects={() => setOpenProject(null)} />
      )}
    </div>
  );
}

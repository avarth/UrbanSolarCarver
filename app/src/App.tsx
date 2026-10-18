// The page (UX 4, 5.1, 6.1, 11, R2 7): the top bar with the device status, then the start screen or the open project. The device
// status is polled every second while the GPU warms up. A request that finds no engine is checked against GET health a few
// times before the page says the engine stopped, so one lost request does not end the session. The runs are followed here, one
// at a time as the engine runs them, so a run goes on being followed while the start screen or another project is open. The
// projects folder and the project menus (on the start screen and on the project name in the top bar) send their requests here:
// a rename keeps the open project open under its new name, a delete of it returns to the start screen, a reset opens it afresh.
import { useEffect, useRef, useState } from "react";
import {
  chooseProjectsFolder, createProject, createProjectFromExample, deleteProject, getExamples, getHealth, getModes, getProject, getProjectsFolder,
  getSchema, listProjects, openProjectFolder, readTokenFromLaunchUrl, refusalDetailOf, renameProject, resetProjectToExample, serviceProblemOf,
  type ExampleInfo, type HealthReply, type ModeInfo, type ProjectDetail, type ProjectsFolderReply, type ProjectSummary,
} from "./api_client/client";
import { messages, type MessagePart } from "./messages";
import { MessageParts } from "./settings_form/SettingTooltip";
import { projectFolderPath, sameProjectName } from "./steps/ProjectDialogs";
import { ProjectMenu, type ProjectActions } from "./steps/ProjectMenu";
import { moveAutoUpdateChoice } from "./steps/CarvingStep";
import { ProjectWorkspace, type OpenProjectSettingsSaver } from "./steps/ProjectWorkspace";
import { useRunLoop } from "./steps/run_state";
import { cpuChosenAtLaunch, exampleTitleOf, isWarmingUp, Spinner, StartScreen, type ProjectsFolderChange } from "./steps/StartScreen";
import "./App.css";

const accessToken = readTokenFromLaunchUrl();
const HEALTH_POLL_MILLISECONDS = 1000;
const FAILED_POLLS_BEFORE_ENGINE_STOPPED = 3;
const PROJECT_NAME_MAXIMUM_LENGTH = 64;
const NEW_PROJECT_MODE = "time-based";      // Solar time-based (UX 3, 5.1)

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

export function DeviceStatus({ warmUp }: { warmUp: HealthReply["warm_up"] }) {
  const [reasonOpen, setReasonOpen] = useState(false);
  if (isWarmingUp(warmUp)) return <span className="device-status"><Spinner />{messages.gpuPreparing}</span>;
  if (warmUp.state === "ready") return <span className="device-status"><span className="device-dot device-dot-ready" />{messages.gpuReady}</span>;
  if (cpuChosenAtLaunch(warmUp)) return <span className="device-status"><span className="device-dot" />{messages.cpuModeChosenAtLaunch}</span>;
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
  // Whether the examples were read since the start screen last showed: the project made from each changes while a project is
  // open (made, renamed or deleted), so the start screen lists them only once read again. Their titles stay valid for the top bar.
  const [examplesCurrent, setExamplesCurrent] = useState(false);
  const [openProject, setOpenProject] = useState<ProjectDetail | null>(null);
  const [projectsFolder, setProjectsFolder] = useState<ProjectsFolderReply | null>(null);
  // Counts the resets of the open project: the workspace is made again for the fresh copy, which keeps the project's name.
  const [openProjectResets, setOpenProjectResets] = useState(0);
  // The open project was deleted from the top bar: the start screen then takes the focus on its heading.
  const [focusStartScreenHeading, setFocusStartScreenHeading] = useState(false);
  const openProjectSettings = useRef<OpenProjectSettingsSaver | null>(null);
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
    return () => {
      stopPolling();
      engineCheck.current?.();
    };
  }, []);

  /** The projects and the examples, whose project (the one made from each) changes with every project made, renamed or deleted. */
  const readStartScreenLists = () => {
    listProjects(accessToken).then(setProjects).catch(handleServiceProblem);
    getExamples(accessToken).then((read) => {
      setExamples(read);
      setExamplesCurrent(true);
    }).catch(handleServiceProblem);
  };
  const readProjectsFolder = () => getProjectsFolder(accessToken).then(setProjectsFolder).catch(handleServiceProblem);

  useEffect(() => {
    if (openProject === null) readStartScreenLists();
    else setExamplesCurrent(false);
  }, [openProject === null]);

  // Whether the folder may change depends on a run being active, so it is asked again when a run starts or ends.
  useEffect(() => {
    if (openProject === null) void readProjectsFolder();
  }, [openProject === null, runs.activeRun === null]);

  /** Opens the project the request gives; resolves with the reason it failed, or null. */
  const openFrom = async (request: Promise<ProjectDetail>): Promise<string | null> => {
    try {
      setOpenProject(await request);
      setFocusStartScreenHeading(false);
      return null;
    } catch (error) {
      handleServiceProblem(error);
      return refusalDetailOf(error);
    }
  };

  /** A failed request in words: the service's reason, or that it did not reach the engine. */
  const failureText = (error: unknown): string => {
    handleServiceProblem(error);
    return refusalDetailOf(error) ?? (serviceProblemOf(error) === "engine_stopped" ? messages.requestDidNotReachEngine : String(error));
  };

  /** Resolves with the service's reason when the request fails, or null once it and *then* are done. */
  const reasonIfRefused = async <Reply,>(request: () => Promise<Reply>, then: (reply: Reply) => void): Promise<string | null> => {
    try {
      then(await request());
      return null;
    } catch (error) {
      return failureText(error);
    }
  };
  const isOpenProject = (name: string) => openProject !== null && sameProjectName(openProject.name, name);

  /**
   * After a rename, reset or delete: the open project's settings saver sends nothing more when its workspace closes (a save
   * to the old name, or of the old values over the fresh copy), and the run record and the auto-update choice follow the change.
   */
  const afterProjectChange = (name: string, newName: string | null, keepsAutoUpdate: boolean) => {
    if (isOpenProject(name)) openProjectSettings.current?.cancel();
    runs.forget(name);
    moveAutoUpdateChoice(name, keepsAutoUpdate ? newName : null);
  };

  const projectActions: ProjectActions = {
    openFolder: (name) => reasonIfRefused(() => openProjectFolder(accessToken, name), () => {}),
    rename: async (name, newName) => {
      // The settings are saved under the old name first; a save that fails keeps the project as it is.
      if (isOpenProject(name) && (await openProjectSettings.current?.flush()) === "failed") return messages.settingsNotSavedSoNotRenamed;
      return reasonIfRefused(() => renameProject(accessToken, name, newName), (renamed) => {
        afterProjectChange(name, renamed.name, true);
        if (isOpenProject(name)) setOpenProject(renamed);
        else readStartScreenLists();
      });
    },
    delete: async (name, confirmName) => {
      if (isOpenProject(name)) await openProjectSettings.current?.flush();     // discarded with the project, failed or not
      return reasonIfRefused(() => deleteProject(accessToken, name, confirmName), () => {
        afterProjectChange(name, null, false);
        if (!isOpenProject(name)) return readStartScreenLists();
        setFocusStartScreenHeading(true);
        setOpenProject(null);     // the start screen then reads its lists
      });
    },
    resetToExample: async (name) => {
      if (isOpenProject(name)) await openProjectSettings.current?.flush();     // replaced by the example's, failed or not
      return reasonIfRefused(() => resetProjectToExample(accessToken, name), (reset) => {
        afterProjectChange(name, null, false);
        if (!isOpenProject(name)) return readStartScreenLists();
        setOpenProject(reset);
        setOpenProjectResets((resets) => resets + 1);
      });
    },
  };

  const changeProjectsFolder = async (): Promise<ProjectsFolderChange> => {
    try {
      const choice = await chooseProjectsFolder(accessToken);
      if (choice.status === "changed") {
        // The start screen waits while the picker is open; should a project be open all the same, it belongs to the old folder.
        openProjectSettings.current?.cancel();
        setOpenProject(null);
        readStartScreenLists();
      }
      return choice.status === "unavailable" ? { status: "unavailable", problem: choice.problem ?? "" } : { status: choice.status };
    } catch (error) {
      return { status: "refused", reason: failureText(error) };
    } finally {
      void readProjectsFolder();      // the folder in use, and whether it may change (a run elsewhere may have started)
    }
  };

  const runActiveFor = (name: string) => runs.activeRun !== null && sameProjectName(runs.activeRun.project, name);

  if (problem !== null) {
    return <div className="service-problem-overlay" role="alert"><MessageText parts={problem === "access_lost" ? messages.accessLost : messages.engineStopped} /></div>;
  }
  return (
    <div className="app">
      <header className="top-bar">
        <span className="top-bar-product">{messages.productName}</span>
        {openProject && (
          <>
            <ProjectMenu projectName={openProject.name} exampleTitle={exampleTitleOf(openProject.example, examples)}
                         projectFolderPath={projectsFolder && projectFolderPath(projectsFolder.path, openProject.name)}
                         runActive={runActiveFor(openProject.name)} actions={projectActions} placement="top_bar" />
            <button type="button" className="link-button" onClick={() => setOpenProject(null)}>{messages.projectsLink}</button>
          </>
        )}
        <span className="top-bar-device">{health && <DeviceStatus warmUp={health.warm_up} />}</span>
      </header>
      {openProject === null && (
        <StartScreen health={health} projects={projects} examples={examplesCurrent ? examples : null} projectsFolder={projectsFolder}
                     activeRunProject={runs.activeRun?.project ?? null} projectActions={projectActions} headingTakesFocus={focusStartScreenHeading}
                     onCreateProject={(name) => openFrom(createProject(accessToken, name, NEW_PROJECT_MODE))}
                     onOpenProject={(name) => openFrom(getProject(accessToken, name))}
                     onTryExample={(example) => openFrom(example.project
                       ? getProject(accessToken, example.project)       // made from this example before (R2 7.4)
                       : createProjectFromExample(accessToken, freeProjectName(example.title, (projects ?? []).map((project) => project.name)), example.name))}
                     onChangeProjectsFolder={changeProjectsFolder} />
      )}
      {openProject !== null && setup !== null && (
        <ProjectWorkspace key={`${openProject.name}/${openProjectResets}`} token={accessToken} project={openProject} schema={setup.schema} modes={setup.modes}
                          warmUpState={health?.warm_up.state ?? null} runs={runs} onServiceProblem={handleServiceProblem}
                          onShowProjects={() => setOpenProject(null)} onSettingsSaverReady={(saver) => { openProjectSettings.current = saver; }} />
      )}
    </div>
  );
}

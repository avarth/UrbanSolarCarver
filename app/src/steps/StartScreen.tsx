// The start screen (UX 5.1, R2 7.1, 7.2): the version, the device and its warm-up, and three cards side by side: a new project,
// the projects there are (newest first) under the projects folder and its Change folder, each with its menu, and the bundled
// examples. Choosing one opens the project at its Inputs step.
import { useId, useState, type FormEvent, type ReactNode } from "react";
import type { ExampleInfo, HealthReply, ProjectsFolderReply, ProjectSummary } from "../api_client/client";
import { dateAndTime, messages } from "../messages";
import { MessageParts } from "../settings_form/SettingTooltip";
import { projectFolderPath, sameProjectName } from "./ProjectDialogs";
import { ProjectMenu, type ProjectActions } from "./ProjectMenu";
import "./steps.css";

/** How Change folder ended: the service's answer, or its refusal (409: a run is active, or the picker is open already). */
export type ProjectsFolderChange =
  | { status: "changed" | "cancelled" }
  | { status: "unavailable"; problem: string }
  | { status: "refused"; reason: string };

interface StartScreenProps {
  health: HealthReply | null;
  projects: ProjectSummary[] | null;
  examples: ExampleInfo[] | null;
  projectsFolder: ProjectsFolderReply | null;
  /** The project of the run starting or under way, or null: its menu waits. */
  activeRunProject: string | null;
  projectActions: ProjectActions;
  /** Each resolves with the reason the project could not be made or opened, or null once it is open. */
  onCreateProject: (name: string) => Promise<string | null>;
  onOpenProject: (name: string) => Promise<string | null>;
  onTryExample: (example: ExampleInfo) => Promise<string | null>;
  /** Shows the folder picker on this computer; resolves once it is closed. */
  onChangeProjectsFolder: () => Promise<ProjectsFolderChange>;
}

/** The title of the example a project came from, for its Reset to the example; null for a project not made from one. */
export function exampleTitleOf(example: string | null | undefined, examples: ExampleInfo[] | null): string | null {
  if (example === null || example === undefined) return null;
  return examples?.find((candidate) => candidate.name === example)?.title ?? example;
}

export function isWarmingUp(warmUp: HealthReply["warm_up"] | undefined): boolean {
  return warmUp === undefined || warmUp.state === "not_started" || warmUp.state === "running";
}

/**
 * The CPU was chosen when USC started (usc ui --device cpu) on a computer that has a CUDA device. A CPU state without
 * cuda_available true means no CUDA device was found.
 */
export function cpuChosenAtLaunch(warmUp: HealthReply["warm_up"]): boolean {
  return warmUp.state === "cpu" && warmUp.cuda_available === true;
}

/** The device line once the warm-up has ended: the GPU's name, the CPU and why, or why Warp cannot run (with the engine's repair). */
function deviceLine(warmUp: HealthReply["warm_up"]): string {
  switch (warmUp.state) {
    case "ready":
      return warmUp.device_name ? messages.gpuReadyWithDevice(warmUp.device_name) : messages.gpuReady;
    case "cpu":
      return cpuChosenAtLaunch(warmUp) ? messages.cpuModeChosenAtLaunch : messages.noCudaGpuFound;
    default:
      return warmUp.problem ?? messages.gpuNotAvailable;
  }
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

/** Projects newest first by their last change. */
export function newestFirst(projects: ProjectSummary[]): ProjectSummary[] {
  return [...projects].sort((first, second) => Date.parse(second.modified) - Date.parse(first.modified));
}

function NewProjectCard({ onCreateProject }: Pick<StartScreenProps, "onCreateProject">) {
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fieldId = useId();
  const hintId = useId();
  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    const reason = await onCreateProject(name.trim());
    setBusy(false);
    setProblem(reason);
  };
  return (
    <section className="start-card">
      <h2>{messages.newProject}</h2>
      <form className="start-new-project" onSubmit={create}>
        <label htmlFor={fieldId}>{messages.projectNameLabel}</label>
        <input id={fieldId} className="setting-number start-name-field" value={name} maxLength={64} aria-describedby={hintId}
               aria-invalid={problem !== null || undefined} onChange={(event) => { setName(event.target.value); setProblem(null); }} />
        <p id={hintId} className="start-hint">{messages.projectNameHint}</p>
        {problem !== null && <p className="setting-error" role="alert">{problem}</p>}
        <button type="submit" className="primary-button" disabled={!name.trim() || busy}>{messages.createProject}</button>
      </form>
    </section>
  );
}

function ChoiceListCard<Item>({ title, items, emptyText, keyOf, onChoose, render, menuOf, children }: {
  title: string;
  items: Item[] | null;
  emptyText: string;
  keyOf: (item: Item) => string;
  onChoose: (item: Item) => Promise<string | null>;
  render: (item: Item) => { name: string; detail: string };
  /** The menu beside an item, for items that have one. */
  menuOf?: (item: Item) => ReactNode;
  /** Shown under the title. */
  children?: ReactNode;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const choose = async (item: Item) => {
    if (busy) return;
    setBusy(true);
    setProblem(await onChoose(item));
    setBusy(false);
  };
  return (
    <section className="start-card">
      <h2>{title}</h2>
      {children}
      {items !== null && items.length === 0 && <p className="start-hint">{emptyText}</p>}
      {items !== null && items.length > 0 && (
        <ul className="start-choice-list">
          {items.map((item) => {
            const { name, detail } = render(item);
            return (
              <li key={keyOf(item)} className="start-choice-row">
                <button type="button" className="start-choice" disabled={busy} onClick={() => void choose(item)}>
                  <span className="start-choice-name">{name}</span>
                  <span className="start-choice-detail">{detail}</span>
                </button>
                {menuOf?.(item)}
              </li>
            );
          })}
        </ul>
      )}
      {problem !== null && <p className="setting-error" role="alert">{problem}</p>}
    </section>
  );
}

/** The projects folder, with Change folder while the service allows it, else why not; and how the last change ended. */
function ProjectsFolderLine({ projectsFolder, onChangeProjectsFolder }: Pick<StartScreenProps, "onChangeProjectsFolder"> & {
  projectsFolder: ProjectsFolderReply;
}) {
  const [choosing, setChoosing] = useState(false);
  const [change, setChange] = useState<ProjectsFolderChange | null>(null);
  const chooseFolder = async () => {
    if (choosing) return;
    setChoosing(true);
    setChange(null);
    setChange(await onChangeProjectsFolder());
    setChoosing(false);
  };
  return (
    <div className="start-projects-folder">
      <p className="start-hint">{messages.projectsFolderIs}<span className="start-projects-folder-path">{projectsFolder.path}</span></p>
      {projectsFolder.can_change
        ? <button type="button" className="link-button" disabled={choosing} onClick={() => void chooseFolder()}>{messages.changeFolder}</button>
        : (
          <p className="start-hint">
            {projectsFolder.source === "command_line" ? <MessageParts parts={messages.folderGivenOnCommandLine} /> : messages.folderChangesOnceRunEnds}
          </p>
        )}
      {choosing && <p className="start-hint" role="status">{messages.folderPickerOpen}</p>}
      {change?.status === "unavailable" && (
        <p className="setting-error" role="alert">{change.problem}<MessageParts parts={messages.folderPickerUnavailableWay} /></p>
      )}
      {change?.status === "refused" && <p className="setting-error" role="alert">{change.reason}</p>}
    </div>
  );
}

export function StartScreen({ health, projects, examples, projectsFolder, activeRunProject, projectActions, onCreateProject, onOpenProject,
                              onTryExample, onChangeProjectsFolder }: StartScreenProps) {
  const warmingUp = isWarmingUp(health?.warm_up);
  return (
    <main className="start-screen">
      <header className="start-heading">
        <h1>{messages.productName}</h1>
        {health && <p className="start-version">{messages.versionLine(health.version)}</p>}
      </header>
      {health && warmingUp && (
        <section className="start-device-card" aria-live="polite">
          <p className="start-device-status"><Spinner />{messages.gpuPreparing}</p>
          <p className="start-hint">{messages.gpuWarmUpHint}</p>
        </section>
      )}
      {health && !warmingUp && <p className="start-device-line" aria-live="polite">{deviceLine(health.warm_up)}</p>}
      <div className="start-cards">
        <NewProjectCard onCreateProject={onCreateProject} />
        <ChoiceListCard title={messages.openProject} items={projects === null ? null : newestFirst(projects)} emptyText={messages.noProjectsYet}
                        keyOf={(project) => project.name} onChoose={(project) => onOpenProject(project.name)}
                        render={(project) => ({ name: project.name, detail: dateAndTime(new Date(project.modified)) })}
                        menuOf={(project) => (
                          <ProjectMenu projectName={project.name} exampleTitle={exampleTitleOf(project.example, examples)}
                                       projectFolderPath={projectsFolder && projectFolderPath(projectsFolder.path, project.name)}
                                       runActive={activeRunProject !== null && sameProjectName(activeRunProject, project.name)}
                                       actions={projectActions} placement="project_row" />
                        )}>
          {projectsFolder !== null && <ProjectsFolderLine projectsFolder={projectsFolder} onChangeProjectsFolder={onChangeProjectsFolder} />}
        </ChoiceListCard>
        <ChoiceListCard title={messages.tryExample} items={examples} emptyText="" keyOf={(example) => example.name} onChoose={onTryExample}
                        render={(example) => ({ name: example.title, detail: example.description })} />
      </div>
    </main>
  );
}

// The start screen (UX 5.1): the version, the device and its warm-up, and three cards side by side: a new project, the
// projects there are (newest first), and the bundled examples. Choosing one opens the project at its Inputs step.
import { useId, useState, type FormEvent } from "react";
import type { ExampleInfo, HealthReply, ProjectSummary } from "../api_client/client";
import { dateAndTime, messages } from "../messages";
import "./steps.css";

interface StartScreenProps {
  health: HealthReply | null;
  projects: ProjectSummary[] | null;
  examples: ExampleInfo[] | null;
  /** Each resolves with the reason the project could not be made or opened, or null once it is open. */
  onCreateProject: (name: string) => Promise<string | null>;
  onOpenProject: (name: string) => Promise<string | null>;
  onTryExample: (example: ExampleInfo) => Promise<string | null>;
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

function ChoiceListCard<Item>({ title, items, emptyText, keyOf, onChoose, render }: {
  title: string;
  items: Item[] | null;
  emptyText: string;
  keyOf: (item: Item) => string;
  onChoose: (item: Item) => Promise<string | null>;
  render: (item: Item) => { name: string; detail: string };
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
      {items !== null && items.length === 0 && <p className="start-hint">{emptyText}</p>}
      {items !== null && items.length > 0 && (
        <ul className="start-choice-list">
          {items.map((item) => {
            const { name, detail } = render(item);
            return (
              <li key={keyOf(item)}>
                <button type="button" className="start-choice" disabled={busy} onClick={() => void choose(item)}>
                  <span className="start-choice-name">{name}</span>
                  <span className="start-choice-detail">{detail}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {problem !== null && <p className="setting-error" role="alert">{problem}</p>}
    </section>
  );
}

export function StartScreen({ health, projects, examples, onCreateProject, onOpenProject, onTryExample }: StartScreenProps) {
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
                        render={(project) => ({ name: project.name, detail: dateAndTime(new Date(project.modified)) })} />
        <ChoiceListCard title={messages.tryExample} items={examples} emptyText="" keyOf={(example) => example.name} onChoose={onTryExample}
                        render={(example) => ({ name: example.title, detail: example.description })} />
      </div>
    </main>
  );
}

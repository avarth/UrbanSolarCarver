// The settings of one study, in a popover beside the studies panel (simulate design, section 4): its name (a change renames it),
// its metric (a select; the metrics whose inputs are missing are greyed with the reason), the analysis period when the metric has
// one (the period control of the Criteria step), the metric's few mode settings in a fold, its study surfaces (its files: the files
// the project stores, to use or take out, and new files to add by the button or by dropping them; then check boxes for the project's
// surfaces it samples too: the surroundings, and the terrain or, without one, the ground around the site) and Delete. Each change is saved at once: a text or number
// field when it is left or Enter is pressed, the other controls on the change. The popover is a non-modal dialog: the view
// around it stays usable; Escape and Close end it, and the focus goes back to the study's settings button.
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { InputFileInfo, MetricInfo, StudyChange, StudyWithState } from "../api_client/client";
import { ProtectsBox } from "../criteria/ProtectsBox";
import { messages } from "../messages";
import { ANALYSIS_PERIOD_FIELDS, BALANCE_TEMPERATURE_FIELDS, SETTING_PRESENTATIONS } from "../settings_form/presentation";
import { AnalysisPeriod, type AnalysisPeriodField } from "../settings_form/widgets/AnalysisPeriod";
import { BalanceTemperatureSlider } from "../settings_form/widgets/BalanceTemperatureSlider";
import { useDialogRequest } from "../steps/ProjectDialogs";

interface StudyPopoverProps {
  id: string;
  study: StudyWithState;
  metrics: MetricInfo[];
  /** The test surface files the project stores (every criterion's and study's), with their triangle counts. */
  storedFiles: InputFileInfo[];
  /** The project has surroundings files: the study can sample them. */
  hasSurroundings: boolean;
  /** The project has a terrain file: the study can sample it, and the ground around the site is not offered. */
  hasTerrain: boolean;
  /** Why the study cannot be changed now (a run of the project); null when it can. */
  disabledReason: string | null;
  /** Saves a change of the study; resolves with the reason it was refused, or null. */
  onChange: (change: StudyChange) => Promise<string | null>;
  /** Uploads the files to the study; resolves with a message per file that could not be added (empty when all were). */
  onAddFiles: (files: File[]) => Promise<string[]>;
  onUseFile: (fileName: string) => Promise<string | null>;
  onRemoveFile: (fileName: string) => Promise<string | null>;
  onDelete: () => Promise<string | null>;
  onClose: () => void;
}

// The settings drawn as their own control, apart from the fold: the period. The time basis is read only by sun hours (the engine
// refuses another clock than standard time for the other metrics), so the fold shows it for sun hours alone.
const PERIOD_KEYS: readonly string[] = ANALYSIS_PERIOD_FIELDS;
const TIME_BASIS = "time_basis";
const METRICS_WITH_A_CLOCK = ["sun_hours"];
// The setting of the surfaces the study samples besides its files, drawn as check boxes under them.
const SURFACES_FROM = "surfaces_from";
const SOURCE_ORDER = ["context", "terrain", "ground"];

/** The project's surfaces the study samples besides its files, from its settings. */
export function surfacesFromOf(settings: Record<string, unknown>): string[] {
  const value = settings[SURFACES_FROM];
  return Array.isArray(value) ? value.filter((source): source is string => typeof source === "string") : [];
}

function labelOf(setting: string): string {
  return SETTING_PRESENTATIONS[setting]?.label ?? setting;
}

/** A number saved when the field is left or Enter is pressed, when it is a number and not the stored one. */
function NumberField({ setting, value, disabled, onSave }: { setting: string; value: number; disabled: boolean; onSave: (value: number) => void }) {
  const [typed, setTyped] = useState<string | null>(null);
  const inputId = useId();
  const unit = SETTING_PRESENTATIONS[setting]?.unit ?? "";
  const save = () => {
    const number = typed === null ? value : Number(typed);
    setTyped(null);
    if (typed !== null && typed.trim() !== "" && Number.isFinite(number) && number !== value) onSave(number);
  };
  return (
    <div className="study-field">
      <label htmlFor={inputId}>{labelOf(setting)}</label>
      <span className="study-field-value">
        <input id={inputId} type="number" className="setting-number" step="any" value={typed ?? String(value)} disabled={disabled}
               onChange={(event) => setTyped(event.target.value)} onBlur={save}
               onKeyDown={(event) => { if (event.key === "Enter") save(); }} />
        {unit !== "" && <span className="setting-unit">{unit}</span>}
      </span>
    </div>
  );
}

/** The metric's own settings, in a fold: the balance temperature (one control for its two settings), the others one field each. */
function MoreSettings({ metric, settings, disabled, onChange }: { metric: string; settings: Record<string, unknown>; disabled: boolean;
                                                                 onChange: (values: Record<string, unknown>) => void }) {
  const balanceLabelId = useId();
  const balanceInputId = useId();
  const timeBasisId = useId();
  const keys = Object.keys(settings).filter((key) => !PERIOD_KEYS.includes(key) && (key !== TIME_BASIS || METRICS_WITH_A_CLOCK.includes(metric))
    && key !== BALANCE_TEMPERATURE_FIELDS[1] && key !== SURFACES_FROM);
  if (keys.length === 0) return null;
  const balance = SETTING_PRESENTATIONS[BALANCE_TEMPERATURE_FIELDS[0]];
  return (
    <details className="study-more-settings">
      <summary>{messages.studyMoreSettings}</summary>
      {keys.map((key) => {
        const value = settings[key];
        if (key === BALANCE_TEMPERATURE_FIELDS[0]) {
          return (
            <div key={key} className="study-field study-field-wide">
              <span id={balanceLabelId}>{balance.label}</span>
              <BalanceTemperatureSlider balanceTemperature={typeof value === "number" ? value : null}
                                        deadBand={typeof settings[BALANCE_TEMPERATURE_FIELDS[1]] === "number" ? settings[BALANCE_TEMPERATURE_FIELDS[1]] as number : null}
                                        track={balance.slider!} unit={balance.unit} onChange={onChange} inputId={balanceInputId} labelId={balanceLabelId}
                                        invalid={false} describedBy={undefined} disabled={disabled} />
            </div>
          );
        }
        if (key === TIME_BASIS) {
          return (
            <div key={key} className="study-field">
              <label htmlFor={timeBasisId}>{labelOf(key)}</label>
              <select id={timeBasisId} value={String(value)} disabled={disabled} onChange={(event) => onChange({ [key]: event.target.value })}>
                {Object.entries(messages.timeBasisChoices).map(([choice, label]) => <option key={choice} value={choice}>{label}</option>)}
              </select>
            </div>
          );
        }
        if (typeof value === "boolean") {
          return (
            <label key={key} className="study-field study-field-check">
              <input type="checkbox" checked={value} disabled={disabled} onChange={(event) => onChange({ [key]: event.target.checked })} />
              {labelOf(key)}
            </label>
          );
        }
        return <NumberField key={key} setting={key} value={Number(value)} disabled={disabled} onSave={(number) => onChange({ [key]: number })} />;
      })}
    </details>
  );
}

/** Check boxes for the project's surfaces the study samples besides its files. The surroundings wait for the project's surroundings
 *  files; the terrain is offered when the project has one, the ground around the site when it has none. A source the study samples
 *  is shown and can be turned off even when its file has gone. */
function SurfacesFrom({ chosen, hasSurroundings, hasTerrain, disabled, onChange }: { chosen: string[]; hasSurroundings: boolean; hasTerrain: boolean;
                                                                                     disabled: boolean; onChange: (sources: string[]) => void }) {
  const shown = [
    { source: "context", available: hasSurroundings, reason: messages.studyNeedsSurroundingsFiles },
    ...(hasTerrain || chosen.includes("terrain") ? [{ source: "terrain", available: hasTerrain, reason: undefined }] : []),
    ...(!hasTerrain || chosen.includes("ground") ? [{ source: "ground", available: true, reason: undefined }] : []),
  ];
  const toggle = (source: string, on: boolean) =>
    onChange(SOURCE_ORDER.filter((each) => (each === source ? on : chosen.includes(each))));
  return (
    <div className="study-surfaces-from">
      {shown.map(({ source, available, reason }) => {
        const checked = chosen.includes(source);
        return (
          <label key={source} className="study-field study-field-check" title={available ? undefined : reason}>
            <input type="checkbox" checked={checked} disabled={disabled || (!available && !checked)}
                   onChange={(event) => toggle(source, event.target.checked)} />
            {messages.studySurfacesFrom[source]}
          </label>
        );
      })}
    </div>
  );
}

export function StudyPopover({ id, study, metrics, storedFiles, hasSurroundings, hasTerrain, disabledReason, onChange, onAddFiles, onUseFile, onRemoveFile,
                               onDelete, onClose }: StudyPopoverProps) {
  const { entry } = study;
  const settings = entry.settings ?? {};
  const files = entry.test_surface_files ?? [];
  const disabled = disabledReason !== null;
  const metric = metrics.find((info) => info.name === entry.metric);
  const hasPeriod = metric !== undefined && PERIOD_KEYS.every((key) => key in metric.default_settings);
  const [nameTyped, setNameTyped] = useState<string | null>(null);
  const { problem, send } = useDialogRequest(() => {});
  const nameInput = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const nameId = useId();
  const metricId = useId();
  const periodLabelId = useId();
  const periodInputId = useId();
  const filesTitleId = useId();

  useEffect(() => nameInput.current?.focus(), []);

  const change = (requested: StudyChange) => void send(() => onChange(requested));
  const saveName = () => {
    const typed = nameTyped;
    setNameTyped(null);
    if (typed !== null && typed !== entry.name) change({ name: typed });
  };
  const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onClose();
  };

  return (
    <div id={id} className="study-popover" role="dialog" aria-labelledby={titleId} onKeyDown={closeOnEscape}>
      <div className="study-popover-header">
        <h3 id={titleId}>{entry.name}</h3>
        <button type="button" className="study-popover-close" aria-label={messages.closeStudySettings} title={messages.closeStudySettings} onClick={onClose}>
          <span aria-hidden="true">×</span>
        </button>
      </div>
      <div className="study-field">
        <label htmlFor={nameId}>{messages.studyName}</label>
        <input ref={nameInput} id={nameId} type="text" value={nameTyped ?? entry.name} disabled={disabled} onChange={(event) => setNameTyped(event.target.value)}
               onBlur={saveName} onKeyDown={(event) => { if (event.key === "Enter") saveName(); }} />
      </div>
      <div className="study-field">
        <label htmlFor={metricId}>{messages.studyMetric}</label>
        <select id={metricId} value={entry.metric} disabled={disabled} onChange={(event) => change({ metric: event.target.value })}>
          {metrics.map((info) => (
            <option key={info.name} value={info.name} disabled={!info.available}>
              {info.available ? messages.metricOption(info.label, info.unit) : messages.metricUnavailableOption(info.label)}
            </option>
          ))}
        </select>
      </div>
      {hasPeriod && (
        <div className="study-field study-field-wide">
          <span id={periodLabelId}>{labelOf(ANALYSIS_PERIOD_FIELDS[0])}</span>
          <AnalysisPeriod values={Object.fromEntries(ANALYSIS_PERIOD_FIELDS.map((key) => [key, (settings[key] as number | undefined) ?? null])) as Record<AnalysisPeriodField, number | null>}
                          onChange={(values) => change({ values })} inputId={periodInputId} labelId={periodLabelId} invalid={false}
                          describedBy={undefined} disabled={disabled} />
        </div>
      )}
      <MoreSettings metric={entry.metric} settings={settings} disabled={disabled} onChange={(values) => change({ values })} />
      <div className="study-files" role="group" aria-labelledby={filesTitleId}>
        <p id={filesTitleId} className="study-files-title">{messages.studySurfaces}</p>
        <ProtectsBox files={files.map((name) => storedFiles.find((file) => file.name === name) ?? { name, triangle_count: 0 })} mode=""
                     hint={messages.studyNoSurfaceFiles} addLabel={messages.addStudySurfaces} onAddFiles={onAddFiles} onRemoveFile={onRemoveFile}
                     disabledReason={disabledReason} otherFiles={storedFiles.map((file) => file.name).filter((name) => !files.includes(name))}
                     onUseFile={onUseFile} otherFilesTitle={messages.useFileOfProject} />
        <SurfacesFrom chosen={surfacesFromOf(settings)} hasSurroundings={hasSurroundings} hasTerrain={hasTerrain} disabled={disabled}
                      onChange={(sources) => change({ values: { [SURFACES_FROM]: sources } })} />
      </div>
      {problem !== null && <p className="studies-panel-problem" role="alert">{problem}</p>}
      <button type="button" className="secondary-button study-delete" disabled={disabled} onClick={() => void send(onDelete)}>{messages.deleteStudy}</button>
    </div>
  );
}

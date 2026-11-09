// The settings of one study, in a popover beside the studies panel (simulate design, section 4): its name (a change renames it),
// its metric (a select; the metrics whose inputs are missing are greyed with the reason), the analysis period when the metric has
// one (the period control of the Criteria step), the metric's few mode settings and the test point spacing in a fold, its study
// surfaces (what it accounts for on the plot, a select like the metric's: nothing, the max volume, the envelope or the massing; then
// one list of switches for what it simulates: that geometry, the context, the terrain or, without one, the ground, and each test
// surface file the project stores), Duplicate and Delete. Each change is saved at once: a text or number
// field when it is left or Enter is pressed, the other controls on the change. The popover is a non-modal dialog: the view
// around it stays usable; Escape and Close end it, and the focus goes back to the study's settings button.
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { InputFileInfo, MetricInfo, StudyChange, StudyWithState } from "../api_client/client";
import { messages } from "../messages";
import { formattedNumber } from "../format_numbers";
import { STUDY_STANDS, type StudyStand } from "../viewer/study_values";
import { standOf } from "./use_study_view";
import { ANALYSIS_PERIOD_FIELDS, BALANCE_TEMPERATURE_FIELDS, SETTING_PRESENTATIONS } from "../settings_form/presentation";
import { AnalysisPeriod, type AnalysisPeriodField } from "../settings_form/widgets/AnalysisPeriod";
import { BalanceTemperatureSlider } from "../settings_form/widgets/BalanceTemperatureSlider";
import { useDialogRequest } from "../common/dialogs";

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
  /** Carve has built the envelope, the massing: a study can account for them. */
  envelopeBuilt: boolean;
  massingBuilt: boolean;
  /** Whether the project has a base height, whose base volume a study can stand (design/base-height.md). */
  hasBaseVolume?: boolean;
  /** The carving's test point spacing (m), which a study follows until it has its own. */
  carvingSpacing: number;
  /** Why the study cannot be changed now (a run of the project); null when it can. */
  disabledReason: string | null;
  /** Saves a change of the study; resolves with the reason it was refused, or null. */
  onChange: (change: StudyChange) => Promise<string | null>;
  onUseFile: (fileName: string) => Promise<string | null>;
  onRemoveFile: (fileName: string) => Promise<string | null>;
  onDuplicate: () => Promise<string | null>;
  /** Opens picking on the surroundings for this study (design/test-surfaces-on-context.md); absent without surroundings. */
  onPickFromSurroundings?: () => void;
  onDelete: () => Promise<string | null>;
  onClose: () => void;
}

// The settings drawn as their own control, apart from the fold: the period. The time basis is read only by sun hours (the engine
// refuses another clock than standard time for the other metrics), so the fold shows it for sun hours alone.
const PERIOD_KEYS: readonly string[] = ANALYSIS_PERIOD_FIELDS;
const TIME_BASIS = "time_basis";
const METRICS_WITH_A_CLOCK = ["sun_hours"];
// The settings of what the study accounts for and simulates, drawn in its study surfaces rather than in the fold, and its spacing,
// drawn in the fold as a field of its own.
const SURFACES_FROM = "surfaces_from";
const GEOMETRY = "geometry";
const SAMPLE_GEOMETRY = "sample_geometry";
const SAMPLE_SPACING = "sample_spacing";
const QUICK = "quick";
const METRICS_WITH_A_QUICK_COUNT = ["sun_hours"];
const OWN_CONTROLS: readonly string[] = [SURFACES_FROM, GEOMETRY, SAMPLE_GEOMETRY, SAMPLE_SPACING, QUICK];
const SOURCE_ORDER = ["context", "terrain", "ground"];

/** The study simulates the faces of the geometry it accounts for (not for nothing). */
export function simulatesGeometry(settings: Record<string, unknown>): boolean {
  return settings[SAMPLE_GEOMETRY] === true && standOf(settings) !== "none";
}

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
function MoreSettings({ metric, settings, carvingSpacing, disabled, onChange }: { metric: string; settings: Record<string, unknown>;
                                                                                 carvingSpacing: number; disabled: boolean;
                                                                                 onChange: (values: Record<string, unknown>) => void }) {
  const balanceLabelId = useId();
  const balanceInputId = useId();
  const timeBasisId = useId();
  const keys = Object.keys(settings).filter((key) => !PERIOD_KEYS.includes(key) && (key !== TIME_BASIS || METRICS_WITH_A_CLOCK.includes(metric))
    && key !== BALANCE_TEMPERATURE_FIELDS[1] && !OWN_CONTROLS.includes(key));
  const balance = SETTING_PRESENTATIONS[BALANCE_TEMPERATURE_FIELDS[0]];
  const ownSpacing = typeof settings[SAMPLE_SPACING] === "number" ? settings[SAMPLE_SPACING] as number : null;
  return (
    <details className="study-more-settings">
      <summary>{messages.studyMoreSettings}</summary>
      <SpacingField own={ownSpacing} carving={carvingSpacing} disabled={disabled} onChange={(spacing) => onChange({ [SAMPLE_SPACING]: spacing })} />
      {keys.map((key) => {
        const value = settings[key];
        if (key === BALANCE_TEMPERATURE_FIELDS[0]) {
          const harmCounted = settings.include_harm === true;
          return (
            <div key={key} className="study-field study-field-wide">
              <span id={balanceLabelId}>{harmCounted ? balance.label : messages.balanceSunCountsBelow}</span>
              <BalanceTemperatureSlider balanceTemperature={typeof value === "number" ? value : null}
                                        deadBand={typeof settings[BALANCE_TEMPERATURE_FIELDS[1]] === "number" ? settings[BALANCE_TEMPERATURE_FIELDS[1]] as number : null}
                                        track={balance.slider!} unit={balance.unit} onChange={onChange} inputId={balanceInputId} labelId={balanceLabelId}
                                        invalid={false} describedBy={undefined} disabled={disabled}
                                        harmCounted={harmCounted} />
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

/** The test point spacing: the study's own, or the carving's while it has none ("0.5, from Carve"). Typing a number gives the study its
 *  own; Follows Carve takes it away again. */
function SpacingField({ own, carving, disabled, onChange }: { own: number | null; carving: number; disabled: boolean;
                                                              onChange: (spacing: number | null) => void }) {
  const [typed, setTyped] = useState<string | null>(null);
  const inputId = useId();
  const hintId = useId();
  const save = () => {
    const number = typed === null ? NaN : Number(typed);
    setTyped(null);
    if (typed !== null && typed.trim() !== "" && Number.isFinite(number) && number > 0 && number !== own) onChange(number);
  };
  return (
    <div className="study-field study-spacing">
      <label htmlFor={inputId} title={messages.studySpacingHint}>{messages.studySpacing}</label>
      <span className="study-field-value">
        <input id={inputId} type="number" className="setting-number" step="any" min="0" value={typed ?? (own === null ? "" : String(own))}
               placeholder={formattedNumber(carving)} aria-describedby={hintId} disabled={disabled}
               onChange={(event) => setTyped(event.target.value)} onBlur={save} onKeyDown={(event) => { if (event.key === "Enter") save(); }} />
        {own === null
          ? <span id={hintId} className="study-spacing-note">{messages.studySpacingFollowsCarve}</span>
          : <button id={hintId} type="button" className="link-button study-spacing-reset" disabled={disabled} onClick={() => onChange(null)}>{messages.studySpacingReset}</button>}
      </span>
    </div>
  );
}

/** A switch row of the study surfaces: a label, its hint on hover, and an on/off switch. */
function SwitchRow({ label, hint, checked, disabled, onChange }: { label: string; hint?: string; checked: boolean; disabled: boolean;
                                                                   onChange: (on: boolean) => void }) {
  return (
    <label className="study-field study-switch-row" title={hint}>
      <span>{label}</span>
      <input type="checkbox" role="switch" className="setting-switch" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

/** What the study accounts for on the plot (a select of four; the envelope and the massing wait until Carve built them), and one list of
 *  switches for what it simulates: that geometry's faces, the context (waiting for the project's surroundings files), the terrain when the
 *  project has one or the ground when it has none, then each test surface file the project stores. A source or file the study samples is
 *  shown and can be turned off even when its file has gone. */
function AccountAndSimulate({ settings, hasSurroundings, hasTerrain, envelopeBuilt, massingBuilt, hasBaseVolume, fileChoices, chosenFiles, disabled, onChange,
                              onToggleFile, setNames, onPickFromSurroundings }: {
  settings: Record<string, unknown>; hasSurroundings: boolean; hasTerrain: boolean; envelopeBuilt: boolean; massingBuilt: boolean;
  hasBaseVolume: boolean;
  fileChoices: string[]; chosenFiles: string[]; disabled: boolean; onChange: (values: Record<string, unknown>) => void;
  onToggleFile: (fileName: string, on: boolean) => void;
  /** The name each stored file is shown by (its surface set's). */
  setNames: Readonly<Record<string, string>>;
  onPickFromSurroundings?: () => void;
}) {
  const accountId = useId();
  const stand = standOf(settings);
  const chosen = surfacesFromOf(settings);
  const built: Record<StudyStand, boolean> = { none: true, max_volume: true, base_volume: hasBaseVolume, envelope: envelopeBuilt, massing: massingBuilt };
  // The base volume is a choice only while the project has a base height (or the study already stands it)
  const stands = STUDY_STANDS.filter((each) => each !== "base_volume" || hasBaseVolume || stand === "base_volume");
  const sources = [
    { source: "context", available: hasSurroundings, reason: messages.studyNeedsSurroundingsFiles },
    ...(hasTerrain || chosen.includes("terrain") ? [{ source: "terrain", available: hasTerrain, reason: undefined }] : []),
    ...(!hasTerrain || chosen.includes("ground") ? [{ source: "ground", available: true, reason: undefined }] : []),
  ];
  const toggle = (source: string, on: boolean) =>
    onChange({ [SURFACES_FROM]: SOURCE_ORDER.filter((each) => (each === source ? on : chosen.includes(each))) });
  return (
    <>
      <div className="study-field">
        <label htmlFor={accountId} title={messages.studyAccountForHint}>{messages.studyAccountFor}</label>
        <select id={accountId} className="study-account-for" value={stand} disabled={disabled}
                onChange={(event) => onChange({ [GEOMETRY]: event.target.value })}>
          {stands.map((each) => (
            <option key={each} value={each} disabled={!built[each] && each !== stand}>
              {/* The study's own choice says it waits too (a base height set back to none), so a run that leaves it out is no surprise */}
              {built[each] ? messages.studyStands[each] : messages.studyStandWaiting(messages.studyStands[each], messages.buildGeometryFirst[each])}
            </option>
          ))}
        </select>
      </div>
      <p className="study-subtitle">{messages.studySimulate}</p>
      <div className="study-switches">
        <SwitchRow label={stand === "none" ? messages.nothingToSimulate : messages.studyStands[stand]}
                   hint={stand === "none" ? undefined : messages.studySimulateGeometryHint}
                   checked={simulatesGeometry(settings)} disabled={disabled || stand === "none"}
                   onChange={(on) => onChange({ [SAMPLE_GEOMETRY]: on })} />
        {sources.map(({ source, available, reason }) => {
          const checked = chosen.includes(source);
          return (
            <SwitchRow key={source} label={messages.studySurfacesFrom[source]} hint={available ? messages.studySurfacesFromHint[source] : reason}
                       checked={checked} disabled={disabled || (!available && !checked)} onChange={(on) => toggle(source, on)} />
          );
        })}
      </div>
      <p className="study-subtitle">{messages.studyTestSurfaceFiles}</p>
      {fileChoices.length === 0
        ? <p className="study-note">{messages.studyNoTestSurfaceFiles}</p>
        : (
          <div className="study-switches study-file-switches">
            {fileChoices.map((fileName) => (
              <SwitchRow key={fileName} label={setNames[fileName] ?? fileName} checked={chosenFiles.includes(fileName)} disabled={disabled}
                         onChange={(on) => onToggleFile(fileName, on)} />
            ))}
          </div>
        )}
      {onPickFromSurroundings !== undefined && (
        <button type="button" className="secondary-button study-pick-surfaces" disabled={disabled} onClick={onPickFromSurroundings}>{messages.pickFromSurroundings}</button>
      )}
    </>
  );
}

export function StudyPopover({ id, study, metrics, storedFiles, hasSurroundings, hasTerrain, envelopeBuilt, massingBuilt, hasBaseVolume = false, carvingSpacing, disabledReason,
                               onChange, onUseFile, onRemoveFile, onDuplicate, onDelete, onClose, onPickFromSurroundings }: StudyPopoverProps) {
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
  // The files a study can simulate: every test surface file the project stores, and any the study lists that has gone.
  const fileChoices = [...storedFiles.map((file) => file.name), ...files.filter((name) => !storedFiles.some((file) => file.name === name))];

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
      {METRICS_WITH_A_QUICK_COUNT.includes(entry.metric) && (
        <div className="study-quick">
          <SwitchRow label={messages.studyQuick} hint={messages.studyQuickHint} checked={settings[QUICK] === true} disabled={disabled}
                     onChange={(on) => change({ values: { [QUICK]: on } })} />
        </div>
      )}
      <MoreSettings metric={entry.metric} settings={settings} carvingSpacing={carvingSpacing} disabled={disabled} onChange={(values) => change({ values })} />
      <div className="study-files" role="group" aria-labelledby={filesTitleId}>
        <p id={filesTitleId} className="study-files-title">{messages.studySurfaces}</p>
        <AccountAndSimulate settings={settings} hasSurroundings={hasSurroundings} hasTerrain={hasTerrain} envelopeBuilt={envelopeBuilt}
                            massingBuilt={massingBuilt} hasBaseVolume={hasBaseVolume} fileChoices={fileChoices} chosenFiles={files} disabled={disabled}
                            onChange={(values) => change({ values })}
                            onToggleFile={(fileName, on) => void send(() => (on ? onUseFile(fileName) : onRemoveFile(fileName)))}
                            setNames={Object.fromEntries(storedFiles.map((file) => [file.name, file.shown_name ?? file.name]))}
                            onPickFromSurroundings={onPickFromSurroundings} />
      </div>
      {problem !== null && <p className="studies-panel-problem" role="alert">{problem}</p>}
      <div className="study-popover-actions">
        <button type="button" className="secondary-button study-duplicate" disabled={disabled} onClick={() => void send(onDuplicate)}>{messages.duplicateStudy}</button>
        <button type="button" className="secondary-button study-delete" disabled={disabled} onClick={() => void send(onDelete)}>{messages.deleteStudy}</button>
      </div>
    </div>
  );
}

// The typical building of the project (one per project, shared by its energy-weighted Solar usefulness criteria): the box in a
// criterion's Settings that names its type and the state of its weights, and the sheet beside the criterion panel where it is
// edited and calculated, as Simulate's study popover sits beside its list. The sheet has Start from (the three types the engine's
// model was checked on), the values in six folded groups with a line each (Shape, Windows, Walls and glass, Air, Use, Summer
// shading), Calculate, then the weight of each hour as a day-by-hour chart (benefit, and harm when the criterion counts harm) and
// three numbers. Each change is saved at once (use_typical_building.ts): a number when its field is left or Enter is pressed, the
// other controls on the change; a refused value shows its error at its field, and its group opens. While the building or the
// weather file differs from the one calculated, the chart is dimmed and Calculate reads Calculate again. The sheet is a non-modal
// dialog: Escape and Close end it, and the focus goes back to Edit building.
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import type { TypicalBuildingPreset } from "../api_client/client";
import { listedWithAnd, messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import { SettingTooltip } from "../settings_form/SettingTooltip";
import { formatNumber, formattedNumber } from "../steps/format_numbers";
import { studyPaletteColour } from "../viewer/study_palettes";
import { PanelSection } from "./PanelSection";
import type { TypicalBuildingHook, TypicalBuildingValues } from "./use_typical_building";
import "../steps/steps.css";

export type BuildingGroupId = "shape" | "windows" | "walls" | "air" | "use" | "shading";

export const BUILDING_GROUPS: readonly BuildingGroupId[] = ["shape", "windows", "walls", "air", "use", "shading"];

// The values each group holds, as the service names their fields ("wwr.south" is in Windows by "wwr").
const VALUES_OF_GROUP: Record<BuildingGroupId, readonly string[]> = {
  shape: ["width", "length", "height", "orientation"],
  windows: ["wwr", "g_value"],
  walls: ["u_opaque", "u_window", "mass_class"],
  air: ["ach_vent", "ach_infiltration", "heat_recovery"],
  use: ["t_set_heating", "t_set_cooling", "gains_day_w_m2", "gains_night_w_m2"],
  shading: ["shading_permanent", "shading_hot", "hot_months"],
};
const SIDES = ["north", "east", "south", "west"] as const;
const MASS_CLASSES = ["very_light", "light", "medium", "heavy", "very_heavy"];
const DAYS_IN_YEAR = 365;
const HOURS_IN_DAY = 24;
const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
// The option of Start from while the values are none of the types'.
const CUSTOM = "custom";

/** The group that shows the field the service names; null for a field of none ("start_from"). */
export function groupOfField(field: string): BuildingGroupId | null {
  const value = field.split(".")[0];
  return BUILDING_GROUPS.find((group) => VALUES_OF_GROUP[group].includes(value)) ?? null;
}

/** The value with its object keys sorted, so two values compare by their JSON. */
function sortedKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedKeys);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortedKeys((value as Record<string, unknown>)[key])]));
}

const sameValues = (first: unknown, second: unknown) => JSON.stringify(sortedKeys(first)) === JSON.stringify(sortedKeys(second));

/** The type the values are: the one they started from while none differs, else another type they equal; null when none (Custom). */
export function typeOfValues(values: TypicalBuildingValues, startFrom: string | null, presets: Record<string, TypicalBuildingPreset>): string | null {
  if (startFrom !== null && presets[startFrom] !== undefined && sameValues(values, presets[startFrom].values)) return startFrom;
  return Object.keys(presets).find((key) => sameValues(values, presets[key].values)) ?? null;
}

const numberOf = (values: TypicalBuildingValues, key: string) => (typeof values[key] === "number" ? (values[key] as number) : null);
const numberText = (value: number | null) => (value === null ? "?" : formattedNumber(value));

/** The months as "Jun, Jul and Aug". */
function monthsText(months: unknown): string {
  return listedWithAnd((Array.isArray(months) ? months : []).filter((month) => typeof month === "number" && month >= 1 && month <= 12)
    .map((month) => messages.monthAbbreviations[month - 1]));
}

/** The line a closed group says: "5 × 7 × 3 m, 0° from north", "S 0.27, E 0.1, W 0.1; g 0.6", ... */
export function buildingGroupSummary(group: BuildingGroupId, values: TypicalBuildingValues): string {
  const text = (key: string) => numberText(numberOf(values, key));
  switch (group) {
    case "shape": return messages.shapeSummary(text("width"), text("length"), text("height"), text("orientation"));
    case "windows": {
      const shares = (values.wwr ?? {}) as Record<string, unknown>;
      const withWindows = SIDES.filter((side) => typeof shares[side] === "number" && (shares[side] as number) > 0);
      if (withWindows.length === 0) return messages.noWindows;
      const sharesText = withWindows.map((side) => `${messages.typicalBuildingSideInitials[side]} ${formattedNumber(shares[side] as number)}`).join(", ");
      return messages.windowsSummary(sharesText, text("g_value"));
    }
    case "walls": return messages.wallsSummary(text("u_opaque"), text("u_window"), (messages.massClasses[String(values.mass_class)] ?? String(values.mass_class)).toLowerCase());
    case "air": {
      const recovery = numberOf(values, "heat_recovery");
      return messages.airSummary(text("ach_vent"), text("ach_infiltration"), recovery === null || recovery === 0 ? null : formattedNumber(recovery));
    }
    case "use": return messages.useSummary(text("t_set_heating"), text("t_set_cooling"), text("gains_day_w_m2"), text("gains_night_w_m2"));
    case "shading": {
      const permanent = numberOf(values, "shading_permanent"), summer = numberOf(values, "shading_hot");
      const parts = [...(permanent === null ? [] : [messages.permanentShadingSummary(formattedNumber(permanent))]),
                     ...(summer === null ? [] : [messages.summerShadingSummary(formattedNumber(summer), monthsText(values.hot_months))])];
      if (parts.length === 0) return messages.noShading;
      const line = parts.join("; ");
      return line.charAt(0).toUpperCase() + line.slice(1);
    }
  }
}

interface TypicalBuildingBoxProps {
  building: TypicalBuildingHook;
  sheetOpen: boolean;
  sheetId: string;
  onToggleSheet: () => void;
  /** Edit building, which the focus goes back to when the sheet closes. */
  editButton: RefObject<HTMLButtonElement | null>;
}

/**
 * In a criterion's Settings: the type of the building as stored (or Custom), the state of its weights, and Edit building. A value
 * refused in the sheet is not in it: the run uses the stored building.
 */
export function TypicalBuildingBox({ building, sheetOpen, sheetId, onToggleSheet, editButton }: TypicalBuildingBoxProps) {
  const titleId = useId();
  const { stored, presets } = building;
  const typeKey = stored === null || presets === null ? null : typeOfValues(stored.values, stored.start_from, presets);
  return (
    <div className="typical-building-box" role="group" aria-labelledby={titleId}>
      <p id={titleId} className="typical-building-box-title">{messages.typicalBuilding}</p>
      {stored === null ? (
        building.readProblem === null ? <p className="step-reason">{messages.typicalBuildingReading}</p>
          : <p className="setting-error"><WarningIcon /><span>{building.readProblem}</span></p>
      ) : (
        <>
          <p className="typical-building-box-type">{typeKey === null || presets === null ? messages.typicalBuildingCustom : presets[typeKey].label}</p>
          <p className="typical-building-box-state">
            {stored.state === "current" ? messages.typicalBuildingStates.current
              : `${messages.typicalBuildingStates[stored.state]}. ${messages.typicalBuildingRunCalculates}`}
          </p>
        </>
      )}
      <button ref={editButton} type="button" className="secondary-button" aria-expanded={sheetOpen} aria-controls={sheetOpen ? sheetId : undefined}
              onClick={onToggleSheet}>
        {messages.editBuilding}
      </button>
    </div>
  );
}

interface LeaveSavedNumberProps {
  id?: string;
  ariaLabel?: string;
  value: number | null;
  /** An empty field saves null (no shading); else it gives the value back. */
  mayBeEmpty?: boolean;
  placeholder?: string;
  short?: boolean;
  invalid: boolean;
  describedBy?: string;
  disabled: boolean;
  onSave: (value: number | null) => void;
}

/** A number saved when the field is left or Enter is pressed, when it is a number and not the shown one (as a study's fields). */
function LeaveSavedNumber({ id, ariaLabel, value, mayBeEmpty = false, placeholder, short = false, invalid, describedBy, disabled, onSave }: LeaveSavedNumberProps) {
  const [typed, setTyped] = useState<string | null>(null);
  const save = () => {
    if (typed === null) return;
    setTyped(null);
    const text = typed.trim();
    if (text === "") {
      if (mayBeEmpty && value !== null) onSave(null);
      return;
    }
    const number = Number(text);
    if (Number.isFinite(number) && number !== value) onSave(number);
  };
  return (
    <input id={id} type="number" className={short ? "setting-number setting-number-short" : "setting-number"} step="any" inputMode="decimal"
           aria-label={ariaLabel} value={typed ?? (value === null ? "" : String(value))} placeholder={placeholder} disabled={disabled}
           aria-invalid={invalid} aria-describedby={describedBy} onChange={(event) => setTyped(event.target.value)} onBlur={save}
           onKeyDown={(event) => { if (event.key === "Enter") save(); }} />
  );
}

/** An error under a field, with the warning icon. */
function FieldError({ id, message }: { id?: string; message: string }) {
  return <p id={id} className="setting-error"><WarningIcon /><span>{message}</span></p>;
}

interface BuildingNumberProps {
  name: string;
  unit?: string;
  note?: string;
  value: number | null;
  error: string | undefined;
  mayBeEmpty?: boolean;
  disabled: boolean;
  onSave: (value: number | null) => void;
}

function BuildingNumber({ name, unit, note, value, error, mayBeEmpty, disabled, onSave }: BuildingNumberProps) {
  const inputId = useId();
  const errorId = useId();
  return (
    <div className="setting-field" data-building-field={name}>
      <div className="setting-label-row"><label htmlFor={inputId} className="setting-label">{messages.typicalBuildingFields[name]}</label></div>
      <div className="setting-control">
        <LeaveSavedNumber id={inputId} value={value} mayBeEmpty={mayBeEmpty} placeholder={mayBeEmpty ? messages.noShading : undefined}
                          invalid={error !== undefined} describedBy={error === undefined ? undefined : errorId} disabled={disabled} onSave={onSave} />
        {unit !== undefined && <span className="setting-unit">{unit}</span>}
      </div>
      {error !== undefined && <FieldError id={errorId} message={error} />}
      {note !== undefined && <p className="setting-note">{note}</p>}
    </div>
  );
}

const rgbOf = (hex: string) => [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
const VIRIDIS_RAMP = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => studyPaletteColour("viridis", t)).join(", ")})`;

/**
 * The weight of each hour of the year, 0 to 1 in viridis: a canvas of 365 days across and 24 hours down (hour 0 of 1 January at
 * the top left), the month initials under it, the hours beside it and the colour ramp. Null *weights*: they are being read.
 */
export function WeightsChart({ title, weights }: { title: string; weights: readonly number[] | null }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const context = weights === null ? null : canvas.current?.getContext("2d") ?? null;
    if (context === null || weights === null) return;
    const image = context.createImageData(DAYS_IN_YEAR, HOURS_IN_DAY);
    for (let day = 0; day < DAYS_IN_YEAR; day++) {
      for (let hour = 0; hour < HOURS_IN_DAY; hour++) {
        const [red, green, blue] = rgbOf(studyPaletteColour("viridis", weights[day * HOURS_IN_DAY + hour] ?? 0));
        const offset = (hour * DAYS_IN_YEAR + day) * 4;
        image.data[offset] = red;
        image.data[offset + 1] = green;
        image.data[offset + 2] = blue;
        image.data[offset + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
  }, [weights]);
  return (
    <figure className="weights-chart">
      <figcaption className="weights-chart-title">{title}</figcaption>
      <div className="weights-chart-plot">
        <div className="weights-chart-hours" aria-hidden="true"><span>0</span><span>12</span><span>24</span></div>
        <canvas ref={canvas} className="weights-chart-canvas" width={DAYS_IN_YEAR} height={HOURS_IN_DAY} role="img" aria-label={messages.weightsChartLabel(title)} />
      </div>
      <div className="weights-chart-months" aria-hidden="true">
        {messages.monthInitials.map((initial, index) => <span key={index} style={{ flexGrow: DAYS_IN_MONTH[index] }}>{initial}</span>)}
      </div>
      <div className="weights-chart-legend" aria-hidden="true">
        <span>0</span><span className="weights-chart-ramp" style={{ background: VIRIDIS_RAMP }} /><span>1</span>
      </div>
      {weights === null && <p className="step-reason">{messages.weightsChartWaits}</p>}
    </figure>
  );
}

interface TypicalBuildingSheetProps {
  id: string;
  building: TypicalBuildingHook;
  /** The criterion counts harm (include_harm): the chart of harm is shown too. */
  includesHarm: boolean;
  hasWeatherFile: boolean;
  /** Why the building cannot be changed now (a run of the project); null when it can. */
  disabledReason: string | null;
  onClose: () => void;
}

export function TypicalBuildingSheet({ id, building, includesHarm, hasWeatherFile, disabledReason, onClose }: TypicalBuildingSheetProps) {
  const { values, stored, presets, fieldErrors, weights } = building;
  const titleId = useId();
  const startFromId = useId();
  const startFromErrorId = useId();
  const sharesLabelId = useId();
  const sharesErrorId = useId();
  const massId = useId();
  const monthsLabelId = useId();
  const reasonId = useId();
  const startFrom = useRef<HTMLSelectElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [openGroups, setOpenGroups] = useState<ReadonlySet<BuildingGroupId>>(new Set());
  const disabled = disabledReason !== null;

  // The focus goes to Start from once the building is read, else to Close.
  const focused = useRef(false);
  useEffect(() => {
    if (focused.current) return;
    if (values !== null && startFrom.current !== null) startFrom.current.focus();
    else closeButton.current?.focus();
    focused.current = values !== null;
  }, [values !== null]);
  // A group with a field the last save refused opens, before the page is drawn.
  const groupsWithErrors = BUILDING_GROUPS.filter((group) => Object.keys(fieldErrors).some((field) => groupOfField(field) === group));
  useLayoutEffect(() => {
    if (groupsWithErrors.some((group) => !openGroups.has(group))) setOpenGroups((open) => new Set([...open, ...groupsWithErrors]));
  }, [groupsWithErrors.join(" ")]);
  // The weights of the last calculation, read while the sheet is open.
  useEffect(() => {
    if (stored !== null && stored.state !== "missing" && weights === null) building.readWeights();
  }, [stored?.state, weights]);

  const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onClose();
  };
  const toggleGroup = (group: BuildingGroupId) => setOpenGroups((open) => {
    const next = new Set(open);
    if (!next.delete(group)) next.add(group);
    return next;
  });

  const header = (
    <div className="study-popover-header">
      <h3 id={titleId}>{messages.typicalBuilding}</h3>
      <button ref={closeButton} type="button" className="study-popover-close" aria-label={messages.closeTypicalBuilding} title={messages.closeTypicalBuilding}
              onClick={onClose}>
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
  if (values === null || stored === null || presets === null) {
    return (
      <div id={id} className="typical-building-sheet" role="dialog" aria-labelledby={titleId} onKeyDown={closeOnEscape}>
        {header}
        {building.readProblem === null ? <p className="step-reason">{messages.typicalBuildingReading}</p> : <FieldError message={building.readProblem} />}
      </div>
    );
  }

  const change = (key: string, value: unknown) => building.change({ ...values, [key]: value }, building.startFrom);
  const number = (key: string) => numberOf(values, key);
  const field = (key: string, unit?: string, note?: string, mayBeEmpty = false) => (
    <BuildingNumber name={key} unit={unit} note={note} value={number(key)} error={fieldErrors[key]} mayBeEmpty={mayBeEmpty} disabled={disabled}
                    onSave={(value) => change(key, value)} />
  );
  const shares = (values.wwr ?? {}) as Record<string, number>;
  const shareErrors = [fieldErrors.wwr, ...SIDES.flatMap((side) => {
    const error = fieldErrors[`wwr.${side}`];
    return error === undefined ? [] : [`${messages.typicalBuildingSides[side]}: ${error}`];
  })].filter((error) => error !== undefined);
  const months = Array.isArray(values.hot_months) ? (values.hot_months as number[]) : [];
  const toggleMonth = (month: number) => change("hot_months", months.includes(month) ? months.filter((each) => each !== month)
    : [...months, month].sort((first, second) => first - second));
  const units = messages.typicalBuildingUnits;
  const content: Record<BuildingGroupId, ReactNode> = {
    shape: <>{field("width", units.metres)}{field("length", units.metres)}{field("height", units.metres)}
             {field("orientation", units.degrees, messages.typicalBuildingNotes.orientation)}</>,
    windows: (
      <>
        <div className="setting-field" data-building-field="wwr" role="group" aria-labelledby={sharesLabelId}>
          <div className="setting-label-row"><span id={sharesLabelId} className="setting-label">{messages.typicalBuildingFields.wwr}</span></div>
          <div className="setting-angle-grid">
            {SIDES.map((side) => (
              <label key={side} className="setting-angle-direction">
                <span>{messages.typicalBuildingSideInitials[side]}</span>
                <LeaveSavedNumber ariaLabel={messages.typicalBuildingSides[side]} short value={typeof shares[side] === "number" ? shares[side] : 0}
                                  invalid={fieldErrors[`wwr.${side}`] !== undefined || fieldErrors.wwr !== undefined}
                                  describedBy={shareErrors.length > 0 ? sharesErrorId : undefined} disabled={disabled}
                                  onSave={(share) => change("wwr", { ...shares, [side]: share ?? 0 })} />
              </label>
            ))}
          </div>
          {shareErrors.length > 0 && <div id={sharesErrorId}>{shareErrors.map((error) => <FieldError key={error} message={error} />)}</div>}
          <p className="setting-note">{messages.typicalBuildingNotes.wwr}</p>
        </div>
        {field("g_value")}
      </>
    ),
    walls: (
      <>
        {field("u_opaque", units.uValue)}{field("u_window", units.uValue)}
        <div className="setting-field" data-building-field="mass_class">
          <div className="setting-label-row"><label htmlFor={massId} className="setting-label">{messages.typicalBuildingFields.mass_class}</label></div>
          <select id={massId} className="setting-select" value={String(values.mass_class)} disabled={disabled} aria-invalid={fieldErrors.mass_class !== undefined}
                  onChange={(event) => change("mass_class", event.target.value)}>
            {MASS_CLASSES.map((mass) => <option key={mass} value={mass}>{messages.massClasses[mass]}</option>)}
          </select>
          {fieldErrors.mass_class !== undefined && <FieldError message={fieldErrors.mass_class} />}
        </div>
      </>
    ),
    air: <>{field("ach_vent", units.perHour)}{field("ach_infiltration", units.perHour)}{field("heat_recovery", undefined, messages.typicalBuildingNotes.heat_recovery)}</>,
    use: <>{field("t_set_heating", units.celsius)}{field("t_set_cooling", units.celsius)}{field("gains_day_w_m2", units.wattsPerSquareMetre)}
           {field("gains_night_w_m2", units.wattsPerSquareMetre, messages.typicalBuildingNotes.gains)}</>,
    shading: (
      <>
        {field("shading_permanent", undefined, messages.typicalBuildingNotes.shading, true)}
        {field("shading_hot", undefined, undefined, true)}
        {number("shading_hot") !== null && (
          <div className="setting-field" data-building-field="hot_months">
            <div className="setting-label-row"><span id={monthsLabelId} className="setting-label">{messages.typicalBuildingFields.hot_months}</span></div>
            <div className="typical-building-months" role="group" aria-labelledby={monthsLabelId}>
              {messages.monthAbbreviations.map((name, index) => (
                <button key={name} type="button" className="period-preset" aria-pressed={months.includes(index + 1)} disabled={disabled}
                        onClick={() => toggleMonth(index + 1)}>
                  {name}
                </button>
              ))}
            </div>
            {fieldErrors.hot_months !== undefined && <FieldError message={fieldErrors.hot_months} />}
          </div>
        )}
      </>
    ),
  };

  const typeKey = typeOfValues(values, building.startFrom, presets);
  // A refusal of a field the groups do not show (the service's own checks), said over the groups.
  const otherErrors = Object.entries(fieldErrors).filter(([name]) => name !== "start_from" && groupOfField(name) === null).map(([, message]) => message);
  const calculateBlocker = building.calculating ? null : disabledReason ?? (!hasWeatherFile ? messages.calculateNeedsWeatherFile
    : Object.keys(fieldErrors).length > 0 ? messages.calculateWaitsForValues : null);
  const outOfDate = stored.state === "out_of_date";
  const oneDecimal = (value: number | null | undefined) => (value === null || value === undefined ? "?" : formatNumber(value, undefined, 1));

  return (
    <div id={id} className="typical-building-sheet" role="dialog" aria-labelledby={titleId} onKeyDown={closeOnEscape}>
      {header}
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      <div className="setting-field" data-building-field="start_from">
        <div className="setting-label-row"><label htmlFor={startFromId} className="setting-label">{messages.startFrom}</label></div>
        <select ref={startFrom} id={startFromId} className="setting-select" value={typeKey ?? CUSTOM} disabled={disabled}
                aria-invalid={fieldErrors.start_from !== undefined} aria-describedby={fieldErrors.start_from === undefined ? undefined : startFromErrorId}
                onChange={(event) => {
                  const preset = presets[event.target.value];
                  if (preset !== undefined) building.change(JSON.parse(JSON.stringify(preset.values)) as TypicalBuildingValues, event.target.value);
                }}>
          {Object.entries(presets).map(([key, preset]) => <option key={key} value={key}>{preset.label}</option>)}
          {typeKey === null && <option value={CUSTOM} disabled>{messages.typicalBuildingCustom}</option>}
        </select>
        {fieldErrors.start_from !== undefined && <FieldError id={startFromErrorId} message={fieldErrors.start_from} />}
      </div>
      {otherErrors.map((error) => <FieldError key={error} message={error} />)}
      <div className="typical-building-groups">
        {BUILDING_GROUPS.map((group) => (
          <PanelSection key={group} id={group} title={messages.typicalBuildingGroups[group]} summary={buildingGroupSummary(group, values)}
                        open={openGroups.has(group)} onToggle={() => toggleGroup(group)} problem={groupsWithErrors.includes(group)}>
            {content[group]}
          </PanelSection>
        ))}
      </div>
      <div className="typical-building-calculate">
        <button type="button" className="primary-button" disabled={building.calculating || calculateBlocker !== null} aria-busy={building.calculating || undefined}
                aria-describedby={calculateBlocker === null ? undefined : reasonId} onClick={building.calculate}>
          {building.calculating ? <><span className="spinner" aria-hidden="true" />{messages.calculating}</>
            : outOfDate ? messages.calculateAgain : messages.calculate}
        </button>
        {calculateBlocker !== null && <p id={reasonId} className="run-button-reason">{calculateBlocker}</p>}
        {building.problem !== null && <p className="setting-error" role="alert"><WarningIcon /><span>{building.problem}</span></p>}
      </div>
      {stored.state !== "missing" && (
        <div className="typical-building-results-area">
          {outOfDate && <p className="typical-building-out-of-date">{messages.typicalBuildingOutOfDate}</p>}
          <div className={outOfDate ? "typical-building-results typical-building-results-out-of-date" : "typical-building-results"}>
            <WeightsChart title={messages.benefitChartTitle} weights={weights?.benefit ?? null} />
            {includesHarm && <WeightsChart title={messages.harmChartTitle} weights={weights?.harm ?? null} />}
            <dl className="typical-building-numbers">
              <div><dt>{messages.heatingDemand}</dt><dd>{messages.demandPerYear(oneDecimal(stored.heating_kwh_m2))}</dd></div>
              <div><dt>{messages.coolingDemand}</dt><dd>{messages.demandPerYear(oneDecimal(stored.cooling_kwh_m2))}</dd></div>
              <div>
                <dt>{messages.countedHours}<SettingTooltip settingLabel={messages.countedHours} help={messages.countedHoursNote} /></dt>
                <dd>{stored.counted_hours == null ? "?" : messages.countedHoursOfYear(stored.counted_hours)}</dd>
              </div>
            </dl>
          </div>
        </div>
      )}
    </div>
  );
}


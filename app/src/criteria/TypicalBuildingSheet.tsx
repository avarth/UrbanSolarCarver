// The typical building of the project (one per project, shared by its energy-weighted Solar usefulness criteria): the box in a
// criterion's Settings that names the library entry it came from and the state of its weights, and the window over the page where it
// is edited and calculated (a modal dialog, the frame of the project dialogs). The window has, in a left column, the library at the
// top (the examples by the groups the service names, then the user's own entries; choosing one replaces the project's copy; Save to
// library, Save as new, rename and delete of own entries) and the values in folded groups with a line each (Use, Fabric, Summer
// shading, and under Advanced: Room, Roof and floor, Air); in a right column, Calculate, then the effect of each hour's sun as a
// day-by-hour chart and three numbers; and Done under both. In a window narrower than 900 px the columns are one under the other. A new project has no building: the box asks to choose one, and the window shows only the library, open. Each change is
// saved at once (use_typical_building.ts): a number when its field is left or Enter is pressed, the other controls on the change; a
// refused value shows its error at its field, and its group opens. While the building or the weather file differs from the one
// calculated, the chart is dimmed and Calculate reads Calculate again. The window opens with the focus on its title; Escape, × and Done end it,
// and the focus goes back to Edit building.
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { TypicalBuildingLibraryEntry, TypicalBuildingReply, TypicalBuildingWeightsReply } from "../api_client/client";
import { dayAndMonth, messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import { SettingTooltip } from "../settings_form/SettingTooltip";
import { formatNumber, formattedNumber, groupedDigits } from "../steps/format_numbers";
import { DialogFrame } from "../steps/ProjectDialogs";
import { useAppTheme, type AppTheme } from "../theme/app_theme";
import { PanelSection } from "./PanelSection";
import { DeleteLibraryEntryDialog, LibraryNameDialog } from "./TypicalBuildingDialogs";
import type { TypicalBuildingHook, TypicalBuildingValues } from "./use_typical_building";
import "../steps/steps.css";

export type BuildingGroupId = "use" | "fabric" | "shading" | "room" | "roof_and_floor" | "air";

export const BASIC_GROUPS: readonly BuildingGroupId[] = ["use", "fabric", "shading"];
export const ADVANCED_GROUPS: readonly BuildingGroupId[] = ["room", "roof_and_floor", "air"];
const BUILDING_GROUPS = [...BASIC_GROUPS, ...ADVANCED_GROUPS];

// The values each group holds, as the service names their fields ("wwr.sw" is in Room by "wwr").
const VALUES_OF_GROUP: Record<BuildingGroupId, readonly string[]> = {
  use: ["schedule", "t_set_heating", "t_set_cooling", "gains_w_m2", "fresh_air_m3h_m2", "heat_recovery"],
  fabric: ["u_wall", "u_window", "g_value", "mass_capacity_kj_m2k"],
  shading: ["shading_factor", "shading_start", "shading_end"],
  room: ["room", "height", "depth", "width", "length", "orientation", "wwr"],
  roof_and_floor: ["roof_exposed", "u_roof", "floor_exposed", "u_floor"],
  air: ["ach_infiltration"],
};
const SCHEDULES = ["residential", "office", "always"];
const ROOMS = ["average", "box"];
// The sides of each room (typical_building.WWR_SIDES): the average room is turned 45°, its walls face NE, SE, SW and NW.
const SIDES_OF_ROOM: Record<string, readonly string[]> = { average: ["ne", "se", "sw", "nw"], box: ["north", "east", "south", "west"] };
// The keys of the two rooms that are not shared (the window shares name the room's sides).
const ROOM_KEYS = ["depth", "width", "length", "orientation", "wwr"];
const DAYS_IN_YEAR = 365;
const HOURS_IN_DAY = 24;
const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

/** The group that shows the field the service names; null for a field of none ("library_id", "name"). */
export function groupOfField(field: string): BuildingGroupId | null {
  const value = field.split(".")[0];
  return BUILDING_GROUPS.find((group) => VALUES_OF_GROUP[group].includes(value)) ?? null;
}

const numberOf = (values: TypicalBuildingValues, key: string) => (typeof values[key] === "number" ? (values[key] as number) : null);
const numberText = (value: number | null) => (value === null ? "?" : formattedNumber(value));
const roomOf = (values: TypicalBuildingValues) => (values.room === "box" ? "box" : "average");
const sharesOf = (values: TypicalBuildingValues) => (typeof values.wwr === "object" && values.wwr !== null ? values.wwr as Record<string, unknown> : {});
const shareOf = (shares: Record<string, unknown>, side: string) => (typeof shares[side] === "number" ? (shares[side] as number) : 0);
const roundedTo = (value: number, decimals: number) => Math.round(value * 10 ** decimals) / 10 ** decimals;

/**
 * The values with the other kind of room: the average room of depth d is the box 4d × 4d turned 45° whose north, east, south and
 * west shares are the NE, SE, SW and NW ones (typical_building.py); a box becomes the average room with its facade per m² of floor
 * (depth = width × length / (2 × (width + length))) and its shares turned the same way. The other kind's keys go: the service
 * refuses them.
 */
export function withRoom(values: TypicalBuildingValues, room: string): TypicalBuildingValues {
  if (roomOf(values) === room) return values;
  const { depth, width, length } = values;
  const shares = sharesOf(values);
  const shared = Object.fromEntries(Object.entries(values).filter(([key]) => !ROOM_KEYS.includes(key)));
  if (room === "box") {
    const side = typeof depth === "number" ? roundedTo(4 * depth, 2) : null;
    return { ...shared, room: "box", width: side, length: side, orientation: 45,
             wwr: { north: shareOf(shares, "ne"), east: shareOf(shares, "se"), south: shareOf(shares, "sw"), west: shareOf(shares, "nw") } };
  }
  const facadeDepth = typeof width === "number" && typeof length === "number" && width + length > 0
    ? roundedTo(width * length / (2 * (width + length)), 2) : null;
  return { ...shared, room: "average", depth: facadeDepth,
           wwr: { ne: shareOf(shares, "north"), se: shareOf(shares, "east"), sw: shareOf(shares, "south"), nw: shareOf(shares, "west") } };
}

/** The window shares as "windows 0.4 on each side" when they are all one, else "SW 0.56" (the sides with a window). */
function sharesSummary(values: TypicalBuildingValues): string {
  const shares = sharesOf(values);
  const sides = SIDES_OF_ROOM[roomOf(values)];
  const all = sides.map((side) => shareOf(shares, side));
  if (all.every((share) => share === 0)) return messages.noWindows;
  if (all.every((share) => share === all[0])) return messages.sameShareSummary(formattedNumber(all[0]));
  return sides.filter((side) => shareOf(shares, side) > 0).map((side) => `${messages.typicalBuildingSideInitials[side]} ${formattedNumber(shareOf(shares, side))}`).join(", ");
}

/** The line a closed group says: "Residential hours, 20 to 26 °C, gains 6 W/m²", "U 0.5 and 3 W/m²K, g 0.55, mass 250 kJ/m²K", ... */
export function buildingGroupSummary(group: BuildingGroupId, values: TypicalBuildingValues): string {
  const text = (key: string) => numberText(numberOf(values, key));
  switch (group) {
    case "use":
      return messages.useSummary(messages.scheduleWords[String(values.schedule)] ?? String(values.schedule), text("t_set_heating"), text("t_set_cooling"),
                                 text("gains_w_m2"));
    case "fabric": return messages.fabricSummary(text("u_wall"), text("u_window"), text("g_value"), text("mass_capacity_kj_m2k"));
    case "shading": {
      const factor = numberOf(values, "shading_factor");
      if (factor === null) return messages.noShading;
      return messages.shadingSummary(formattedNumber(factor), dayAndMonth(String(values.shading_start)), dayAndMonth(String(values.shading_end)));
    }
    case "room":
      return roomOf(values) === "average" ? messages.averageRoomSummary(text("depth"), text("height"), sharesSummary(values))
        : messages.boxRoomSummary(text("width"), text("length"), text("height"), text("orientation"), sharesSummary(values));
    case "roof_and_floor":
      return messages.roofAndFloorSummary(values.roof_exposed === true ? text("u_roof") : null, values.floor_exposed === true ? text("u_floor") : null);
    case "air": return messages.airSummary(text("ach_infiltration"));
  }
}

/** What the building is, by its library entry: none chosen, its name, "Changed from" it, or that it is gone from the library. */
export function libraryLineOf(stored: TypicalBuildingReply, library: readonly TypicalBuildingLibraryEntry[] | null): string {
  if (stored.state === "not_chosen") return messages.noBuildingChosen;
  const name = stored.library_name;
  if (name === null) return messages.notFromLibrary;
  if (library !== null && !library.some((entry) => entry.id === stored.library_id)) return messages.goneFromLibrary(name);
  return stored.changed ? messages.changedFrom(name) : name;
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
 * In a criterion's Settings: the library entry of the building as stored ("Changed from" it when it differs), the state of its
 * weights, and Edit building; without a building, that none is chosen and Choose building. A value refused in the sheet is not in
 * it: the run uses the stored building.
 */
export function TypicalBuildingBox({ building, sheetOpen, sheetId, onToggleSheet, editButton }: TypicalBuildingBoxProps) {
  const titleId = useId();
  const { stored } = building;
  return (
    <div className="typical-building-box" role="group" aria-labelledby={titleId}>
      <p id={titleId} className="typical-building-box-title">{messages.typicalBuilding}</p>
      {stored === null ? (
        building.readProblem === null ? <p className="step-reason">{messages.typicalBuildingReading}</p>
          : <p className="setting-error"><WarningIcon /><span>{building.readProblem}</span></p>
      ) : (
        <>
          <p className="typical-building-box-type">{libraryLineOf(stored, building.library)}</p>
          <p className="typical-building-box-state">
            {stored.state === "not_chosen" ? messages.chooseBuildingToRun
              : stored.state === "current" ? messages.typicalBuildingStates.current
                : `${messages.typicalBuildingStates[stored.state]}. ${messages.typicalBuildingRunCalculates}`}
          </p>
        </>
      )}
      <button ref={editButton} type="button" className="secondary-button" aria-expanded={sheetOpen} aria-controls={sheetOpen ? sheetId : undefined}
              onClick={onToggleSheet}>
        {stored?.state === "not_chosen" ? messages.chooseBuilding : messages.editBuilding}
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

/** A field's label row, its control, its error and its note. */
function BuildingField({ name, labelFor, labelId, error, errorId, note, children }: {
  name: string;
  /** The control the label names; absent, the label is the name of a group of controls (*labelId*). */
  labelFor?: string;
  labelId?: string;
  error: string | undefined;
  errorId?: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <div className="setting-field" data-building-field={name}>
      <div className="setting-label-row">
        {labelFor !== undefined ? <label htmlFor={labelFor} className="setting-label">{messages.typicalBuildingFields[name]}</label>
          : <span id={labelId} className="setting-label">{messages.typicalBuildingFields[name]}</span>}
      </div>
      {children}
      {error !== undefined && <FieldError id={errorId} message={error} />}
      {note !== undefined && <p className="setting-note">{note}</p>}
    </div>
  );
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
    <BuildingField name={name} labelFor={inputId} error={error} errorId={errorId} note={note}>
      <div className="setting-control">
        <LeaveSavedNumber id={inputId} value={value} mayBeEmpty={mayBeEmpty} placeholder={mayBeEmpty ? messages.noShading : undefined}
                          invalid={error !== undefined} describedBy={error === undefined ? undefined : errorId} disabled={disabled} onSave={onSave} />
        {unit !== undefined && <span className="setting-unit">{unit}</span>}
      </div>
    </BuildingField>
  );
}

interface BuildingChoiceProps {
  name: string;
  value: string;
  /** The options in order, with their names. */
  options: readonly string[];
  optionNames: Record<string, string>;
  note?: string;
  error: string | undefined;
  disabled: boolean;
  onChoose: (option: string) => void;
}

function BuildingChoice({ name, value, options, optionNames, note, error, disabled, onChoose }: BuildingChoiceProps) {
  const selectId = useId();
  return (
    <BuildingField name={name} labelFor={selectId} error={error} note={note}>
      <select id={selectId} className="setting-select" value={value} disabled={disabled} aria-invalid={error !== undefined}
              onChange={(event) => onChoose(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{optionNames[option] ?? option}</option>)}
      </select>
    </BuildingField>
  );
}

/** A two-way switch of the app (the Sun panel's, Which hours count's) with a label. */
function BuildingSwitch({ name, value, options, optionNames, error, disabled, onChoose }: Omit<BuildingChoiceProps, "note">) {
  const labelId = useId();
  return (
    <BuildingField name={name} labelId={labelId} error={error}>
      <div className="segmented-switch" role="group" aria-labelledby={labelId}>
        {options.map((option) => (
          <button key={option} type="button" aria-pressed={value === option} disabled={disabled} onClick={() => { if (option !== value) onChoose(option); }}>
            {optionNames[option]}
          </button>
        ))}
      </div>
    </BuildingField>
  );
}

/** An on/off value (a roof or floor exposed), the settings form's switch. */
function BuildingOnOff({ name, value, error, disabled, onChange }: { name: string; value: boolean; error: string | undefined; disabled: boolean;
                                                                     onChange: (value: boolean) => void }) {
  const inputId = useId();
  return (
    <BuildingField name={name} labelFor={inputId} error={error}>
      <input id={inputId} type="checkbox" role="switch" className="setting-switch" checked={value} disabled={disabled} aria-invalid={error !== undefined}
             onChange={(event) => onChange(event.target.checked)} />
    </BuildingField>
  );
}

/** A day of the year as "MM-DD": the day a number, the month a choice. The service checks the date (no 31 April). */
function BuildingDate({ name, value, error, disabled, onSave }: { name: string; value: string; error: string | undefined; disabled: boolean;
                                                                  onSave: (value: string) => void }) {
  const labelId = useId();
  const [month, day] = value.split("-").map(Number);
  const twoDigits = (number: number) => String(number).padStart(2, "0");
  return (
    <BuildingField name={name} labelId={labelId} error={error}>
      <div className="setting-control" role="group" aria-labelledby={labelId}>
        <LeaveSavedNumber ariaLabel={messages.typicalBuildingDay} short value={Number.isFinite(day) ? day : null} invalid={error !== undefined} disabled={disabled}
                          onSave={(newDay) => { if (newDay !== null) onSave(`${twoDigits(month)}-${twoDigits(newDay)}`); }} />
        <select className="setting-select" aria-label={messages.typicalBuildingMonth} value={String(month)} disabled={disabled} aria-invalid={error !== undefined}
                onChange={(event) => onSave(`${twoDigits(Number(event.target.value))}-${twoDigits(day)}`)}>
          {messages.monthAbbreviations.map((abbreviation, index) => <option key={abbreviation} value={String(index + 1)}>{abbreviation}</option>)}
        </select>
      </div>
    </BuildingField>
  );
}

// The colours of the chart: a diverging scale (ColorBrewer RdBu) from white, 0, to red, the sun offsets heating (+1), and to blue,
// it adds to cooling (-1); the hours with the sun down grey. The ends are dark enough to read on the panel and on the dark viewport.
export const OFFSETS_HEATING_STOPS = ["#ffffff", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"];
export const ADDS_TO_COOLING_STOPS = ["#ffffff", "#d1e5f0", "#92c5de", "#4393c3", "#2166ac"];
export const SUN_DOWN_COLOUR = "#c4c4c4";
// In the dark theme the scale starts from the dark panel, 0, and grows brighter with the effect, so that no effect is not a
// white block on the dark panel; the sun-down grey is a little lighter than the panel.
export const OFFSETS_HEATING_STOPS_DARK = ["#1e272e", "#4f2a30", "#8a2d35", "#d6604d", "#f4a582"];
export const ADDS_TO_COOLING_STOPS_DARK = ["#1e272e", "#22394f", "#2b5f8f", "#4393c3", "#92c5de"];
export const SUN_DOWN_COLOUR_DARK = "#3e474e";

const CHART_COLOURS = {
  light: { heating: OFFSETS_HEATING_STOPS, cooling: ADDS_TO_COOLING_STOPS, sunDown: SUN_DOWN_COLOUR },
  dark: { heating: OFFSETS_HEATING_STOPS_DARK, cooling: ADDS_TO_COOLING_STOPS_DARK, sunDown: SUN_DOWN_COLOUR_DARK },
};

const rgbOf = (hex: string) => [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));

/** The colour of an hour whose sun has *effect*, -1 (adds to cooling) to 1 (offsets heating), as [red, green, blue]. */
export function effectColour(effect: number, theme: AppTheme = "light"): number[] {
  const stops = effect >= 0 ? CHART_COLOURS[theme].heating : CHART_COLOURS[theme].cooling;
  const position = Math.min(1, Math.abs(Number.isFinite(effect) ? effect : 0)) * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(position));
  const [low, high] = [rgbOf(stops[index]), rgbOf(stops[index + 1])];
  return low.map((channel, at) => Math.round(channel + (high[at] - channel) * (position - index)));
}

/**
 * The effect of each hour's sun: benefit minus harm when the criterion counts harm, else benefit alone (the red half). A canvas of
 * 365 days across and 24 hours down (hour 0 of 1 January at the top left), the month initials under it, the hours beside it and
 * the legend. Null *weights*: they are being read.
 */
export function EffectChart({ weights, countsHarm }: { weights: TypicalBuildingWeightsReply | null; countsHarm: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const theme = useAppTheme();
  const colours = CHART_COLOURS[theme];
  useEffect(() => {
    const context = weights === null ? null : canvas.current?.getContext("2d") ?? null;
    if (context === null || weights === null) return;
    const image = context.createImageData(DAYS_IN_YEAR, HOURS_IN_DAY);
    const sunDown = rgbOf(colours.sunDown);
    for (let day = 0; day < DAYS_IN_YEAR; day++) {
      for (let hour = 0; hour < HOURS_IN_DAY; hour++) {
        const at = day * HOURS_IN_DAY + hour;
        const effect = (weights.benefit[at] ?? 0) - (countsHarm ? weights.harm[at] ?? 0 : 0);
        const [red, green, blue] = weights.sun_up[at] === 0 ? sunDown : effectColour(effect, theme);
        const offset = (hour * DAYS_IN_YEAR + day) * 4;
        image.data[offset] = red;
        image.data[offset + 1] = green;
        image.data[offset + 2] = blue;
        image.data[offset + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
  }, [weights, countsHarm, theme]);
  const ramp = countsHarm ? [...colours.cooling.slice(1).reverse(), ...colours.heating] : colours.heating;
  const legend = messages.effectLegend;
  return (
    <figure className="weights-chart">
      <figcaption className="weights-chart-title">{messages.effectChartTitle}</figcaption>
      <div className="weights-chart-plot">
        <div className="weights-chart-hours" aria-hidden="true"><span>0</span><span>12</span><span>24</span></div>
        <canvas ref={canvas} className="weights-chart-canvas" width={DAYS_IN_YEAR} height={HOURS_IN_DAY} role="img" aria-label={messages.effectChartLabel(countsHarm)} />
      </div>
      <div className="weights-chart-months" aria-hidden="true">
        {messages.monthInitials.map((initial, index) => <span key={index} style={{ flexGrow: DAYS_IN_MONTH[index] }}>{initial}</span>)}
      </div>
      <div className="weights-chart-legend" aria-hidden="true">
        <span>{countsHarm ? legend.cooling : legend.none}</span>
        <span className="weights-chart-ramp" style={{ background: `linear-gradient(to right, ${ramp.join(", ")})` }} />
        <span>{legend.heating}</span>
        <span className="weights-chart-sun-down"><span className="weights-chart-swatch" style={{ background: colours.sunDown }} />{legend.sunDown}</span>
      </div>
      {weights === null && <p className="step-reason">{messages.weightsChartWaits}</p>}
    </figure>
  );
}

/** A dialog of the library open over the sheet: Save as new, or Rename or Delete of an own entry. */
type LibraryDialog = { kind: "save_as_new" } | { kind: "rename" | "delete"; entry: TypicalBuildingLibraryEntry };

interface LibraryProps {
  building: TypicalBuildingHook;
  stored: TypicalBuildingReply;
  library: readonly TypicalBuildingLibraryEntry[];
  open: boolean;
  onToggle: () => void;
  disabled: boolean;
  onDialog: (dialog: LibraryDialog) => void;
}

/**
 * The groups of the library in order: the examples' groups as the service names them, in the order of their first entry, then the
 * user's own entries (group null) as Your buildings; a group without entries is left out.
 */
export function libraryGroupsOf(library: readonly TypicalBuildingLibraryEntry[]): { name: string; entries: TypicalBuildingLibraryEntry[] }[] {
  const exampleGroups = [...new Set(library.flatMap((entry) => (entry.group === null ? [] : [entry.group])))];
  return [...exampleGroups.map((name) => ({ name, entries: library.filter((entry) => entry.group === name) })),
          { name: messages.ownBuildings, entries: library.filter((entry) => entry.group === null) }].filter((group) => group.entries.length > 0);
}

/** The library section: the entry the building is (or came from) in its line; open, the entries by group to choose from. */
function Library({ building, stored, library, open, onToggle, disabled, onDialog }: LibraryProps) {
  const source = library.find((entry) => entry.id === stored.library_id)?.source ?? null;
  return (
    <PanelSection id="library" title={messages.typicalBuildingLibrary} summary={libraryLineOf(stored, library)} open={open} onToggle={onToggle} problem={false}
                  alwaysShown={source !== null && <p className="typical-building-source">{source}</p>}>
      <p className="setting-note">{stored.state === "not_chosen" ? messages.libraryChooseFirst : messages.libraryChooseNote}</p>
      {libraryGroupsOf(library).map(({ name, entries }) => {
        return (
          <div key={name} className="typical-building-library-group">
            <p className="typical-building-library-group-name">{name}</p>
            <ul className="typical-building-library-list">
              {entries.map((entry) => {
                const inUse = entry.id === stored.library_id && !stored.changed;
                return (
                  <li key={entry.id} data-library-entry={entry.id}>
                    <button type="button" className="period-preset typical-building-library-entry" aria-pressed={inUse} disabled={disabled}
                            onClick={() => { if (!inUse) building.choose(entry); }}>
                      {entry.name}
                    </button>
                    {!entry.read_only && (
                      <>
                        <button type="button" className="link-button" aria-label={messages.renameLibraryEntry(entry.name)} disabled={disabled}
                                onClick={() => onDialog({ kind: "rename", entry })}>
                          {messages.rename}
                        </button>
                        <button type="button" className="link-button" aria-label={messages.deleteLibraryEntry(entry.name)} disabled={disabled}
                                onClick={() => onDialog({ kind: "delete", entry })}>
                          {messages.delete}
                        </button>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </PanelSection>
  );
}

interface TypicalBuildingSheetProps {
  id: string;
  building: TypicalBuildingHook;
  /** The criterion counts harm (include_harm): the chart shows benefit minus harm, red and blue. */
  includesHarm: boolean;
  hasWeatherFile: boolean;
  /** Why the building cannot be changed now (a run of the project); null when it can. */
  disabledReason: string | null;
  onClose: () => void;
}

export function TypicalBuildingSheet({ id, building, includesHarm, hasWeatherFile, disabledReason, onClose }: TypicalBuildingSheetProps) {
  const { values, stored, library, fieldErrors, weights } = building;
  const sharesLabelId = useId();
  const sharesErrorId = useId();
  const reasonId = useId();
  const sheet = useRef<HTMLDivElement>(null);
  const [openGroups, setOpenGroups] = useState<ReadonlySet<BuildingGroupId | "library">>(new Set());
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [dialog, setDialog] = useState<LibraryDialog | null>(null);
  // The control that opened a dialog, which the focus goes back to (or the library's header, when it went with an entry).
  const dialogOpener = useRef<HTMLElement | null>(null);
  const disabled = disabledReason !== null;
  const read = stored !== null && library !== null;
  const notChosen = stored?.state === "not_chosen";

  // The window changes shape (reading, library only, the full window) with different elements, so the control that had the focus (the
  // entry just chosen) is gone: the focus goes to the title, so it stays in the window and Escape and Tab still reach it.
  const shape = !read ? "reading" : notChosen || values === null ? "library" : "full";
  const shapeBefore = useRef(shape);
  useLayoutEffect(() => {
    if (shapeBefore.current === shape) return;
    shapeBefore.current = shape;
    const window = sheet.current?.closest('[role="dialog"]');
    if (window !== undefined && window !== null && !window.contains(document.activeElement)) window.querySelector<HTMLElement>("h2")?.focus();
  }, [shape]);
  // Without a building the library opens, to choose one from.
  useLayoutEffect(() => {
    if (notChosen) setOpenGroups((open) => new Set([...open, "library"]));
  }, [notChosen]);
  // A group with a field the last save refused opens, before the page is drawn, and Advanced with it when it is one of its groups.
  const groupsWithErrors = BUILDING_GROUPS.filter((group) => Object.keys(fieldErrors).some((field) => groupOfField(field) === group));
  useLayoutEffect(() => {
    if (groupsWithErrors.some((group) => !openGroups.has(group))) setOpenGroups((open) => new Set([...open, ...groupsWithErrors]));
    if (groupsWithErrors.some((group) => ADVANCED_GROUPS.includes(group))) setAdvancedOpen(true);
  }, [groupsWithErrors.join(" ")]);
  // The weights of the last calculation, read while the sheet is open.
  useEffect(() => {
    if (stored !== null && stored.state !== "missing" && stored.state !== "not_chosen" && weights === null) building.readWeights();
  }, [stored?.state, weights]);

  const toggleGroup = (group: BuildingGroupId | "library") => setOpenGroups((open) => {
    const next = new Set(open);
    if (!next.delete(group)) next.add(group);
    return next;
  });
  const openDialog = (next: LibraryDialog) => {
    dialogOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setDialog(next);
  };
  const closeDialog = () => {
    setDialog(null);
    const opener = dialogOpener.current;
    requestAnimationFrame(() => {
      if (opener !== null && opener.isConnected) opener.focus();
      else sheet.current?.querySelector<HTMLButtonElement>('[data-section="library"] .panel-section-header')?.focus();
    });
  };

  // The window: the frame of the project dialogs, wide, with × and its title in focus. Each of the three states below is one, so the
  // window stays open while the building is read. It is drawn into the page's body: inside the criterion panel, which narrow windows
  // make a stacking context under the view's overlays, its dimmed backdrop could not cover them.
  const windowOf = (content: ReactNode) => createPortal(
    <DialogFrame title={messages.typicalBuilding} busy={false} onClose={onClose} wide closeLabel={messages.closeTypicalBuilding} titleTakesFocus>
      <div ref={sheet} id={id} className="typical-building-sheet">{content}</div>
    </DialogFrame>,
    document.body,
  );
  if (!read) {
    return windowOf(building.readProblem === null ? <p className="step-reason">{messages.typicalBuildingReading}</p> : <FieldError message={building.readProblem} />);
  }
  const dialogs = (
    <>
      {dialog?.kind === "save_as_new" && (
        <LibraryNameDialog title={messages.saveAsNew} name="" confirmLabel={messages.save} onSave={building.saveAsNew} onClose={closeDialog} />
      )}
      {dialog?.kind === "rename" && (
        <LibraryNameDialog title={messages.renameLibraryEntry(dialog.entry.name)} name={dialog.entry.name} confirmLabel={messages.rename}
                           onSave={(name) => building.renameEntry(dialog.entry.id, name)} onClose={closeDialog} />
      )}
      {dialog?.kind === "delete" && (
        <DeleteLibraryEntryDialog name={dialog.entry.name} onDelete={() => building.deleteEntry(dialog.entry.id)} onClose={closeDialog} />
      )}
    </>
  );
  const librarySection = (
    <div className="typical-building-groups">
      <Library building={building} stored={stored} library={library} open={openGroups.has("library")} onToggle={() => toggleGroup("library")}
               disabled={disabled} onDialog={openDialog} />
    </div>
  );
  if (notChosen || values === null) {
    return windowOf(
      <>
        {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
        {librarySection}
        {building.problem !== null && <p className="setting-error" role="alert"><WarningIcon /><span>{building.problem}</span></p>}
        {dialogs}
      </>,
    );
  }

  const change = (key: string, value: unknown) => building.change({ ...values, [key]: value });
  const number = (key: string) => numberOf(values, key);
  const units = messages.typicalBuildingUnits;
  const notes = messages.typicalBuildingNotes;
  const field = (key: string, unit?: string, note?: string, mayBeEmpty = false) => (
    <BuildingNumber name={key} unit={unit} note={note} value={number(key)} error={fieldErrors[key]} mayBeEmpty={mayBeEmpty} disabled={disabled}
                    onSave={(value) => change(key, value)} />
  );
  const choice = (key: string, options: readonly string[], optionNames: Record<string, string>, note?: string) => (
    <BuildingChoice name={key} value={String(values[key])} options={options} optionNames={optionNames} note={note} error={fieldErrors[key]}
                    disabled={disabled} onChoose={(option) => change(key, option)} />
  );
  const room = roomOf(values);
  const sides = SIDES_OF_ROOM[room];
  const shares = sharesOf(values);
  const shareErrors = [fieldErrors.wwr, ...sides.flatMap((side) => {
    const error = fieldErrors[`wwr.${side}`];
    return error === undefined ? [] : [`${messages.typicalBuildingSides[side]}: ${error}`];
  })].filter((error) => error !== undefined);
  const content: Record<BuildingGroupId, ReactNode> = {
    use: (
      <>
        {choice("schedule", SCHEDULES, messages.schedules, notes.schedule)}
        {field("t_set_heating", units.celsius)}{field("t_set_cooling", units.celsius)}
        {field("gains_w_m2", units.wattsPerSquareMetre, notes.gains_w_m2)}{field("fresh_air_m3h_m2", units.airPerFloor, notes.fresh_air_m3h_m2)}
        {field("heat_recovery", undefined, notes.heat_recovery)}
      </>
    ),
    fabric: (
      <>
        {field("u_wall", units.uValue)}{field("u_window", units.uValue)}{field("g_value", undefined, notes.g_value)}
        {field("mass_capacity_kj_m2k", units.capacity, notes.mass_capacity_kj_m2k)}
      </>
    ),
    shading: (
      <>
        {field("shading_factor", undefined, notes.shading_factor, true)}
        {number("shading_factor") !== null && (
          <>
            <BuildingDate name="shading_start" value={String(values.shading_start)} error={fieldErrors.shading_start} disabled={disabled}
                          onSave={(date) => change("shading_start", date)} />
            <BuildingDate name="shading_end" value={String(values.shading_end)} error={fieldErrors.shading_end} disabled={disabled}
                          onSave={(date) => change("shading_end", date)} />
            <p className="setting-note">{notes.shading_period}</p>
          </>
        )}
      </>
    ),
    room: (
      <>
        <BuildingSwitch name="room" value={room} options={ROOMS} optionNames={messages.roomKinds} error={fieldErrors.room} disabled={disabled}
                        onChoose={(kind) => building.change(withRoom(values, kind))} />
        {room === "average" && <p className="setting-note">{notes.average}</p>}
        {field("height", units.metres)}
        {room === "average" ? field("depth", units.metres)
          : <>{field("width", units.metres)}{field("length", units.metres)}{field("orientation", units.degrees, notes.orientation)}</>}
        <div className="setting-field" data-building-field="wwr" role="group" aria-labelledby={sharesLabelId}>
          <div className="setting-label-row"><span id={sharesLabelId} className="setting-label">{messages.typicalBuildingFields.wwr}</span></div>
          <div className="setting-angle-grid">
            {sides.map((side) => (
              <label key={side} className="setting-angle-direction">
                <span>{messages.typicalBuildingSideInitials[side]}</span>
                <LeaveSavedNumber ariaLabel={messages.typicalBuildingSides[side]} short value={shareOf(shares, side)}
                                  invalid={fieldErrors[`wwr.${side}`] !== undefined || fieldErrors.wwr !== undefined}
                                  describedBy={shareErrors.length > 0 ? sharesErrorId : undefined} disabled={disabled}
                                  onSave={(share) => change("wwr", { ...shares, [side]: share ?? 0 })} />
              </label>
            ))}
          </div>
          {shareErrors.length > 0 && <div id={sharesErrorId}>{shareErrors.map((error) => <FieldError key={error} message={error} />)}</div>}
          <p className="setting-note">{notes.wwr}</p>
        </div>
      </>
    ),
    roof_and_floor: (
      <>
        <BuildingOnOff name="roof_exposed" value={values.roof_exposed === true} error={fieldErrors.roof_exposed} disabled={disabled}
                       onChange={(exposed) => change("roof_exposed", exposed)} />
        {values.roof_exposed === true && field("u_roof", units.uValue)}
        <BuildingOnOff name="floor_exposed" value={values.floor_exposed === true} error={fieldErrors.floor_exposed} disabled={disabled}
                       onChange={(exposed) => change("floor_exposed", exposed)} />
        {values.floor_exposed === true && field("u_floor", units.uValue)}
        <p className="setting-note">{notes.roof_and_floor}</p>
      </>
    ),
    air: field("ach_infiltration", units.airChanges, notes.ach_infiltration),
  };
  const group = (id: BuildingGroupId) => (
    <PanelSection key={id} id={id} title={messages.typicalBuildingGroups[id]} summary={buildingGroupSummary(id, values)} open={openGroups.has(id)}
                  onToggle={() => toggleGroup(id)} problem={groupsWithErrors.includes(id)}>
      {content[id]}
    </PanelSection>
  );

  // A refusal of a field the groups do not show (the library entry, the service's own checks), said over the groups.
  const otherErrors = Object.entries(fieldErrors).filter(([name]) => groupOfField(name) === null).map(([, message]) => message);
  const hasErrors = Object.keys(fieldErrors).length > 0;
  const entry = library.find((each) => each.id === stored.library_id) ?? null;
  const ownEntry = entry !== null && !entry.read_only;
  const calculateBlocker = building.calculating ? null : disabledReason ?? (!hasWeatherFile ? messages.calculateNeedsWeatherFile
    : hasErrors ? messages.calculateWaitsForValues : null);
  const outOfDate = stored.state === "out_of_date";
  const oneDecimal = (value: number | null | undefined) => (value === null || value === undefined ? "?" : formatNumber(value, undefined, 1));
  const daytimeHours = weights === null ? null : weights.sun_up.reduce((count, up) => count + (up === 0 ? 0 : 1), 0);

  return windowOf(
    <>
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      <div className="typical-building-window-columns">
        <div className="typical-building-window-values">
          {librarySection}
          <div className="typical-building-library-actions">
            <div className="typical-building-library-buttons">
              <button type="button" className="secondary-button" disabled={disabled || hasErrors || !ownEntry || !stored.changed} onClick={building.saveToLibrary}>
                {messages.saveToLibrary}
              </button>
              <button type="button" className="secondary-button" disabled={disabled || hasErrors} onClick={() => openDialog({ kind: "save_as_new" })}>
                {messages.saveAsNew}
              </button>
            </div>
            {entry !== null && entry.read_only && stored.changed && <p className="setting-note">{messages.exampleCannotChange(entry.name)}</p>}
          </div>
          {otherErrors.map((error) => <FieldError key={error} message={error} />)}
          <div className="typical-building-groups">
            {BASIC_GROUPS.map(group)}
          </div>
          <div className="typical-building-advanced">
            <button type="button" className="panel-section-header typical-building-advanced-toggle" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((open) => !open)}>
              {messages.typicalBuildingAdvanced}
              {!advancedOpen && groupsWithErrors.some((each) => ADVANCED_GROUPS.includes(each)) && (
                <span className="panel-section-summary-problem"><WarningIcon /><span className="visually-hidden">{messages.sectionNeedsAttention}</span></span>
              )}
            </button>
            {advancedOpen && <div className="typical-building-groups">{ADVANCED_GROUPS.map(group)}</div>}
          </div>
        </div>
        <div className="typical-building-window-results">
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
                <EffectChart weights={weights} countsHarm={includesHarm} />
                <dl className="typical-building-numbers">
                  <div><dt>{messages.heatingDemand}</dt><dd>{messages.demandPerYear(oneDecimal(stored.heating_kwh_m2))}</dd></div>
                  <div><dt>{messages.coolingDemand}</dt><dd>{messages.demandPerYear(oneDecimal(stored.cooling_kwh_m2))}</dd></div>
                  <div>
                    <dt>{messages.countedHours}<SettingTooltip settingLabel={messages.countedHours} help={messages.countedHoursNote} /></dt>
                    <dd>{stored.counted_hours == null ? "?" : daytimeHours === null ? groupedDigits(stored.counted_hours)
                      : messages.countedHoursOfDaytime(stored.counted_hours, daytimeHours)}</dd>
                  </div>
                </dl>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="project-dialog-buttons">
        <button type="button" className="primary-button" onClick={onClose}>{messages.done}</button>
      </div>
      {dialogs}
    </>,
  );
}

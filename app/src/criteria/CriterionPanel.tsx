// A criterion's panel (spec 7.1, 7.2), in four folded sections (PanelSection): Test surfaces (ProtectsBox), Mode (the tiles of
// ModeStep, with the weather box and the values a mode change reset), Settings (the analysis settings that are criterion keys,
// SettingsStep) and Carving rule (CarvingStep, put together in result_steps.tsx). Run analysis is in the bar pinned under the step list
// (CriteriaRunBar). The shared settings are in Site and grid. The open sections are the workspace's (usePanelSections); a section opens
// when something it shows appears: no test surfaces or the weather box under the tiles (of a criterion that is on), a field with an
// error of the criterion's save, or the values reset under the tiles. A criterion just selected shows them all as new. A criterion
// that is off needs neither test surfaces nor a weather file, and its closed Carving rule reads Off. The notice of a new weather file
// is under the Settings header, open or closed. In Solar usefulness, Settings starts with Which hours count: Cold hours (the balance
// temperature rule) or Energy-weighted, which hides the balance temperature and shows the typical building's box, whose Edit
// building opens its window (TypicalBuildingSheet).
import { useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import type { ColdPeriodState, Hemisphere } from "../settings_form/analysis_period";
import { shownValue, type FormState } from "../settings_form/form_state";
import { BALANCE_TEMPERATURE_FIELDS } from "../settings_form/presentation";
import { SettingTooltip } from "../settings_form/SettingTooltip";
import { ModeStep } from "../steps/ModeStep";
import { useDialogRequest } from "../steps/ProjectDialogs";
import { SettingsStep, WeatherChangeRegion, type WeatherChangeNoticeContent } from "../steps/SettingsStep";
import { PanelSection, type PanelSections } from "./PanelSection";
import { ProtectsBox } from "./ProtectsBox";
import { TypicalBuildingBox, TypicalBuildingSheet } from "./TypicalBuildingSheet";
import type { TypicalBuildingHook } from "./use_typical_building";
import {
  carvingRuleSummary, criterionSettingsSummary, modeSummary, PANEL_SECTIONS, settingsToFixBySection, testSurfacesSummary, type PanelSectionId,
} from "./section_summaries";
import "../steps/steps.css";

export interface CriterionPanelProps extends PanelSections {
  /** The criterion's test surface files, with their triangle counts. */
  testSurfaces: InputFileInfo[];
  /** Whether the chain uses the criterion; while it is off it needs no test surfaces nor weather file. Absent: true. */
  criterionOn?: boolean;
  /** The files of the test surfaces the 3D view cannot draw. */
  testSurfaceDrawingProblems?: string[];
  onAddTestSurfaces: (files: File[]) => Promise<string[]>;
  onRemoveTestSurface: (fileName: string) => Promise<string | null>;
  /** The stored test surface files other criteria use and this one does not, offered for use (several criteria only). */
  otherTestSurfaces?: string[];
  onUseTestSurface?: (fileName: string) => Promise<string | null>;
  /** The settings the panel shows: the criterion's, with the shared ones they are read with. */
  form: FormState;
  /** The messages of the criterion's last save that name no setting. */
  stepErrors: readonly string[];
  criterionKeys: ReadonlySet<string>;
  onChange: (values: Record<string, unknown>) => void;
  onChooseMode: (mode: string) => void;
  /** Why the criterion cannot be changed now (a run is in progress); null when it can. */
  disabledReason: string | null;
  /** The weather box under the tiles, when the criterion's mode needs a weather file the project lacks. */
  weatherDropZone: ReactNode;
  inputRoles?: readonly string[];
  coldPeriod?: ColdPeriodState | null;
  hemisphere?: Hemisphere;
  weatherChangeNotice?: WeatherChangeNoticeContent | null;
  /** The criterion's carving rule, or why it waits for an analysis. */
  carvingRule: ReactNode;
  /** The unit of the mode's scores, for a cutoff in the carving rule's summary; absent: none. */
  scoreUnit?: string;
  /** Which hours count and the typical building, shown in Solar usefulness; absent: neither is shown. */
  hoursCounted?: HoursCountedProps;
}

export interface HoursCountedProps {
  /** The criterion counts its hours by the typical building (Energy-weighted), not by the cold hours rule. */
  energyWeighted: boolean;
  /** Saves Which hours count; resolves with why it was refused, or null. */
  onChange: (energyWeighted: boolean) => Promise<string | null>;
  building: TypicalBuildingHook;
  hasWeatherFile: boolean;
}

const CHOICES = [false, true] as const;
const BALANCE_TEMPERATURE: readonly string[] = BALANCE_TEMPERATURE_FIELDS;

interface WhichHoursCountProps {
  hoursCounted: HoursCountedProps;
  disabled: boolean;
  sheetOpen: boolean;
  sheetId: string;
  onToggleSheet: () => void;
  editButton: RefObject<HTMLButtonElement | null>;
}

/** The two-way switch of Solar usefulness, Cold hours or Energy-weighted, and under it, energy-weighted, the typical building's box. */
function WhichHoursCount({ hoursCounted, disabled, sheetOpen, sheetId, onToggleSheet, editButton }: WhichHoursCountProps) {
  const labelId = useId();
  const { problem, send } = useDialogRequest(() => {});
  const { energyWeighted } = hoursCounted;
  return (
    <div className="setting-field hours-counted" data-setting="energy_weighted">
      <div className="setting-label-row">
        <span id={labelId} className="setting-label">{messages.whichHoursCount}</span>
        <SettingTooltip settingLabel={messages.whichHoursCount} help={messages.whichHoursCountHelp} />
      </div>
      <div className="segmented-switch" role="group" aria-labelledby={labelId}>
        {CHOICES.map((choice) => (
          <button key={String(choice)} type="button" aria-pressed={energyWeighted === choice} disabled={disabled}
                  onClick={() => { if (choice !== energyWeighted) void send(() => hoursCounted.onChange(choice)); }}>
            {messages.whichHoursCountChoices[choice ? "energy_weighted" : "cold_hours"]}
          </button>
        ))}
      </div>
      {problem !== null && <p className="setting-error" role="alert">{problem}</p>}
      {energyWeighted && (
        <TypicalBuildingBox building={hoursCounted.building} sheetOpen={sheetOpen} sheetId={sheetId} onToggleSheet={onToggleSheet} editButton={editButton} />
      )}
    </div>
  );
}

export function CriterionPanel(props: CriterionPanelProps) {
  const { form, criterionKeys, onChange, disabledReason, openSections, onOpenSections } = props;
  // Which hours count, in Solar usefulness; energy-weighted, the balance temperature is not read, and is not shown, counted or summed up.
  const hoursCounted = form.mode === "benefit" ? props.hoursCounted : undefined;
  const energyWeighted = hoursCounted?.energyWeighted ?? false;
  const readKeys = energyWeighted ? new Set([...criterionKeys].filter((name) => !BALANCE_TEMPERATURE.includes(name))) : criterionKeys;
  const toFix = settingsToFixBySection({ fieldErrors: form.fieldErrors, stepErrors: props.stepErrors }, readKeys);
  const criterionOn = props.criterionOn ?? true;
  const needsWeatherFile = criterionOn && props.weatherDropZone !== null && props.weatherDropZone !== undefined && props.weatherDropZone !== false;
  // What a section has to fix: its summary is in the warning colour.
  const problems: Record<PanelSectionId, boolean> = {
    test_surfaces: criterionOn && props.testSurfaces.length === 0,
    mode: needsWeatherFile || toFix.mode !== undefined,
    settings: toFix.settings !== undefined,
    carving: toFix.carving !== undefined,
  };
  const valuesReset = (form.valuesResetByModeChange?.settings.length ?? 0) > 0;
  const [sheetOpen, setSheetOpen] = useState(false);
  // Cold hours (or another mode) ends the sheet; Energy-weighted again does not bring it back.
  if (sheetOpen && !energyWeighted) setSheetOpen(false);
  const sheetId = useId();
  const editButton = useRef<HTMLButtonElement>(null);
  const closeSheet = () => {
    setSheetOpen(false);
    editButton.current?.focus();
  };
  // A section opens when something it shows appears, before the page is drawn; the user may close it again.
  const calling = PANEL_SECTIONS.filter((id) => problems[id] || (id === "mode" && valuesReset));
  const calledBefore = useRef<ReadonlySet<PanelSectionId>>(new Set());
  useLayoutEffect(() => {
    const appeared = calling.filter((id) => !calledBefore.current.has(id));
    calledBefore.current = new Set(calling);
    if (appeared.length > 0) onOpenSections(appeared);
  }, [calling.join(" ")]);

  const summaries: Record<PanelSectionId, string> = {
    test_surfaces: testSurfacesSummary(props.testSurfaces.map((file) => file.name)),
    mode: needsWeatherFile ? messages.modeNeedsWeatherFileSummary(modeSummary(form.mode)) : modeSummary(form.mode),
    settings: energyWeighted ? messages.energyWeightedSummary(criterionSettingsSummary(form, readKeys)) : criterionSettingsSummary(form, readKeys),
    carving: criterionOn ? carvingRuleSummary(form, props.scoreUnit) : messages.criterionOff,
  };
  // A closed section with settings to fix says how many, as a step row does.
  const section = (id: PanelSectionId, children: ReactNode, alwaysShown?: ReactNode) => {
    const settingsToFix = toFix[id];
    return (
      <PanelSection id={id} title={messages.panelSectionTitles[id]} open={openSections.has(id)} onToggle={() => props.onToggleSection(id)}
                    summary={settingsToFix === undefined ? summaries[id] : messages.settingsToFix(settingsToFix)} problem={problems[id]}
                    alwaysShown={alwaysShown}>
        {children}
      </PanelSection>
    );
  };
  return (
    <div className="criterion-panel">
      {section("test_surfaces", (
        <ProtectsBox files={props.testSurfaces} mode={form.mode} onAddFiles={props.onAddTestSurfaces} onRemoveFile={props.onRemoveTestSurface}
                     disabledReason={disabledReason} drawingProblems={props.testSurfaceDrawingProblems} otherFiles={props.otherTestSurfaces}
                     onUseFile={props.onUseTestSurface} />
      ))}
      {section("mode", (
        // The field of the mode, which a link to the mode focuses: its chosen tile.
        <div className="criterion-mode" data-setting="mode">
          <ModeStep mode={form.mode} onChoose={props.onChooseMode} disabledReason={disabledReason} valuesReset={form.valuesResetByModeChange}
                    weatherDropZone={props.weatherDropZone} showsDisabledReason={false} />
        </div>
      ))}
      {section("settings", (
        <>
          {hoursCounted !== undefined && (
            <WhichHoursCount hoursCounted={hoursCounted} disabled={disabledReason !== null} sheetOpen={sheetOpen} sheetId={sheetId}
                             onToggleSheet={() => setSheetOpen((open) => !open)} editButton={editButton} />
          )}
          <SettingsStep form={form} stepErrors={props.stepErrors} onChange={onChange} disabledReason={disabledReason} inputRoles={props.inputRoles}
                        coldPeriod={props.coldPeriod} hemisphere={props.hemisphere} coldPeriodForColdHours={energyWeighted}
                        settingShown={(name) => readKeys.has(name)}
                        showsDisabledReason={false} />
        </>
      ), (
        <WeatherChangeRegion notice={props.weatherChangeNotice ?? null} form={form} onChange={onChange} disabled={disabledReason !== null} />
      ))}
      {section("carving", <div className="criterion-carving">{props.carvingRule}</div>)}
      {hoursCounted !== undefined && sheetOpen && (
        <TypicalBuildingSheet id={sheetId} building={hoursCounted.building} includesHarm={shownValue(form, "include_harm") === true}
                              hasWeatherFile={hoursCounted.hasWeatherFile} disabledReason={disabledReason} onClose={closeSheet} />
      )}
    </div>
  );
}

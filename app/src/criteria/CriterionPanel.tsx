// A criterion's panel (spec 7.1, 7.2): what it protects (ProtectsBox), its mode (the tiles of ModeStep), its own settings (the
// analysis settings that are criterion keys, SettingsStep), its carving rule (CarvingStep, put together in result_steps.tsx) and
// Run analysis, in that order. The shared settings are in Site and grid.
import { useState, type ReactNode } from "react";
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import type { ColdPeriodState, Hemisphere } from "../settings_form/analysis_period";
import type { FormState } from "../settings_form/form_state";
import { ModeStep } from "../steps/ModeStep";
import { SettingsStep, type WeatherChangeNoticeContent } from "../steps/SettingsStep";
import { ProtectsBox } from "./ProtectsBox";
import "../steps/steps.css";

export interface CriterionPanelProps {
  /** The criterion's test surface files, with their triangle counts. */
  testSurfaces: InputFileInfo[];
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
  /** Run analysis, with the progress of its run. */
  runAnalysis: ReactNode;
}

/**
 * The carving rule of the only criterion when it is bypassed (a project.json edited by hand): with no card there is no bypass switch,
 * so the panel turns it on. *onTurnOn* resolves with why it could not, or null.
 */
export function TurnOnCriterion({ onTurnOn, disabledReason }: { onTurnOn: () => Promise<string | null>; disabledReason: string | null }) {
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <div className="criterion-turn-on">
      <button type="button" className="secondary-button" disabled={disabledReason !== null} onClick={async () => setProblem(await onTurnOn())}>
        {messages.turnOnCriterion}
      </button>
      {problem !== null && <p className="setting-error" role="alert">{problem}</p>}
    </div>
  );
}

export function CriterionPanel(props: CriterionPanelProps) {
  const { form, criterionKeys, onChange, disabledReason } = props;
  return (
    <div className="criterion-panel">
      <ProtectsBox files={props.testSurfaces} mode={form.mode} onAddFiles={props.onAddTestSurfaces} onRemoveFile={props.onRemoveTestSurface}
                   disabledReason={disabledReason} drawingProblems={props.testSurfaceDrawingProblems} otherFiles={props.otherTestSurfaces}
                   onUseFile={props.onUseTestSurface} />
      <ModeStep mode={form.mode} onChoose={props.onChooseMode} disabledReason={disabledReason} valuesReset={form.valuesResetByModeChange}
                weatherDropZone={props.weatherDropZone} showsDisabledReason={false} />
      <SettingsStep form={form} stepErrors={props.stepErrors} onChange={onChange} disabledReason={disabledReason} inputRoles={props.inputRoles}
                    coldPeriod={props.coldPeriod} hemisphere={props.hemisphere} weatherChangeNotice={props.weatherChangeNotice}
                    settingShown={(name) => criterionKeys.has(name)} showsDisabledReason={false} />
      <div className="criterion-carving">{props.carvingRule}</div>
      <div className="criterion-run">{props.runAnalysis}</div>
    </div>
  );
}

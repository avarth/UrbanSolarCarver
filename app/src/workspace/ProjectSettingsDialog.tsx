// The project settings (UX 5.4, 11): the analysis settings every criterion shares, those that are not criterion keys (GET
// criterion-keys): north, the surroundings switch, the voxel size with the grid budget line under it, and, folded, the rays per batch.
// The Settings button in the top bar opens the window, in every workspace of an open project; its tooltip gives North and the voxel
// size, and it carries the "!" of a step row while a shared setting is to fix (settingsToFixByPlace). The window is the frame of the
// project dialogs, with × and Done; each change is saved as the form saves (no Apply), and while a run is in progress the fields
// wait and say why. A setting whose inputs the project has no files for (Account for context blocking without surroundings or
// terrain) is greyed out with the reason. The window ends with links to the steps that hold the other shared settings. Run analysis
// is in the Criteria step; its reason names Settings when a setting here is to fix, with Open settings beside it.
import { createPortal } from "react-dom";
import type { Ref } from "react";
import { messages } from "../messages";
import type { FormState } from "../settings_form/form_state";
import { SettingsStep } from "../settings_form/SettingsStep";
import type { StepName } from "../stages";
import { DialogFrame } from "../common/dialogs";
import "../theme/panels.css";

function GearIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
    </svg>
  );
}

interface ProjectSettingsButtonProps {
  /** "North 10°, 0.5 m voxels" (projectSettingsSummary). */
  summary: string;
  /** The shared settings to fix: the button shows "!" and names the count. */
  settingsToFix: number;
  open: boolean;
  onOpen: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
}

export function ProjectSettingsButton({ summary, settingsToFix, open, onOpen, buttonRef }: ProjectSettingsButtonProps) {
  return (
    <button ref={buttonRef} type="button" className="top-bar-settings-button" title={messages.projectSettingsHint(summary)} aria-haspopup="dialog"
            aria-expanded={open} aria-label={settingsToFix > 0 ? messages.projectSettingsButtonWithFixes(settingsToFix) : undefined} onClick={onOpen}>
      {settingsToFix > 0 ? <span className="step-mark step-mark-error" aria-hidden="true">!</span> : <GearIcon />}
      {messages.projectSettingsButton}
    </button>
  );
}

interface ProjectSettingsDialogProps {
  /** The two forms as one (useBothForms): the window draws the shared settings of it. */
  form: FormState;
  /** The messages of the shared settings' last save that name no setting. */
  stepErrors: readonly string[];
  criterionKeys: ReadonlySet<string>;
  onChange: (values: Record<string, unknown>) => void;
  /** Why the settings cannot be changed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The input roles the project has files for: Account for context blocking needs surroundings or terrain. */
  inputRoles: readonly string[];
  onClose: () => void;
  /** Closes the window and opens a step that holds other shared settings (Envelope and massing, Export). */
  onOpenStep: (step: StepName) => void;
  /** The element of the window's content, where a setting to focus is looked for. */
  contentRef?: Ref<HTMLDivElement>;
}

const STEPS_WITH_OTHER_SHARED_SETTINGS: readonly StepName[] = ["envelope_and_massing", "export"];

export function ProjectSettingsDialog({ form, stepErrors, criterionKeys, onChange, disabledReason, inputRoles, onClose, onOpenStep,
                                        contentRef }: ProjectSettingsDialogProps) {
  // Drawn into the page's body, as the typical building's window: inside the panel its backdrop could not cover the view's overlays.
  return createPortal(
    <DialogFrame title={messages.projectSettingsTitle} busy={false} onClose={onClose} closeLabel={messages.closeProjectSettings} titleTakesFocus>
      <div ref={contentRef} className="project-settings">
        <p className="project-settings-intro">{messages.projectSettingsIntro}</p>
        <SettingsStep form={form} stepErrors={stepErrors} onChange={onChange} disabledReason={disabledReason} inputRoles={inputRoles}
                      withoutInputs="disabled" settingShown={(name) => !criterionKeys.has(name)} />
        <p className="project-settings-elsewhere">
          {messages.projectSettingsElsewhere}{" "}
          {STEPS_WITH_OTHER_SHARED_SETTINGS.map((step, index) => (
            <span key={step}>
              {index > 0 && ", "}
              <button type="button" className="link-button" onClick={() => onOpenStep(step)}>{messages.stepTitles[step]}</button>
            </span>
          ))}
        </p>
      </div>
      <div className="project-dialog-buttons">
        <button type="button" className="primary-button" onClick={onClose}>{messages.done}</button>
      </div>
    </DialogFrame>,
    document.body,
  );
}

// The project settings (UX 5.4, 11): the analysis settings every criterion shares, those that are not criterion keys (GET
// criterion-keys): north, the surroundings switch, the voxel size with the grid budget line under it, and, folded, the rays per batch.
// The Settings button in the top bar opens the window, in every workspace of an open project; its tooltip gives North and the voxel
// size, and it carries the "!" of a step row while a shared setting is to fix (settingsToFixByPlace). The window is the frame of the
// project dialogs, with × and Done; each change is saved as the form saves (no Apply), and while a run is in progress the fields
// wait and say why. A setting whose inputs the project has no files for (Account for context blocking without surroundings or
// terrain) is greyed out with the reason. Run analysis is in the Criteria step; its reason names Settings when a setting here is to
// fix, with Open settings beside it. The button's symbol is a gear: the sun already marks the theme button and the sun tool.
import { createPortal } from "react-dom";
import type { ReactNode, Ref } from "react";
import { messages } from "../messages";
import type { FormState } from "../settings_form/form_state";
import { SettingsStep } from "../settings_form/SettingsStep";
import { DialogFrame } from "../common/dialogs";
import "../theme/panels.css";

/** A gear of eight teeth, with its hole. */
function GearIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" aria-hidden="true">
      <path d="M6.17 2.92 L6.54 0.95 L9.46 0.95 L9.83 2.92 L10.30 3.11 L11.95 1.98 L14.02 4.05 L12.89 5.70 L13.08 6.17 L15.05 6.54 L15.05 9.46 L13.08 9.83 L12.89 10.30 L14.02 11.95 L11.95 14.02 L10.30 12.89 L9.83 13.08 L9.46 15.05 L6.54 15.05 L6.17 13.08 L5.70 12.89 L4.05 14.02 L1.98 11.95 L3.11 10.30 L2.92 9.83 L0.95 9.46 L0.95 6.54 L2.92 6.17 L3.11 5.70 L1.98 4.05 L4.05 1.98 L5.70 3.11 Z" />
      <circle cx="8" cy="8" r="2.3" />
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
  /** The element of the window's content, where a setting to focus is looked for. */
  contentRef?: Ref<HTMLDivElement>;
  /** The Heights group (HeightsSettings), drawn after the shared settings. */
  heights?: ReactNode;
  /** The weather file's box, first in the Location group (design/new-project-setup.md). */
  weather?: ReactNode;
  /** The Carving group: whether the carving reruns as its settings change. */
  carving?: ReactNode;
}

export function ProjectSettingsDialog({ form, stepErrors, criterionKeys, onChange, disabledReason, inputRoles, onClose, contentRef, heights, weather, carving }: ProjectSettingsDialogProps) {
  // Drawn into the page's body, as the typical building's window: inside the panel its backdrop could not cover the view's overlays.
  return createPortal(
    <DialogFrame title={messages.projectSettingsTitle} busy={false} onClose={onClose} closeLabel={messages.closeProjectSettings} titleTakesFocus>
      <div ref={contentRef} className="project-settings">
        <p className="project-settings-intro">{messages.projectSettingsIntro}</p>
        <SettingsStep form={form} stepErrors={stepErrors} onChange={onChange} disabledReason={disabledReason} inputRoles={inputRoles}
                      withoutInputs="disabled" settingShown={(name) => !criterionKeys.has(name)} groupLeads={weather === undefined ? undefined : { Location: weather }} />
        {carving}
        {heights}
      </div>
      <div className="project-dialog-buttons">
        <button type="button" className="primary-button" onClick={onClose}>{messages.done}</button>
      </div>
    </DialogFrame>,
    document.body,
  );
}

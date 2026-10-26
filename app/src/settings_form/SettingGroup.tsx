// One group of settings in a step (UX 5.4 to 5.6): a small header, the essential settings, and the others folded under a
// link-styled button ("More carving settings"). A group without essential settings (the carving of the angle rule, which has no
// threshold) is one fold titled with the group name. A fold holding a setting with an error stays open, so the message is never
// hidden. Every field takes a row of its own, so a slider has the panel's width to be dragged along (the three massing sliders side
// by side were too narrow to set a value with).
import { useId, useState } from "react";
import type { FormState } from "./form_state";
import type { SettingGroupView } from "./presentation";
import { fieldErrorOf, SettingField, type SettingFieldExtras } from "./SettingField";
import { Subheading } from "./Subheading";
import "./settings_form.css";

interface SettingGroupProps {
  group: SettingGroupView;
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
  /** What the step adds under some of the group's fields, by setting name. */
  fieldExtras?: Record<string, SettingFieldExtras>;
  /** While *disabled*, a field holding an error stays editable, so it can be fixed (Carving while the analysis is out of date). */
  fieldsWithErrorEditable?: boolean;
}

export function SettingGroup({ group, form, onChange, disabled = false, fieldExtras = {}, fieldsWithErrorEditable = false }: SettingGroupProps) {
  const disabledField = (view: SettingGroupView["essential"][number]) => disabled && !(fieldsWithErrorEditable && fieldErrorOf(form, view) !== undefined);
  const [unfoldedByUser, setUnfoldedByUser] = useState(false);
  const foldId = useId();
  const foldHoldsAnError = group.folded.some((view) => fieldErrorOf(form, view) !== undefined);
  const unfolded = unfoldedByUser || foldHoldsAnError;
  return (
    <div className="setting-group">
      {group.essential.length > 0 && (
        <>
          <Subheading className="setting-group-title">{group.title}</Subheading>
          <div className="setting-group-essential">
            {group.essential.map((view) => <SettingField key={view.name} view={view} form={form} onChange={onChange} disabled={disabledField(view)} extras={fieldExtras[view.name]} />)}
          </div>
        </>
      )}
      {group.folded.length > 0 && (
        <>
          <button type="button" className="setting-fold" aria-expanded={unfolded} aria-controls={unfolded ? foldId : undefined} onClick={() => setUnfoldedByUser(!unfolded)}>
            {group.foldLabel}
          </button>
          {unfolded && (
            <div id={foldId} className="setting-group-folded">
              {group.folded.map((view) => <SettingField key={view.name} view={view} form={form} onChange={onChange} disabled={disabledField(view)} extras={fieldExtras[view.name]} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

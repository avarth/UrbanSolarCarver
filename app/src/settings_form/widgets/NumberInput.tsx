// The number field every setting widget uses. While the user types, the text stays as typed; each text that reads as a number
// is passed on, an empty one is passed on as null (unset) only for a setting that may be empty, and leaving the field shows
// the setting's value again.
import { useState } from "react";

/** What SettingField gives every control: the ids that tie it to its label and error message, and whether it may be used. */
export interface ControlProps {
  inputId: string;
  labelId: string;
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
}

interface NumberInputProps {
  value: number | null;
  onValue: (value: number | null) => void;
  mayBeEmpty: boolean;
  id?: string;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
  minimum?: number;
  maximum?: number;
  wholeNumbers?: boolean;
  className?: string;
}

export function NumberInput({ value, onValue, mayBeEmpty, id, ariaLabel, ariaLabelledBy, invalid, describedBy, disabled, minimum, maximum, wholeNumbers,
                              className }: NumberInputProps) {
  const [typedText, setTypedText] = useState<string | null>(null);
  const shownText = typedText ?? (value === null ? "" : String(value));
  return (
    <input id={id} type="number" className={className ?? "setting-number"} value={shownText} min={minimum} max={maximum}
           step={wholeNumbers ? 1 : "any"} inputMode={wholeNumbers ? "numeric" : "decimal"} aria-label={ariaLabel} aria-labelledby={ariaLabelledBy}
           aria-invalid={invalid} aria-describedby={describedBy} disabled={disabled}
           onChange={(event) => {
             const text = event.target.value;
             setTypedText(text);
             if (text.trim() === "") {
               if (mayBeEmpty) onValue(null);
               return;
             }
             const typedNumber = Number(text);
             if (Number.isFinite(typedNumber)) onValue(typedNumber);
           }}
           onBlur={() => setTypedText(null)} />
  );
}

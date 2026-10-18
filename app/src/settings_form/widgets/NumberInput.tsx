// The number field every setting widget uses. While the user types, the text stays as typed; each text that reads as a number
// in the setting's range is passed on, an empty one is passed on as null (unset) only for a setting that may be empty, and
// leaving the field shows the setting's value again. A number outside the range (the engine's bounds, an exclusive bound such
// as "more than 0" included), or a fraction where a whole number is needed, is refused here and *onRefused* gets the message
// that says what to use; it gets null again once a number is taken, the field is emptied, or the value changes from elsewhere.
// A refusal gives the setting back the value it had when the editing began, so the part typed in range before the refused
// keystroke ("36" on the way to "360") is never kept.
import { useEffect, useRef, useState } from "react";
import { messages } from "../../messages";

/** What SettingField gives every control: the ids that tie it to its label and error message, and whether it may be used. */
export interface ControlProps {
  inputId: string;
  labelId: string;
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
  /** A number typed in one of the control's fields was refused (out of range), with the message; null when none is. */
  onRefusedInput?: (message: string | null) => void;
}

/** The range a number must lie in; an exclusive bound is not allowed itself. */
export interface NumberRange {
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
}

interface NumberInputProps extends NumberRange {
  value: number | null;
  onValue: (value: number | null) => void;
  mayBeEmpty: boolean;
  id?: string;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
  wholeNumbers?: boolean;
  className?: string;
  placeholder?: string;
  onRefused?: (message: string | null) => void;
}

/** Why *value* cannot be taken (the message to show), or null when it can. */
export function refusalOf(value: number, range: NumberRange, wholeNumbers = false): string | null {
  if (wholeNumbers && !Number.isInteger(value)) return messages.useWholeNumber;
  const { minimum, maximum, exclusiveMinimum, exclusiveMaximum } = range;
  const belowRange = (minimum !== undefined && value < minimum) || (exclusiveMinimum !== undefined && value <= exclusiveMinimum);
  const aboveRange = (maximum !== undefined && value > maximum) || (exclusiveMaximum !== undefined && value >= exclusiveMaximum);
  if (!belowRange && !aboveRange) return null;
  const lower = exclusiveMinimum !== undefined ? { value: exclusiveMinimum, exclusive: true }
    : minimum !== undefined ? { value: minimum, exclusive: false } : null;
  const upper = exclusiveMaximum !== undefined ? { value: exclusiveMaximum, exclusive: true }
    : maximum !== undefined ? { value: maximum, exclusive: false } : null;
  return messages.useNumberInRange(lower, upper);
}

export function NumberInput({ value, onValue, mayBeEmpty, id, ariaLabel, ariaLabelledBy, invalid, describedBy, disabled, minimum, maximum,
                              exclusiveMinimum, exclusiveMaximum, wholeNumbers, className, placeholder, onRefused }: NumberInputProps) {
  const [typedText, setTypedText] = useState<string | null>(null);
  const valueAtEditStart = useRef<number | null>(value);
  const refusing = useRef(false);
  const shownText = typedText ?? (value === null ? "" : String(value));
  const report = (refusal: string | null) => {
    refusing.current = refusal !== null;
    onRefused?.(refusal);
  };
  // A value set from elsewhere while the field is not being edited (a mode change, another control) ends a refusal's message.
  useEffect(() => {
    if (typedText === null && refusing.current) report(null);
  }, [value]);
  // The browser's own limits for the spinner: an exclusive bound is the nearest the spinner may go, and is refused there.
  const lowest = minimum ?? exclusiveMinimum, highest = maximum ?? exclusiveMaximum;
  return (
    <input id={id} type="number" className={className ?? "setting-number"} value={shownText} min={lowest} max={highest}
           step={wholeNumbers ? 1 : "any"} inputMode={wholeNumbers ? "numeric" : "decimal"} aria-label={ariaLabel} aria-labelledby={ariaLabelledBy}
           aria-invalid={invalid} aria-describedby={describedBy} disabled={disabled} placeholder={placeholder}
           onChange={(event) => {
             const text = event.target.value;
             if (typedText === null) valueAtEditStart.current = value;      // the editing begins
             setTypedText(text);
             if (text.trim() === "") {
               report(null);
               if (mayBeEmpty) onValue(null);
               return;
             }
             const typedNumber = Number(text);
             if (!Number.isFinite(typedNumber)) return;
             const refusal = refusalOf(typedNumber, { minimum, maximum, exclusiveMinimum, exclusiveMaximum }, wholeNumbers);
             report(refusal);
             if (refusal === null) onValue(typedNumber);
             else if (value !== valueAtEditStart.current && (valueAtEditStart.current !== null || mayBeEmpty)) onValue(valueAtEditStart.current);
           }}
           onBlur={() => setTypedText(null)} />
  );
}

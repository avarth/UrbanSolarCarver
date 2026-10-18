// The analysis period (UX 7): the six period settings as one widget, a "From" row and a "To" row of day, month and hour.
// Each number input keeps its own refusal; the field shows the first one standing, so a valid hour never hides a refused day.
import { useRef } from "react";
import { messages } from "../../messages";
import { ANALYSIS_PERIOD_FIELDS } from "../presentation";
import { NumberInput, type ControlProps } from "./NumberInput";

export type AnalysisPeriodField = (typeof ANALYSIS_PERIOD_FIELDS)[number];

interface AnalysisPeriodProps extends ControlProps {
  values: Record<AnalysisPeriodField, number | null>;
  onChange: (values: Partial<Record<AnalysisPeriodField, number | null>>) => void;
}

const PERIOD_ENDS = [
  { title: messages.periodFrom, day: "start_day", month: "start_month", hour: "start_hour" },
  { title: messages.periodTo, day: "end_day", month: "end_month", hour: "end_hour" },
] as const;

export function AnalysisPeriod({ values, onChange, inputId, labelId, invalid, describedBy, disabled, onRefusedInput }: AnalysisPeriodProps) {
  const refusals = useRef<Partial<Record<AnalysisPeriodField, string | null>>>({});
  const refusedIn = (field: AnalysisPeriodField) => (refusal: string | null) => {
    refusals.current = { ...refusals.current, [field]: refusal };
    onRefusedInput?.(ANALYSIS_PERIOD_FIELDS.map((name) => refusals.current[name] ?? null).find((standing) => standing !== null) ?? null);
  };
  return (
    <div role="group" aria-labelledby={labelId} className="setting-period">
      {PERIOD_ENDS.map((periodEnd) => (
        <div key={periodEnd.day} className="setting-period-row">
          <span className="setting-period-end">{periodEnd.title}</span>
          <NumberInput id={periodEnd.day === "start_day" ? inputId : undefined} className="setting-number setting-number-short"
                       ariaLabel={messages.periodFieldNames[periodEnd.day]} value={values[periodEnd.day]} mayBeEmpty={false}
                       minimum={1} maximum={31} wholeNumbers invalid={invalid} describedBy={describedBy} disabled={disabled}
                       onValue={(day) => onChange({ [periodEnd.day]: day })} onRefused={refusedIn(periodEnd.day)} />
          <select className="setting-select" aria-label={messages.periodFieldNames[periodEnd.month]} value={values[periodEnd.month] ?? ""}
                  aria-invalid={invalid} aria-describedby={describedBy} disabled={disabled}
                  onChange={(event) => onChange({ [periodEnd.month]: Number(event.target.value) })}>
            {messages.monthNames.map((monthName, index) => <option key={monthName} value={index + 1}>{monthName}</option>)}
          </select>
          <NumberInput className="setting-number setting-number-short" ariaLabel={messages.periodFieldNames[periodEnd.hour]}
                       value={values[periodEnd.hour]} mayBeEmpty={false} minimum={0} maximum={23} wholeNumbers invalid={invalid}
                       describedBy={describedBy} disabled={disabled} onValue={(hour) => onChange({ [periodEnd.hour]: hour })} onRefused={refusedIn(periodEnd.hour)} />
          <span className="setting-unit">{messages.hourUnit}</span>
        </div>
      ))}
    </div>
  );
}

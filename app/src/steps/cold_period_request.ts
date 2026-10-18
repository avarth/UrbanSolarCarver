// The cold period of the weather file (round 2, section 8), the preset "Cold period from the weather file" of Solar usefulness. It
// is asked for as soon as the weather file is there, for the balance temperature minus the dead band the form shows (a change is
// asked for once the values stop changing), so the preset is ready, and shows as chosen, before it is pressed.
import { useEffect, useRef, useState } from "react";
import { getColdPeriod, serviceProblemOf, failureTextOf } from "../api_client/client";
import { shownValue, type FormState } from "../settings_form/form_state";
import type { ColdPeriodState } from "../settings_form/analysis_period";

export type { ColdPeriodState } from "../settings_form/analysis_period";

export const MODE_WITH_COLD_PERIOD = "benefit";
const ASK_AFTER_MILLISECONDS = 400;     // a drag of the balance slider asks once, when it rests

/** The base temperature of the cold period: the balance temperature minus the dead band the form shows; null while one is empty. */
export function coldPeriodBaseOf(form: FormState): number | null {
  const balanceTemperature = shownValue(form, "balance_temperature"), deadBand = shownValue(form, "balance_offset");
  return typeof balanceTemperature === "number" && typeof deadBand === "number" ? balanceTemperature - deadBand : null;
}

interface ColdPeriodSource {
  token: string;
  project: string;
  form: FormState;
  hasWeatherFile: boolean;
  /** Changes when another weather file replaces the project's one (its location), so the cold period is asked for again. */
  weatherFileKey: string | null;
  onServiceProblem: (error: unknown) => void;
}

/** The cold period for the preset; null when the form's mode has none (only Solar usefulness has a balance temperature). */
export function useColdPeriod({ token, project, form, hasWeatherFile, weatherFileKey, onServiceProblem }: ColdPeriodSource): ColdPeriodState | null {
  const wanted = form.mode === MODE_WITH_COLD_PERIOD;
  const baseTemperature = coldPeriodBaseOf(form);
  const [state, setState] = useState<ColdPeriodState>({ kind: "finding" });
  const requestKey = useRef<string | null>(null);       // the base and weather file last asked for; only its reply is kept
  useEffect(() => {
    if (!wanted) return;
    if (!hasWeatherFile) {
      requestKey.current = null;
      setState({ kind: "needs_weather_file" });
      return;
    }
    if (baseTemperature === null) return;           // an empty balance field: keep the last answer until it is filled
    const key = JSON.stringify([project, weatherFileKey, baseTemperature]);
    if (requestKey.current === key) return;
    setState({ kind: "finding" });
    const timer = window.setTimeout(() => {
      requestKey.current = key;
      getColdPeriod(token, project, baseTemperature).then((reply) => {
        if (requestKey.current !== key) return;
        if (reply.status === "found" && reply.period) {
          const { start_month, start_day, end_month, end_day } = reply.period;
          setState({ kind: "found", dates: { startMonth: start_month, startDay: start_day, endMonth: end_month, endDay: end_day }, baseTemperature });
        } else if (reply.status === "no_weather_file") {
          setState({ kind: "needs_weather_file" });
        } else {
          setState({ kind: "none", baseTemperature });
        }
      }).catch((error) => {
        if (requestKey.current !== key) return;
        if (serviceProblemOf(error) !== "other") onServiceProblem(error);
        setState({ kind: "failed", reason: failureTextOf(error) });
      });
    }, ASK_AFTER_MILLISECONDS);
    return () => window.clearTimeout(timer);
  }, [wanted, hasWeatherFile, weatherFileKey, baseTemperature, project]);
  return wanted ? state : null;
}

// The cold period of the weather file (round 2, section 8), the preset "Cold period from the weather file" of Solar usefulness. It
// is asked for as soon as the weather file is there, for the balance temperature minus the dead band the form shows (a change is
// asked for once the values stop changing), so the preset is ready, and shows as chosen, before it is pressed.
//
// Answers are kept by what they were asked for (project, weather file revision, base), so a base that comes back to one already
// answered shows that answer at once, and a reply for a base the form no longer shows is kept but not shown. The answer shown
// says which weather file revision it is of, so the notice of a new weather file (weather_change_notice.ts) waits for that file's.
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
  /** Goes up whenever a weather file is added or replaced (the service keeps one name for it), so the cold period is asked for again. */
  weatherFileRevision: number;
  onServiceProblem: (error: unknown) => void;
}

export interface ColdPeriodShown {
  /** The cold period for the preset; null when the form's mode has none (only Solar usefulness has a balance temperature). */
  coldPeriod: ColdPeriodState | null;
  /** The weather file revision a "found" or "none" shown is the answer for; null while none is shown. */
  answeredWeatherFileRevision: number | null;
}

interface ShownAnswer {
  coldPeriod: ColdPeriodState;
  weatherFileRevision: number | null;
}

/** The cold period of the weather file for the base the form shows, and which weather file revision it is of. */
export function useColdPeriod({ token, project, form, hasWeatherFile, weatherFileRevision, onServiceProblem }: ColdPeriodSource): ColdPeriodShown {
  const wanted = form.mode === MODE_WITH_COLD_PERIOD;
  const baseTemperature = coldPeriodBaseOf(form);
  const [shown, setShown] = useState<ShownAnswer>({ coldPeriod: hasWeatherFile ? { kind: "finding" } : { kind: "needs_weather_file" }, weatherFileRevision: null });
  const answers = useRef(new Map<string, ColdPeriodState>());       // by request key
  const shownKey = useRef<string | null>(null);                      // the request key of what the form shows now
  useEffect(() => {
    if (!wanted) return;
    if (!hasWeatherFile) {
      shownKey.current = null;
      setShown({ coldPeriod: { kind: "needs_weather_file" }, weatherFileRevision: null });
      return;
    }
    if (baseTemperature === null) return;           // an empty balance field: keep the last answer until it is filled
    const key = JSON.stringify([project, weatherFileRevision, baseTemperature]);
    shownKey.current = key;
    const answerOfThisFile = (coldPeriod: ColdPeriodState) => ({ coldPeriod, weatherFileRevision });
    const known = answers.current.get(key);
    if (known !== undefined) {
      setShown(answerOfThisFile(known));
      return;
    }
    setShown({ coldPeriod: { kind: "finding" }, weatherFileRevision: null });
    const answer = (reached: ColdPeriodState) => {
      answers.current.set(key, reached);
      if (shownKey.current === key) setShown(answerOfThisFile(reached));
    };
    const timer = window.setTimeout(() => {
      getColdPeriod(token, project, baseTemperature).then((reply) => {
        if (reply.status === "found" && reply.period) {
          const { start_month, start_day, end_month, end_day } = reply.period;
          answer({ kind: "found", dates: { startMonth: start_month, startDay: start_day, endMonth: end_month, endDay: end_day }, baseTemperature });
        } else if (reply.status === "no_weather_file") {
          answer({ kind: "needs_weather_file" });
        } else {
          answer({ kind: "none", baseTemperature });
        }
      }).catch((error) => {
        if (serviceProblemOf(error) !== "other") onServiceProblem(error);
        if (shownKey.current === key) setShown({ coldPeriod: { kind: "failed", reason: failureTextOf(error) }, weatherFileRevision: null });    // not kept: asked again next time
      });
    }, ASK_AFTER_MILLISECONDS);
    return () => window.clearTimeout(timer);
  }, [wanted, hasWeatherFile, weatherFileRevision, baseTemperature, project]);
  return wanted ? { coldPeriod: shown.coldPeriod, answeredWeatherFileRevision: shown.weatherFileRevision } : { coldPeriod: null, answeredWeatherFileRevision: null };
}

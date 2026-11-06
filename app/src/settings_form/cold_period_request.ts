// The cold period of the weather file (round 2, section 8), the preset "Cold period from the weather file" of Solar heating. It
// is asked for as soon as the weather file is there, for the balance temperature minus the dead band the form shows (a change is
// asked for once the values stop changing), so the preset is ready, and shows as chosen, before it is pressed.
//
// Answers are kept by what they were asked for (project, weather file revision, base), so a base that comes back to one already
// answered shows that answer at once, and a reply for a base the form no longer shows is kept but not shown. The answer shown
// says which weather file revision it is of, so the notice of a new weather file (weather_change_notice.ts) waits for that file's.
import { useEffect, useEffectEvent, useState } from "react";
import { failureTextOf, getColdPeriod, reportServiceProblem } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import { shownValue, type FormState } from "./form_state";
import { withoutFloatingPointNoise } from "./widgets/BalanceTemperatureSlider";
import type { ColdPeriodState } from "./analysis_period";

export type { ColdPeriodState } from "./analysis_period";

export const MODE_WITH_COLD_PERIOD = "benefit";
const ASK_AFTER_MILLISECONDS = 400;     // a drag of the balance slider asks once, when it rests

/**
 * The base temperature of the cold period: the balance temperature minus the dead band the form shows, rounded as the slider rounds
 * its lower end (16.1 - 2.9 is 13.2, not 13.200000000000001); null while one is empty.
 */
export function coldPeriodBaseOf(form: FormState): number | null {
  const balanceTemperature = shownValue(form, "balance_temperature"), deadBand = shownValue(form, "balance_offset");
  return typeof balanceTemperature === "number" && typeof deadBand === "number" ? withoutFloatingPointNoise(balanceTemperature - deadBand) : null;
}

interface ColdPeriodSource {
  form: FormState;
  hasWeatherFile: boolean;
  /** Goes up whenever a weather file is added or replaced (the service keeps one name for it), so the cold period is asked for again. */
  weatherFileRevision: number;
}

export interface ColdPeriodShown {
  /** The cold period for the preset; null when the form's mode has none (only Solar heating has a balance temperature). */
  coldPeriod: ColdPeriodState | null;
  /** The weather file revision a "found" or "none" shown is the answer for; null while none is shown. */
  answeredWeatherFileRevision: number | null;
}

/** What the form asked about last: nothing yet, no weather file there, or a request (by its key) for one weather file revision. */
type AskedAbout = { kind: "nothing_yet" | "no_weather_file" } | { kind: "request"; key: string; weatherFileRevision: number };

const keyOfAsked = (asked: AskedAbout) => (asked.kind === "request" ? asked.key : asked.kind);

/** The cold period of the weather file for the base the form shows, and which weather file revision it is of. */
export function useColdPeriod({ form, hasWeatherFile, weatherFileRevision }: ColdPeriodSource): ColdPeriodShown {
  const { token, project, onServiceProblem } = useProjectSession();
  const wanted = form.mode === MODE_WITH_COLD_PERIOD;
  const baseTemperature = coldPeriodBaseOf(form);
  const [answers, setAnswers] = useState<ReadonlyMap<string, ColdPeriodState>>(() => new Map());       // by request key
  // Failures since the form asked about what it shows; not kept: asked again when the form comes back to them.
  const [failures, setFailures] = useState<ReadonlyMap<string, string>>(() => new Map());
  const requestKey = JSON.stringify([project, weatherFileRevision, baseTemperature]);
  // An empty balance field keeps the last answer until it is filled.
  const asking: AskedAbout | null = !wanted ? null : !hasWeatherFile ? { kind: "no_weather_file" }
    : baseTemperature === null ? null : { kind: "request", key: requestKey, weatherFileRevision };
  const [asked, setAsked] = useState<AskedAbout>(() => ({ kind: hasWeatherFile ? "nothing_yet" : "no_weather_file" }));
  if (asking !== null && keyOfAsked(asking) !== keyOfAsked(asked)) {
    setAsked(asking);
    setFailures(new Map());
  }
  // A mode without a cold period shows none, so a failure is not kept for when the form comes back to the same base.
  if (!wanted && failures.size > 0) setFailures(new Map());

  const known = asked.kind === "request" ? answers.get(asked.key) : undefined;
  const failure = asked.kind === "request" ? failures.get(asked.key) : undefined;
  const shown: ColdPeriodShown = asked.kind === "no_weather_file" ? { coldPeriod: { kind: "needs_weather_file" }, answeredWeatherFileRevision: null }
    : asked.kind === "request" && known !== undefined ? { coldPeriod: known, answeredWeatherFileRevision: asked.weatherFileRevision }
    : failure !== undefined ? { coldPeriod: { kind: "failed", reason: failure }, answeredWeatherFileRevision: null }
    : { coldPeriod: { kind: "finding" }, answeredWeatherFileRevision: null };

  const isAnswered = useEffectEvent((key: string) => answers.has(key));
  const ask = useEffectEvent((base: number) => getColdPeriod(token, project, base));
  const reportProblem = useEffectEvent((error: unknown) => onServiceProblem(error));
  useEffect(() => {
    if (!wanted || !hasWeatherFile || baseTemperature === null || isAnswered(requestKey)) return;
    const key = requestKey;
    const answer = (reached: ColdPeriodState) => setAnswers((current) => new Map(current).set(key, reached));
    const timer = window.setTimeout(() => {
      ask(baseTemperature).then((reply) => {
        if (reply.status === "found" && reply.period) {
          const { start_month, start_day, end_month, end_day } = reply.period;
          answer({ kind: "found", dates: { startMonth: start_month, startDay: start_day, endMonth: end_month, endDay: end_day }, baseTemperature });
        } else if (reply.status === "no_weather_file") {
          answer({ kind: "needs_weather_file" });
        } else {
          answer({ kind: "none", baseTemperature });
        }
      }).catch((error) => {
        reportServiceProblem(error, reportProblem);
        setFailures((current) => new Map(current).set(key, failureTextOf(error)));
      });
    }, ASK_AFTER_MILLISECONDS);
    return () => window.clearTimeout(timer);
  }, [wanted, hasWeatherFile, baseTemperature, requestKey]);
  return wanted ? shown : { coldPeriod: null, answeredWeatherFileRevision: null };
}

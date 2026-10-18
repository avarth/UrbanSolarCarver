// The sun path of the stored analysis period (UX 8.2), asked for as soon as the mode reads one, the weather file is there and
// every part of the period is set, before any run.
import { useEffect, useRef, useState } from "react";
import { getSunPath, serviceProblemOf, type SunPath } from "../api_client/client";
import { shownValue, type FormState } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS } from "../settings_form/presentation";
import { settingsToFixCount } from "./SettingsStep";
import type { AnalysisPeriod } from "./step_summaries";

const MODE_WITH_SUN_PATH = "time-based";

/** The analysis period the form holds, when the mode reads one and every part of it is set. */
export function analysisPeriodOf(form: FormState, modeReadsPeriod: boolean): AnalysisPeriod | null {
  const values = ANALYSIS_PERIOD_FIELDS.map((name) => shownValue(form, name));
  if (!modeReadsPeriod || !values.every((value) => typeof value === "number")) return null;
  const [startMonth, startDay, startHour, endMonth, endDay, endHour] = values as number[];
  return { startMonth, startDay, startHour, endMonth, endDay, endHour };
}

interface SunPathSource {
  token: string;
  project: string;
  form: FormState;
  hasWeatherFile: boolean;
  northDegrees: number;
  onServiceProblem: (error: unknown) => void;
}

/** The sun path of the stored period; null when the mode has none, the weather file or a part of the period is missing. */
export function useSunPathOfStoredPeriod({ token, project, form, hasWeatherFile, northDegrees, onServiceProblem }: SunPathSource): SunPath | null {
  const [sunPath, setSunPath] = useState<SunPath | null>(null);
  const sunPathKey = JSON.stringify([form.mode, ANALYSIS_PERIOD_FIELDS.map((name) => shownValue(form, name)), northDegrees, hasWeatherFile]);
  const sunPathWanted = form.mode === MODE_WITH_SUN_PATH && hasWeatherFile && analysisPeriodOf(form, true) !== null;
  const sunPathRequestKey = useRef<string | null>(null);      // the period last asked for; only its reply is kept
  useEffect(() => {
    if (!sunPathWanted) {
      sunPathRequestKey.current = null;
      setSunPath(null);
      return;
    }
    // The service reads the stored settings: wait for the save, and keep the last path while the form holds a refused change.
    if (form.pendingSave || settingsToFixCount(form) > 0 || sunPathRequestKey.current === sunPathKey) return;
    const requestKey = sunPathKey;
    sunPathRequestKey.current = requestKey;
    getSunPath(token, project).then((reply) => { if (sunPathRequestKey.current === requestKey) setSunPath(reply); }).catch((error) => {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    });
  }, [sunPathKey, sunPathWanted, form.pendingSave]);
  return sunPath;
}

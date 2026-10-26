// The sun path of the stored analysis period (UX 8.2), asked for as soon as the mode reads one, the weather file is there and
// every part of the period is set, before any run; of the selected criterion, asked for again when another is selected.
import { useEffect, useRef, useState } from "react";
import { getSunPath, serviceProblemOf } from "../api_client/client";
import { shownValue, storedValue, type FormState } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS } from "../settings_form/presentation";
import { settingsToFixCount } from "./SettingsStep";
import type { SunPathWithNorth } from "../viewer/sun_path";

const MODE_WITH_SUN_PATH = "time-based";

export interface AnalysisPeriod {
  startMonth: number;
  startDay: number;
  startHour: number;
  endMonth: number;
  endDay: number;
  endHour: number;
}

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
  /** The criterion whose period it is; absent: the service's default criterion. */
  criterionId?: string;
  onServiceProblem: (error: unknown) => void;
}

/**
 * The sun path of the stored period, with the stored North it was computed with; null when the mode has none, the weather file or a
 * part of the period is missing.
 */
export function useSunPathOfStoredPeriod({ token, project, form, hasWeatherFile, northDegrees, criterionId, onServiceProblem }: SunPathSource): SunPathWithNorth | null {
  const [sunPath, setSunPath] = useState<SunPathWithNorth | null>(null);
  const sunPathKey = JSON.stringify([form.mode, ANALYSIS_PERIOD_FIELDS.map((name) => shownValue(form, name)), northDegrees, hasWeatherFile, criterionId]);
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
    const storedNorthDegrees = Number(storedValue(form, "north_deg") ?? 0);
    sunPathRequestKey.current = requestKey;
    getSunPath(token, project, criterionId).then((reply) => {
      if (sunPathRequestKey.current === requestKey) setSunPath({ path: reply, northDegrees: storedNorthDegrees });
    }).catch((error) => {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
    });
  }, [sunPathKey, sunPathWanted, form.pendingSave]);
  return sunPath;
}

// The project's typical building, which an energy-weighted Solar usefulness criterion counts its hours by: its values, the types
// it can start from, the state of its weights and the weights themselves. One building per project, read once something shows it
// (*active*: the shown criterion is energy-weighted) and read again when a run of the project ends (the run calculates the
// weights when they are missing or out of date) and when the weather file changes (the weights depend on it). The sheet's changes
// are saved one after another, each with all the values; a refused save (422) keeps the values shown with an error at each field,
// as the settings form keeps a refused value. Calculate saves what waits first, then calculates the stored building.
import { useEffect, useRef, useState } from "react";
import {
  ApiError, calculateTypicalBuilding, failureTextOf, getTypicalBuilding, getTypicalBuildingPresets, getTypicalBuildingWeights, putTypicalBuilding,
  serviceProblemOf, type TypicalBuildingPreset, type TypicalBuildingReply, type TypicalBuildingWeightsReply,
} from "../api_client/client";

export type TypicalBuildingValues = Record<string, unknown>;

export interface TypicalBuildingHook {
  /** The building as stored, with the state of its weights and their numbers; null until it is read. */
  stored: TypicalBuildingReply | null;
  /** The values shown: the stored ones, or the ones of a change that waits for its save or was refused. */
  values: TypicalBuildingValues | null;
  /** The type the values started from; null when none. */
  startFrom: string | null;
  /** The types the building can start from, by key, in the order the service gives them; null until read. */
  presets: Record<string, TypicalBuildingPreset> | null;
  /** Why the building could not be read; null when it was or is being read. */
  readProblem: string | null;
  /** The messages of the last refused save, by field ("wwr.south" for a window share); empty after a save that was stored. */
  fieldErrors: Record<string, string>;
  /** Why the last save or calculation failed, when no field is named; null when none did. */
  problem: string | null;
  calculating: boolean;
  /** The weights of the last calculation once read (readWeights); null before. */
  weights: TypicalBuildingWeightsReply | null;
  /** Saves *values* (all of them) and the type they started from. */
  change: (values: TypicalBuildingValues, startFrom: string | null) => void;
  calculate: () => void;
  /** Reads the weights of the last calculation, unless they are read or being read. */
  readWeights: () => void;
}

interface TypicalBuildingOptions {
  token: string;
  project: string;
  active: boolean;
  /** A run of the project is under way. */
  runActive: boolean;
  /** Changes whenever the weather file is added, replaced or removed. */
  weatherRevision: number;
  onServiceProblem: (error: unknown) => void;
}

/** The field errors of a refused save (422 with field_errors), by field; null for another failure. */
function fieldErrorsOf(error: unknown): Record<string, string> | null {
  if (!(error instanceof ApiError) || error.status !== 422 || typeof error.body !== "object" || error.body === null) return null;
  const fieldErrors = (error.body as { field_errors?: { field: string | null; message: string }[] }).field_errors;
  if (!Array.isArray(fieldErrors)) return null;
  return Object.fromEntries(fieldErrors.map((fieldError) => [fieldError.field ?? "", fieldError.message]));
}

export function useTypicalBuilding({ token, project, active, runActive, weatherRevision, onServiceProblem }: TypicalBuildingOptions): TypicalBuildingHook {
  const [stored, setStored] = useState<TypicalBuildingReply | null>(null);
  const [shown, setShown] = useState<{ values: TypicalBuildingValues; startFrom: string | null } | null>(null);
  const [presets, setPresets] = useState<Record<string, TypicalBuildingPreset> | null>(null);
  const [readProblem, setReadProblem] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [weights, setWeights] = useState<TypicalBuildingWeightsReply | null>(null);
  // The saves go out one after another; while one waits, a reply does not replace the values shown.
  const saves = useRef<Promise<void>>(Promise.resolve());
  const savesWaiting = useRef(0);
  const weightsAsked = useRef(false);
  const latestState = useRef<TypicalBuildingReply["state"] | null>(null);

  const failed = (error: unknown): string | null => {
    if (serviceProblemOf(error) !== "other") {
      onServiceProblem(error);
      return null;
    }
    return failureTextOf(error);
  };
  // A reply of the service: the stored building, shown unless a change waits. Weights calculated since the last reply (now current,
  // and not before; or after Calculate) are read again.
  const take = (reply: TypicalBuildingReply, calculated = false) => {
    if (calculated || reply.state === "missing" || (reply.state === "current" && latestState.current !== "current")) {
      setWeights(null);
      weightsAsked.current = false;
    }
    latestState.current = reply.state;
    setStored(reply);
    if (savesWaiting.current === 0) setShown({ values: reply.values, startFrom: reply.start_from });
  };
  const read = () => {
    setReadProblem(null);
    getTypicalBuilding(token, project).then((reply) => take(reply), (error: unknown) => setReadProblem(failed(error)));
  };

  useEffect(() => {
    if (!active || stored !== null) return;
    read();
    if (presets === null) getTypicalBuildingPresets(token).then(setPresets, (error: unknown) => setReadProblem(failed(error)));
  }, [active]);
  // A run may have calculated the weights; a new weather file makes them out of date.
  const runWasActive = useRef(runActive);
  useEffect(() => {
    const ended = runWasActive.current && !runActive;
    runWasActive.current = runActive;
    if (ended && stored !== null) read();
  }, [runActive]);
  const weatherRevisionSeen = useRef(weatherRevision);
  useEffect(() => {
    if (weatherRevisionSeen.current === weatherRevision) return;
    weatherRevisionSeen.current = weatherRevision;
    if (stored !== null) read();
  }, [weatherRevision]);

  const change = (values: TypicalBuildingValues, startFrom: string | null) => {
    setShown({ values, startFrom });
    savesWaiting.current += 1;
    saves.current = saves.current.then(async () => {
      try {
        const reply = await putTypicalBuilding(token, project, values, startFrom);
        savesWaiting.current -= 1;
        setFieldErrors({});
        setProblem(null);
        take(reply);
      } catch (error) {
        savesWaiting.current -= 1;
        const refused = fieldErrorsOf(error);
        setFieldErrors(refused ?? {});
        setProblem(refused === null ? failed(error) : null);
      }
    });
  };

  const calculate = () => {
    setCalculating(true);
    setProblem(null);
    saves.current = saves.current.then(async () => {
      try {
        take(await calculateTypicalBuilding(token, project), true);
      } catch (error) {
        setProblem(failed(error));
      } finally {
        setCalculating(false);
      }
    });
  };

  const readWeights = () => {
    if (weightsAsked.current) return;
    weightsAsked.current = true;
    getTypicalBuildingWeights(token, project).then(setWeights, (error: unknown) => {
      weightsAsked.current = false;
      setProblem(failed(error));
    });
  };

  return {
    stored, values: shown?.values ?? null, startFrom: shown?.startFrom ?? null, presets, readProblem, fieldErrors, problem, calculating, weights,
    change, calculate, readWeights,
  };
}

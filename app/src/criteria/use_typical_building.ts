// The project's typical building, which an energy-weighted Solar usefulness criterion counts its hours by: its values, the library
// it is chosen from, the state of its weights and the weights themselves. One building per project, a copy of a library entry (none
// in a new project, state not_chosen, until one is chosen), read
// once something shows it (*active*: the shown criterion is energy-weighted) and read again when a run of the project ends (the run
// calculates the weights when they are missing or out of date) and when the weather file changes (the weights depend on it). The
// sheet's changes are saved one after another, each with all the values; a refused save (422) keeps the values shown with an error
// at each field, as the settings form keeps a refused value. Calculate saves what waits first, then calculates the stored building.
// The library's changes (Save to library, Save as new, rename, delete) go in the same line, and the library and the building are
// read again after each: the building's library name and "changed" follow them.
import { useEffect, useRef, useState } from "react";
import {
  addTypicalBuildingLibraryEntry, ApiError, calculateTypicalBuilding, deleteTypicalBuildingLibraryEntry, failureTextOf, getTypicalBuilding,
  getTypicalBuildingLibrary, getTypicalBuildingWeights, putTypicalBuilding, serviceProblemOf, updateTypicalBuildingLibraryEntry,
  type TypicalBuildingLibraryEntry, type TypicalBuildingReply, type TypicalBuildingWeightsReply,
} from "../api_client/client";

export type TypicalBuildingValues = Record<string, unknown>;

export interface TypicalBuildingHook {
  /** The building as stored, with its library entry, the state of its weights and their numbers; null until it is read. */
  stored: TypicalBuildingReply | null;
  /** The values shown: the stored ones, or the ones of a change that waits for its save or was refused; null before they are read
   * and while no building is chosen. */
  values: TypicalBuildingValues | null;
  /** The library: the examples in their order, then the user's own entries by name; null until read. */
  library: TypicalBuildingLibraryEntry[] | null;
  /** Why the building could not be read; null when it was or is being read. */
  readProblem: string | null;
  /** The messages of the last refused save, by field ("wwr.sw" for a window share); empty after a save that was stored. */
  fieldErrors: Record<string, string>;
  /** Why the last save, library change or calculation failed, when no field is named; null when none did. */
  problem: string | null;
  calculating: boolean;
  /** The weights of the last calculation once read (readWeights); null before. */
  weights: TypicalBuildingWeightsReply | null;
  /** Saves *values* (all of them); the building still comes from the same library entry. */
  change: (values: TypicalBuildingValues) => void;
  /** Replaces the building with a copy of the library entry. */
  choose: (entry: TypicalBuildingLibraryEntry) => void;
  /** Writes the stored values over the own library entry the building came from. */
  saveToLibrary: () => void;
  /** Saves the stored values as a new own entry named *name*, which the building then comes from; resolves with why it was refused, or null. */
  saveAsNew: (name: string) => Promise<string | null>;
  /** Renames an own entry; resolves with why it was refused, or null. */
  renameEntry: (entryId: string, name: string) => Promise<string | null>;
  /** Deletes an own entry (a project that came from it keeps its copy); resolves with why it was refused, or null. */
  deleteEntry: (entryId: string) => Promise<string | null>;
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
  const [shown, setShown] = useState<TypicalBuildingValues | null>(null);
  const [library, setLibrary] = useState<TypicalBuildingLibraryEntry[] | null>(null);
  const [readProblem, setReadProblem] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [weights, setWeights] = useState<TypicalBuildingWeightsReply | null>(null);
  // The saves go out one after another; while one waits, a reply does not replace the values shown.
  const saves = useRef<Promise<void>>(Promise.resolve());
  const savesWaiting = useRef(0);
  const weightsAsked = useRef(false);
  const latest = useRef<TypicalBuildingReply | null>(null);

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
    if (calculated || reply.state === "missing" || (reply.state === "current" && latest.current?.state !== "current")) {
      setWeights(null);
      weightsAsked.current = false;
    }
    latest.current = reply;
    setStored(reply);
    if (savesWaiting.current === 0) setShown(reply.values);
  };
  const read = () => {
    setReadProblem(null);
    getTypicalBuilding(token, project).then((reply) => take(reply), (error: unknown) => setReadProblem(failed(error)));
  };
  const readLibrary = () => getTypicalBuildingLibrary(token).then(setLibrary, (error: unknown) => setReadProblem(failed(error)));

  useEffect(() => {
    if (!active || stored !== null) return;
    read();
    if (library === null) void readLibrary();
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

  /** Saves *values*, from the entry *libraryId* when given. */
  const save = (values: TypicalBuildingValues, libraryId?: string) => {
    setShown(values);
    savesWaiting.current += 1;
    saves.current = saves.current.then(async () => {
      try {
        const reply = await putTypicalBuilding(token, project, values, libraryId);
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

  /**
   * Sends a change of the library after the saves that wait; then the library and the building are read again. Resolves with why
   * it was refused, or null.
   */
  const changeLibrary = (request: () => Promise<unknown>) => new Promise<string | null>((resolve) => {
    saves.current = saves.current.then(async () => {
      let reason: string | null = null;
      try {
        await request();
      } catch (error) {
        reason = failed(error) ?? "";
      }
      await readLibrary();
      try {
        take(await getTypicalBuilding(token, project));
      } catch (error) {
        setReadProblem(failed(error));
      }
      resolve(reason);
    });
  });

  const saveToLibrary = () => {
    setProblem(null);
    void changeLibrary(async () => {
      const reply = latest.current;
      if (reply?.library_id != null && reply.values !== null) await updateTypicalBuildingLibraryEntry(token, reply.library_id, { values: reply.values });
    }).then((reason) => { if (reason !== null) setProblem(reason); });
  };
  const saveAsNew = (name: string) => changeLibrary(async () => {
    const entry = await addTypicalBuildingLibraryEntry(token, name, latest.current!.values!);
    await putTypicalBuilding(token, project, entry.values, entry.id);
  });
  const renameEntry = (entryId: string, name: string) => changeLibrary(() => updateTypicalBuildingLibraryEntry(token, entryId, { name }));
  const deleteEntry = (entryId: string) => changeLibrary(() => deleteTypicalBuildingLibraryEntry(token, entryId));

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
    stored, values: shown, library, readProblem, fieldErrors, problem, calculating, weights,
    change: (values) => save(values), choose: (entry) => save(structuredClone(entry.values), entry.id), saveToLibrary, saveAsNew, renameEntry,
    deleteEntry, calculate, readWeights,
  };
}

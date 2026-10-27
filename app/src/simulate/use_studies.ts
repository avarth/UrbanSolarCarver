// The studies of the open project (Simulate): the list with the state of each study's result, the metrics a study can show, the
// selected study and the calls that change them. A change takes the service's reply as the study's entry at once, then reads the
// list again, since the state of a study (out of date, refused) is the service's to say. A refused change rejects with its ApiError
// and changes nothing; a failed read keeps what was shown and says why (loadProblem).
import { useRef, useState } from "react";
import {
  addStudy, addStudyTestSurface, deleteStudy, failureTextOf, getStudies, removeStudyTestSurface, reorderStudies, serviceProblemOf, updateStudy,
  useStudyTestSurface,
  type MetricInfo, type StudyChange, type StudyEntry, type StudySource, type StudyWithState,
} from "../api_client/client";

export interface StudiesHook {
  studies: StudyWithState[];
  metrics: MetricInfo[];
  /** The study shown in the view; null when none is. */
  selectedId: string | null;
  /** Why the studies could not be read; null when they were (or have not been asked for yet). */
  loadProblem: string | null;
  select: (id: string | null) => void;
  /** Adds a study at the end and selects it. */
  add: (source: StudySource) => Promise<StudyEntry>;
  update: (id: string, change: StudyChange) => Promise<StudyEntry>;
  /** Removes the study; when it was selected, none is. */
  remove: (id: string) => Promise<void>;
  /** Puts the studies in the order of *ids* (every id once). */
  reorder: (ids: string[]) => Promise<void>;
  /** Uploads a test surface file to the study (one file; a stored file of that name is replaced). */
  addFile: (id: string, file: File) => Promise<StudyEntry>;
  /** Lets the study use a stored test surface file. */
  useFile: (id: string, fileName: string) => Promise<StudyEntry>;
  removeFile: (id: string, fileName: string) => Promise<StudyEntry>;
  /** Reads the studies and the metrics again; never rejects. */
  refresh: () => Promise<void>;
}

interface StudiesState {
  studies: StudyWithState[];
  metrics: MetricInfo[];
  selectedId: string | null;
  loadProblem: string | null;
}

/** A study the list does not have yet, until the list read after the change says its state. */
const newStudy = (entry: StudyEntry): StudyWithState => ({ entry, state: "not_run", reason: null, geometries: [] });

/** *onServiceProblem*: told a failed read that lost the token or the engine (the app's overlay says it). */
export function useStudies(token: string, project: string, onServiceProblem: (error: unknown) => void = () => {}): StudiesHook {
  const [state, setState] = useState<StudiesState>({ studies: [], metrics: [], selectedId: null, loadProblem: null });
  // The latest state, read by calls that wait for a reply while another reply arrives.
  const latest = useRef(state);
  const commit = (next: Partial<StudiesState>) => {
    latest.current = { ...latest.current, ...next };
    setState(latest.current);
  };
  // Only the last read asked for is shown: an earlier one that answers later has an older list.
  const readsAskedFor = useRef(0);

  const refresh = async () => {
    const read = ++readsAskedFor.current;
    try {
      const reply = await getStudies(token, project);
      if (read !== readsAskedFor.current) return;
      const { selectedId } = latest.current;
      commit({ studies: reply.studies, metrics: reply.metrics, loadProblem: null,
               selectedId: reply.studies.some((study) => study.entry.id === selectedId) ? selectedId : null });
    } catch (error) {
      if (read !== readsAskedFor.current) return;
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      commit({ loadProblem: failureTextOf(error) });
    }
  };
  const replaceEntry = (entry: StudyEntry) =>
    commit({ studies: latest.current.studies.map((study) => (study.entry.id === entry.id ? { ...study, entry } : study)) });
  const changeEntry = async (request: Promise<StudyEntry>) => {
    const entry = await request;
    replaceEntry(entry);
    void refresh();
    return entry;
  };

  return {
    ...state,
    select: (id) => commit({ selectedId: id }),
    add: async (source) => {
      const entry = await addStudy(token, project, source);
      commit({ studies: [...latest.current.studies, newStudy(entry)], selectedId: entry.id });
      void refresh();
      return entry;
    },
    update: (id, change) => changeEntry(updateStudy(token, project, id, change)),
    remove: async (id) => {
      await deleteStudy(token, project, id);
      const { studies, selectedId } = latest.current;
      commit({ studies: studies.filter((study) => study.entry.id !== id), selectedId: selectedId === id ? null : selectedId });
      void refresh();       // a read asked for before the delete may answer after it with the study still in its list: this one replaces it
    },
    reorder: async (ids) => {
      const entries = await reorderStudies(token, project, ids);
      const byId = new Map(latest.current.studies.map((study) => [study.entry.id, study]));
      commit({ studies: entries.map((entry) => ({ ...(byId.get(entry.id) ?? newStudy(entry)), entry })) });
      void refresh();       // as in remove: a read asked for before the new order may answer after it
    },
    addFile: (id, file) => changeEntry(addStudyTestSurface(token, project, id, file)),
    useFile: (id, fileName) => changeEntry(useStudyTestSurface(token, project, id, fileName)),
    removeFile: (id, fileName) => changeEntry(removeStudyTestSurface(token, project, id, fileName)),
    refresh,
  };
}

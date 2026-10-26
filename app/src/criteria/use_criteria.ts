// The criteria of the open project: the list in carving order, the selected card and the calls that change them. Each call sends
// its request, takes the service's reply as the new state (a list reply replaces the list, an entry reply the entry of its id) and
// returns a promise the workspace awaits. A refused request rejects with its ApiError and changes nothing.
import { useRef, useState } from "react";
import {
  addCriterion, addCriterionTestSurface, deleteCriterion, duplicateCriterion, removeCriterionTestSurface, reorderCriteria, reuseTestSurface,
  updateCriterion, type CriterionEntry, type ProjectDetail,
} from "../api_client/client";
import { selectionAfterRemoving } from "./criteria_state";

export interface CriteriaHook {
  criteria: CriterionEntry[];
  /** The id of the selected criterion; empty when the project lists none. */
  selectedId: string;
  /** The list and the selection as they are now, with the replies that arrived since the last render. */
  current: () => { criteria: CriterionEntry[]; selectedId: string };
  select: (id: string) => void;
  /** Adds a criterion of *mode* at the end and selects it. */
  add: (mode: string) => Promise<CriterionEntry>;
  rename: (id: string, name: string) => Promise<CriterionEntry>;
  setBypassed: (id: string, on: boolean) => Promise<CriterionEntry>;
  /** Adds a copy at the end and selects it. */
  duplicate: (id: string) => Promise<CriterionEntry>;
  /** Removes the criterion; when it was selected, the next card (else the previous one) is selected. */
  remove: (id: string) => Promise<void>;
  /** Puts the criteria in the order of *ids* (every id once). */
  reorder: (ids: string[]) => Promise<void>;
  /** Uploads the files one after another, each reply replacing the entry. */
  addTestSurfaces: (id: string, files: File[]) => Promise<void>;
  reuseFile: (id: string, fileName: string) => Promise<CriterionEntry>;
  removeFile: (id: string, fileName: string) => Promise<CriterionEntry>;
  /** Replaces the entry that has the id of *entry* (a reply some other call of the workspace received). */
  applyReply: (entry: CriterionEntry) => void;
}

export function useCriteria(token: string, project: ProjectDetail): CriteriaHook {
  const start = project.criteria ?? [];
  const [state, setState] = useState({ criteria: start, selectedId: start[0]?.id ?? "" });
  // The latest state, read by calls that wait for a reply while another reply arrives (a file upload goes on while a name is saved).
  const latest = useRef(state);
  const commit = (next: typeof state) => {
    latest.current = next;
    setState(next);
  };
  const replaceEntry = (entry: CriterionEntry) =>
    commit({ ...latest.current, criteria: latest.current.criteria.map((criterion) => (criterion.id === entry.id ? entry : criterion)) });
  const appendAndSelect = (entry: CriterionEntry) => commit({ criteria: [...latest.current.criteria, entry], selectedId: entry.id });
  const changeEntry = async (request: Promise<CriterionEntry>) => {
    const entry = await request;
    replaceEntry(entry);
    return entry;
  };

  return {
    criteria: state.criteria,
    selectedId: state.selectedId,
    current: () => latest.current,
    select: (id) => commit({ ...latest.current, selectedId: id }),
    add: async (mode) => {
      const entry = await addCriterion(token, project.name, mode);
      appendAndSelect(entry);
      return entry;
    },
    rename: (id, name) => changeEntry(updateCriterion(token, project.name, id, { name })),
    setBypassed: (id, on) => changeEntry(updateCriterion(token, project.name, id, { bypassed: on })),
    duplicate: async (id) => {
      const entry = await duplicateCriterion(token, project.name, id);
      appendAndSelect(entry);
      return entry;
    },
    remove: async (id) => {
      await deleteCriterion(token, project.name, id);
      const { criteria, selectedId } = latest.current;
      commit({ criteria: criteria.filter((criterion) => criterion.id !== id), selectedId: selectionAfterRemoving(criteria, id, selectedId) });
    },
    reorder: async (ids) => {
      commit({ ...latest.current, criteria: await reorderCriteria(token, project.name, ids) });
    },
    addTestSurfaces: async (id, files) => {
      for (const file of files) replaceEntry(await addCriterionTestSurface(token, project.name, id, file));
    },
    reuseFile: (id, fileName) => changeEntry(reuseTestSurface(token, project.name, id, fileName)),
    removeFile: (id, fileName) => changeEntry(removeCriterionTestSurface(token, project.name, id, fileName)),
    applyReply: replaceEntry,
  };
}

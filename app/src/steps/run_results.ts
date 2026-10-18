// The results of the project's runs that the steps and the 3D view show: the run summary, the score points, the sky dome, the
// envelope and building massing meshes and plates.json. Each is fetched again when a stage that writes it has run (UX 6.3:
// results arrive stage by stage), and the result of the last request wins. A result a stage has not written (yet) is null.
import { useCallback, useEffect, useRef, useState } from "react";
import type * as THREE from "three";
import {
  ApiError, getRunFileJson, getRunSummary, getScorePoints, getSkyPatches, runFileUrl, serviceProblemOf, type RunSummary, type SkyDome,
} from "../api_client/client";
import { loadMesh } from "../viewer/loaders";
import type { Point3 } from "../viewer/local_origin";
import { decodeScorePoints, type ScorePoints } from "../viewer/score_points_decoder";
import type { PlatesFile } from "./EnvelopeAndMassingStep";
import { exportedMeshPath, MASSING_JSON_PATH, MASSING_OBJ_PATH, meshFormatOf } from "./ExportStep";
import { stagesDone, type RunRecord } from "./run_state";
import type { PipelineStage } from "./step_summaries";

export interface RunResults {
  summary: RunSummary | null;
  scorePoints: ScorePoints | null;
  skyDome: SkyDome | null;
  envelope: THREE.BufferGeometry | null;
  massing: THREE.BufferGeometry | null;
  platesFile: PlatesFile | null;
}

type ResultName = keyof RunResults;

const NO_RESULTS: RunResults = { summary: null, scorePoints: null, skyDome: null, envelope: null, massing: null, platesFile: null };

/**
 * What each stage writes. The score points need the carving's mask, so they follow thresholding, not the analysis; the run
 * summary holds the numbers of the carving, the envelope and the massing.
 */
const RESULTS_OF_STAGE: Record<PipelineStage, ResultName[]> = {
  preprocessing: ["skyDome"],
  thresholding: ["summary", "scorePoints"],
  exporting: ["summary", "envelope"],
  massing: ["summary", "massing", "platesFile"],
};
const MESH_RESULTS: ResultName[] = ["envelope", "massing"];
const NOT_FOUND = 404;

export function resultsOfStages(stages: readonly string[]): ResultName[] {
  return [...new Set(stages.flatMap((stage) => RESULTS_OF_STAGE[stage as PipelineStage] ?? []))];
}

interface RunResultsSource {
  token: string;
  project: string;
  /** The local origin the meshes are drawn in; a new one reloads them. */
  origin: Point3;
  /** The stages with results when the project opens. */
  stagesWithResults: readonly string[];
  onServiceProblem: (error: unknown) => void;
}

/** The results, and the function that fetches again what the given stages write; its promise resolves once every fetch has ended. */
export function useRunResults({ token, project, origin, stagesWithResults, onServiceProblem }: RunResultsSource): [RunResults, (stages: readonly string[]) => Promise<void>] {
  const [results, setResults] = useState<RunResults>(NO_RESULTS);
  const latestRequest = useRef<Partial<Record<ResultName, number>>>({});
  const source = useRef({ token, origin, onServiceProblem });
  source.current = { token, origin, onServiceProblem };

  const fetchResult = (name: ResultName): Promise<RunResults[ResultName]> => {
    const { token: currentToken, origin: currentOrigin } = source.current;
    switch (name) {
      case "summary":
        return getRunSummary(currentToken, project);
      case "scorePoints":
        return getScorePoints(currentToken, project).then(decodeScorePoints);
      case "skyDome":
        return getSkyPatches(currentToken, project);
      case "envelope":
        // The file exporting wrote, which the run summary names: a format chosen since without a build has no file yet.
        return getRunSummary(currentToken, project).then((summary) => {
          const meshFile = summary.envelope?.mesh_file;
          return meshFile === undefined ? null : loadMesh(runFileUrl(project, exportedMeshPath(meshFile)), currentToken, meshFormatOf(meshFile), currentOrigin);
        });
      case "massing":
        return loadMesh(runFileUrl(project, MASSING_OBJ_PATH), currentToken, "obj", currentOrigin);
      case "platesFile":
        return getRunFileJson<PlatesFile>(currentToken, project, MASSING_JSON_PATH);
    }
  };

  const fetchResults = useCallback((names: readonly ResultName[]): Promise<void> => {
    const fetches = names.map((name) => {
      const request = (latestRequest.current[name] ?? 0) + 1;
      latestRequest.current[name] = request;
      const keep = (value: RunResults[ResultName]) => {
        if (latestRequest.current[name] === request) setResults((current) => ({ ...current, [name]: value }));
      };
      return fetchResult(name).then(keep).catch((error) => {
        keep(null);
        // A result the stage has not written is a 404 and stays null. Any other failure that is not a refusal may be a lost
        // engine: the app asks GET health before it says so, so a mesh the view cannot read only costs that check.
        const isMissingResult = error instanceof ApiError && error.status === NOT_FOUND;
        if (!isMissingResult && serviceProblemOf(error) !== "other") source.current.onServiceProblem(error);
      });
    });
    return Promise.all(fetches).then(() => undefined);     // each fetch handles its own failure, so none rejects
  }, [project]);

  const reload = useCallback((stages: readonly string[]) => fetchResults(resultsOfStages(stages)), [fetchResults]);

  useEffect(() => {
    reload(stagesWithResults);
  }, []);

  // The meshes are drawn in the local origin of the inputs; new inputs can move it.
  const originKey = origin.join(",");
  const firstOrigin = useRef(originKey);
  useEffect(() => {
    if (originKey === firstOrigin.current) return;
    firstOrigin.current = originKey;
    fetchResults(MESH_RESULTS.filter((name) => results[name] !== null));
  }, [originKey]);

  return [results, reload];
}

interface FollowedRun {
  serial: number | null;
  reloadedStages: Set<string>;
  ended: boolean;
}

/**
 * Fetches again what a run's stages wrote as each one is done, and at the run's end what its unfinished stages left (a
 * cancelled or failed stage removed its old results when it began); calls *onRunEnded* once per run. A run that had ended
 * before the project was opened is not followed again: the project opened with its results. Nothing is fetched for a run whose
 * value the user has left (RunRecord.isSuperseded): its results would show that value until the next run's arrive.
 */
export function useResultsFollowingRun(record: RunRecord | null, reload: (stages: readonly string[]) => void, onRunEnded: (record: RunRecord) => void): void {
  const followed = useRef<FollowedRun>({ serial: record?.serial ?? null, reloadedStages: new Set(), ended: record?.state.final != null });
  const doneStages = record === null ? [] : stagesDone(record.state);
  const progressKey = record === null ? "" : `${record.serial}:${doneStages.join(",")}:${record.state.final}`;
  useEffect(() => {
    if (record === null || record.refusal !== null) return;
    if (followed.current.serial !== record.serial) followed.current = { serial: record.serial, reloadedStages: new Set(), ended: false };
    const run = followed.current;
    if (run.ended) return;
    const stagesToReload = (record.state.final === null ? doneStages : record.state.order).filter((stage) => !run.reloadedStages.has(stage));
    stagesToReload.forEach((stage) => run.reloadedStages.add(stage));
    if (stagesToReload.length > 0 && !(record.isSuperseded?.() ?? false)) reload(stagesToReload);
    if (record.state.final !== null) {
      run.ended = true;
      onRunEnded(record);
    }
  }, [progressKey]);
}

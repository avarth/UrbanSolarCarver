// The results of the project's runs that the steps and the 3D view show: the run summary, the score points, the sky dome, the
// envelope and building massing meshes and plates.json. Each is fetched again when a stage that writes it has run (UX 6.3:
// results arrive stage by stage), and the result of the last request wins. A result a stage has not written (yet) is null. The
// score points and the sky dome are those of the selected criterion: another criterion selected fetches them again, and so does
// the selected one gaining results in its stage status (turned back on after a bypass).
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
import { criterionOfKey, runStages, stageOfKey, stagesDone, type RunRecord } from "./run_state";
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
/** The results of one criterion (the summary holds every criterion's numbers). */
const CRITERION_RESULTS: ResultName[] = ["scorePoints", "skyDome"];
const NOT_FOUND = 404;

export function resultsOfStages(stages: readonly string[]): ResultName[] {
  return [...new Set(stages.flatMap((stage) => RESULTS_OF_STAGE[stage as PipelineStage] ?? []))];
}

/**
 * What to fetch when the project opens: the results of the project's stages, and the score points and sky dome only when the
 * selected criterion's own stages wrote them (given as *criterionStages*; absent: as the project's).
 */
export function resultsAtOpen(stages: readonly string[], criterionStages?: readonly string[]): ResultName[] {
  if (criterionStages === undefined) return resultsOfStages(stages);
  const ofCriterion = resultsOfStages(criterionStages).filter((name) => CRITERION_RESULTS.includes(name));
  return [...new Set([...resultsOfStages(stages).filter((name) => !CRITERION_RESULTS.includes(name)), ...ofCriterion])];
}

interface RunResultsSource {
  token: string;
  project: string;
  /** The local origin the meshes are drawn in; a new one reloads them. */
  origin: Point3;
  /** The stages with results when the project opens. */
  stagesWithResults: readonly string[];
  /** The criterion whose score points and sky dome are shown; absent: the service's default (the last criterion that is on). */
  criterionId?: string;
  /** That criterion's stages with output: its score points and sky dome are asked for only when they are there (no 404s). */
  criterionStagesWithResults?: readonly string[];
  onServiceProblem: (error: unknown) => void;
}

/**
 * The results, the function that fetches again what the given stages write (its promise resolves once every fetch has ended),
 * and the one that fetches the run summary again.
 */
export function useRunResults({ token, project, origin, stagesWithResults, criterionId, criterionStagesWithResults, onServiceProblem }: RunResultsSource): [RunResults, (stages: readonly string[]) => Promise<void>, () => Promise<void>] {
  const [results, setResults] = useState<RunResults>(NO_RESULTS);
  const latestRequest = useRef<Partial<Record<ResultName, number>>>({});
  const source = useRef({ token, origin, criterionId, onServiceProblem });
  source.current = { token, origin, criterionId, onServiceProblem };

  /** *summary*: the run summary of this round of fetches, asked for once however many results read it. */
  const fetchResult = (name: ResultName, summary: () => Promise<RunSummary>): Promise<RunResults[ResultName]> => {
    const { token: currentToken, origin: currentOrigin, criterionId: currentCriterion } = source.current;
    switch (name) {
      case "summary":
        return summary();
      case "scorePoints":
        return getScorePoints(currentToken, project, currentCriterion).then(decodeScorePoints);
      case "skyDome":
        return getSkyPatches(currentToken, project, currentCriterion);
      case "envelope":
        // The file exporting wrote, which the run summary names: a format chosen since without a build has no file yet.
        return summary().then((reply) => {
          const meshFile = reply.envelope?.mesh_file;
          return meshFile === undefined ? null : loadMesh(runFileUrl(project, exportedMeshPath(meshFile)), currentToken, meshFormatOf(meshFile), currentOrigin);
        });
      case "massing":
        return loadMesh(runFileUrl(project, MASSING_OBJ_PATH), currentToken, "obj", currentOrigin);
      case "platesFile":
        return getRunFileJson<PlatesFile>(currentToken, project, MASSING_JSON_PATH);
    }
  };

  // The score points and sky dome asked for since the criterion shown was selected (or the project opened).
  const askedOfCriterion = useRef(new Set<ResultName>());

  const fetchResults = useCallback((names: readonly ResultName[]): Promise<void> => {
    names.filter((name) => CRITERION_RESULTS.includes(name)).forEach((name) => askedOfCriterion.current.add(name));
    let summaryRequest: Promise<RunSummary> | null = null;
    const summary = () => (summaryRequest ??= getRunSummary(source.current.token, project));
    const fetches = names.map((name) => {
      const request = (latestRequest.current[name] ?? 0) + 1;
      latestRequest.current[name] = request;
      const keep = (value: RunResults[ResultName]) => {
        if (latestRequest.current[name] === request) setResults((current) => ({ ...current, [name]: value }));
      };
      return fetchResult(name, summary).then(keep).catch((error) => {
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
    fetchResults(resultsAtOpen(stagesWithResults, criterionStagesWithResults));
  }, []);

  // Another criterion selected: its score points and sky dome replace the last one's, which are not shown meanwhile.
  const writtenOfCriterion = criterionStagesWithResults === undefined ? CRITERION_RESULTS
    : resultsOfStages(criterionStagesWithResults).filter((name) => CRITERION_RESULTS.includes(name));
  const firstCriterion = useRef(criterionId);
  useEffect(() => {
    if (criterionId === firstCriterion.current) return;
    firstCriterion.current = criterionId;
    setResults((current) => ({ ...current, scorePoints: null, skyDome: null }));
    // A request still out for the criterion before is not kept.
    for (const name of CRITERION_RESULTS) latestRequest.current[name] = (latestRequest.current[name] ?? 0) + 1;
    askedOfCriterion.current = new Set();
    fetchResults(writtenOfCriterion);
  }, [criterionId]);

  // The criterion shown gains results it had not (it is turned back on after a bypass, and its stage status lists its stages
  // again): they are fetched, unless already asked for (a run that wrote them fetched them as it ended).
  const writtenKey = writtenOfCriterion.join(",");
  const lastWrittenKey = useRef(writtenKey);
  useEffect(() => {
    if (writtenKey === lastWrittenKey.current) return;          // unchanged, or at open, where resultsAtOpen decides
    lastWrittenKey.current = writtenKey;
    const notAskedFor = writtenOfCriterion.filter((name) => !askedOfCriterion.current.has(name));
    if (criterionId === firstCriterion.current && notAskedFor.length > 0) fetchResults(notAskedFor);
  }, [writtenKey]);

  // The meshes are drawn in the local origin of the inputs; new inputs can move it.
  const originKey = origin.join(",");
  const firstOrigin = useRef(originKey);
  useEffect(() => {
    if (originKey === firstOrigin.current) return;
    firstOrigin.current = originKey;
    fetchResults(MESH_RESULTS.filter((name) => results[name] !== null));
  }, [originKey]);

  const reloadSummary = useCallback(() => fetchResults(["summary"]), [fetchResults]);
  return [results, reload, reloadSummary];
}

interface FollowedRun {
  serial: number | null;
  reloadedStages: Set<string>;
  /** The criteria whose thresholding the run has done (onCriterionCarved). */
  carvedCriteria: Set<string>;
  ended: boolean;
}

/**
 * Fetches again what a run's stages wrote as each one is done, and at the run's end what its unfinished stages left (a
 * cancelled or failed stage removed its old results when it began); calls *onRunEnded* once per run. A run that had ended
 * before the project was opened is not followed again: the project opened with its results. Nothing is fetched for a run whose
 * value the user has left (RunRecord.isSuperseded): its results would show that value until the next run's arrive. With
 * several criteria, *onCriterionCarved* is called once for each criterion whose thresholding is done while the run still has the
 * thresholding of others to do (the stage's results are fetched again once it is done for every criterion).
 */
export function useResultsFollowingRun(record: RunRecord | null, reload: (stages: readonly string[]) => void, onRunEnded: (record: RunRecord) => void,
                                       onCriterionCarved?: (criterionId: string) => void): void {
  const followed = useRef<FollowedRun>({ serial: record?.serial ?? null, reloadedStages: new Set(), carvedCriteria: new Set(), ended: record?.state.final != null });
  const doneStages = record === null ? [] : stagesDone(record.state);
  const doneKeys = record === null ? [] : record.state.order.filter((key) => record.state.stages[key].state === "done");
  const progressKey = record === null ? "" : `${record.serial}:${doneKeys.join(",")}:${record.state.final}`;
  useEffect(() => {
    if (record === null || record.refusal !== null) return;
    if (followed.current.serial !== record.serial) followed.current = { serial: record.serial, reloadedStages: new Set(), carvedCriteria: new Set(), ended: false };
    const run = followed.current;
    if (run.ended) return;
    const superseded = record.isSuperseded?.() ?? false;
    const stagesToReload = (record.state.final === null ? doneStages : runStages(record.state)).filter((stage) => !run.reloadedStages.has(stage));
    stagesToReload.forEach((stage) => run.reloadedStages.add(stage));
    if (stagesToReload.length > 0 && !superseded) reload(stagesToReload);
    if (record.state.final === null && !run.reloadedStages.has("thresholding")) {
      for (const key of doneKeys) {
        const criterion = criterionOfKey(key);
        if (criterion === null || stageOfKey(key) !== "thresholding" || run.carvedCriteria.has(criterion)) continue;
        run.carvedCriteria.add(criterion);
        if (!superseded) onCriterionCarved?.(criterion);
      }
    }
    if (record.state.final !== null) {
      run.ended = true;
      onRunEnded(record);
    }
  }, [progressKey]);
}

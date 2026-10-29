// A start refused because criteria that are on protect nothing (MissingInputsReply naming "test_surfaces:<id>", spec 7.2, 7.3):
// the first of them is selected (unless one of them is selected already) and its editor is shown, and its panel asks for test
// surfaces until its files change or another run is asked for. The Criteria bar's Run analysis and carving update say the refusal under their button, so
// the panel asks only for a refusal of a button elsewhere (Site and grid), and never says it twice.
import { useEffect, useMemo, useRef } from "react";
import type { CriterionEntry } from "../api_client/client";
import { messages } from "../messages";
import type { RunOrigin, RunRecord } from "../steps/run_state";

const TEST_SURFACES_ROLE_PREFIX = "test_surfaces:";
/** The runs whose progress and outcome are shown in the bar pinned under the Criteria step. */
const ORIGINS_IN_CRITERIA_BAR: readonly RunOrigin[] = ["carving_run_analysis", "carving_update"];

/** A criterion's test surface files as one string, to tell whether they changed. */
function testSurfaceFilesKey(criteria: CriterionEntry[], id: string): string {
  return (criteria.find((entry) => entry.id === id)?.test_surface_files ?? []).join("\n");
}

interface RefusalSelectionSource {
  /** The last run of the project (its refusal, when the service refused to start it); null when none. */
  record: RunRecord | null;
  criteria: CriterionEntry[];
  selectedId: string;
  /** The criterion whose panel is shown; null when the project lists none. */
  shownCriterion: CriterionEntry | null;
  /** Selects a card as a press does and shows its editor (useCriterionSelection's showCriterion, whose onShowCriterion opens the editor). */
  showCriterion: (id: string) => void;
}

/** What the shown criterion's panel says over its settings about the refusal: "Add test surfaces to {name}.", or null. */
export function useRefusalSelection({ record, criteria, selectedId, shownCriterion, showCriterion }: RefusalSelectionSource): string | null {
  const askedFor = record?.missingInputs?.filter((role) => role.startsWith(TEST_SURFACES_ROLE_PREFIX))
    .map((role) => role.slice(TEST_SURFACES_ROLE_PREFIX.length)) ?? [];
  const filesWhenRefused = useMemo(() => Object.fromEntries(askedFor.map((id) => [id, testSurfaceFilesKey(criteria, id)])), [record?.serial]);
  const refusalSeen = useRef(record?.serial ?? null);
  useEffect(() => {
    if (record === null || record.serial === refusalSeen.current) return;
    refusalSeen.current = record.serial;
    if (askedFor.length > 0) showCriterion(askedFor.includes(selectedId) ? selectedId : askedFor[0]);
  }, [record?.serial]);
  const asksHere = shownCriterion !== null && record !== null && !ORIGINS_IN_CRITERIA_BAR.includes(record.origin) && askedFor.includes(shownCriterion.id)
    && filesWhenRefused[shownCriterion.id] === testSurfaceFilesKey(criteria, shownCriterion.id);
  return asksHere ? messages.addTestSurfacesTo(shownCriterion.name) : null;
}

// What the Criteria step shows the first time it opens after the project opens: a project with one criterion opens on its editor
// (there is nothing to choose from), with two or more on the list. From then on the workspace keeps what the step showed.
import type { CriteriaShows } from "./CriteriaStep";

/** What the Criteria step shows first, for a project of *criterionCount* criteria: the editor for one, the list otherwise (none included). */
export function firstCriteriaShows(criterionCount: number): CriteriaShows {
  return criterionCount === 1 ? "editor" : "list";
}

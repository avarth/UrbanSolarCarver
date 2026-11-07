// The result card in the bottom right corner of Simulate's view (simulate design, section 3), for the selected study: what its points
// keep of the no-build value (the sum of their values over the sum with nothing built), the mean, the lowest tenth (10th percentile)
// and, with a target, the share of points at or above it. The points on the faces of the study's geometry have a block of their own
// ("The massing"), with a table of the same by the way they face (roofs, then the facades by compass point), so the ground and the
// surroundings do not hide what the building gets; the study's other surfaces are the first block. A block without points is left out,
// and a result without test points shows no card. The card minimises to its title bar, and the table by facing is a fold, closed at
// first, so the card stays small over the view.
import { useState } from "react";
import { messages } from "../messages";
import { formatPercent, formattedNumber, withUnit } from "../format_numbers";
import { FACING_GROUPS, type FacingGroup, type StudyGeometry, type StudyStatistics } from "../viewer/study_values";

export interface ResultCardProps {
  unit: string;
  /** The study's files, the surroundings, the terrain and the ground; null when the study samples none of them. */
  surroundings: StudyStatistics | null;
  /** The faces of the study's geometry, whole and by facing; null when the study does not sample them. */
  building: { stand: StudyGeometry; statistics: StudyStatistics; byFacing: Record<FacingGroup, StudyStatistics | null> } | null;
  /** A quick sun hours result counted the sun on every this many days: the card says so. 1 (the default) for an exact count. */
  sunDayStep?: number;
}

const percentOf = (share: number) => formatPercent(Math.round(share * 100));

function linesOf(statistics: StudyStatistics, unit: string): string[] {
  const lines = [
    ...(statistics.keptShare == null ? [] : [messages.resultKept(percentOf(statistics.keptShare))]),
    messages.resultMean(withUnit(formattedNumber(statistics.mean), unit)),
    messages.resultLowestTenth(withUnit(formattedNumber(statistics.lowestTenth), unit)),
  ];
  if (statistics.shareAtTarget !== null) lines.push(messages.resultAtTarget(percentOf(statistics.shareAtTarget)));
  return lines;
}

const hasPoints = (statistics: StudyStatistics | null): statistics is StudyStatistics => statistics !== null && !Number.isNaN(statistics.mean);

export function ResultCard({ unit, surroundings, building, sunDayStep = 1 }: ResultCardProps) {
  const others = hasPoints(surroundings) ? surroundings : null;
  const own = building !== null && hasPoints(building.statistics) ? building : null;
  const [minimised, setMinimised] = useState(false);
  if (others === null && own === null) return null;           // a result without test points has nothing to say
  const withTarget = own !== null && own.statistics.shareAtTarget !== null;
  const facings = own === null ? [] : FACING_GROUPS.filter((group) => hasPoints(own.byFacing[group]));
  return (
    <section className={`viewer-overlay result-card${minimised ? " result-card-minimised" : ""}`} aria-label={messages.resultCard}>
      <div className="result-card-header">
        <span className="result-card-title">{messages.resultCard}</span>
        <button type="button" className="result-card-toggle" aria-expanded={!minimised}
                aria-label={minimised ? messages.resultCardShow : messages.resultCardMinimise} title={minimised ? messages.resultCardShow : messages.resultCardMinimise}
                onClick={() => setMinimised(!minimised)}>
          <span aria-hidden="true">{minimised ? "+" : "\u2212"}</span>
        </button>
      </div>
      {!minimised && sunDayStep > 1 && <p className="result-card-note">{messages.resultQuick(sunDayStep)}</p>}
      {!minimised && others !== null && (
        <div className="result-card-block">
          {own !== null && <h3>{messages.resultSurroundings}</h3>}
          <ul>{linesOf(others, unit).map((line) => <li key={line} className="result-card-line">{line}</li>)}</ul>
        </div>
      )}
      {!minimised && own !== null && (
        <div className="result-card-block result-card-building">
          <h3>{messages.resultBuilding[own.stand]}</h3>
          <ul>{linesOf(own.statistics, unit).map((line) => <li key={line} className="result-card-line">{line}</li>)}</ul>
          {facings.length > 0 && (
            <details className="result-card-facings-fold">
            <summary>{messages.resultByFacing}</summary>
            <table className="result-card-facings" aria-label={messages.resultByFacing}>
              <thead>
                <tr>
                  <th scope="col">{messages.resultFacingColumns.facing}</th>
                  <th scope="col">{messages.resultFacingColumns.mean}</th>
                  <th scope="col">{messages.resultFacingColumns.lowestTenth}</th>
                  {withTarget && <th scope="col">{messages.resultFacingColumns.atTarget}</th>}
                </tr>
              </thead>
              <tbody>
                {facings.map((group) => {
                  const statistics = own.byFacing[group]!;
                  return (
                    <tr key={group} className="result-card-facing" data-facing={group}>
                      <th scope="row">{messages.resultFacings[group]}</th>
                      <td>{formattedNumber(statistics.mean)}</td>
                      <td>{formattedNumber(statistics.lowestTenth)}</td>
                      {withTarget && <td>{statistics.shareAtTarget === null ? "" : percentOf(statistics.shareAtTarget)}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

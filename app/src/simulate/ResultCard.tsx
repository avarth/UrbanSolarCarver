// The result card in the bottom right corner of Simulate's view (simulate design, section 3): for the selected study on the geometry
// shown, the mean, the lowest tenth (10th percentile) and, with a target, the share of points at or above it; each with the
// maximum volume's value in brackets, which the heading names: "mean 3.6 h (4.1)".
import { messages } from "../messages";
import { formatPercent, formattedNumber, withUnit } from "../steps/format_numbers";
import type { StudyGeometry, StudyStatistics } from "./study_values";

export interface ResultCardProps {
  geometry: StudyGeometry;
  unit: string;
  statistics: StudyStatistics;
  /** The maximum volume's statistics; null on the maximum volume itself. */
  baseline: StudyStatistics | null;
}

const percentOf = (share: number) => formatPercent(Math.round(share * 100));

export function ResultCard({ geometry, unit, statistics, baseline }: ResultCardProps) {
  const besideIt = (value: string | null) => (baseline === null || value === null ? "" : ` (${value})`);
  const lines = [
    messages.resultMean(withUnit(formattedNumber(statistics.mean), unit)) + besideIt(baseline && formattedNumber(baseline.mean)),
    messages.resultLowestTenth(withUnit(formattedNumber(statistics.lowestTenth), unit)) + besideIt(baseline && formattedNumber(baseline.lowestTenth)),
  ];
  if (statistics.shareAtTarget !== null) {
    const baselineShare = baseline?.shareAtTarget ?? null;
    lines.push(messages.resultAtTarget(percentOf(statistics.shareAtTarget)) + besideIt(baselineShare === null ? null : String(Math.round(baselineShare * 100))));
  }
  return (
    <section className="viewer-overlay result-card" aria-label={messages.resultCard}>
      <h3>
        {messages.studyGeometries[geometry]}
        {baseline !== null && <span className="result-card-baseline"> ({messages.studyGeometries.max_volume})</span>}
      </h3>
      <ul>
        {lines.map((line) => <li key={line} className="result-card-line">{line}</li>)}
      </ul>
    </section>
  );
}

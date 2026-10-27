// The geometry switch at the top centre of Simulate's view (simulate design, section 3): Max volume | Envelope | Massing, the
// geometry the selected study's values are shown on. Envelope and Massing wait, with the reason as their tooltip, until Design has
// built them, and while the selected study's last result does not have them (it ran before they were built); one Design shows out
// of date is marked so. Beside it Change, which colours each point by its change from the maximum
// volume (the baseline), and so waits on the maximum volume itself. The segments are toggle buttons in a labelled group; a button
// that waits stays focusable (aria-disabled), so its tooltip and reason can be reached.
import { useId } from "react";
import { messages } from "../messages";
import { STUDY_GEOMETRIES, type StudyGeometry } from "./study_values";

export interface GeometrySwitchProps {
  /** The geometries that can be shown: the maximum volume, and the envelope and the massing once built. */
  available: readonly StudyGeometry[];
  /** The geometries Design shows out of date. */
  outOfDateInDesign: readonly StudyGeometry[];
  /** Built geometries the selected study's last result does not have: they wait for a new run of the study. */
  waitingForStudy?: readonly StudyGeometry[];
  value: StudyGeometry;
  /** Colour by the change from the maximum volume. */
  change: boolean;
  onChange: (geometry: StudyGeometry) => void;
  onChangeToggle: (change: boolean) => void;
}

export function GeometrySwitch({ available, outOfDateInDesign, waitingForStudy = [], value, change, onChange, onChangeToggle }: GeometrySwitchProps) {
  const id = useId();
  const segments = STUDY_GEOMETRIES.map((geometry) => {
    const waitReason = geometry === "max_volume" ? null : !available.includes(geometry) ? messages.buildGeometryFirst[geometry]
      : waitingForStudy.includes(geometry) ? messages.runStudyAgainFor[geometry] : null;
    const outOfDate = waitReason === null && outOfDateInDesign.includes(geometry);
    return { geometry, waitReason, outOfDate, note: waitReason ?? (outOfDate ? messages.outOfDateInDesign : null), noteId: `${id}-${geometry}` };
  });
  const changeWaits = value === "max_volume";
  const changeNoteId = `${id}-change`;
  return (
    <div className="geometry-switch">
      <div className="geometry-switch-segments" role="group" aria-label={messages.geometrySwitch}>
        {segments.map(({ geometry, waitReason, outOfDate, note, noteId }) => (
          <button key={geometry} type="button" className="geometry-switch-segment" aria-pressed={geometry === value}
                  aria-disabled={waitReason === null ? undefined : true} title={note ?? undefined} aria-describedby={note === null ? undefined : noteId}
                  onClick={() => { if (waitReason === null && geometry !== value) onChange(geometry); }}>
            {messages.studyGeometries[geometry]}
            {outOfDate && <span className="geometry-switch-stale" aria-hidden="true" />}
          </button>
        ))}
      </div>
      <button type="button" className="geometry-switch-change" aria-pressed={change && !changeWaits} aria-disabled={changeWaits ? true : undefined}
              title={changeWaits ? messages.changeNeedsGeometry : messages.changeToggleHint} aria-describedby={changeWaits ? changeNoteId : undefined}
              onClick={() => { if (!changeWaits) onChangeToggle(!change); }}>
        {messages.changeToggle}
      </button>
      {/* The reasons and marks the buttons name (aria-describedby), read but not shown: their tooltips show them. */}
      {segments.map(({ note, noteId }) => note !== null && <span key={noteId} id={noteId} hidden>{note}</span>)}
      {changeWaits && <span id={changeNoteId} hidden>{messages.changeNeedsGeometry}</span>}
    </div>
  );
}

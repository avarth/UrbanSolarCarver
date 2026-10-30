// The Files panel of Inspect (inspect design, sections 3, 5 and 6): small, floating over the top left of the 3D view as Simulate's
// studies panel, collapsible to an icon button. The input mesh files by role (maximum volume, test surfaces, existing surroundings,
// terrain), each row with its triangle count and area; a file that cannot be read shows why, with nothing to select. A press on a row
// selects the file (the view frames it) and opens its summary: its bounds, a note when they are far from zero and,
// for a test surface file, its surfaces. The selected test surface file's row has Flip mode and Flip all; a file with turns not saved
// says how many, with Save and Discard; a file whose original is kept offers Restore original. Save and Restore wait while a run of
// the project goes on, as uploads do. Face normals, at the top, draws one normal per surface.
import { useId, useState, type ReactNode } from "react";
import type { InspectedFile } from "../api_client/client";
import { messages } from "../messages";
import { SettingTooltip } from "../settings_form/SettingTooltip";
import { formattedNumber } from "../steps/format_numbers";
import type { Point3 } from "../viewer/local_origin";
import { TEST_SURFACES_ROLE, type InspectionHook } from "./use_inspection";
import "./inspect.css";

const INSPECT_ROLES = ["max_volume", TEST_SURFACES_ROLE, "context", "terrain"] as const;
// Bounds with a corner further than this from zero are in georeferenced coordinates (a site's projected system), not a local one.
const FAR_FROM_ZERO_METRES = 10_000;

/** How far the bounds' furthest corner lies from zero, in metres. */
export function furthestCornerDistance(bounds: number[][]): number {
  const [min, max] = bounds;
  return Math.hypot(...min.map((low, axis) => Math.max(Math.abs(low), Math.abs(max[axis]))));
}

export interface FilesPanelProps {
  inspection: InspectionHook;
  /** The local origin the view is drawn around, stated under the list. */
  origin: Point3;
  /** Why Save and Restore original cannot be pressed now (a run of the project); null when they can. */
  saveDisabledReason: string | null;
  /** The notice of input files changed in the project folder or missing from it, at the top of the body. */
  notice?: ReactNode;
}

function FilesIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M4 2h7l3 3v11H4z" strokeLinejoin="round" />
      <path d="M7 9h4M7 12h4" strokeLinecap="round" />
    </svg>
  );
}

const number = formattedNumber;

function FileSummary({ file }: { file: InspectedFile }) {
  const [min, max] = file.bounds;
  const distance = furthestCornerDistance(file.bounds);
  // No closed-bodies line: CAD exports keep a corner per face, so faces share no edges and every body counted open, while the
  // voxelizer's three-axis vote fills such volumes as closed ones (user, 2026-10-28: "0 everywhere").
  return (
    <div className="inspect-summary">
      <p>{messages.inspectBounds(number(min[0]), number(max[0]), number(min[1]), number(max[1]), number(min[2]), number(max[2]))}</p>
      {distance > FAR_FROM_ZERO_METRES && <p>{messages.georeferencedCoordinates(distance / 1000)}</p>}
      {file.surface_count != null && <p>{messages.inspectSurfaces(file.surface_count)}</p>}
    </div>
  );
}

function FileRow({ file, inspection, saveDisabledReason }: { file: InspectedFile; inspection: InspectionHook; saveDisabledReason: string | null }) {
  const flipReasonId = useId();
  const saveReasonId = useId();
  const { selected, busy } = inspection;
  const name = file.file_name;
  const isSelected = selected !== null && selected.role === file.role && selected.file_name === name;
  const isTestSurface = file.role === TEST_SURFACES_ROLE;
  const turnedCount = isTestSurface ? inspection.turned.get(name)?.size ?? 0 : 0;
  if (file.problem != null) {
    return (
      <li className="inspect-file inspect-file-unreadable" data-file-name={name} data-role={file.role}>
        <span className="inspect-file-name">{name}</span>
        <span className="inspect-file-problem">{file.problem}</span>
      </li>
    );
  }
  const offersRestore = isSelected && isTestSurface && file.original_kept;
  const saveWaits = saveDisabledReason !== null && (turnedCount > 0 || offersRestore);
  const saveDescribedBy = saveDisabledReason !== null ? saveReasonId : undefined;
  const flipDescribedBy = file.flippable ? undefined : flipReasonId;
  return (
    <li className="inspect-file" aria-current={isSelected || undefined} data-file-name={name} data-role={file.role}>
      <button type="button" className="inspect-file-select" onClick={() => inspection.select(file)}>
        <span className="inspect-file-name">{name}</span>
        <span className="inspect-file-line">{messages.inspectFileLine(file.triangle_count, file.area_m2)}</span>
        {turnedCount > 0 && <span className="inspect-file-turned">{messages.surfacesTurnedNotSaved(turnedCount)}</span>}
      </button>
      {isSelected && <FileSummary file={file} />}
      {isSelected && isTestSurface && (
        <div className="inspect-file-actions">
          <button type="button" className="secondary-button inspect-flip-mode" aria-pressed={inspection.flipMode} disabled={!file.flippable}
                  aria-describedby={flipDescribedBy} onClick={() => inspection.setFlipMode(!inspection.flipMode)}>
            {messages.flipMode}
          </button>
          <button type="button" className="secondary-button" disabled={!file.flippable} aria-describedby={flipDescribedBy}
                  onClick={() => inspection.flipAll(name)}>
            {messages.flipAll}
          </button>
        </div>
      )}
      {isSelected && isTestSurface && !file.flippable && <p id={flipReasonId} className="run-button-reason">{messages.closedAsWhole}</p>}
      {(turnedCount > 0 || offersRestore) && (
        <div className="inspect-file-actions">
          {turnedCount > 0 && (
            <>
              <button type="button" className="primary-button" disabled={busy || saveDisabledReason !== null} aria-describedby={saveDescribedBy}
                      onClick={() => void inspection.save(name)}>
                {messages.saveTurns}
              </button>
              <button type="button" className="secondary-button" disabled={busy} onClick={() => inspection.discard(name)}>{messages.discardTurns}</button>
            </>
          )}
          {offersRestore && (
            <button type="button" className="secondary-button" disabled={busy || saveDisabledReason !== null} aria-describedby={saveDescribedBy}
                    onClick={() => void inspection.restore(name)}>
              {messages.restoreOriginal}
            </button>
          )}
        </div>
      )}
      {saveWaits && <p id={saveReasonId} className="run-button-reason">{saveDisabledReason}</p>}
    </li>
  );
}

export function FilesPanel({ inspection, origin, saveDisabledReason, notice }: FilesPanelProps) {
  const [open, setOpen] = useState(true);
  const bodyId = useId();
  const titleId = useId();
  const files = inspection.reply?.files ?? [];
  const roles = INSPECT_ROLES.filter((role) => files.some((file) => file.role === role));
  return (
    <section className={`files-panel ${open ? "files-panel-open" : "files-panel-collapsed"}`} aria-labelledby={open ? titleId : undefined}
             aria-label={open ? undefined : messages.inspectFilesTitle}>
      <div className="files-panel-header">
        <button type="button" className="files-panel-toggle" aria-label={messages.inspectFilesTitle} aria-expanded={open}
                aria-controls={open ? bodyId : undefined} title={messages.inspectFilesTitle} onClick={() => setOpen((shown) => !shown)}>
          <FilesIcon />
        </button>
        {open && <h2 id={titleId} className="files-panel-title">{messages.inspectFilesTitle}</h2>}
        {open && inspection.reply !== null && (
          <SettingTooltip settingLabel={messages.inspectViewOriginLabel} help={messages.inspectViewOrigin(number(origin[0]), number(origin[1]), number(origin[2]))} />
        )}
      </div>
      {open && (
        <div id={bodyId} className="files-panel-body">
          {notice}
          {inspection.problem !== null && <p className="files-panel-problem" role="alert">{inspection.problem}</p>}
          <label className="inspect-arrows">
            <input type="checkbox" checked={inspection.arrows} onChange={(event) => inspection.setArrows(event.target.checked)} />
            {messages.inspectArrows}
          </label>
          {roles.map((role) => (
            <section key={role} className="inspect-role">
              <h3 className="inspect-role-title">{messages.layerNames[role]}</h3>
              <ul className="inspect-file-list">
                {files.filter((file) => file.role === role).map((file) => (
                  <FileRow key={file.file_name} file={file} inspection={inspection} saveDisabledReason={saveDisabledReason} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

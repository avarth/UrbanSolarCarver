// What a criterion protects (spec 7.2, design/test-surfaces-on-context.md): one switch per surface set of the project, on for the
// sets the criterion uses, under the hint of what its mode may protect. The sets are added, picked and named in the Site step
// (SurfaceSetsBox); without any the section says so, with a link there.
import { useState } from "react";
import type { InputFileInfo } from "../api_client/client";
import { protectsHintOf } from "../common/SurfaceSetsBox";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import "../theme/panels.css";

interface SurfaceSetSwitchesProps {
  /** The project's surface sets. */
  sets: InputFileInfo[];
  /** The file names of the sets the criterion uses. */
  chosen: readonly string[];
  /** The criterion's mode, whose hint the section gives. */
  mode: string;
  /** Switches a set on or off for the criterion; resolves with the reason it could not, or null. */
  onToggle: (fileName: string, on: boolean) => Promise<string | null>;
  /** Opens the Site step, where sets are added. */
  onOpenSite: () => void;
  /** Why sets cannot be switched now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The sets the 3D view cannot draw, one text each naming the file. */
  drawingProblems?: string[];
}

export function SurfaceSetSwitches({ sets, chosen, mode, onToggle, onOpenSite, disabledReason, drawingProblems = [] }: SurfaceSetSwitchesProps) {
  const [problem, setProblem] = useState<string | null>(null);
  const toggle = async (fileName: string, on: boolean) => {
    setProblem(null);
    setProblem(await onToggle(fileName, on));
  };
  return (
    <div className="surface-set-switches">
      <p className="input-box-hint">{protectsHintOf(mode)}</p>
      {sets.length === 0 ? (
        <p className="surface-set-note">
          {messages.noSurfaceSets}{" "}
          <button type="button" className="link-button" onClick={onOpenSite}>{messages.openSiteStep}</button>
        </p>
      ) : (
        <div className="surface-set-list">
          {sets.map((set) => {
            const name = set.shown_name ?? set.name;
            return (
              <label key={set.name} className="surface-set-row" title={set.shown_name !== set.name ? set.name : undefined}>
                <span className="surface-set-label">
                  <span className="input-file-name">{name}</span>
                  <span className="input-file-detail">{messages.triangleCount(set.triangle_count)}</span>
                </span>
                <input type="checkbox" role="switch" className="setting-switch" aria-label={messages.useSurfaceSet(name)} checked={chosen.includes(set.name)}
                       disabled={disabledReason !== null} onChange={(event) => void toggle(set.name, event.target.checked)} />
              </label>
            );
          })}
        </div>
      )}
      {[...(problem === null ? [] : [problem]), ...drawingProblems].map((text) => <p key={text} className="input-box-problem"><WarningIcon />{text}</p>)}
    </div>
  );
}

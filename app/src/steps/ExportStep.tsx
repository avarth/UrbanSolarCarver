// The Export step (UX 5.7): the mesh file format of the carved envelope, whose change reruns the envelope mesh only, and the
// downloads: the envelope in that format, the building massing (OBJ) and its data (JSON), the settings (config.yaml) and the
// whole project as a zip. Each file of a stage is offered once the stage exists (R2 5: the envelope and the massing are built
// on their own); one built from settings that changed since is labelled out of date and can still be downloaded.
// The files are fetched with the token and handed to the browser to save (a plain link cannot send the token header).
import type { ReactNode } from "react";
import { projectConfigUrl, projectDownloadUrl, runFileUrl } from "../api_client/client";
import { messages } from "../messages";
import type { FormState } from "../settings_form/form_state";
import { settingView } from "../settings_form/presentation";
import { SettingField, WarningIcon } from "../settings_form/SettingField";
import type { StageState } from "./step_summaries";
import "./steps.css";

export interface ExportDownload {
  label: string;
  address: string;
  fileName: string;
  outOfDate: boolean;
}

export const MASSING_OBJ_PATH = "massing/plates.obj";
export const MASSING_JSON_PATH = "massing/plates.json";

export function exportedMeshPath(meshFormat: string): string {
  return `exporting/export.${meshFormat}`;
}

interface DownloadListState {
  project: string;
  meshFormat: string;
  /** The stage status of exporting and of massing. */
  envelope: StageState;
  massing: StageState;
}

/** The files of the Export step, in the order of UX 5.7, the envelope's and the massing's once their stage exists. */
export function exportDownloads({ project, meshFormat, envelope, massing }: DownloadListState): ExportDownload[] {
  const formatName = messages.meshFormatNames[meshFormat as keyof typeof messages.meshFormatNames] ?? meshFormat.toUpperCase();
  const envelopeFiles: ExportDownload[] = envelope === "missing" ? [] : [
    { label: messages.envelopeMeshDownload(formatName), address: runFileUrl(project, exportedMeshPath(meshFormat)),
      fileName: `${project} envelope.${meshFormat}`, outOfDate: envelope === "out_of_date" },
  ];
  const massingOutOfDate = massing === "out_of_date";
  const massingFiles: ExportDownload[] = massing === "missing" ? [] : [
    { label: messages.massingObjDownload, address: runFileUrl(project, MASSING_OBJ_PATH), fileName: `${project} massing.obj`, outOfDate: massingOutOfDate },
    { label: messages.massingJsonDownload, address: runFileUrl(project, MASSING_JSON_PATH), fileName: `${project} massing.json`, outOfDate: massingOutOfDate },
  ];
  return [
    ...envelopeFiles,
    ...massingFiles,
    { label: messages.settingsDownload, address: projectConfigUrl(project), fileName: "config.yaml", outOfDate: false },
    { label: messages.projectZipDownload, address: projectDownloadUrl(project), fileName: `${project}.zip`, outOfDate: false },
  ];
}

interface ExportStepProps {
  form: FormState;
  downloads: ExportDownload[];
  /** Why the format cannot be changed now (a run); null when it can. */
  disabledReason: string | null;
  /** Why a format change is stored without rebuilding the envelope (Carving is locked); null when it rebuilds it. */
  formatRunReason: string | null;
  onFormatChange: (meshFormat: string) => void;
  onDownload: (download: ExportDownload) => void;
  /** The progress and outcome of the envelope mesh run a format change started. */
  formatFeedback: ReactNode;
  /** Why the last download failed, in the service's words; null when it did not. */
  downloadProblem: string | null;
}

export function ExportStep({ form, downloads, disabledReason, formatRunReason, onFormatChange, onDownload, formatFeedback, downloadProblem }: ExportStepProps) {
  return (
    <div className="export-step">
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      <SettingField view={settingView("final_mesh_format", form.mode)} form={form} disabled={disabledReason !== null}
                    extras={formatRunReason === null ? undefined : { note: formatRunReason }}
                    onChange={(values) => onFormatChange(String(values.final_mesh_format))} />
      {formatFeedback}
      <ul className="download-list">
        {downloads.map((download) => (
          <li key={download.label}>
            <button type="button" className="link-button" onClick={() => onDownload(download)}>{download.label}</button>
            {download.outOfDate && <span className="out-of-date-tag">{messages.outOfDateFile}</span>}
          </li>
        ))}
      </ul>
      {downloadProblem !== null && <p className="setting-error"><WarningIcon /><span>{downloadProblem}</span></p>}
    </div>
  );
}

// The Export step (UX 5.7): the mesh file format of the carved envelope, whose change reruns the envelope mesh only, and the
// downloads: the envelope file that was built (named by the run summary; a format chosen while Carving was locked is stored
// and written by the next envelope build, which the download says), the building massing (OBJ) and its data (JSON), the
// settings (config.yaml) and the whole project as a zip. Each file of a stage is offered once the stage exists (R2 5: the envelope and the massing are built
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
  /** What else the user should know about the file (built in another format than the one chosen). */
  note?: string;
}

export const MASSING_OBJ_PATH = "massing/plates.obj";
export const MASSING_JSON_PATH = "massing/plates.json";

/** The path in the run folder of the envelope mesh exporting wrote, from its file name (EnvelopeSummary.mesh_file). */
export function exportedMeshPath(meshFile: string): string {
  return `exporting/${meshFile}`;
}

/** The mesh format of a file, from its extension: "export.ply" is "ply". */
export function meshFormatOf(meshFile: string): string {
  return meshFile.slice(meshFile.lastIndexOf(".") + 1).toLowerCase();
}

const meshFormatName = (meshFormat: string) => messages.meshFormatNames[meshFormat as keyof typeof messages.meshFormatNames] ?? meshFormat.toUpperCase();

interface DownloadListState {
  project: string;
  /** The format chosen in the settings. */
  meshFormat: string;
  /** The envelope mesh on disk (EnvelopeSummary.mesh_file); null until the run summary names it. */
  envelopeFile: string | null;
  /** The stage status of exporting and of massing. */
  envelope: StageState;
  massing: StageState;
}

/**
 * The files of the Export step, in the order of UX 5.7, the envelope's and the massing's once their stage exists. The envelope is
 * the file that was built, under its own format: a format chosen since without a build has no file yet.
 */
export function exportDownloads({ project, meshFormat, envelopeFile, envelope, massing }: DownloadListState): ExportDownload[] {
  const builtFormat = envelopeFile === null ? null : meshFormatOf(envelopeFile);
  const envelopeFiles: ExportDownload[] = envelope === "missing" || envelopeFile === null || builtFormat === null ? [] : [
    { label: messages.envelopeMeshDownload(meshFormatName(builtFormat)), address: runFileUrl(project, exportedMeshPath(envelopeFile)),
      fileName: `${project} envelope.${builtFormat}`, outOfDate: envelope === "out_of_date",
      note: builtFormat === meshFormat ? undefined : messages.envelopeBuiltInOtherFormat(meshFormatName(builtFormat), meshFormatName(meshFormat)) },
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
            {download.note !== undefined && <span className="download-note">{download.note}</span>}
          </li>
        ))}
      </ul>
      {downloadProblem !== null && <p className="setting-error"><WarningIcon /><span>{downloadProblem}</span></p>}
    </div>
  );
}

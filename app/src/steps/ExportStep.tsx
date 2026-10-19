// The Export step (UX 5.7): the mesh file format of the carved envelope and the building massing, whose change rebuilds the parts
// that exist, and the downloads: the envelope file that was built (named by the run summary; a format chosen while Carving was
// locked is stored and written by the next envelope build, which the download says), the building massing file that was built,
// named and noted the same way, and its data (JSON), the settings (config.yaml) and the whole project as a zip. Each file of a stage is offered once the stage exists (R2 5: the envelope and the
// massing are built on their own); one built from settings that changed since is labelled out of date and can still be
// downloaded. The files are fetched with the token and handed to the browser to save (a plain link cannot send the token header).
// A part's files wait while a run of the project rebuilds it: its stage removes them when it begins.
import { useId, type ReactNode } from "react";
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
  /** A run under way rebuilds the file, so there is none to download until its stage is done. */
  waitsForRun?: boolean;
}

/** The plates as OBJ with one named part per plate, which massing writes in every run; the 3D view draws it. */
export const MASSING_OBJ_PATH = "massing/plates.obj";
export const MASSING_JSON_PATH = "massing/plates.json";

/** The path in the run folder of the envelope mesh exporting wrote, from its file name (EnvelopeSummary.mesh_file). */
export function exportedMeshPath(meshFile: string): string {
  return `exporting/${meshFile}`;
}

/** The path in the run folder of the massing mesh in the format it was built in, from its file name (MassingSummary.export_mesh_file). */
export function exportedMassingPath(massingFile: string): string {
  return `massing/${massingFile}`;
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
  /** The massing mesh on disk in the format it was built in (MassingSummary.export_mesh_file); null until the run summary names it. */
  massingFile: string | null;
  /** The stage status of exporting and of massing. */
  envelope: StageState;
  massing: StageState;
  /** The stages a run under way has still to finish (their files are removed); none when no run of the project is under way. */
  stagesBeingRebuilt?: readonly string[];
}

/**
 * The files of the Export step, in the order of UX 5.7, the envelope's and the massing's once their stage exists. The envelope and
 * the massing mesh are the files that were built, under their own format: a format chosen since without a build has no file yet.
 */
export function exportDownloads({ project, meshFormat, envelopeFile, massingFile, envelope, massing, stagesBeingRebuilt = [] }: DownloadListState): ExportDownload[] {
  const envelopeFiles: ExportDownload[] = [];
  if (envelope !== "missing" && envelopeFile !== null) {
    const builtFormat = meshFormatOf(envelopeFile);
    envelopeFiles.push({
      label: messages.envelopeMeshDownload(meshFormatName(builtFormat)), address: runFileUrl(project, exportedMeshPath(envelopeFile)),
      fileName: `${project} envelope.${builtFormat}`, outOfDate: envelope === "out_of_date",
      note: builtFormat === meshFormat ? undefined : messages.envelopeBuiltInOtherFormat(meshFormatName(builtFormat), meshFormatName(meshFormat)),
      waitsForRun: stagesBeingRebuilt.includes("exporting"),
    });
  }
  const massingOutOfDate = massing === "out_of_date", massingWaitsForRun = stagesBeingRebuilt.includes("massing");
  const massingFiles: ExportDownload[] = [];
  if (massing !== "missing" && massingFile !== null) {
    const builtFormat = meshFormatOf(massingFile);
    massingFiles.push({
      label: messages.massingMeshDownload(meshFormatName(builtFormat)), address: runFileUrl(project, exportedMassingPath(massingFile)),
      fileName: `${project} massing.${builtFormat}`, outOfDate: massingOutOfDate,
      note: builtFormat === meshFormat ? undefined : messages.massingBuiltInOtherFormat(meshFormatName(builtFormat), meshFormatName(meshFormat)),
      waitsForRun: massingWaitsForRun,
    });
  }
  if (massing !== "missing") {
    massingFiles.push({ label: messages.massingJsonDownload, address: runFileUrl(project, MASSING_JSON_PATH), fileName: `${project} massing.json`,
                        outOfDate: massingOutOfDate, waitsForRun: massingWaitsForRun });
  }
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
  const reasonId = useId();
  return (
    <div className="export-step">
      {disabledReason !== null && <p id={reasonId} className="step-reason">{disabledReason}</p>}
      <SettingField view={settingView("final_mesh_format", form.mode)} form={form} disabled={disabledReason !== null}
                    extras={formatRunReason === null ? undefined : { notes: [formatRunReason] }}
                    onChange={(values) => onFormatChange(String(values.final_mesh_format))} />
      {formatFeedback}
      <ul className="download-list">
        {downloads.map((download) => (
          <li key={download.label}>
            <button type="button" className="link-button" disabled={download.waitsForRun} aria-describedby={download.waitsForRun ? reasonId : undefined}
                    onClick={() => onDownload(download)}>{download.label}</button>
            {download.outOfDate && <span className="out-of-date-tag">{messages.outOfDateFile}</span>}
            {download.note !== undefined && <span className="download-note">{download.note}</span>}
          </li>
        ))}
      </ul>
      {downloadProblem !== null && <p className="setting-error"><WarningIcon /><span>{downloadProblem}</span></p>}
    </div>
  );
}

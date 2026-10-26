// Typed access to the local service: one function per route, each sending the launch token in X-USC-Token.
// The shapes come from generated_types.ts (npm run api-types), which is made from the service's own OpenAPI document.
import { messages } from "../messages";
import type { components } from "./generated_types";

type Schemas = components["schemas"];
export type HealthReply = Schemas["HealthReply"];
export type ModeInfo = Schemas["ModeInfo"];
export type ExampleInfo = Schemas["ExampleInfo"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type ProjectDetail = Schemas["ProjectDetail"];
export type InputFilesReply = Schemas["InputFilesReply"];
export type InputFileInfo = Schemas["InputFileInfo"];
export type ConfigReply = Schemas["ConfigReply"];
export type ConfigErrorReply = Schemas["ConfigErrorReply"];
export type GridPlanReply = Schemas["GridPlanReply"];
export type StageStatusReply = Schemas["StageStatusReply"];
export type SunPath = Schemas["SunPath"];
export type ColdPeriodReply = Schemas["ColdPeriodReply"];
export type StartRunReply = Schemas["StartRunReply"];
export type CancelRunReply = Schemas["CancelRunReply"];
export type RunSummary = Schemas["RunSummary"];
export type SkyDome = Schemas["SkyDome"];
export type ProjectsFolderReply = Schemas["ProjectsFolderReply"];
export type ProjectsFolderChoiceReply = Schemas["ProjectsFolderChoiceReply"];
export type CriterionEntry = Schemas["CriterionEntry"];
export type CriterionCarvingSummary = Schemas["CriterionCarvingSummary"];
export type ChainSummary = Schemas["ChainSummary"];
export type CriterionSettingsReply = Schemas["CriterionSettingsReply"];

export const TOKEN_HEADER = "X-USC-Token";
const TOKEN_QUERY_PARAMETER = "token";
const STORED_TOKEN_KEY = "usc.token";
const BLOB_ADDRESS_LIFETIME_MILLISECONDS = 10_000;

/** A reply that is not 2xx. *body* is the parsed JSON of the reply (the service's error models), or its text when it is not JSON. */
export class ApiError extends Error {
  constructor(readonly status: number, readonly body: unknown) {
    super(`The service answered ${status}`);
    this.name = "ApiError";
  }
}

/**
 * The token the launch address carries, which is then removed from the address bar so it is not copied or bookmarked.
 * It is kept in this tab's session storage, so a reload (which has no token in the address) finds it again; without
 * storage (blocked by the browser) a reload loses it. Without a token in the address, the kept one is returned.
 */
export function readTokenFromLaunchUrl(): string {
  const parameters = new URLSearchParams(window.location.search);
  const tokenInAddress = parameters.get(TOKEN_QUERY_PARAMETER);
  const token = tokenInAddress ?? readStoredToken();
  if (tokenInAddress !== null) storeToken(tokenInAddress);
  parameters.delete(TOKEN_QUERY_PARAMETER);
  const remainingQuery = parameters.toString();
  window.history.replaceState(null, "", window.location.pathname + (remainingQuery ? `?${remainingQuery}` : "") + window.location.hash);
  return token;
}

function readStoredToken(): string {
  try {
    return window.sessionStorage.getItem(STORED_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function storeToken(token: string): void {
  try {
    window.sessionStorage.setItem(STORED_TOKEN_KEY, token);
  } catch {
    // storage is blocked: the token then lives only in this page load
  }
}

/**
 * What a failed request says about the service: 401 means this page has no valid token; a request that never got a reply means the
 * engine is not running.
 */
export function serviceProblemOf(error: unknown): "access_lost" | "engine_stopped" | "other" {
  if (error instanceof ApiError) return error.status === 401 ? "access_lost" : "other";
  return "engine_stopped";
}

function projectPath(project: string): string {
  return `/api/projects/${encodeURIComponent(project)}`;
}

/** The service's own words for a refused request (its "detail", or the messages of its field errors); null for another failure. */
export function refusalDetailOf(error: unknown): string | null {
  if (!(error instanceof ApiError) || typeof error.body !== "object" || error.body === null) return null;
  const body = error.body as { detail?: unknown; field_errors?: { message: string }[] };
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.field_errors)) return body.field_errors.map((fieldError) => fieldError.message).join(" ");
  return null;
}

/**
 * A failed request in words, the same wherever it is shown: the service's reason; a sentence with the status when the service
 * gave none (a 500 without a body the service wrote); or that the request did not reach the engine.
 */
export function failureTextOf(error: unknown): string {
  const reason = refusalDetailOf(error);
  if (reason !== null) return reason;
  return error instanceof ApiError ? messages.requestRefusedWithoutReason(error.status) : messages.requestDidNotReachEngine;
}

/** The address of an uploaded input file. A request for it needs the token header like any other. */
export function inputFileUrl(project: string, role: string, fileName: string): string {
  return `${projectPath(project)}/inputs/${encodeURIComponent(role)}/${encodeURIComponent(fileName)}`;
}

/** The address of a result file of the project's last run. A request for it needs the token header like any other. */
export function runFileUrl(project: string, path: string): string {
  return `${projectPath(project)}/run/files/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** The address of the zip archive of the project folder. A request for it needs the token header like any other. */
export function projectDownloadUrl(project: string): string {
  return `${projectPath(project)}/download`;
}

/** The address of the project's config.yaml as stored. A request for it needs the token header like any other. */
export function projectConfigUrl(project: string): string {
  return `${projectPath(project)}/config.yaml`;
}

async function send(token: string, address: string, method = "GET", body?: BodyInit, contentType?: string): Promise<Response> {
  const headers = new Headers({ [TOKEN_HEADER]: token });
  if (contentType) headers.set("Content-Type", contentType);
  const reply = await fetch(address, { method, headers, body });
  if (!reply.ok) {
    const text = await reply.text();
    let errorBody: unknown = text;
    try {
      errorBody = JSON.parse(text);
    } catch {
      // not JSON: the text stays as it is
    }
    throw new ApiError(reply.status, errorBody);
  }
  return reply;
}

/** A request whose reply is JSON; a given *payload* is sent as the JSON body. */
async function requestJson<Reply>(token: string, address: string, method = "GET", payload?: unknown): Promise<Reply> {
  const hasPayload = payload !== undefined;
  const reply = await send(token, address, method, hasPayload ? JSON.stringify(payload) : undefined, hasPayload ? "application/json" : undefined);
  return reply.json() as Promise<Reply>;
}

export const getHealth = (token: string) => requestJson<HealthReply>(token, "/api/health");
export const getModes = (token: string) => requestJson<ModeInfo[]>(token, "/api/modes");
export const getSchema = (token: string) => requestJson<Record<string, unknown>>(token, "/api/schema");
export const getExamples = (token: string) => requestJson<ExampleInfo[]>(token, "/api/examples");
export const listProjects = (token: string) => requestJson<ProjectSummary[]>(token, "/api/projects");

export const createProject = (token: string, name: string, mode?: string) =>
  requestJson<ProjectDetail>(token, "/api/projects", "POST", mode === undefined ? { name } : { name, mode });

export const getProject = (token: string, name: string) => requestJson<ProjectDetail>(token, projectPath(name));

export const createProjectFromExample = (token: string, name: string, example: string) =>
  requestJson<ProjectDetail>(token, `${projectPath(name)}/examples/${encodeURIComponent(example)}`, "POST");

export const getProjectsFolder = (token: string) => requestJson<ProjectsFolderReply>(token, "/api/projects-folder");

/** Shows the folder picker on this computer (the browser sends no path); resolves once it is closed. */
export const chooseProjectsFolder = (token: string) => requestJson<ProjectsFolderChoiceReply>(token, "/api/projects-folder/choose", "POST");

export const renameProject = (token: string, name: string, newName: string) =>
  requestJson<ProjectDetail>(token, `${projectPath(name)}/rename`, "POST", { new_name: newName });

/** Moves the project folder to the recycle bin; *confirmName* is the name the user typed, which the service checks again. */
export async function deleteProject(token: string, name: string, confirmName: string): Promise<void> {
  await send(token, `${projectPath(name)}?confirm_name=${encodeURIComponent(confirmName)}`, "DELETE");
}

export const resetProjectToExample = (token: string, name: string) =>
  requestJson<ProjectDetail>(token, `${projectPath(name)}/reset-to-example`, "POST");

/** Opens the project folder in the file manager of this computer. */
export async function openProjectFolder(token: string, name: string): Promise<void> {
  await send(token, `${projectPath(name)}/open-folder`, "POST");
}

export async function addInput(token: string, project: string, role: string, file: File): Promise<InputFilesReply> {
  const form = new FormData();
  form.append("file", file);
  const reply = await send(token, `${projectPath(project)}/inputs/${encodeURIComponent(role)}`, "POST", form);    // the browser sets the multipart boundary
  return reply.json();
}

export const removeInput = (token: string, project: string, role: string, fileName: string) =>
  requestJson<InputFilesReply>(token, inputFileUrl(project, role, fileName), "DELETE");

/** The stored files of a role (for the test surfaces, every criterion's), with their triangle counts. */
export const getInputFiles = (token: string, project: string, role: string) =>
  requestJson<InputFileInfo[]>(token, `${projectPath(project)}/inputs/${encodeURIComponent(role)}`);

export const getStageStatus = (token: string, project: string) =>
  requestJson<StageStatusReply>(token, `${projectPath(project)}/stage-status`);

/** The settings that belong to a criterion; every other setting is shared by the criteria. */
export const getCriterionKeys = (token: string) => requestJson<string[]>(token, "/api/criterion-keys");

/** Saves the settings the criteria share (no mode); the reply holds them as stored. */
export const putSharedSettings = (token: string, project: string, values: Record<string, unknown>) =>
  requestJson<ConfigReply>(token, `${projectPath(project)}/shared-settings`, "PUT", { values });

/** The settings of one criterion with the shared ones. */
export const getCriterionSettings = (token: string, project: string, criterionId: string) =>
  requestJson<CriterionSettingsReply>(token, `${criterionPath(project, criterionId)}/settings`);

function criterionPath(project: string, criterionId: string): string {
  return `${projectPath(project)}/criteria/${encodeURIComponent(criterionId)}`;
}

/** *address* with the query of the criterion whose results are wanted; without one the service picks its default criterion. */
function forCriterion(address: string, criterionId?: string): string {
  return criterionId === undefined ? address : `${address}?criterion=${encodeURIComponent(criterionId)}`;
}

/** Adds a criterion of *mode* at the end of the chain; without a *name* the service names it from the mode. */
export const addCriterion = (token: string, project: string, mode: string, name?: string) =>
  requestJson<CriterionEntry>(token, `${projectPath(project)}/criteria`, "POST", name === undefined ? { mode } : { mode, name });

/** Changes what is given of a criterion's name, colour, bypass and settings; what is not given stays. */
export const updateCriterion = (token: string, project: string, criterionId: string,
                                changes: { name?: string; colour?: string; bypassed?: boolean; values?: Record<string, unknown> }) =>
  requestJson<CriterionEntry>(token, criterionPath(project, criterionId), "PATCH", changes);

export async function deleteCriterion(token: string, project: string, criterionId: string): Promise<void> {
  await send(token, criterionPath(project, criterionId), "DELETE");
}

export const duplicateCriterion = (token: string, project: string, criterionId: string) =>
  requestJson<CriterionEntry>(token, `${criterionPath(project, criterionId)}/duplicate`, "POST");

/** Puts the criteria in the order of *ids*, which has each criterion once; the reply is the list in that order. */
export const reorderCriteria = (token: string, project: string, ids: string[]) =>
  requestJson<CriterionEntry[]>(token, `${projectPath(project)}/criteria/order`, "PUT", { ids });

export async function addCriterionTestSurface(token: string, project: string, criterionId: string, file: File): Promise<CriterionEntry> {
  const form = new FormData();
  form.append("file", file);
  const reply = await send(token, `${criterionPath(project, criterionId)}/test-surfaces`, "POST", form);    // the browser sets the multipart boundary
  return reply.json();
}

/** Lets the criterion use a test surface file that is stored already (not a React hook, whatever the name says). */
export const reuseTestSurface = (token: string, project: string, criterionId: string, fileName: string) =>
  requestJson<CriterionEntry>(token, `${criterionPath(project, criterionId)}/test-surfaces/${encodeURIComponent(fileName)}`, "PUT");

export const removeCriterionTestSurface = (token: string, project: string, criterionId: string, fileName: string) =>
  requestJson<CriterionEntry>(token, `${criterionPath(project, criterionId)}/test-surfaces/${encodeURIComponent(fileName)}`, "DELETE");

export const getSunPath = (token: string, project: string, criterionId?: string) =>
  requestJson<SunPath>(token, forCriterion(`${projectPath(project)}/sun-path`, criterionId));
export const getColdPeriod = (token: string, project: string, baseTemperature: number) =>
  requestJson<ColdPeriodReply>(token, `${projectPath(project)}/cold-period?base_temperature=${encodeURIComponent(String(baseTemperature))}`);

/** Starts a run of the given stages; without *produce* the service runs its default (export and massing). */
export const startRun = (token: string, project: string, produce?: string[]) =>
  requestJson<StartRunReply>(token, `${projectPath(project)}/runs`, "POST", produce === undefined ? {} : { produce });

export const cancelRun = (token: string, runId: string) =>
  requestJson<CancelRunReply>(token, `/api/runs/${encodeURIComponent(runId)}/cancel`, "POST");

export const getRunSummary = (token: string, project: string) => requestJson<RunSummary>(token, `${projectPath(project)}/run/summary`);
export const getSkyPatches = (token: string, project: string, criterionId?: string) =>
  requestJson<SkyDome>(token, forCriterion(`${projectPath(project)}/run/sky-patches`, criterionId));

/** The score points of the last run as the service packs them (binary); of the criterion given, else of the last criterion that is on. */
export async function getScorePoints(token: string, project: string, criterionId?: string): Promise<ArrayBuffer> {
  return (await send(token, forCriterion(`${projectPath(project)}/run/score-points`, criterionId))).arrayBuffer();
}

/** Which criterion removed each voxel of the grid, as the service packs it (binary). */
export async function getCarvedByCriterion(token: string, project: string): Promise<ArrayBuffer> {
  return (await send(token, `${projectPath(project)}/run/carved-by-criterion`)).arrayBuffer();
}

/** A result file of the last run as text (the run report). */
export async function getRunFileText(token: string, project: string, path: string): Promise<string> {
  return (await send(token, runFileUrl(project, path))).text();
}

/** A result file of the last run as parsed JSON (plates.json). */
export async function getRunFileJson<Reply>(token: string, project: string, path: string): Promise<Reply> {
  return (await send(token, runFileUrl(project, path))).json() as Promise<Reply>;
}

/**
 * Saves a file of the service to the computer under *fileName*. A plain link cannot send the token header, so the file is
 * fetched with it and offered through a blob address.
 */
export async function downloadWithToken(token: string, address: string, fileName: string): Promise<void> {
  const blob = await (await send(token, address)).blob();
  const blobAddress = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobAddress;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Kept for a while after the click: a browser that starts the download later (Firefox) would lose a revoked address.
  setTimeout(() => URL.revokeObjectURL(blobAddress), BLOB_ADDRESS_LIFETIME_MILLISECONDS);
}

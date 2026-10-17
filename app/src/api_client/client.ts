// Typed access to the local service: one function per route, each sending the launch token in X-USC-Token.
// The shapes come from generated_types.ts (npm run api-types), which is made from the service's own OpenAPI document.
import type { components } from "./generated_types";

type Schemas = components["schemas"];
export type HealthReply = Schemas["HealthReply"];
export type ModeInfo = Schemas["ModeInfo"];
export type ExampleInfo = Schemas["ExampleInfo"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type ProjectDetail = Schemas["ProjectDetail"];
export type InputFilesReply = Schemas["InputFilesReply"];
export type ConfigReply = Schemas["ConfigReply"];
export type StageStatusReply = Schemas["StageStatusReply"];
export type SunPath = Schemas["SunPath"];
export type StartRunReply = Schemas["StartRunReply"];
export type CancelRunReply = Schemas["CancelRunReply"];
export type RunSummary = Schemas["RunSummary"];
export type SkyDome = Schemas["SkyDome"];

export const TOKEN_HEADER = "X-USC-Token";
const TOKEN_QUERY_PARAMETER = "token";
const STORED_TOKEN_KEY = "usc.token";

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

/** What a failed request says about the service: 401 means this page has no valid token; a request that never got a reply means the engine is not running. */
export function serviceProblemOf(error: unknown): "access_lost" | "engine_stopped" | "other" {
  if (error instanceof ApiError) return error.status === 401 ? "access_lost" : "other";
  return "engine_stopped";
}

function projectPath(project: string): string {
  return `/api/projects/${encodeURIComponent(project)}`;
}

/** The address of a result file of the project's last run. A request for it needs the token header like any other. */
export function runFileUrl(project: string, path: string): string {
  return `${projectPath(project)}/run/files/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** The address of the zip archive of the project folder. A request for it needs the token header like any other. */
export function projectDownloadUrl(project: string): string {
  return `${projectPath(project)}/download`;
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

export async function addInput(token: string, project: string, role: string, file: File): Promise<InputFilesReply> {
  const form = new FormData();
  form.append("file", file);
  const reply = await send(token, `${projectPath(project)}/inputs/${encodeURIComponent(role)}`, "POST", form);    // the browser sets the multipart boundary
  return reply.json();
}

export const removeInput = (token: string, project: string, role: string, fileName: string) =>
  requestJson<InputFilesReply>(token, `${projectPath(project)}/inputs/${encodeURIComponent(role)}/${encodeURIComponent(fileName)}`, "DELETE");

export const putConfig = (token: string, project: string, values: Record<string, unknown>) =>
  requestJson<ConfigReply>(token, `${projectPath(project)}/config`, "PUT", { values });

export const getStageStatus = (token: string, project: string) =>
  requestJson<StageStatusReply>(token, `${projectPath(project)}/stage-status`);

export const getSunPath = (token: string, project: string) => requestJson<SunPath>(token, `${projectPath(project)}/sun-path`);

/** Starts a run of the given stages; without *produce* the service runs its default (export and massing). */
export const startRun = (token: string, project: string, produce?: string[]) =>
  requestJson<StartRunReply>(token, `${projectPath(project)}/runs`, "POST", produce === undefined ? {} : { produce });

export const cancelRun = (token: string, runId: string) =>
  requestJson<CancelRunReply>(token, `/api/runs/${encodeURIComponent(runId)}/cancel`, "POST");

export const getRunSummary = (token: string, project: string) => requestJson<RunSummary>(token, `${projectPath(project)}/run/summary`);
export const getSkyPatches = (token: string, project: string) => requestJson<SkyDome>(token, `${projectPath(project)}/run/sky-patches`);

/** The score points of the last run as the service packs them (binary). */
export async function getScorePoints(token: string, project: string): Promise<ArrayBuffer> {
  return (await send(token, `${projectPath(project)}/run/score-points`)).arrayBuffer();
}

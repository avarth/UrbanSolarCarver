// Writes the service's OpenAPI document to app/openapi.json, the first step of `npm run api-types`. It finds the project's
// Python itself, since the system one does not have the package, and reads this checkout's sources, so it works from a git
// worktree that has no environment of its own.
import { execFileSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appFolder = join(dirname(fileURLToPath(import.meta.url)), "..");
const checkout = join(appFolder, "..");
const OPENAPI_DOCUMENT = "import json; from urbansolarcarver.local_web_service.server import openapi_document; print(json.dumps(openapi_document()))";

/** The environment of this checkout, else of the main checkout, else whatever `python` is. */
function projectPython() {
  const gitFolder = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { cwd: checkout, encoding: "utf8" }).trim();
  const candidates = [checkout, dirname(gitFolder)].flatMap((folder) => [join(folder, ".venv", "Scripts", "python.exe"), join(folder, ".venv", "bin", "python")]);
  return candidates.find((candidate) => existsSync(candidate)) ?? "python";
}

const document = execFileSync(projectPython(), ["-c", OPENAPI_DOCUMENT], {
  env: { ...process.env, PYTHONPATH: join(checkout, "src") },
  encoding: "utf8",
  maxBuffer: 64 * 1024 * 1024,
  stdio: ["ignore", "pipe", "inherit"],
});
writeFileSync(join(appFolder, "openapi.json"), document);

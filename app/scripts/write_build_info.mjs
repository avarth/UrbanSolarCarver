// Records a hash of the front-end sources next to the build, so a test can tell when app/ changed without a rebuild.
// The same hash is computed by app_source_sha256 in tests/test_local_web_packaging.py; change both together.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appFolder = join(dirname(fileURLToPath(import.meta.url)), "..");
const buildInfoPath = join(appFolder, "..", "src", "urbansolarcarver", "ui_static", "build_info.json");

function relativePathsUnder(folder) {
  return readdirSync(join(appFolder, folder), { withFileTypes: true }).flatMap((entry) => {
    const relativePath = `${folder}/${entry.name}`;
    return entry.isDirectory() ? relativePathsUnder(relativePath) : [relativePath];
  });
}

function appSourceSha256() {
  const relativePaths = ["package.json", "package-lock.json", ...relativePathsUnder("src")];
  relativePaths.sort((first, second) => Buffer.compare(Buffer.from(first), Buffer.from(second)));
  const digest = createHash("sha256");
  for (const relativePath of relativePaths) {
    digest.update(`${relativePath}\n`);
    digest.update(lineFeedsOnly(readFileSync(join(appFolder, relativePath))));
  }
  return digest.digest("hex");
}

/** The bytes with every CRLF turned into LF, so a Windows checkout hashes like a Linux one. Latin-1 maps each byte to one character, so any file survives the round trip. */
function lineFeedsOnly(bytes) {
  return Buffer.from(bytes.toString("latin1").replaceAll("\r\n", "\n"), "latin1");
}

writeFileSync(buildInfoPath, `${JSON.stringify({ app_source_sha256: appSourceSha256() })}\n`);

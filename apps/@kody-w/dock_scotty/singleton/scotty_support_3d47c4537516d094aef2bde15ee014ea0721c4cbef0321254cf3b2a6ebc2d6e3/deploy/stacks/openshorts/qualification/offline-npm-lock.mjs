import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [lockPath, manifestPath, tarballDirectory] = process.argv.slice(2);
if (!lockPath || !manifestPath || !tarballDirectory || process.argv.length !== 5) {
  throw new Error("Expected lock path, reviewed artifact manifest, and verified tarball directory");
}
const original = readFileSync(lockPath);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (createHash("sha256").update(original).digest("hex") !== manifest.lockfile_sha256) {
  throw new Error("Upstream lock bytes differ from the reviewed artifact manifest");
}
const locations = new Map();
const verified = new Set();
for (const artifact of manifest.artifacts) {
  if (!/^[a-f0-9]{128}$/.test(artifact.sha512_hex)) {
    throw new Error("Invalid locked artifact digest");
  }
  const file = resolve(tarballDirectory, `${artifact.sha512_hex}.tgz`);
  if (!verified.has(file)) {
    if (createHash("sha512").update(readFileSync(file)).digest("hex") !== artifact.sha512_hex) {
      throw new Error("Offline artifact does not match upstream integrity");
    }
    verified.add(file);
  }
  const integrity = `sha512-${Buffer.from(artifact.sha512_hex, "hex").toString("base64")}`;
  if (integrity !== artifact.integrity) throw new Error("Inconsistent artifact integrity");
  locations.set(artifact.url, { url: pathToFileURL(file).href, integrity });
}
function rewrite(value) {
  if (!value || typeof value !== "object") return;
  if (typeof value.resolved === "string") {
    const replacement = locations.get(value.resolved);
    if (!replacement || replacement.integrity !== value.integrity) {
      throw new Error("Lock contains an unreviewed artifact location or integrity");
    }
    value.resolved = replacement.url;
  }
  for (const child of Object.values(value)) rewrite(child);
}
const lock = JSON.parse(original);
rewrite(lock);
writeFileSync(`${lockPath}.upstream`, original, { flag: "wx" });
writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`);
console.log(JSON.stringify({
  status: "locked-artifacts-relocated-offline",
  artifact_count: verified.size,
  upstream_lock_sha256: manifest.lockfile_sha256,
  dependency_versions_changed: false,
}));

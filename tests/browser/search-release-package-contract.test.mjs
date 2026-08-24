import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const paths = {
  manifest: new URL("data/search-v2-voyage-manifest.json", root),
  vectors: new URL("data/search-v2-voyage-vectors.f16", root),
  release: new URL("data/search-v2-release.json", root),
  allowlist: new URL("workers/search-voyage-proxy/generated/corpus-allowlist.json", root),
  worker: new URL("workers/search-voyage-proxy/src/index.js", root),
  vectorBuilder: new URL("tools/build_search_v2_voyage_vectors.mjs", root),
  packageBuilder: new URL("tools/build_search_release_package.mjs", root),
  workflow: new URL(".github/workflows/refresh-opportunities.yml", root),
};
const [manifest, vectors, release, allowlist, worker, vectorBuilder, packageBuilder, workflow] = await Promise.all([
  readFile(paths.manifest, "utf8").then(JSON.parse),
  readFile(paths.vectors),
  readFile(paths.release, "utf8").then(JSON.parse),
  readFile(paths.allowlist, "utf8").then(JSON.parse),
  readFile(paths.worker, "utf8"),
  readFile(paths.vectorBuilder, "utf8"),
  readFile(paths.packageBuilder, "utf8"),
  readFile(paths.workflow, "utf8"),
]);

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

test("release manifest, vector binary, and Worker allowlist identify one current corpus", async () => {
  assert.equal(release.current_corpus_sha256, manifest.corpus_sha256);
  assert.equal(release.vector_sha256, manifest.vector_sha256);
  assert.equal(sha256(vectors), manifest.vector_sha256);
  assert.equal(vectors.byteLength, manifest.vector_bytes);
  assert.equal(allowlist.current.corpus_sha256, manifest.corpus_sha256);
  assert.equal(allowlist.current.passage_count, manifest.passage_count);
  assert.deepEqual(
    allowlist.current.passages,
    manifest.passages.map(item => ({ passage_id: item.passage_id, text_sha256: item.text_sha256 })),
  );
  assert.equal(
    release.worker_allowlist_sha256,
    sha256(await readFile(paths.allowlist)),
  );
});

test("Worker package contains only current and immediately previous corpus generations", () => {
  assert.deepEqual(Object.keys(allowlist).sort(), ["current", "previous", "schema_version"]);
  assert.ok(allowlist.previous);
  assert.equal(release.previous_corpus_sha256, allowlist.previous.corpus_sha256);
  assert.notEqual(allowlist.previous.corpus_sha256, allowlist.current.corpus_sha256);
  assert.equal(allowlist.previous.passages.length, allowlist.previous.passage_count);
  assert.match(worker, /\[allowlist\?\.current, allowlist\?\.previous\]/);
  assert.doesNotMatch(worker, /passageManifest|arbitrary historic/i);
});

test("production vector builds force every current passage through one model contract", () => {
  assert.match(vectorBuilder, /const force = process\.argv\.includes\("--force"\) \|\| production/);
  assert.match(vectorBuilder, /build_mode: production \? "production_full_rebuild"/);
  assert.match(vectorBuilder, /production_reused_vectors: production \? false/);
  assert.match(vectorBuilder, /model: MODEL,[\s\S]*?input_type: "document",[\s\S]*?output_dimension: DIMENSION/);
  assert.doesNotMatch(workflow, /build_search_v2_voyage_vectors\.mjs --write(?! --production)/);
  assert.match(workflow, /build_search_v2_voyage_vectors\.mjs --production --write/);
});

test("scheduled publication deploys a validated compatibility Worker before one atomic commit", () => {
  const ordered = [
    "Build and validate complete public opportunity catalog",
    "Rebuild every production document vector",
    "Build the current/previous Worker compatibility package",
    "Verify the complete search package is internally consistent",
    "Deploy the compatibility Worker before publishing Pages assets",
    "Commit refreshed catalog",
    "Verify GitHub Pages serves the coordinated search package",
  ].map(label => workflow.indexOf(label));
  ordered.forEach(index => assert.ok(index >= 0));
  assert.deepEqual(ordered, ordered.slice().sort((left, right) => left - right));
  assert.match(workflow, /git add[^\n]*search-v2-voyage-manifest\.json[^\n]*search-v2-voyage-vectors\.f16[^\n]*search-v2-release\.json/);
  assert.match(workflow, /git add[^\n]*corpus-allowlist\.json/);
  assert.doesNotMatch(
    workflow.slice(workflow.indexOf("Rebuild every production document vector"), workflow.indexOf("Commit refreshed catalog")),
    /continue-on-error:\s*true/,
  );
});

test("release package verification is a deterministic no-write gate", () => {
  assert.match(packageBuilder, /Choose exactly one of --write or --check/);
  const run = spawnSync(process.execPath, [fileURLToPath(paths.packageBuilder), "--check"], {
    cwd: fileURLToPath(root),
    encoding: "utf8",
  });
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /"status": "verified"/);
});

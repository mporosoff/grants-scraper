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
  canaries: new URL("data/search-v2-voyage-canaries.json", root),
  receipt: new URL("evaluation/search_v2_hybrid_vector_build.json", root),
  release: new URL("data/search-v2-release.json", root),
  allowlist: new URL("workers/search-voyage-proxy/generated/corpus-allowlist.json", root),
  worker: new URL("workers/search-voyage-proxy/src/index.js", root),
  vectorBuilder: new URL("tools/build_search_v2_voyage_vectors.mjs", root),
  packageBuilder: new URL("tools/build_search_release_package.mjs", root),
  workflow: new URL(".github/workflows/refresh-opportunities.yml", root),
};
const [manifest, vectors, canaries, receipt, release, allowlist, worker, vectorBuilder, packageBuilder, workflow] = await Promise.all([
  readFile(paths.manifest, "utf8").then(JSON.parse),
  readFile(paths.vectors),
  readFile(paths.canaries, "utf8").then(JSON.parse),
  readFile(paths.receipt, "utf8").then(JSON.parse),
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
  assert.equal(release.model_space_fingerprint, manifest.model_space_fingerprint);
  assert.equal(allowlist.current.model_space_fingerprint, manifest.model_space_fingerprint);
  assert.equal(canaries.model_space_fingerprint, manifest.model_space_fingerprint);
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
  assert.equal(receipt.build_mode, "production_full_rebuild");
  assert.equal(receipt.reused_passage_count, 0);
  assert.equal(receipt.production_reused_vectors, false);
  assert.equal(receipt.production_generation_uniform.model_alias_count, 1);
  assert.equal(receipt.production_generation_uniform.response_model_count, 1);
  assert.equal(receipt.production_generation_uniform.dimension_count, 1);
  assert.equal(receipt.production_generation_uniform.output_type_count, 1);
  assert.equal(receipt.production_generation_uniform.build_timestamp_count, 1);
  assert.equal(receipt.production_generation_uniform.canary_fingerprint_count, 1);
});

test("fixed public canaries fingerprint and gate the embedding space", () => {
  assert.equal(canaries.canary_set_version, 1);
  assert.equal(canaries.model_alias, manifest.model);
  assert.equal(canaries.response_model, manifest.response_model);
  assert.equal(canaries.dimension, manifest.dimension);
  assert.equal(canaries.canaries.length, manifest.model_space.canary_count);
  assert.match(canaries.model_space_fingerprint, /^[a-f0-9]{64}$/);
  assert.equal(canaries.comparison_to_prior_generation.status, "passed");
  assert.equal(canaries.comparison_to_prior_generation.gross_discontinuity, false);
  assert.ok(canaries.comparison_to_prior_generation.minimum_cosine >= .95);
  assert.ok(canaries.comparison_to_prior_generation.mean_cosine >= .98);
  assert.match(vectorBuilder, /Gross embedding-space discontinuity:[\s\S]*Publication blocked after full rebuild/);
  assert.match(packageBuilder, /model_space_fingerprint/);
  assert.match(worker, /body\.model_space_fingerprint !== generation\.model_space_fingerprint/);
});

test("scheduled publication deploys a validated compatibility Worker before one atomic commit", () => {
  const ordered = [
    "Build and validate complete public opportunity catalog",
    "Rebuild every production document vector",
    "Build the current/previous Worker compatibility package",
    "Verify the complete search package is internally consistent",
    "Run real-browser product and accessibility gates",
    "Refuse to deploy a stale generation",
    "Deploy the compatibility Worker before publishing Pages assets",
    "Commit refreshed catalog",
    "Verify GitHub Pages serves the coordinated search package",
  ].map(label => workflow.indexOf(label));
  ordered.forEach(index => assert.ok(index >= 0));
  assert.deepEqual(ordered, ordered.slice().sort((left, right) => left - right));
  assert.match(workflow, /git add[^\n]*search-v2-voyage-manifest\.json[^\n]*search-v2-voyage-vectors\.f16[^\n]*search-v2-voyage-canaries\.json[^\n]*search-v2-release\.json/);
  assert.match(workflow, /git add[^\n]*corpus-allowlist\.json/);
  assert.match(workflow, /uses: actions\/checkout@v6[\s\S]*?with:[\s\S]*?ref: main/);
  assert.match(workflow, /built_from_sha="\$\(git rev-parse HEAD\)"/);
  assert.match(workflow, /current_main_sha="\$\(git ls-remote origin refs\/heads\/main/);
  assert.match(workflow, /refusing to deploy stale Worker or Pages assets/);
  assert.match(workflow, /pull-requests: write/);
  assert.match(workflow, /statuses: write/);
  assert.match(workflow, /gh api --method POST "repos\/\$\{GITHUB_REPOSITORY\}\/statuses\/\$\{head_sha\}"/);
  assert.match(workflow, /-f context=python/);
  assert.match(workflow, /-f context=browser/);
  assert.match(workflow, /pnpm test:e2e/);
  assert.match(workflow, /-f context=e2e/);
  const generatedCommitStatuses = workflow.slice(
    workflow.indexOf('head_sha="$(git rev-parse HEAD)"'),
    workflow.indexOf("if ! pr_url="),
  );
  for (const context of ["python", "browser", "e2e"]) {
    assert.match(generatedCommitStatuses, new RegExp(`-f context=${context}`));
  }
  assert.match(workflow, /gh pr create/);
  assert.match(workflow, /gh pr merge "\$pr_url" --squash --delete-branch/);
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

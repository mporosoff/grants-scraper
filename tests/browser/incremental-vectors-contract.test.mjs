import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, readdir, rename, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { withBuildLock, writeCoherentFiles } from "../../tools/coherent_files.mjs";
import { buildGeneration } from "../../tools/build_search_v2_voyage_vectors.mjs";
import { buildAllowlist } from "../../tools/build_search_release_package.mjs";
import { configuration, digest, manifestDigest, validateAsset } from "../../tools/embedding_contract.mjs";

const config = configuration(digest("synthetic preprocessing"));
const passage = (id, text = id) => ({passage_id: `parent:${id}`, parent_id: id, record_id: id, passage_kind: "parent", text});
const inputs = [passage("one"), passage("two"), passage("three")];
function provider(drift = 0) {
  return async texts => ({vectors: texts.map(text => {
    const bytes = Buffer.from(digest(text), "hex");
    return Float32Array.from({length: 1024}, (_, i) => (bytes[i % 32] + 1) / 10000 + drift);
  }), receipt: {model: "voyage-4-lite", usage_total_tokens: texts.length}});
}
async function build(corpus, previous = null, overrides = {}) {
  corpus = structuredClone(corpus);
  const result = await buildGeneration({corpus, previous, config, embedBatch: provider(), ...overrides});
  const binary = Buffer.from(result.vectorWords.buffer);
  const manifest = {schema_version: 1, model: config.model, dimension: 1024, dtype: "float16-le", byte_order: "little-endian",
    input_type: "document", source_output_dtype: "float", generated_at: "2099-01-01T00:00:00Z",
    passage_count: corpus.length, vector_bytes: binary.length, vector_sha256: digest(binary), corpus_sha256: digest(JSON.stringify(corpus)),
    reuse_permitted: result.canaryArtifact.reuse_permitted,
    reuse_contract: result.config, configuration_sha256: digest(JSON.stringify(result.config)),
    model_space_fingerprint: result.canaryArtifact.model_space_fingerprint, response_model: config.model,
    reuse_space_identity: result.canaryArtifact.reuse_space_identity, canary_sha256: digest(JSON.stringify(result.canaryArtifact)),
    passages: corpus.map(({text, ...row}, vector_row) => ({...row, vector_row}))};
  manifest.integrity_sha256 = manifestDigest(manifest);
  const asset = {manifest, binary, canaries: result.canaryArtifact};
  validateAsset(manifest, binary, asset.canaries, {requireReusable: true});
  return {...asset, result};
}

test("cold, warm, new and amended passages equal clean builds with exact reused bytes", async () => {
  const cold = await build(inputs);
  const warm = await build(inputs, cold);
  assert.equal(warm.result.reused, 3);
  assert.equal(warm.result.changed.length, 0);
  assert.equal(warm.result.receipts.length, 1, "only the separately counted identity check is due");
  assert.deepEqual(warm.binary, cold.binary);
  for (const updated of [[...inputs, passage("four")], [inputs[0], passage("two", "material amendment"), inputs[2]], inputs.slice(1)]) {
    const incremental = await build(updated, cold);
    const clean = await build(updated);
    assert.deepEqual(incremental.binary, clean.binary);
    assert.deepEqual(incremental.manifest.passages, clean.manifest.passages);
    assert.equal(incremental.result.reused, updated.length === 4 ? 3 : 2);
    for (const row of incremental.manifest.passages) {
      const old = cold.manifest.passages.find(item => item.passage_id === row.passage_id && item.text_sha256 === row.text_sha256);
      if (old) assert.deepEqual(incremental.binary.subarray(row.vector_row * 2048, (row.vector_row + 1) * 2048),
        cold.binary.subarray(old.vector_row * 2048, (old.vector_row + 1) * 2048));
    }
  }
});

test("every embedding configuration dependency and exact space drift prohibit mixing", async () => {
  const cold = await build(inputs);
  for (const key of Object.keys(config)) {
    const drifted = {...config, [key]: `${config[key]} changed`};
    // Provider/model/dimensions are independently rejected by response validation;
    // production configuration is fixed. Exercise the remaining cache-key axes.
    if (["dimension", "model"].includes(key)) continue;
    const result = await buildGeneration({corpus: structuredClone(inputs), previous: cold, config: drifted, embedBatch: provider()});
    assert.equal(result.reused, 0, key);
  }
  const drift = await build(inputs, cold, {embedBatch: provider(0.000001)});
  assert.equal(drift.result.reused, 0, "tiny changes below old rounded/cosine gates still rebuild");
  assert.equal((await build(inputs, cold, {force: true})).result.reused, 0);
  assert.equal((await build(inputs, {...cold, manifest: {...cold.manifest, reuse_contract: undefined}})).result.reused, 0);
});

test("corrupt shape, bytes, hashes, ownership, row layout and canaries recover cold", async () => {
  const cold = await build(inputs);
  const mutations = [asset => {asset.binary[0] ^= 1;}, asset => {asset.manifest.vector_bytes++;},
    asset => {asset.manifest.passages[0].parent_id = "someone-else";},
    asset => {asset.manifest.passages[1].passage_id = asset.manifest.passages[0].passage_id;},
    asset => {asset.manifest.passages[0].vector_row = 1;},
    asset => {asset.canaries.canaries[0].exact_embedding[0] += 0.1;},
    asset => {asset.binary.writeUInt16LE(0x7c00, 0); asset.manifest.vector_sha256 = digest(asset.binary);}];
  for (const mutate of mutations) {
    const asset = {manifest: structuredClone(cold.manifest), binary: Buffer.from(cold.binary), canaries: structuredClone(cold.canaries)};
    mutate(asset);
    const recovered = await build(inputs, asset);
    assert.equal(recovered.result.reused, 0);
    assert.deepEqual(recovered.binary, cold.binary);
  }
});

test("the preceding intact reuse contract stays deployable but cannot supply cached rows", async () => {
  const cold = await build(inputs);
  delete cold.manifest.reuse_permitted;
  delete cold.canaries.reuse_permitted;
  delete cold.canaries.batch_space_checks;
  cold.manifest.canary_sha256 = digest(JSON.stringify(cold.canaries));
  cold.manifest.integrity_sha256 = manifestDigest(cold.manifest);
  assert.equal(validateAsset(cold.manifest, cold.binary, cold.canaries), true);
  assert.throws(() => validateAsset(cold.manifest, cold.binary, cold.canaries, {requireReusable: true}), /reuse manifest integrity/);
  assert.equal((await build(inputs, cold)).result.reused, 0);
  cold.binary[0] ^= 1;
  assert.throws(() => validateAsset(cold.manifest, cold.binary, cold.canaries), /binary contract/);
});

test("failures and overall request/time exhaustion produce no replacement release", async () => {
  const cold = await build(inputs);
  const before = Buffer.from(cold.binary);
  for (const overrides of [{maxRequests: 0}, {deadline: 0}, {embedBatch: async () => {throw new Error("unavailable");}},
    {embedBatch: async texts => ({vectors: texts.map(() => Array(1024).fill(NaN)), receipt: {model: config.model}})}]) {
    await assert.rejects(build([...inputs, passage("new")], cold, overrides));
    assert.deepEqual(cold.binary, before);
  }
});

test("same corpus with a new space retains the immediately prior Worker identity", async () => {
  const cold = await build(inputs);
  const prior = buildAllowlist(cold.manifest, null);
  const updated = await build(inputs, cold, {embedBatch: provider(0.000001)});
  const allowlist = buildAllowlist(updated.manifest, prior);
  assert.equal(allowlist.current.corpus_sha256, allowlist.previous.corpus_sha256);
  assert.notEqual(allowlist.current.model_space_fingerprint, allowlist.previous.model_space_fingerprint);
});

test("identity drift inside a fresh batch cannot mix with reused rows", async () => {
  const cold = await build(inputs);
  let calls = 0;
  await assert.rejects(build([...inputs, ...Array.from({length: 251}, (_, i) => passage(`new-${i}`))], cold, {
    embedBatch: texts => provider(calls++ ? 0.000001 : 0)(texts),
  }), /space changed during generation/);
});

test("unrounded variation permits only homogeneous fresh builds and never certifies later reuse", async () => {
  const corpus = Array.from({length: 256}, (_, i) => passage(`fresh-${i}`));
  let calls = 0;
  const cold = await build(corpus, null, {embedBatch: texts => provider(calls++ * 0.000001)(texts)});
  assert.equal(cold.result.reused, 0);
  assert.equal(cold.result.changed.length, 256);
  assert.equal(cold.manifest.reuse_permitted, false);
  assert.equal(cold.result.reuseReason, "homogeneous_unstable_identity");
  assert.equal(cold.result.receipts.length, 2, "the previous full-build request ceiling is unchanged");
  assert.equal((await build(corpus, cold)).result.reused, 0, "even a repeated preflight cannot certify this prior generation");
  const invalid = structuredClone({manifest: cold.manifest, canaries: cold.canaries});
  invalid.manifest.reuse_permitted = invalid.canaries.reuse_permitted = true;
  invalid.manifest.canary_sha256 = digest(JSON.stringify(invalid.canaries));
  invalid.manifest.integrity_sha256 = manifestDigest(invalid.manifest);
  assert.throws(() => validateAsset(invalid.manifest, cold.binary, invalid.canaries), /reuse manifest integrity/,
    "a homogeneous fallback cannot be certified for reuse even with recomputed file hashes");
  calls = 0;
  await assert.rejects(build(corpus, null, {embedBatch: async texts => {
    const result = await provider()(texts);
    if (calls++) result.vectors = result.vectors.map(vector => Float32Array.from(vector, x => -x));
    return result;
  }}), /space changed during generation/, "gross discontinuity still blocks every build");
});

test("coherent writes roll back failures and exclude concurrent builders", async () => {
  const directory = await mkdtemp(join(tmpdir(), "funding-vectors-"));
  const root = pathToFileURL(directory + "/");
  try {
    const files = [new URL("vectors.bin", root), new URL("manifest.json", root)];
    await writeCoherentFiles(files.map(path => [path, "prior"]));
    let replacements = 0;
    await assert.rejects(writeCoherentFiles(files.map(path => [path, "next"]), async (...args) => {
      if (++replacements === 2) throw new Error("synthetic persistence failure");
      return rename(...args);
    }), /persistence failure/);
    assert.deepEqual(await Promise.all(files.map(path => readFile(path, "utf8"))), ["prior", "prior"]);
    await withBuildLock(root, async () => {
      await assert.rejects(withBuildLock(root, async () => assert.fail("concurrent writer entered")), /EEXIST/);
    });
    await withBuildLock(root, () => writeCoherentFiles(files.map(path => [path, "next"])));
    assert.deepEqual((await readdir(root)).sort(), ["manifest.json", "vectors.bin"]);
    assert.deepEqual(await Promise.all(files.map(path => readFile(path, "utf8"))), ["next", "next"]);
  } finally {
    await rm(directory, {recursive: true, force: true});
  }
});

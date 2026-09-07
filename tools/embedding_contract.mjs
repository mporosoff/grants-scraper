// Shared by the production builder and release validation. Legacy packages may
// be served, but cannot supply reusable rows until this complete contract exists.
import { createHash } from "node:crypto";

export const digest = value => createHash("sha256").update(value).digest("hex");
export const configuration = preprocessingSha => ({
  contract_version: 1, provider: "https://api.voyageai.com/v1/embeddings",
  model: "voyage-4-lite", dimension: 1024, input_type: "document",
  truncation: true, source_output_dtype: "float", normalization: "provider-output-unmodified",
  preprocessing_sha256: preprocessingSha, chunking: "one-buildCorpus-passage-per-input",
  encoding: "ieee754-float16-little-endian-v1",
});

export function validateFloatVectors(vectors, count, dimension = 1024) {
  if (!Array.isArray(vectors) || vectors.length !== count) throw new Error("Embedding count mismatch.");
  for (const vector of vectors) {
    if (!(Array.isArray(vector) || vector instanceof Float32Array) || vector.length !== dimension
      || Array.from(vector).some(x => typeof x !== "number" || !Number.isFinite(x))
      || !vector.some(x => x !== 0)) throw new Error("Invalid embedding values or shape.");
  }
  return vectors;
}

export function exactSpaceIdentity(config, canaries, responseModel) {
  validateFloatVectors(canaries.map(row => row.exact_embedding), canaries.length, config.dimension);
  if (responseModel !== config.model || !canaries.length) throw new Error("Unknown embedding identity.");
  // No rounding and no cosine threshold is used to authorize reuse. This is an
  // observed space identity, not an invented provider revision. Any bit drift
  // requires a homogeneous rebuild; the independent coarse canary gate remains.
  return digest(JSON.stringify({config, response_model: responseModel, canaries: canaries.map(row => ({
    id: row.id, text_sha256: row.text_sha256, embedding: row.exact_embedding,
  }))}));
}

export function manifestDigest(manifest) {
  const { integrity_sha256, ...content } = manifest;
  return digest(JSON.stringify(content));
}

export function validateAsset(manifest, binary, canaries, { requireReusable = false } = {}) {
  const fail = message => { throw new Error(`Invalid semantic package: ${message}`); };
  if (manifest?.model !== "voyage-4-lite" || manifest.dimension !== 1024
    || manifest.dtype !== "float16-le" || manifest.byte_order !== "little-endian"
    || !Array.isArray(manifest.passages) || manifest.passages.length !== manifest.passage_count
    || binary.length !== manifest.passage_count * manifest.dimension * 2
    || binary.length !== manifest.vector_bytes || digest(binary) !== manifest.vector_sha256) fail("binary contract");
  if (canaries?.model_alias !== manifest.model || canaries?.response_model !== manifest.response_model
    || canaries?.dimension !== manifest.dimension || canaries?.input_type !== "document"
    || canaries?.source_output_dtype !== "float" || canaries?.canary_set_version !== 1
    || canaries?.model_space_fingerprint !== manifest.model_space_fingerprint
    || !Array.isArray(canaries?.canaries) || canaries.canaries.length !== 6
    || new Set(canaries.canaries.map(row => row.id)).size !== 6
    || canaries.canaries.some(row => !/^[a-f0-9]{64}$/.test(row.text_sha256))) fail("canary contract");
  validateFloatVectors(canaries.canaries.map(row => row.embedding), 6);
  const roundedFingerprint = digest(JSON.stringify({canary_set_version: 1, model: manifest.model,
    dimension: 1024, input_type: "document", output_dtype: "float", rounding_decimals: 4,
    canaries: canaries.canaries.map(row => ({id: row.id, embedding: row.embedding}))}));
  if (roundedFingerprint !== (canaries.rounded_fingerprint || canaries.model_space_fingerprint)) fail("canary fingerprint");
  const ids = new Set();
  for (const [index, row] of manifest.passages.entries()) {
    const parent = row.passage_kind === "parent";
    if ((!parent && row.passage_kind !== "publication_eligible_child")
      || row.passage_id !== `${parent ? "parent" : "child"}:${row.record_id}`
      || !row.record_id || typeof row.parent_id !== "string" || !row.parent_id
      || (parent && row.parent_id !== row.record_id) || row.vector_row !== index
      || ids.has(row.passage_id) || !/^[a-f0-9]{64}$/.test(row.text_sha256)) fail("passage ownership or layout");
    ids.add(row.passage_id);
    let nonzero = false;
    for (let offset = index * 2048; offset < (index + 1) * 2048; offset += 2) {
      const word = binary.readUInt16LE(offset);
      if ((word & 0x7c00) === 0x7c00) fail("non-finite vector");
      if (word & 0x7fff) nonzero = true;
    }
    if (!nonzero) fail("zero vector");
  }
  if (requireReusable || manifest.reuse_contract) {
    const config = manifest.reuse_contract;
    if (!config || typeof manifest.reuse_permitted !== "boolean"
      || manifest.reuse_permitted !== canaries?.reuse_permitted
      || !Array.isArray(canaries?.batch_space_checks)
      || canaries.batch_space_checks.some(check => typeof check?.exact_match !== "boolean"
        || !Number.isFinite(check.minimum_cosine) || !Number.isFinite(check.mean_cosine)
        || check.minimum_cosine < .95 || check.mean_cosine < .98
        || check.gross_discontinuity !== false || (manifest.reuse_permitted && !check.exact_match))
      || digest(JSON.stringify(config)) !== manifest.configuration_sha256
      || JSON.stringify(config) !== JSON.stringify(configuration(config.preprocessing_sha256))
      || !/^[a-f0-9]{64}$/.test(config.preprocessing_sha256)
      || manifestDigest(manifest) !== manifest.integrity_sha256
      || canaries?.reuse_space_identity !== manifest.reuse_space_identity
      || manifest.model_space_fingerprint !== manifest.reuse_space_identity
      || canaries?.model_space_fingerprint !== manifest.model_space_fingerprint
      || exactSpaceIdentity(config, canaries?.canaries || [], canaries?.response_model) !== manifest.reuse_space_identity
      || manifest.canary_sha256 !== digest(JSON.stringify(canaries))) fail("reuse manifest integrity");
  }
  return true;
}

export function reusableRows(corpus, previous, config, spaceIdentity, force = false) {
  const reusable = !force && previous?.manifest?.reuse_permitted === true && previous?.manifest?.reuse_contract
    && previous.manifest.configuration_sha256 === digest(JSON.stringify(config))
    && previous.manifest.reuse_space_identity === spaceIdentity;
  if (reusable) validateAsset(previous.manifest, previous.binary, previous.canaries, {requireReusable: true});
  const rows = new Map((reusable ? previous.manifest.passages : []).map(row => [row.passage_id, row]));
  return corpus.map(row => {
    const prior = rows.get(row.passage_id);
    return prior && ["parent_id", "record_id", "passage_kind"].every(key => row[key] === prior[key])
      && digest(row.text) === prior.text_sha256 ? prior.vector_row : null;
  });
}

// Assemble the existing vector contract from seven accepted owned responses.
// No request client or provider credential is used by this entry point.
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {buildGeneration} from './build_search_v2_voyage_vectors.mjs';
import {configuration, manifestDigest, validateAsset} from './embedding_contract.mjs';
import {corpusHash} from './catalog_correction_bodies.mjs';

const sha = value => createHash('sha256').update(value).digest('hex');
const json = async path => JSON.parse(await readFile(path, 'utf8'));
const bytes = value => JSON.stringify(value, null, 2) + '\n';
const require = (ok, message) => { if (!ok) throw Error('catalog_vector_export_' + message); };
const number = value => Number(Number(value).toFixed(6));

export async function validateVectorPrefix({corpus, previous, responses, preprocessingSha}) {
  require(Array.isArray(responses) && responses.length >= 1 && responses.length <= 7, 'bounded_response_prefix');
  class NeedNextAcceptedBatch extends Error {}
  let cursor = 0;
  try {
    await buildGeneration({corpus:structuredClone(corpus), previous, force:true,
      config:configuration(preprocessingSha), maxRequests:7, deadline:Infinity,
      embedBatch:async texts => {
        if (cursor === responses.length) throw new NeedNextAcceptedBatch();
        const row = responses[cursor++];
        require(row && JSON.stringify(texts) === JSON.stringify(row.body.input), 'request_order_and_texts');
        const rows = row.payload.data.slice().sort((a, b) => a.index - b.index);
        require(rows.length === texts.length && rows.every((v, i) => v.index === i), 'complete_response_indexes');
        return {vectors:rows.map(r => Float32Array.from(r.embedding)), receipt:{model:row.payload.model}};
      }});
    require(cursor === responses.length && cursor === 7, 'complete_response_prefix');
    return {accepted_prefix:cursor, complete:true, provider_requests:0};
  } catch (error) {
    if (!(error instanceof NeedNextAcceptedBatch)) throw error;
    require(cursor === responses.length && cursor < 7, 'exact_next_batch_boundary');
    return {accepted_prefix:cursor, complete:false, provider_requests:0};
  }
}

export async function assembleVectors({corpus, previous, responses, generatedAt, preprocessingSha, sourceHashes}) {
  require(Array.isArray(responses) && responses.length === 7 && /^\d{4}-\d\d-\d\dT/.test(generatedAt), 'complete_owned_packet');
  let cursor = 0;
  const built = await buildGeneration({corpus:structuredClone(corpus), previous, force:true,
    config:configuration(preprocessingSha), maxRequests:7, deadline:Infinity,
    embedBatch:async (texts, batchIndex) => {
      const row = responses[cursor++];
      require(row && JSON.stringify(texts) === JSON.stringify(row.body.input), 'request_order_and_texts');
      const data = row.payload.data.slice().sort((a, b) => a.index - b.index);
      require(data.length === texts.length && data.every((v, i) => v.index === i), 'complete_response_indexes');
      return {vectors:data.map(r => Float32Array.from(r.embedding)), receipt:{
        batch_index:batchIndex, passage_count:texts.length, http_status:200,
        request_id:row.request_id, model:row.payload.model,
        usage_total_tokens:row.payload.usage.total_tokens,
        request_payload_bytes:row.wire_bytes, response_payload_bytes:row.response_bytes,
        latency_ms:number(row.elapsed_seconds * 1000)}};
    }});
  require(cursor === 7 && built.reused === 0, 'seven_complete_fresh_batches');
  const {canaryArtifact, canaryComparison, vectorWords, receipts, quantizationCosines} = built;
  const vectorBuffer = Buffer.alloc(vectorWords.length * 2);
  vectorWords.forEach((word, i) => vectorBuffer.writeUInt16LE(word, i * 2));
  canaryArtifact.generated_at = generatedAt;
  const manifest = {
    schema_version:1, generated_at:generatedAt, model:'voyage-4-lite',
    provider_revision:'not exposed by the real-time embedding API', response_model:'voyage-4-lite',
    input_type:'document', source_output_dtype:'float', dimension:1024, dtype:'float16-le', byte_order:'little-endian',
    passage_count:corpus.length, parent_passage_count:corpus.filter(r => r.passage_kind === 'parent').length,
    child_passage_count:corpus.filter(r => r.passage_kind === 'publication_eligible_child').length,
    corpus_sha256:corpusHash(corpus), vector_sha256:sha(vectorBuffer), vector_bytes:vectorBuffer.length,
    model_space_fingerprint:canaryArtifact.model_space_fingerprint,
    model_space:{canary_set_version:1, canary_count:6,
      fingerprint_method:'sha256 of exact unrounded canaries and complete embedding configuration',
      comparison_to_prior_generation:canaryComparison},
    reuse_permitted:canaryArtifact.reuse_permitted, reuse_contract:built.config,
    configuration_sha256:sha(JSON.stringify(built.config)), reuse_space_identity:canaryArtifact.reuse_space_identity,
    canary_sha256:sha(JSON.stringify(canaryArtifact)),
    stable_passage_id_contract:'parent:<opportunity_id> or child:<subtopic_id>',
    passages:corpus.map((r, vector_row) => ({passage_id:r.passage_id, parent_id:r.parent_id,
      passage_kind:r.passage_kind, record_id:r.record_id, text_sha256:sha(r.text), vector_row}))};
  manifest.integrity_sha256 = manifestDigest(manifest);
  validateAsset(manifest, vectorBuffer, canaryArtifact, {requireReusable:true});
  const tokens = receipts.reduce((s, r) => s + r.usage_total_tokens, 0);
  const receipt = {schema_version:1, generated_at:generatedAt, status:'written',
    build_mode:'forced_full_rebuild', reuse_reason:built.reuseReason, reuse_permitted:built.canaryArtifact.reuse_permitted,
    batch_space_checks:canaryArtifact.batch_space_checks, canary_request_count:1, corpus_request_count:7,
    canary_only_request_count:0, canary_input_count:42, model:manifest.model,
    provider_revision:manifest.provider_revision, response_model:manifest.response_model, input_type:'document',
    API_key_printed_or_persisted:false, passage_count:corpus.length, reused_passage_count:0,
    embedded_passage_count:corpus.length,
    removed_prior_passage_count:previous.manifest.passages.filter(r => !corpus.some(n => n.passage_id === r.passage_id)).length,
    corpus_sha256:manifest.corpus_sha256, vector_sha256:manifest.vector_sha256, vector_format:manifest.dtype,
    vector_bytes:manifest.vector_bytes, build_timestamp:generatedAt, model_space_fingerprint:manifest.model_space_fingerprint,
    model_space:manifest.model_space, source_hashes:sourceHashes, API_requests:receipts, API_request_count:7,
    usage_total_tokens:tokens, estimated_cost_at_published_paid_pricing_usd:number(tokens / 1_000_000 * .02),
    float16_quantization:{vectors_checked:quantizationCosines.length,
      minimum_cosine_to_float32:number(Math.min(...quantizationCosines)),
      mean_cosine_to_float32:number(quantizationCosines.reduce((s, v) => s + v, 0) / quantizationCosines.length),
      spent_set_candidate_recall_validation_required:true},
    vectors_contain_public_passages_only:true, vectors_persist_private_profile_or_researcher_data:false,
    production_reused_vectors:false, production_generation_uniform:{model_alias_count:1, response_model_count:1,
      dimension_count:1, output_type_count:1, build_timestamp_count:1, canary_fingerprint_count:1, corpus_sha_count:1, vector_sha_count:1}};
  return new Map([['data/search-v2-voyage-vectors.f16', vectorBuffer],
    ['data/search-v2-voyage-canaries.json', bytes(canaryArtifact)],
    ['data/search-v2-voyage-manifest.json', bytes(manifest)],
    ['evaluation/search_v2_hybrid_vector_build.json', bytes(receipt)]]);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [inputArg, packetArg, destinationArg] = process.argv.slice(2);
  const input = resolve(inputArg), original = join(input, 'original-candidate/files');
  const packet = await json(packetArg);
  const previous = {manifest:await json(join(original, 'data/search-v2-voyage-manifest.json')),
    canaries:await json(join(original, 'data/search-v2-voyage-canaries.json')),
    binary:await readFile(join(original, 'data/search-v2-voyage-vectors.f16'))};
  const complete = {...packet, corpus:await json(join(input, 'corpus.json')), previous};
  if (destinationArg === '--validate-prefix') {
    console.log(JSON.stringify(await validateVectorPrefix(complete)));
    process.exit(0);
  }
  const files = await assembleVectors(complete);
  for (const [name, value] of files) {
    const target = join(destinationArg, name);
    await mkdir(resolve(target, '..'), {recursive:true});
    await writeFile(target, value, {flag:'wx'});
  }
  console.log(JSON.stringify({files:Object.fromEntries([...files].map(([name, value]) => [name, sha(value)])), provider_requests:0}));
}

// Pure reconstruction of one pinned public corpus and its finite request wires.
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {resolve, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {loadHarness, makeVariantHarness} from './run_search_diagnosis.mjs';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const sha = value => createHash('sha256').update(value).digest('hex');
const json = async path => JSON.parse(await readFile(path, 'utf8'));
const assignment = text => JSON.parse(text.match(/globalThis\.\w+\s*=\s*([\s\S]*);/)[1]);
const check = (ok, reason) => { if (!ok) throw Error('catalog_correction_' + reason); };
export const corpusHash = rows => sha(rows.map(r => `${r.passage_id}\0${r.parent_id}\0${r.text}\n`).join(''));

export async function prepareBodies(directory) {
  const root = resolve(directory), p = await json(join(ROOT, 'config/catalog_vpr_correction_v1.json'));
  const hybridSource = await readFile(join(ROOT, 'assets/search-hybrid.js'), 'utf8');
  const builderSource = await readFile(join(ROOT, 'tools/build_search_v2_voyage_vectors.mjs'), 'utf8');
  check(sha(hybridSource) === p.hybrid_sha256 && sha(builderSource) === p.vector_builder_sha256, 'exact_preprocessing');
  const context = {globalThis:{}};
  vm.runInNewContext(hybridSource, context);
  const hybrid = context.globalThis.FUNDING_HYBRID_SEARCH;
  const canaries = vm.runInNewContext(builderSource.match(/const MODEL_SPACE_CANARIES = Object.freeze\(([\s\S]*?)\);/)[1]);
  const capacity = Number(builderSource.match(/const BATCH_SIZE = (\d+);/)[1]) - canaries.length;
  check(capacity === 250 && canaries.length === 6, 'fixed_batch_contract');
  const candidate = join(root, 'original-candidate/files');
  const child = assignment(await readFile(join(candidate, 'data/subtopics.js'), 'utf8'));
  const corrected = await json(join(root, 'corrected-catalog.json'));
  const base = await loadHarness();
  base.childCatalog = base.retrievalApi.createChildCatalog(child);
  const corpus = catalog => {
    const h = makeVariantHarness({...base, catalog}, {searchV2:true});
    const gate = h.parentEngine.score('funding research', {evidence:false});
    return hybrid.buildCorpus({parentCatalog:h.parentCatalog, childCatalog:h.childCatalog,
      currentnessRejectedIndexes:gate.currentnessRejectedIndexes});
  };
  const original = corpus(assignment(await readFile(join(candidate, 'data/opportunities.js'), 'utf8')));
  const oldManifest = await json(join(candidate, 'data/search-v2-voyage-manifest.json'));
  check(corpusHash(original) === oldManifest.corpus_sha256 && oldManifest.reuse_permitted === false, 'original_corpus');
  const rows = corpus(corrected), before = new Map(original.map(r => [r.passage_id, r]));
  check(rows.length === p.corpus_passages && corpusHash(rows) === p.corpus_sha256, 'corrected_corpus');
  check(original.every(r => p.withheld_ids.some(id => r.passage_id === 'parent:' + id)
    ? !rows.some(n => n.passage_id === r.passage_id)
    : rows.some(n => n.passage_id === r.passage_id && n.text === r.text)), 'all_nonquarantined_original_passages_preserved');
  const files = new Map([['corpus.json', JSON.stringify(rows)]]);
  for (let offset = 0; offset < rows.length; offset += capacity) {
    files.set(`embedding-${Math.floor(offset / capacity) + 1}.json`, JSON.stringify({
      input:[...rows.slice(offset, offset + capacity).map(r => r.text), ...canaries.map(r => r.text)],
      model:'voyage-4-lite', input_type:'document', truncation:true, output_dimension:1024, output_dtype:'float'}));
  }
  const previous = (await json(join(candidate, 'workers/search-voyage-proxy/generated/corpus-allowlist.json'))).previous;
  check(previous.corpus_sha256 === p.previous_published_corpus_sha256, 'previous_published_corpus');
  const allowed = new Map(rows.map(r => [r.passage_id, sha(r.text)]));
  const shared = hybrid.buildCorpus({parentCatalog:corrected, childCatalog:child}).find(r =>
    allowed.get(r.passage_id) === sha(r.text) && previous.passages.some(q => q.passage_id === r.passage_id && q.text_sha256 === sha(r.text)));
  check(shared?.passage_id === p.smoke_passage_id && sha(shared.text) === p.smoke_passage_sha256, 'exact_smoke_passage');
  const workerSource = await readFile(join(ROOT, 'workers/search-voyage-proxy/src/index.js'), 'utf8');
  const instruction = JSON.parse(workerSource.match(/const QUERY_INSTRUCTION = ("[^\n]+");/)[1]);
  files.set('smoke-embed-provider.json', JSON.stringify({input:['catalysis'], model:'voyage-4-lite',
    input_type:'query', truncation:true, output_dimension:1024, output_dtype:'float'}));
  const rerank = JSON.stringify({query:instruction.replace('<QUERY>', 'catalysis'), documents:[shared.text],
    model:'rerank-2.5', top_k:1, return_documents:false, truncation:true});
  files.set('smoke-current-rerank-provider.json', rerank);
  files.set('smoke-previous-rerank-provider.json', rerank);
  check(sha(files.get('corpus.json')) === p.corpus_file_sha256, 'exact_corpus_bytes');
  for (const op of [...p.embedding_requests, ...p.smoke_requests]) {
    const wire = files.get(op.body_file);
    check(sha(wire) === op.body_sha256 && Buffer.byteLength(wire) === op.wire_bytes
      && Buffer.byteLength(wire) + 1024 === op.maximum_input_tokens, 'complete_body_bound');
  }
  for (const [name, wire] of files) await writeFile(join(root, name), wire);
  return {files:files.size, original_passages:before.size, corrected_passages:rows.length, provider_requests:0};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(JSON.stringify(await prepareBodies(process.argv[2])));
}

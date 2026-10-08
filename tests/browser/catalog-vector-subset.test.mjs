import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, writeFile, readFile, readdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {projectSubset, projectCompatibility, corpusHash, REMOVED_PARENTS} from '../../tools/catalog_vector_subset.mjs';
import {configuration, digest, exactSpaceIdentity, manifestDigest, validateAsset, reusableRows} from '../../tools/embedding_contract.mjs';
import {buildAllowlist} from '../../tools/build_search_release_package.mjs';

function fixture() {
  const parent = id => ({passage_id:'parent:' + id, parent_id:id, record_id:id,
    passage_kind:'parent', title:id, fields:['parent_title'], values:{parent_title:[id]}, text:'Parent title: ' + id});
  const originalCorpus = [parent('alpha'), ...REMOVED_PARENTS.map(parent), parent('nsf-official'),
    {passage_id:'child:science', parent_id:'alpha', record_id:'science', passage_kind:'publication_eligible_child',
      title:'Science', fields:['child_title'], values:{child_title:['Science']}, text:'Publication-eligible child title: Science'}]
    .sort((a, b) => a.passage_id.localeCompare(b.passage_id));
  const config = configuration(digest('synthetic pinned preprocessing'));
  const canaryRows = Array.from({length:6}, (_, i) => ({id:'canary-' + i, text_sha256:digest('public canary ' + i),
    embedding:Array(1024).fill((i + 1) / 100), exact_embedding:Array(1024).fill((i + 1) / 100)}));
  const identity = exactSpaceIdentity(config, canaryRows, config.model);
  const canaries = {canary_set_version:1, model_alias:config.model, response_model:config.model,
    dimension:1024, input_type:'document', source_output_dtype:'float', model_space_fingerprint:identity,
    reuse_space_identity:identity, reuse_permitted:false,
    batch_space_checks:[{exact_match:false, minimum_cosine:.9999, mean_cosine:.9999, gross_discontinuity:false}],
    canaries:canaryRows,
    rounded_fingerprint:digest(JSON.stringify({canary_set_version:1, model:config.model, dimension:1024,
      input_type:'document', output_dtype:'float', rounding_decimals:4,
      canaries:canaryRows.map(row => ({id:row.id, embedding:row.embedding}))}))};
  const binary = Buffer.alloc(originalCorpus.length * 2048);
  originalCorpus.forEach((row, i) => {
    for (let j = 0; j < 1024; j++) binary.writeUInt16LE(0x3000 + i * 64 + j % 64, i * 2048 + j * 2);
  });
  const manifest = {schema_version:1, generated_at:'2026-10-08T19:10:24.139Z', model:config.model,
    response_model:config.model, input_type:'document', source_output_dtype:'float', dimension:1024,
    dtype:'float16-le', byte_order:'little-endian', passage_count:originalCorpus.length,
    parent_passage_count:REMOVED_PARENTS.length + 2, child_passage_count:1, corpus_sha256:corpusHash(originalCorpus),
    vector_sha256:digest(binary), vector_bytes:binary.length, reuse_permitted:false, reuse_contract:config,
    configuration_sha256:digest(JSON.stringify(config)), model_space_fingerprint:identity,
    reuse_space_identity:identity, canary_sha256:digest(JSON.stringify(canaries)),
    model_space:{canary_count:6, comparison_to_prior_generation:{gross_discontinuity:false}},
    passages:originalCorpus.map((row, vector_row) => ({passage_id:row.passage_id, parent_id:row.parent_id,
      record_id:row.record_id, passage_kind:row.passage_kind, text_sha256:digest(row.text), vector_row}))};
  manifest.integrity_sha256 = manifestDigest(manifest);
  return {originalCorpus, corpus:originalCorpus.filter(row => !REMOVED_PARENTS.includes(row.parent_id)), manifest, binary, canaries};
}

test('withdrawal copies exact row bytes and retains the false reuse policy and original space evidence', () => {
  const input = fixture(), before = structuredClone(input.manifest), binaryBefore = Buffer.from(input.binary);
  const canariesBefore = JSON.stringify(input.canaries), result = projectSubset(input);
  assert.equal(result.manifest.passage_count, 3);
  assert.equal(result.manifest.parent_passage_count, 2);
  assert.equal(result.manifest.child_passage_count, 1);
  assert.equal(result.manifest.reuse_permitted, false);
  assert.equal(result.manifest.generated_at, before.generated_at);
  assert.equal(result.manifest.model_space_fingerprint, before.model_space_fingerprint);
  assert.equal(result.manifest.canary_sha256, before.canary_sha256);
  assert.deepEqual(result.manifest.reuse_contract, before.reuse_contract);
  assert.deepEqual(result.manifest.model_space, before.model_space);
  assert.equal(validateAsset(result.manifest, result.binary, input.canaries, {requireReusable:true}), true);
  for (const [index, row] of result.manifest.passages.entries()) {
    const original = before.passages.find(item => item.passage_id === row.passage_id);
    assert.equal(row.vector_row, index);
    assert.deepEqual(result.binary.subarray(index * 2048, (index + 1) * 2048),
      binaryBefore.subarray(original.vector_row * 2048, (original.vector_row + 1) * 2048));
  }
  assert.deepEqual(input.manifest, before);
  assert.deepEqual(input.binary, binaryBefore);
  assert.equal(JSON.stringify(input.canaries), canariesBefore);
  assert.deepEqual(reusableRows(input.corpus, {manifest:result.manifest, binary:result.binary, canaries:input.canaries},
    input.manifest.reuse_contract, input.manifest.reuse_space_identity), [null, null, null]);
});

test('changed text, ownership, kind, title or input fields cannot borrow an old vector', () => {
  for (const change of [row => {row.text += ' amendment';}, row => {row.parent_id = 'other';},
    row => {row.record_id = 'other';}, row => {row.passage_kind = 'parent';},
    row => {row.title = 'New title';}, row => {row.values.child_title = ['different'];}]) {
    const input = fixture(); input.corpus = structuredClone(input.corpus); change(input.corpus[0]);
    assert.throws(() => projectSubset(input), /exact_ordered_corpus_subset/);
  }
});

test('additional removal, retention of a withdrawn row, duplicate, reorder or new passage fails closed', () => {
  for (const change of [rows => rows.slice(1), rows => [...rows, rows[0]], rows => rows.toReversed(),
    (rows, input) => [...rows, input.originalCorpus.find(row => row.parent_id === REMOVED_PARENTS[0])],
    rows => [...rows, {...rows[0], passage_id:'child:new', record_id:'new'}]]) {
    const input = fixture(); input.corpus = change(input.corpus, input);
    assert.throws(() => projectSubset(input), /exact_ordered_corpus_subset/);
  }
});

test('all original corpus and vector identities are checked before selecting a subset', () => {
  const corruptions = [input => {input.binary[0] ^= 1;}, input => {input.manifest.passages[0].vector_row = 2;},
    input => {input.manifest.passages[1].parent_id = 'different';},
    input => {input.canaries.canaries[0].exact_embedding[0] += .01;},
    input => {input.manifest.reuse_permitted = true;},
    input => {input.originalCorpus = structuredClone(input.originalCorpus); input.originalCorpus[0].text += ' changed';}];
  for (const change of corruptions) {
    const input = fixture(); change(input);
    assert.throws(() => projectSubset(input));
  }
});

test('an apparently valid asset with unexpected withdrawn children is outside the fixed scope', () => {
  const input = fixture(), index = input.originalCorpus.findIndex(row => row.passage_kind === 'publication_eligible_child');
  input.originalCorpus[index].parent_id = REMOVED_PARENTS[0];
  input.manifest.passages[index].parent_id = REMOVED_PARENTS[0];
  input.manifest.corpus_sha256 = corpusHash(input.originalCorpus);
  input.manifest.integrity_sha256 = manifestDigest(input.manifest);
  input.corpus = input.originalCorpus.filter(row => !REMOVED_PARENTS.includes(row.parent_id));
  assert.throws(() => projectSubset(input), /fixed_parent_rows_without_children/);
});

test('all named parent passages must exist in the authenticated parent', () => {
  const input = fixture(), row = input.originalCorpus.find(row => row.parent_id === REMOVED_PARENTS[1]);
  const index = input.originalCorpus.indexOf(row);
  Object.assign(row, {passage_id:'parent:elsewhere', parent_id:'elsewhere', record_id:'elsewhere'});
  Object.assign(input.manifest.passages[index], {passage_id:row.passage_id, parent_id:row.parent_id, record_id:row.record_id});
  input.manifest.corpus_sha256 = corpusHash(input.originalCorpus);
  input.manifest.integrity_sha256 = manifestDigest(input.manifest);
  assert.throws(() => projectSubset(input), /all_withdrawn_parents_present/);
});

test('compatibility retains the published predecessor and never promotes the unpublished parent', () => {
  const input = fixture(), result = projectSubset(input);
  const published = {...input.manifest, corpus_sha256:digest('actually published corpus'),
    model_space_fingerprint:digest('actually published space')};
  const existing = buildAllowlist(input.manifest, null, published);
  const parentRelease = {previous_corpus_sha256:published.corpus_sha256};
  const corrected = projectCompatibility(result.manifest, existing, parentRelease);
  assert.deepEqual(corrected.previous, existing.previous);
  assert.equal(corrected.current.corpus_sha256, result.manifest.corpus_sha256);
  assert.ok(!corrected.current.passages.some(row => REMOVED_PARENTS.some(id => row.passage_id === 'parent:' + id)));
  assert.notEqual(corrected.previous.corpus_sha256, input.manifest.corpus_sha256);
  assert.throws(() => projectCompatibility(result.manifest, existing, {previous_corpus_sha256:'untrusted'}), /published_previous/);
  assert.throws(() => projectCompatibility(result.manifest, {current:existing.current}, parentRelease), /published_previous/);
});

test('CLI refuses an unpinned parent before writing any corrected payload or success receipt', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'catalog-subset-test-'));
  try {
    const parent = join(directory, 'candidate', 'files'), root = join(directory, 'corrected'), receipt = join(directory, 'proof.json');
    await mkdir(parent, {recursive:true}); await mkdir(root);
    await writeFile(join(parent, '..', 'candidate.json'), '{"candidate_id":"untrusted"}\n');
    await writeFile(join(root, 'untouched.txt'), 'keep');
    const run = spawnSync(process.execPath, [fileURLToPath(new URL('../../tools/catalog_vector_subset.mjs', import.meta.url)),
      '--parent', parent, '--root', root, '--receipt', receipt], {encoding:'utf8'});
    assert.notEqual(run.status, 0); assert.match(run.stderr, /pinned_parent_manifest/);
    assert.deepEqual(await readdir(root), ['untouched.txt']);
    assert.equal(await readFile(join(root, 'untouched.txt'), 'utf8'), 'keep');
    await assert.rejects(readFile(receipt), {code:'ENOENT'});
  } finally { await rm(directory, {recursive:true, force:true}); }
});

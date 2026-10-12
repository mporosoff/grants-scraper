import assert from 'node:assert/strict';
import test from 'node:test';
import {verifyCorpus, verifyCatalog, corpusHash} from '../../tools/catalog_identity_package.mjs';
import {configuration, digest, exactSpaceIdentity, manifestDigest} from '../../tools/embedding_contract.mjs';
const EXTRA_PARENTS = ['beta', 'gamma'];

function fixture() {
  const parent = id => ({passage_id:'parent:' + id, parent_id:id, record_id:id,
    passage_kind:'parent', title:id, fields:['parent_title'], values:{parent_title:[id]}, text:'Parent title: ' + id});
  const originalCorpus = [parent('alpha'), ...EXTRA_PARENTS.map(parent), parent('nsf-official'),
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
    parent_passage_count:EXTRA_PARENTS.length + 2, child_passage_count:1, corpus_sha256:corpusHash(originalCorpus),
    vector_sha256:digest(binary), vector_bytes:binary.length, reuse_permitted:false, reuse_contract:config,
    configuration_sha256:digest(JSON.stringify(config)), model_space_fingerprint:identity,
    reuse_space_identity:identity, canary_sha256:digest(JSON.stringify(canaries)),
    model_space:{canary_count:6, comparison_to_prior_generation:{gross_discontinuity:false}},
    passages:originalCorpus.map((row, vector_row) => ({passage_id:row.passage_id, parent_id:row.parent_id,
      record_id:row.record_id, passage_kind:row.passage_kind, text_sha256:digest(row.text), vector_row}))};
  manifest.integrity_sha256 = manifestDigest(manifest);
  return {originalCorpus, corpus:structuredClone(originalCorpus), manifest, binary, canaries};
}

test('identity package accepts identical full corpus without changing paid evidence', () => {
  const input = fixture(), manifest = structuredClone(input.manifest), binary = Buffer.from(input.binary);
  verifyCorpus(input);
  assert.deepEqual(input.manifest, manifest);
  assert.deepEqual(input.binary, binary);
  assert.equal(input.manifest.reuse_permitted, false);
});

test('same text cannot hide altered ownership, title, field labels or values', () => {
  for (const mutate of [row => row.text += ' amendment', row => row.parent_id = 'other',
    row => row.title = 'changed', row => row.fields.push('new'), row => row.values.parent_title = ['different']]) {
    const input = fixture(); mutate(input.corpus[0]);
    assert.throws(() => verifyCorpus(input), /exact_ordered_corpus_identity/);
  }
});

test('removal, insertion, duplicate or reorder cannot reuse unchanged vectors', () => {
  for (const mutate of [rows => rows.slice(1), rows => [...rows, rows[0]], rows => rows.toReversed()]) {
    const input = fixture(); input.corpus = mutate(input.corpus);
    assert.throws(() => verifyCorpus(input), /exact_ordered_corpus_identity/);
  }
});

test('corrupt original vector, canary, manifest or text fails before package creation', () => {
  for (const mutate of [input => input.binary[0] ^= 1, input => input.manifest.passages[0].vector_row = 3,
    input => input.canaries.canaries[0].exact_embedding[0] += .01,
    input => input.originalCorpus[0].text += 'changed', input => input.manifest.reuse_permitted = true]) {
    const input = fixture(); mutate(input);
    assert.throws(() => verifyCorpus(input));
  }
});

function catalogFixture() {
  const before = {generated_at:'2026-10-12T16:08:24.355794Z', diagnostic:{unchanged:true},
    opportunities:[{opportunity_id:'364039', title:'NASA science', close_date:'2027-02-05'},
      {opportunity_id:'363829', title:'Air Force science', description:'Retained scientific content'},
      {opportunity_id:'other', title:'Other agency'}]};
  const corrections = [{opportunity_id:'364039', source_aliases:[{opportunity_id:'nasa-roses:25-B.8-c9ad18a888',
    source:'NASA ROSES', opportunity_number:'NNH25ZDA001N-SSF'}]},
    {opportunity_id:'363829', source_aliases:[{opportunity_id:'vpr-email:vpr-a3ddeff815d159a4',
      official_identity:{target_url:'https://www.grants.gov/search-results-detail/363829'}}]}];
  const after = structuredClone(before);
  for (let i = 0; i < 2; i++) after.opportunities[i].source_aliases = structuredClone(corrections[i].source_aliases);
  return {before, after, corrections};
}

test('package independently restricts the entire catalog to the two exact alias additions', () => {
  const {before, after, corrections} = catalogFixture();
  const preserved = structuredClone(before);
  verifyCatalog(before, after, corrections);
  assert.deepEqual(before, preserved);
  for (const mutate of [value => value.generated_at = '2026-10-13T00:00:00Z',
    value => value.diagnostic.unchanged = false, value => value.opportunities[0].close_date = '2028-02-05',
    value => value.opportunities[1].description += ' new science',
    value => value.opportunities[2].title = 'Unrelated edit', value => value.opportunities.reverse(),
    value => value.opportunities[0].source_aliases[0].source = 'Forged owner']) {
    const altered = structuredClone(after); mutate(altered);
    assert.throws(() => verifyCatalog(before, altered, corrections), /exact_alias_only_catalog/);
  }
});

test('package refuses partial corrections and ambiguous or already present alias ownership', () => {
  const {before, after, corrections} = catalogFixture();
  assert.throws(() => verifyCatalog(before, after, corrections.slice(0, 1)), /fixed_corrections/);
  for (const mutate of [value => value.opportunities[2].opportunity_id = corrections[0].source_aliases[0].opportunity_id,
    value => value.opportunities[2].source_aliases = corrections[0].source_aliases,
    value => value.opportunities[0].source_aliases = corrections[0].source_aliases]) {
    const altered = structuredClone(before); mutate(altered);
    assert.throws(() => verifyCatalog(altered, after, corrections), /unique_alias_owner|original_alias_absent/);
  }
});

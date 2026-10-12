import assert from 'node:assert/strict';
import test from 'node:test';
import {projectionProfile, verifyUrlPayload, PARENT_CANDIDATE, VERSION} from '../../tools/catalog_identity_package.mjs';
import {digest} from '../../tools/embedding_contract.mjs';

const CATALOG = 'data/opportunities.js', CACHE = 'data/source_records.json', EVENTS = 'feeds/changes.json';
const OLD = 'https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page? SolicitationId=a0rcr00001NP7i5AAD';
const NEW = OLD.replace('? ', '?');
const EMPTY_METRICS = {document_current_count:0, document_pending_count:0, document_failed_count:0,
  citation_fact_count:0, document_deadline_count:0, limited_submission_review_count:0,
  review_queue_count:0, changed_document_count:0};
function fixture() {
  const row = url => ({opportunity_id:'nyserda:OSWPON26-1', title:'Wind research', close_date:'2027-02-05',
    description:'Historical quoted URL: ' + OLD, detail_page:url, funding_opportunity_url:url,
    deadlines:[{date:'2027-02-05', source_url:url}], contacts:[{name:'Office', source_url:url}],
    next_submission:{access:'open', event:{source_url:url}}});
  const other = {opportunity_id:'363829', title:'Unrelated', source_aliases:[{opportunity_id:'vpr:old'}]};
  const payloads = url => ({
    [CATALOG]:{generated_at:'2026-10-12T16:08:24.355794Z', opportunities:[row(url), structuredClone(other)],
      diagnostics:{document_evidence:{...EMPTY_METRICS, refreshed_count:33, not_modified_count:2,
        failed_request_count:10, failures:[{opportunity_id:'original', error:'ConnectionError'}],
        remaining_update_count:586, parser_recovery:{source_requests:45}, processing:{status:'complete'}}}},
    [CACHE]:{sources:{nyserda:{fetched_at:'2026-10-12', records:[row(url)]}, other:{records:[structuredClone(other)]}}},
    [EVENTS]:{generated_at:'2026-10-12T16:08:24.355794Z', events:[{id:'original-event', type:'new',
      changed_at:'2026-10-12T16:08:24.355794Z', record:row(url)}, {id:'other', type:'amended', record:structuredClone(other)}]}});
  const before = payloads(OLD), after = payloads(NEW);
  const policy = {url_replacements:{[OLD]:NEW}, evidence_invalidations:{},
    evidence_diagnostics:{before:{...EMPTY_METRICS}, after:{...EMPTY_METRICS}}, payloads:Object.fromEntries([CATALOG, CACHE, EVENTS].map(name =>
    [name, {affected_items:{[name === EVENTS ? 'original-event' : 'nyserda:OSWPON26-1']:{url_leaf_count:5}}}]))};
  return {before, after, policy};
}

test('explicit URL profile cannot replace the original fixed identity package policy', () => {
  const identity = projectionProfile();
  assert.equal(identity.kind, 'identity'); assert.equal(identity.parent, PARENT_CANDIDATE); assert.equal(identity.version, VERSION);
  assert.deepEqual(projectionProfile('identity'), identity);
  const url = projectionProfile('url');
  assert.equal(url.parent, '051d6844ea23709628b9c9209f4a947e309d2427928b0dc19e8ffb8eb8f3cfc4');
  assert.equal(url.manifest, 'f11c8bed90de162868348b262d6b200e2f36bb13c2601b73fbb423c5de4162c1');
  assert.equal(url.version, 'catalog-url-package-20261012-v2'); assert.notEqual(url.policy.href, identity.policy.href);
  for (const kind of ['URL', '', 'custom', '../url']) assert.throws(() => projectionProfile(kind), /fixed_projection_kind/);
});

test('catalog, source cache and retained events permit only exact URL leaves', () => {
  const {before, after, policy} = fixture(), original = structuredClone(before);
  for (const name of [CATALOG, CACHE, EVENTS]) verifyUrlPayload(name, before[name], after[name], policy);
  assert.deepEqual(before, original);
  assert.ok(after[CATALOG].opportunities[0].description.includes(OLD));
});

test('same URL edit cannot conceal changed dates, science, identity, provenance or event history', () => {
  const {before, after, policy} = fixture();
  for (const [name, mutate] of [
    [CATALOG, value => value.generated_at = '2026-10-13T00:00:00Z'],
    [CATALOG, value => value.opportunities[0].description += ' new science'],
    [CATALOG, value => value.opportunities[0].close_date = '2028-02-05'],
    [CATALOG, value => value.opportunities[1].source_aliases = []],
    [CACHE, value => value.sources.nyserda.fetched_at = '2026-10-13'],
    [EVENTS, value => value.events[0].type = 'amended'],
    [EVENTS, value => value.events[0].changed_at = '2026-10-13T00:00:00Z'],
    [EVENTS, value => value.events.pop()]]) {
    const changed = structuredClone(after[name]); mutate(changed);
    assert.throws(() => verifyUrlPayload(name, before[name], changed, policy), /exact_url_only_payload/);
  }
});

test('public description and acquisition-like fields cannot be normalized by broad replacement', () => {
  const {before, after, policy} = fixture();
  const changed = structuredClone(after[CATALOG]);
  changed.opportunities[0].description = changed.opportunities[0].description.replace(OLD, NEW);
  assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], changed, policy), /exact_url_only_payload/);
  before[CACHE].sources.nyserda.source_signature = OLD;
  after[CACHE].sources.nyserda.source_signature = NEW;
  assert.throws(() => verifyUrlPayload(CACHE, before[CACHE], after[CACHE], policy), /exact_url_only_payload/);
});

test('incomplete URL inventory, ambiguous record membership and cross-source changes fail closed', () => {
  const {before, after, policy} = fixture();
  const partial = structuredClone(policy); partial.payloads[CATALOG].affected_items['nyserda:OSWPON26-1'].url_leaf_count = 4;
  assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], partial), /exact_url_inventory/);
  const duplicate = structuredClone(before[CATALOG]); duplicate.opportunities.push(duplicate.opportunities[0]);
  assert.throws(() => verifyUrlPayload(CATALOG, duplicate, after[CATALOG], policy), /unique_payload_membership/);
  const foreign = structuredClone(before[CATALOG]); foreign.opportunities[0].opportunity_id = 'another-source:OSWPON26-1';
  assert.throws(() => verifyUrlPayload(CATALOG, foreign, after[CATALOG], policy), /nyserda_scope/);
});

test('URL mapping cannot change host, scheme, solicitation ID or append new query data', () => {
  const {before, after, policy} = fixture();
  for (const replacement of [NEW.replace('nyserda.ny.gov', 'example.org'), NEW.replace('https:', 'http:'),
    NEW.replace('a0rcr00001NP7i5AAD', 'a0rcr00001NP7i5AAE'), NEW + '&next=elsewhere']) {
    const changed = structuredClone(policy); changed.url_replacements[OLD] = replacement;
    assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], changed), /exact_url_normalization/);
  }
});

const sortedValue = value => Array.isArray(value) ? value.map(sortedValue)
  : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sortedValue(value[key])])) : value;
const recordHash = value => digest(JSON.stringify(sortedValue(value)));
const EVIDENCE_FIELDS = ['document_evidence', 'document_evidence_checked_at', 'document_evidence_status',
  'document_status_signals', 'submission_requirements'];
function evidenceFixture(mutateBefore = () => {}) {
  const value = fixture();
  const evidence = {document_evidence_status:'current', document_evidence_checked_at:'2026-09-07T01:21:25Z',
    document_evidence:{document:{url:'https://portal.nyserda.ny.gov/PortalLoginPage', sha256:'a'.repeat(64)}, facts:[],
      review_queue:[{status:'needs_review'}, {status:'needs_review'}]},
    document_search_text:null, document_status_signals:[], submission_requirements:[]};
  Object.assign(value.before[CATALOG].opportunities[0], structuredClone(evidence));
  Object.assign(value.after[CATALOG].opportunities[0], structuredClone(evidence));
  mutateBefore(value.before[CATALOG].opportunities[0]);
  mutateBefore(value.after[CATALOG].opportunities[0]);
  const row = value.after[CATALOG].opportunities[0];
  const beforeHash = recordHash(row);
  row.document_evidence_status = 'source_changed'; row.document_evidence = null;
  delete row.document_evidence_checked_at; delete row.document_status_signals; delete row.submission_requirements;
  value.policy.evidence_invalidations[row.opportunity_id] = {
    before_sha256:beforeHash, after_sha256:recordHash(row), changed_fields:EVIDENCE_FIELDS};
  value.policy.evidence_diagnostics.before = {...EMPTY_METRICS, document_current_count:1, review_queue_count:2};
  Object.assign(value.before[CATALOG].diagnostics.document_evidence, value.policy.evidence_diagnostics.before);
  return value;
}

test('pinned empty notice evidence is invalidated only in public catalog with all other payloads exact', () => {
  const {before, after, policy} = evidenceFixture(), original = structuredClone(before);
  for (const name of [CATALOG, CACHE, EVENTS]) verifyUrlPayload(name, before[name], after[name], policy);
  assert.deepEqual(before, original);
  assert.equal(after[CATALOG].opportunities[0].document_evidence_status, 'source_changed');
  assert.equal(after[CATALOG].opportunities[0].document_evidence, null);
  assert.ok(!Object.hasOwn(after[CATALOG].opportunities[0], 'document_evidence_checked_at'));
  assert.equal(after[CATALOG].diagnostics.document_evidence.document_current_count, 0);
  assert.equal(after[CATALOG].diagnostics.document_evidence.review_queue_count, 0);
});

test('invalidation requires exact before and after complete-record pins and field inventory', () => {
  for (const [mutate, error] of [
    [pin => pin.before_sha256 = '0'.repeat(64), /evidence_before_pin/],
    [pin => pin.after_sha256 = '0'.repeat(64), /evidence_after_pin/],
    [pin => pin.changed_fields = [...EVIDENCE_FIELDS, 'deadlines'], /fixed_evidence_invalidation/],
    [pin => pin.changed_fields = EVIDENCE_FIELDS.slice(1), /fixed_evidence_invalidation/],
    [pin => pin.unreviewed = true, /fixed_evidence_invalidation/],
  ]) {
    const {before, after, policy} = evidenceFixture();
    mutate(policy.evidence_invalidations['nyserda:OSWPON26-1']);
    assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), error);
  }
});

test('empty-evidence correction cannot strip scientific facts, search text, requirements or program areas', () => {
  for (const mutate of [
    row => row.document_evidence.facts = [{type:'research_scope', value:'Research'}],
    row => row.document_search_text = 'Scientific evidence',
    row => row.document_program_areas = ['cyber'],
    row => row.submission_requirements = [{required:true}],
    row => row.document_status_signals = [{status:'closed'}],
    row => row.document_evidence_status = 'failed',
    row => delete row.document_evidence_checked_at,
  ]) {
    const {before, after, policy} = evidenceFixture(mutate);
    assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /empty_public_evidence_only/);
  }
});

test('omitted invalidations, retained stale fields and unrelated catalog mutations fail closed', () => {
  for (const mutate of [
    row => row.document_evidence_status = 'current',
    row => row.document_evidence = {facts:[]},
    row => row.document_evidence_checked_at = '2026-10-12T18:00:00Z',
    row => row.document_status_signals = [],
    row => row.submission_requirements = [],
    row => row.close_date = '2028-01-01',
  ]) {
    const {before, after, policy} = evidenceFixture(); mutate(after[CATALOG].opportunities[0]);
    assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /exact_url_only_payload/);
  }
  const {before, after, policy} = evidenceFixture();
  policy.evidence_invalidations['nyserda:missing'] = policy.evidence_invalidations['nyserda:OSWPON26-1'];
  assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /exact_evidence_inventory/);
});

test('current evidence summaries are independently recomputed across all eight counters', () => {
  for (const side of ['before', 'after']) for (const key of Object.keys(EMPTY_METRICS)) {
    const {before, after, policy} = evidenceFixture();
    policy.evidence_diagnostics[side][key] += 1;
    assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /evidence_diagnostic_pins/);
  }
  const {before, after, policy} = evidenceFixture();
  policy.evidence_diagnostics.after.unreviewed_counter = 0;
  assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /evidence_diagnostic_pins/);
});

test('stale summaries and altered acquisition history cannot accompany valid record invalidations', () => {
  for (const [key, value] of [['document_current_count', 1], ['review_queue_count', 2],
    ['refreshed_count', 0], ['not_modified_count', 0], ['failed_request_count', 0],
    ['failures', []], ['remaining_update_count', 0], ['parser_recovery', {source_requests:0}],
    ['processing', {status:'incomplete'}]]) {
    const {before, after, policy} = evidenceFixture();
    after[CATALOG].diagnostics.document_evidence[key] = value;
    assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /exact_url_only_payload/);
  }
  const {before, after, policy} = evidenceFixture();
  before[CATALOG].diagnostics.document_evidence.review_queue_count = 100;
  assert.throws(() => verifyUrlPayload(CATALOG, before[CATALOG], after[CATALOG], policy), /original_evidence_diagnostics/);
});

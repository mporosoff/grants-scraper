import assert from 'node:assert/strict';
import test from 'node:test';
import {projectionProfile, verifyUrlPayload, PARENT_CANDIDATE, VERSION} from '../../tools/catalog_identity_package.mjs';

const CATALOG = 'data/opportunities.js', CACHE = 'data/source_records.json', EVENTS = 'feeds/changes.json';
const OLD = 'https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page? SolicitationId=a0rcr00001NP7i5AAD';
const NEW = OLD.replace('? ', '?');
function fixture() {
  const row = url => ({opportunity_id:'nyserda:OSWPON26-1', title:'Wind research', close_date:'2027-02-05',
    description:'Historical quoted URL: ' + OLD, detail_page:url, funding_opportunity_url:url,
    deadlines:[{date:'2027-02-05', source_url:url}], contacts:[{name:'Office', source_url:url}],
    next_submission:{access:'open', event:{source_url:url}}});
  const other = {opportunity_id:'363829', title:'Unrelated', source_aliases:[{opportunity_id:'vpr:old'}]};
  const payloads = url => ({
    [CATALOG]:{generated_at:'2026-10-12T16:08:24.355794Z', opportunities:[row(url), structuredClone(other)]},
    [CACHE]:{sources:{nyserda:{fetched_at:'2026-10-12', records:[row(url)]}, other:{records:[structuredClone(other)]}}},
    [EVENTS]:{generated_at:'2026-10-12T16:08:24.355794Z', events:[{id:'original-event', type:'new',
      changed_at:'2026-10-12T16:08:24.355794Z', record:row(url)}, {id:'other', type:'amended', record:structuredClone(other)}]}});
  const before = payloads(OLD), after = payloads(NEW);
  const policy = {url_replacements:{[OLD]:NEW}, payloads:Object.fromEntries([CATALOG, CACHE, EVENTS].map(name =>
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
  assert.equal(url.version, 'catalog-url-package-20261012-v1'); assert.notEqual(url.policy.href, identity.policy.href);
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

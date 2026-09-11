import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture} from '../helpers/shared-team-inputs.mjs';
import {buildSharedPackage} from '../../tools/build_shared_team_package.mjs';
const plain = x => JSON.parse(JSON.stringify(x));
test('same shared per-person admission and full-member team intersection; no copied fit', async () => {
  const f = await fixture(); assert(f.e.resolveScope(f.action).ok);
  const matcher = f.c.FUNDING_TEAM_MATCHER.create(f.catalog, {}, f.c.FUNDING_SEARCH_QUERY, {now: new Date(f.clock.now)});
  const prepared = matcher.records.find(r => r.id === 'call');
  for (const row of f.directory.researchers) {
    const expected = matcher.scoreProfile(f.c.FUNDING_TEAM_MATCHER.normalizeProfile(row), prepared);
    assert.deepEqual(plain(f.e.admittedFits().find(r => r.id === row.id)?.fit || null), plain(expected));
  }
  const state = f.e.proposal(f.e.opportunityById.get('call')), options = f.e.proposalOptions(state);
  assert.equal(options.length, 8); assert(state.selectedIds.length >= 2 && state.selectedIds.length <= 4);
  for (const option of options) {
    const profiles = option.state.selectedIds.map(id => f.c.FUNDING_TEAM_MATCHER.normalizeProfile(f.directory.researchers.find(p => p.id === id)));
    assert(matcher.matchTeam(profiles).results.some(r => r.id === 'call'));
    assert.equal(new Set(option.state.selectedIds).size, option.state.selectedIds.length);
  }
  assert.deepEqual(plain(f.e.proposalOptions(state)), plain(options));
  const before = plain(f.e.statistics()); f.e.resolveScope(f.action); f.e.proposalOptions(state);
  assert.equal(f.e.statistics().fits, before.fits); assert.equal(f.e.statistics().optimizations, before.optimizations);
  const exposed = f.e.admittedFits(); exposed[0].fit.score = -999;
  assert(f.e.admittedFits()[0].fit.score >= 0, 'a caller cannot corrupt cached scientific evidence');
  const view = f.e.proposalView(state);
  assert.equal(new Set([...view.selectedIds, ...view.replacements.map(r => r.profile.id)]).size, 12);
  assert(view.roles.every(r => !r.filled && !r.directEvidence && !r.required));
  assert(view.selected.every(m => m.evidence.evidence_phrase === m.profile.claims[0].evidence));
});
test('remove/re-add, exclusions, full slots, successive clock actions and retired snapshot', async () => {
  const f = await fixture(); f.e.resolveScope(f.action); let s = f.e.proposal(f.e.opportunityById.get('call'));
  const id = s.selectedIds[0]; s = f.e.removeMember(s, id); assert(s.excludedIds.includes(id));
  assert(f.e.proposalOptions(s).every(o => !o.state.selectedIds.includes(id)));
  s = f.e.addReplacement(s, id); assert(!s.excludedIds.includes(id));
  while (s.selectedIds.length < 4) s = f.e.addReplacement(s, f.e.proposalView(s).replacements[0].profile.id);
  assert.throws(() => f.e.addReplacement(s, f.e.proposalView(s).replacements[0].profile.id));
  f.clock.now = '2026-09-13T00:00:00Z'; assert.throws(() => f.e.proposalView(s), /expired/);
  assert.equal(f.e.resolveScope({...f.action, now: f.clock.now}).ok, false);
  const changed = plain(f.directory); changed.researchers[0].claims[0].status = 'retired';
  await assert.rejects(f.c.SharedTeamEngine.hydrate(f.pack.packet, f.pack.index, changed, f.catalog, f.sidecar), /snapshot/);
});
test('wrong ownership, corrupt input, broad parent and unsupported scope fail closed', async () => {
  const f = await fixture();
  for (const values of [{parentId: 'other'}, {scopeId: 'missing'}, {isBroad: true}]) assert.equal(f.e.resolveScope({...f.action, ...values}).ok, false);
  const corrupt = plain(f.catalog); corrupt.opportunities[0].description = 'different science';
  await assert.rejects(f.c.SharedTeamEngine.hydrate(f.pack.packet, f.pack.index, f.directory, corrupt, f.sidecar), /snapshot/);
  const p = plain(f.pack.packet); p.scopes[0].parent_id = 'other'; const i = {...f.pack.index, generation_id: await f.c.SharedTeamEngine.hash(p), scopes: p.scopes};
  await assert.rejects(f.c.SharedTeamEngine.hydrate(p, i, f.directory, f.catalog, f.sidecar), /ownership/);
});
test('no provider path or startup calculation; complete summary survives normalization', async () => {
  let calls = 0; const fail = () => { calls++; throw Error('network forbidden'); };
  const f = await fixture({fetch: fail, XMLHttpRequest: class {constructor() {fail();}}, WebSocket: class {constructor() {fail();}}});
  assert.equal(f.e.statistics().fits, 0);
  f.e.resolveScope(f.action); const s = f.e.proposal(f.e.opportunityById.get('call'));
  f.e.proposalView(s); f.e.proposalOptions(s); f.e.removeMember(s, s.selectedIds[0]); f.e.resolveScope(f.action); f.e.proposal(f.e.opportunityById.get('call'));
  assert.equal(calls, 0);
  const p = f.c.FUNDING_TEAM_MATCHER.normalizeProfile(f.directory.researchers[0]);
  assert.equal(p.research_summary, f.directory.researchers[0].research_summary);
  assert.equal(p.claims[0].evidence, f.directory.researchers[0].claims[0].evidence);
});
test('canonical selected child has identical parent ownership/currentness and never borrows sibling science', async () => {
  const f = await fixture();
  const children = ['child-a', 'child-b'].map((id, i) => ({subtopic_id: id, parent_id: 'call', title: i ? 'Geometric topology' : 'Catalysis spectroscopy and membranes', summary: i ? 'Geometry of manifolds.' : f.record.description, child_type: 'subject', publication_state: 'publishable', status: 'posted', close_date: '2026-09-12'}));
  const sidecar = {schema_version: 1, records: {call: {subtopics: children}}, search_index: {postings: {}, record_ids: children.map(c => c.subtopic_id), document_count: 2}};
  const scopes = children.map(c => ({id: c.subtopic_id, parent_id: c.parent_id, record_type: 'publishable_child', scope_label: c.title}));
  const pack = await buildSharedPackage({catalog: f.catalog, directory: f.directory, sidecar, config: {}, scopes});
  const data = await f.c.SharedTeamEngine.hydrate(pack.packet, pack.index, f.directory, f.catalog, sidecar), e = f.c.SharedTeamEngine.create(data, {clock: () => f.clock.now});
  const childCatalog = f.c.FUNDING_RETRIEVAL.createChildCatalog(sidecar), m = f.c.FUNDING_TEAM_MATCHER.create(childCatalog, {}, f.c.FUNDING_SEARCH_QUERY, {now: new Date(f.clock.now)});
  for (const scope of scopes) {
    assert(e.resolveScope({...f.action, scopeId: scope.id, childCatalog}).ok);
    const reference = m.records.find(r => r.id === scope.id);
    for (const p of f.directory.researchers) assert.deepEqual(plain(e.admittedFits().find(r => r.id === p.id)?.fit || null), plain(m.scoreProfile(f.c.FUNDING_TEAM_MATCHER.normalizeProfile(p), reference)));
  }
  assert.equal(e.admittedFits().length, 0);
  assert.equal(e.proposal(e.opportunityById.get('child-b')).selectedIds.length, 0);
  const wrong = plain(childCatalog); wrong.opportunities[0].parent_id = 'other';
  assert.equal(e.resolveScope({...f.action, scopeId: 'child-a', childCatalog: wrong}).ok, false);
});

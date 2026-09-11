// Zero-provider integration/consistency observations, not a new quality benchmark.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {webcrypto, createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {performance} from 'node:perf_hooks';
const clock = '2026-09-11T12:00:00Z', calls = [];
const c = vm.createContext({Date, TextEncoder, TextDecoder, crypto: webcrypto, fetch: url => {calls.push(url); throw Error('No network in prepared interactions');}, XMLHttpRequest: class {constructor() {throw Error('No XHR');}}, WebSocket: class {constructor() {throw Error('No socket');}}});
for (const file of ['assets/submission-schedule.js', 'assets/search-query.js', 'assets/search-retrieval.js', 'assets/team-matcher.js', 'assets/shared-team-engine.js', 'data/opportunities.js', 'data/subtopics.js', 'data/researcher_directory.js', 'data/faculty_matches.js']) vm.runInContext(fs.readFileSync(file, 'utf8'), c);
const index = JSON.parse(fs.readFileSync('docs/team-recommender/profile-repair/shared-candidate-index.json', 'utf8'));
const bytes = fs.readFileSync(index.shared.path), packet = JSON.parse(bytes), start = performance.now(), heap = process.memoryUsage().heapUsed;
const data = await c.SharedTeamEngine.hydrate(packet, index, c.RESEARCHER_DIRECTORY, c.GRANT_CATALOG, c.SUBTOPIC_CATALOG);
const hydration = performance.now() - start, e = c.SharedTeamEngine.create(data, {clock: () => clock});
const child = c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG), matcher = c.FUNDING_TEAM_MATCHER.create(c.GRANT_CATALOG, c.FACULTY_MATCHES, c.FUNDING_SEARCH_QUERY, {now: new Date(clock)}), childMatcher = c.FUNDING_TEAM_MATCHER.create(child, c.FACULTY_MATCHES, c.FUNDING_SEARCH_QUERY, {now: new Date(clock)});
const rows = [], timings = [], examples = []; let compared = 0;
for (const s of index.scopes) {
  const record = c.GRANT_CATALOG.opportunities.find(r => r.opportunity_id === s.parent_id), t = performance.now();
  const action = {parentId: s.parent_id, scopeId: s.id, record, childCatalog: s.record_type === 'publishable_child' ? child : null, now: clock};
  const outcome = e.resolveScope(action); const fit_ms = performance.now() - t;
  if (!outcome.ok) { rows.push({id: s.id, state: outcome.reason}); continue; }
  const reference = (s.record_type === 'publishable_child' ? childMatcher : matcher), prepared = reference.records.find(r => r.id === s.id), fits = new Map(e.admittedFits().map(r => [r.id, r.fit]));
  for (const p of c.RESEARCHER_DIRECTORY.researchers.filter(c.SharedTeamEngine.eligible)) {
    const expected = reference.scoreProfile(c.FUNDING_TEAM_MATCHER.normalizeProfile(p), prepared);
    assert.equal(JSON.stringify(fits.get(p.id) || null), JSON.stringify(expected)); compared++;
  }
  rows.push({id: s.id, state: 'same-shared-fit', admitted: fits.size});
  // Fixed source-order integration sample; not result-driven scientific selection.
  if (timings.length < 6) {
    const t2 = performance.now(), state = e.proposal(outcome.opportunity), view = e.proposalView(state), group_ms = performance.now() - t2;
    const t3 = performance.now(); e.resolveScope(action); e.proposalOptions(state); e.proposalView(state); const warm_ms = performance.now() - t3;
    assert.equal(new Set([...view.selectedIds, ...view.replacements.map(r => r.profile.id)]).size, fits.size);
    assert(state.selectedIds.every(id => fits.has(id))); assert(view.roles.every(r => !r.filled && !r.directEvidence));
    const edits = []; if (state.selectedIds.length) {
      const t4 = performance.now(), id = state.selectedIds[0], removed = e.removeMember(state, id), restored = e.addReplacement(removed, id);
      assert(restored.selectedIds.includes(id)); e.proposalView(restored); edits.push(performance.now() - t4);
    }
    timings.push({id: s.id, fit_ms, group_ms, warm_ms, edit_ms: edits[0] ?? null, options: e.proposalOptions(state).length});
    examples.push({id: s.id, title: record.title, selected: view.selected.map(m => ({id: m.profile.id, name: m.profile.name, evidence: m.evidence})), admitted: fits.size});
  }
}
assert.equal(calls.length, 0);
const files = [index.shared.path, 'data/researcher_directory.js', 'data/faculty_matches.js', 'data/subtopics.js', 'assets/team-matcher.js', 'assets/shared-team-engine.js'];
const receipt = {kind: 'corrective-implementation-consistency-check', clock, generation: index.generation_id, registry_generation: packet.registry_generation,
  scope_inventory: index.scopes.length, directory_population: c.RESEARCHER_DIRECTORY.researchers.length, eligible_population: c.RESEARCHER_DIRECTORY.researchers.filter(c.SharedTeamEngine.eligible).length,
  exact_profile_scope_fit_comparisons: compared, disagreements: 0, rows, examples, measurements: {environment: `Node ${process.version} ${process.platform}/${process.arch}; not a browser or physical-device observation`, hydration_ms: hydration,
    elapsed_ms: performance.now() - start, heap_delta_bytes: process.memoryUsage().heapUsed - heap, sample: timings,
    cold_interaction_dependencies: [index.shared.path, 'assets/team-matcher.js', 'assets/shared-team-engine.js', 'data/subtopics.js'],
    transfer_note: 'Measured encoded bytes and local gzip sizes; not observed HTTP transfer. Directory and catalog are existing page inputs. The topic sidecar is needed only if not already loaded.',
    assets: files.map(path => { const b = fs.readFileSync(path); return {path, bytes: b.length, gzip_bytes: gzipSync(b).length, sha256: createHash('sha256').update(b).digest('hex')};})},
  provider_calls: calls.length, human_judgments: 0, quality_acceptance_claimed: false, activated: false};
fs.writeFileSync('docs/team-recommender/profile-repair/real-input-check.json', JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({compared, scopes: rows.length, milliseconds: receipt.measurements.elapsed_ms, hydration, group_ms: timings.map(t => t.group_ms), calls: calls.length}));

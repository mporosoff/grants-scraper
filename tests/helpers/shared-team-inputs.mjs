import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {buildSharedPackage} from '../../tools/build_shared_team_package.mjs';
export function context(extra = {}) {
  const c = vm.createContext({Date, TextEncoder, TextDecoder, crypto: webcrypto, ...extra});
  for (const p of ['submission-schedule', 'search-query', 'search-retrieval', 'team-matcher', 'shared-team-engine']) vm.runInContext(fs.readFileSync(`assets/${p}.js`, 'utf8'), c);
  return c;
}
export async function fixture(extra = {}) {
  const clock = {now: '2026-09-11T12:00:00Z'};
  const c = context(extra), record = {opportunity_id: 'call', title: 'Heterogeneous catalysis, Raman spectroscopy and chemical membrane separation methods', description: 'Heterogeneous catalysis uses Raman spectroscopy and chemical membrane separation methods.', status: 'posted', close_date: '2026-09-12'};
  const catalog = {opportunities: [record, {opportunity_id: 'other', title: 'Geometric topology', description: 'Topology manifolds', close_date: '2027-01-01', status: 'posted'}]};
  const sidecar = {records: {}, search_index: {postings: {}, record_ids: [], document_count: 0}};
  const directory = {schema_version: 1, registry_generation: 'a'.repeat(64), researchers: Array.from({length: 12}, (_, i) => {
    const term = ['heterogeneous catalysis', 'Raman spectroscopy', 'Chemical membrane separation methods'][i % 3];
    return {id: `p${i}`, name: `Person ${i}`, home_unit: 'Example', research_summary: `Studies ${term} for reactive systems.`, status: 'active', auto_proposable: true, pool_state: 'main', pool_visibility: 'institution', source_url: 'https://example.edu/person',
      claims: [{claim_id: `p${i}-c001`, revision: 1, status: 'active', label: term, evidence: `Studies ${term}.`, category: 'Chemistry', type: 'Method', evidence_level: 'direct', source_urls: ['https://example.edu/person']}]};})};
  const scopes = [{id: 'call', parent_id: 'call', record_type: 'specific_parent', scope_label: record.title}];
  const pack = await buildSharedPackage({catalog, sidecar, directory, config: {}, scopes});
  const data = await c.SharedTeamEngine.hydrate(pack.packet, pack.index, directory, catalog, sidecar);
  const e = c.SharedTeamEngine.create(data, {clock: () => clock.now});
  const action = {parentId: 'call', scopeId: 'call', record, now: clock.now};
  return {c, e, data, clock, catalog, directory, sidecar, pack, record, action};
}

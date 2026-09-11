// Build public reusable inputs. This does not calculate teams or activate routing.
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash, webcrypto} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
export function resolveSharedScopes(catalog, childCatalog, reservations) {
  const parents = new Map(catalog.opportunities.map(r => [r.opportunity_id, r]));
  const children = new Map(childCatalog.opportunities.map(r => [r.opportunity_id, r]));
  return reservations.flatMap(s => {
    const record = s.id === s.parent_id ? parents.get(s.id) : children.get(s.id);
    if (!record || !parents.has(s.parent_id) || s.id !== s.parent_id && record.parent_id !== s.parent_id) return [];
    return [{id:s.id,parent_id:s.parent_id,record_type:s.id===s.parent_id?'specific_parent':'publishable_child',scope_label:record.title||s.id}];
  });
}
export async function buildSharedPackage({catalog, sidecar, directory, config, scopes}) {
  const c = vm.createContext({crypto: webcrypto, TextEncoder, TextDecoder});
  vm.runInContext(fs.readFileSync('assets/shared-team-engine.js', 'utf8'), c);
  const api = c.SharedTeamEngine;
  const packet = {schema_version: 3, version: api.VERSION, registry_generation: directory.registry_generation,
    directory_sha256: await api.hash(directory), catalog_sha256: await api.hash(catalog), sidecar_sha256: await api.hash(sidecar),
    config: Object.fromEntries(['theme_lexicon', 'bridge_themes', 'common_topics', 'agency_scope', 'broad_pattern'].filter(k => config[k] !== undefined).map(k => [k, config[k]])),
    scopes: scopes.map(s => ({id: s.id, parent_id: s.parent_id, record_type: s.record_type, scope_label: s.scope_label || '', engine: api.VERSION}))};
  const generation = await api.hash(packet), bytes = Buffer.from(api.canonical(packet)), path = `data/team_ingredients/shared-${sha(bytes)}.json`;
  const index = {schema_version: 3, generation_id: generation, scope_count: scopes.length, scopes: packet.scopes,
    shared: {path, bytes: bytes.length, sha256: sha(bytes)}, runtime: {matcher: sha(fs.readFileSync('assets/team-matcher.js')), shared: sha(fs.readFileSync('assets/shared-team-engine.js'))}};
  return {packet, index, bytes, path};
}
async function main() {
  const outputDir = process.argv.find(a => a.startsWith('--output-dir='))?.slice(13) || 'docs/team-recommender/profile-repair';
  const c = vm.createContext({});
  for (const path of ['data/opportunities.js', 'data/subtopics.js', 'data/researcher_directory.js', 'data/faculty_matches.js', 'data/opportunity_team_index.js', 'assets/search-retrieval.js']) vm.runInContext(fs.readFileSync(path, 'utf8'), c);
  const children = c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG);
  // Preserve the existing experimental scope inventory; only canonical identities
  // that the shared catalog can project are representable. No result-driven choice.
  const historical = c.OPPORTUNITY_TEAM_INDEX.scopes;
  const scopes = resolveSharedScopes(c.GRANT_CATALOG,children,historical), supportedIds = new Set(scopes.map(s=>s.id));
  const pack = await buildSharedPackage({catalog: c.GRANT_CATALOG, sidecar: c.SUBTOPIC_CATALOG, directory: c.RESEARCHER_DIRECTORY, config: c.FACULTY_MATCHES, scopes});
  fs.mkdirSync('data/team_ingredients', {recursive: true}); fs.writeFileSync(pack.path, pack.bytes);
  fs.mkdirSync(outputDir, {recursive: true});
  fs.writeFileSync(outputDir + '/shared-candidate-index.json', JSON.stringify(pack.index, null, 2) + '\n');
  fs.writeFileSync(outputDir + '/shared-package-receipt.json', JSON.stringify({generation: pack.index.generation_id, registry_generation: pack.packet.registry_generation,
    catalog_sha256: pack.packet.catalog_sha256, sidecar_sha256: pack.packet.sidecar_sha256, directory_sha256: pack.packet.directory_sha256,
    historical_scope_inventory: historical.length, canonical_scopes: scopes.length, inventory_source: 'Existing public availability IDs only; no saved team or judge file is read', omitted: historical.filter(s => !supportedIds.has(s.id)).map(s => ({id: s.id, reason: 'No identical canonical parent or publishable child projection'})),
    catalog_records: c.GRANT_CATALOG.opportunities.length, directory_records: c.RESEARCHER_DIRECTORY.researchers.length, eligible_directory: c.RESEARCHER_DIRECTORY.researchers.filter(p => p.auto_proposable && !['reference_only', 'hidden'].includes(p.pool_visibility) && p.status === 'active').length,
    new_vectors: 0, reused_vectors: 0, old_vector_assets: 'Preserved historical inputs; incompatible corrected summaries/claims are never paired with old vectors.',
    calculated_scopes_at_build: 0, paid_calls: 0, activated: false, shared_asset: pack.index.shared, runtime: pack.index.runtime}, null, 2) + '\n');
  console.log(JSON.stringify({generation: pack.index.generation_id, scopes: scopes.length, bytes: pack.bytes.length, activated: false}));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();

import { mockFrozenFundingSearchPackage } from './helpers.mjs';
import { readFile } from 'node:fs/promises';

const originalCatalog = await readFile(new URL('../fixtures/frozen/funding-catalog.js', import.meta.url), 'utf8');
const extraRecords = Array.from({ length: 20 }, (_, index) => ({
  opportunity_id: `workflow-catalysis-${index}`, opportunity_number: `WORKFLOW-${index}`,
  title: `Workflow Catalysis Science ${String(index).padStart(2, '0')}`,
  description: 'Synthetic catalysis science and reaction engineering opportunity for bounded chat validation.',
  topic_areas: ['Catalysis and reaction engineering'], disciplines: ['Engineering and Physical Sciences'],
}));
const catalogSource = originalCatalog.replace('const coreOpportunities = [',
  `const coreOpportunities = [${extraRecords.map(record => `openOpportunity(${JSON.stringify(record)})`).join(',')},`);
if (catalogSource === originalCatalog) throw new Error('Frozen workflow catalog construction did not attach.');

// Synthetic people and roles exercise UI transitions, not scientific fit. The
// parent is the permanent Genesis record in the frozen Funding Finder catalog.
const generation = 'e'.repeat(64);
const poolCounts = { main: 4, standby: 0, unadmitted: 0 };
const counts = { total: 4, rankable: 4, unrankable: 0, pool_counts: poolCounts };
const researchers = ['Alpha', 'Beta', 'Gamma', 'Delta'].map((name, index) => ({
  id: `workflow-${index}`, name: `Workflow Researcher ${name}`, legacy_ids: [], aliases: [],
  home_unit: 'Synthetic test directory', relationship: 'hajim_core_faculty',
  status: 'active', pool_state: 'main', pool_visibility: 'institution', auto_proposable: true,
  source_url: `https://example.test/workflow/${index}`, source_checked_date: '2026-09-01',
  claims: [{ claim_id: `workflow-${index}-claim`, revision: 1, status: 'active',
    label: `Workflow role ${Math.min(index, 2)}`, evidence: 'Synthetic browser test evidence',
    evidence_level: 'direct', source_urls: [`https://example.test/workflow/${index}`] }],
}));
const opportunity = {
  id: '361526:workflow-branch', parent_id: '361526', record_type: 'declared_branch',
  scope_label: 'Synthetic workflow branch', catalog_title: 'The Genesis Mission',
  opportunity_number: 'DE-FOA-0003612', agency: 'Office of Science',
  gate_state: 'pass', gate_label: 'Synthetic fixture', objective: 'Exercise the team workflow.',
  why_team: 'Synthetic complementary roles for browser validation.', missing_skills: [],
  source_url: 'https://example.test/workflow/opportunity',
  members: researchers.slice(0, 3).map((profile, index) => ({
    faculty_id: profile.id, contribution: `Workflow role ${index}`,
    evidence_term: `Workflow role ${index}`, evidence_phrase: 'Synthetic browser test evidence',
    evidence_tier: 'Synthetic fixture', source_url: profile.source_url, why_person: 'Exercises a distinct role.',
  })),
  roles: [0, 1, 2].map(index => ({
    id: `role-${index}`, label: `Workflow role ${index}`, coverage: 'direct',
    accepted_terms: [`Workflow role ${index}`],
    candidate_ids: index === 2 ? ['workflow-2', 'workflow-3'] : [`workflow-${index}`],
    alternative_ids: [], rationale: 'Synthetic complementary role.', source_url: 'https://example.test/workflow/opportunity',
  })),
  variants: [{ member_ids: ['workflow-0', 'workflow-1', 'workflow-3'], label: 'Alternative synthetic team' }],
};
const team = {
  schema_version: 1, generation_id: generation, researcher_registry_generation: generation,
  scope_count: 1, source_roster_counts: counts, pool_counts: poolCounts, opportunities: [opportunity],
};
const index = { schema_version: 1, generation_id: generation, scope_count: 1,
  scopes: [{ id: opportunity.id, parent_id: opportunity.parent_id, record_type: opportunity.record_type }] };
const directory = { schema_version: 1, registry_generation: generation, counts, researchers };
const matches = {
  registry_generation: generation, faculty_count: 4, catalog_size: 1000,
  niche_topics: [], multi_pi_suggestions: [], theme_lexicon: {}, bridge_themes: [], agency_scope: [], broad_pattern: '^$',
  faculty: Object.fromEntries(researchers.map(profile => [profile.name, {
    researcher_id: profile.id, legacy_ids: [], resolved_name: profile.name,
    key_terms: profile.claims.map(claim => claim.label), capability_phrases: [], domains: [], claim_refs: [],
  }])),
  pi_matches: Object.fromEntries(researchers.map(profile => [profile.name, []])),
};

export async function installRecentUpdatesFixture(page) {
  await page.clock.setFixedTime(new Date('2026-09-06T12:00:00Z'));
  await mockFrozenFundingSearchPackage(page, { catalogSource });
  for (const [path, globalName, value] of [
    ['opportunity_team_index.js', 'OPPORTUNITY_TEAM_INDEX', index],
    ['opportunity_teams.js', 'OPPORTUNITY_TEAM_DATA', team],
    ['researcher_directory.js', 'RESEARCHER_DIRECTORY', directory],
    ['faculty_matches.js', 'FACULTY_MATCHES', matches],
  ]) await page.route(`**/data/${path}*`, route => route.fulfill({
    contentType: 'text/javascript', body: `globalThis.${globalName}=${JSON.stringify(value)};`,
  }));
  for (const path of ['match_explorer.html', 'team_match.html']) {
    await page.route(`**/${path}*`, async route => {
      const response = await route.fetch();
      const body = (await response.text()).replace(/(<meta name="opportunity-team-generation" content=")[a-f0-9]{64}/, `$1${generation}`);
      await route.fulfill({ response, body });
    });
  }
}

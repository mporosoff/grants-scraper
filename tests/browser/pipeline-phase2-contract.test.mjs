import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test, { after } from "node:test";
import vm from "node:vm";
import { evaluateSubscriptions } from "../../workers/alerts/src/evaluator.js";
import { eventEmail } from "../../workers/alerts/src/email.js";

// No browser process: VM contracts consume the actual Python command outputs.
const root = fileURLToPath(new URL("../../", import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), "funding-phase2-"));
after(async () => {
  assert.ok(resolve(temporary).startsWith(resolve(tmpdir()) + sep));
  await rm(temporary, { recursive: true, force: true });
});
execFileSync(process.env.PYTHON || "python", ["-m", "tests.fixtures.phase2_pipeline", temporary], {
  cwd: root, env: { ...process.env, PYTHONUTF8: "1" }, timeout: 60000,
});
const context = { console, Date, URL, Blob };
vm.createContext(context);
for (const asset of ["assets/search-v2-config.js", "assets/search-query.js", "assets/search-retrieval.js", "assets/team-matcher.js",
  "data/opportunities.js", "data/subtopics.js", "data/researcher_directory.js", "data/opportunity_team_index.js", "data/opportunity_teams.js", "assets/opportunity-team.js"]) {
  vm.runInContext(await readFile(join(temporary, asset), "utf8"), context, { filename: asset });
}
const catalog = context.GRANT_CATALOG;
const record = catalog.opportunities.find(r => r.opportunity_id.endsWith(":research"));
const unsuitable = catalog.opportunities.find(r => r.opportunity_id.endsWith(":workshop"));
const now = new Date("2026-09-06T12:00:00Z");
const registry = JSON.parse(await readFile(join(temporary, "config/researcher_registry.json"), "utf8"));
const app = await readFile(join(root, "assets/app.js"), "utf8");
function appFunction(name) {
  const source = app.match(new RegExp(`  function ${name}\\([^]*?\\n  }`));
  assert.ok(source, name);
  vm.runInContext(source[0], context);
}

test("accepted official HTML reaches ordinary search through the generated index", () => {
  const retrieval = context.FUNDING_RETRIEVAL.create(catalog, context.FUNDING_SEARCH_QUERY, {
    searchV2: true, searchV2Config: context.FUNDING_SEARCH_V2_CONFIG, catalogRole: "parent", now,
  });
  const scores = retrieval.score("zirconia catalysts", { evidence: true }).scores;
  assert.ok(scores[catalog.opportunities.indexOf(record)] > 0);
  assert.equal(scores[catalog.opportunities.indexOf(unsuitable)], 0);
  assert.ok(retrieval.score("workshop logistics").scores[catalog.opportunities.indexOf(unsuitable)] > 0);
});

test("the same enriched record reaches evidence-qualified Team Match", () => {
  const profiles = registry.researchers.map(row => ({ name: row.display_name, researcher_id: row.researcher_id,
    key_terms: row.claims.map(c => c.label), capability_phrases: row.claims.map(c => c.evidence), research_summary: row.research_summary }));
  const engine = context.FUNDING_TEAM_MATCHER.create(catalog, {}, context.FUNDING_SEARCH_QUERY, { now });
  const results = engine.matchTeam(profiles).results;
  const match = results.find(r => r.id === record.opportunity_id);
  assert.ok(match);
  assert.equal(match.fits.length, 2);
  assert.ok(match.fits.every(fit => fit.score > 0));
  assert.ok(!results.some(r => r.id === unsuitable.opportunity_id));
});

test("generated team index and panel data agree on exact scope and researcher evidence", () => {
  context.document = { querySelector: () => ({ getAttribute: () => context.OPPORTUNITY_TEAM_INDEX.generation_id }) };
  const api = context.OpportunityTeam;
  const data = api.validateData(context.OPPORTUNITY_TEAM_DATA, context.OPPORTUNITY_TEAM_INDEX.generation_id);
  const engine = api.create(data);
  const found = engine.resolveScope({ record, parentId: record.opportunity_id, isBroad: false });
  assert.equal(found.ok, true);
  const state = engine.proposal(found.opportunity);
  assert.equal(state.selectedIds.length, 2);
  assert.ok(state.selectedIds.every(id => registry.researchers.some(r => r.researcher_id === id)));
  assert.equal(engine.resolveScope({ record: unsuitable, parentId: unsuitable.opportunity_id, isBroad: false }).ok, false);
  assert.equal(context.OPPORTUNITY_TEAM_INDEX.scopes.length, 1);
});

test("CSV and calendar use the enriched citation and multiple-deadline payload", async () => {
  const downloads = [];
  Object.assign(context, {
    catalog, runtimeDateIso: () => "2026-09-06", downloadBlob: blob => downloads.push(blob),
    recordId: r => String(r.opportunity_id), safeUrl: value => /^https?:\/\//.test(value || "") ? value : "",
    safeEmail: () => "", escapeAttribute: value => String(value), hasPlaceholderAward: () => false,
    state: { refinement: { assessments: new Map() }, ai: { assessments: new Map() }, deployment: {} },
    currentDisplayMatches: () => [{ index: catalog.opportunities.indexOf(record) }],
    RESULT_WORKFLOW_API: { potentialEvidence: () => null, workflowTierLabel: () => "Strong" },
    recordDeploymentUsage: () => {},
  });
  for (const name of ["officialActions", "deadlineKindLabel", "calendarEvents", "icsEscape", "icsDate", "nextIsoDate", "exportCalendar",
    "evidenceFacts", "deadlineEvidenceLabel", "fundingEvidenceLabel", "primaryContact", "csvCell", "exportCsv"]) appFunction(name);
  context.exportCalendar([record]);
  const calendar = await downloads.pop().text();
  assert.match(calendar, /DTSTART;VALUE=DATE:20261101/);
  assert.match(calendar, /DTSTART;VALUE=DATE:20261231/);
  assert.match(calendar, /Eastern|ET/);
  assert.match(calendar, /science\.example\.gov\/research\.html/);
  context.URL = { createObjectURL: blob => { downloads.push(blob); return "blob:fixture"; }, revokeObjectURL: () => {} };
  context.document = { createElement: () => ({ click() {}, remove() {} }), body: { appendChild() {} } };
  context.exportCsv();
  const csv = await downloads.pop().text();
  assert.ok(csv.includes(record.document_evidence.document.sha256));
  assert.ok(csv.includes(record.opportunity_number));
  assert.match(csv, /Document evidence status/);
  assert.match(csv, /science\.example\.gov\/research\.html/);
});

test("generated change events produce alert payloads without contacting subscribers", async () => {
  const events = JSON.parse(await readFile(join(temporary, "events.json"), "utf8"));
  const queued = [];
  const subscription = { id: "fixture-watch", type: "opportunity", baseline_at: "2026-09-05T00:00:00Z",
    created_at: "2026-09-05T00:00:00Z", definition_json: JSON.stringify({ opportunity_id: record.opportunity_id, triggers: ["new", "amended"] }) };
  const store = { activeSubscriptions: async () => [subscription], enqueueEvent: async value => { queued.push(value); return true; }, markEvaluated: async () => {} };
  const env = { PUBLIC_APP_ORIGIN: "https://funding.example.test", PUBLIC_WORKER_ORIGIN: "https://alerts.example.test" };
  await evaluateSubscriptions({ store, assets: { catalog, changes: { generated_at: catalog.generated_at, events } }, env, now });
  assert.equal(queued.length, 1);
  assert.equal(queued[0].opportunityId, record.opportunity_id);
  assert.equal(queued[0].payload.official_url, record.detail_page);
  const email = eventEmail({ env, event: { event_kind: queued[0].eventKind, payload_json: JSON.stringify(queued[0].payload), email: "fixture@example.test" },
    capabilityLinks: { manage: "https://alerts.example.test/manage", unsubscribeThis: "https://alerts.example.test/unsubscribe", unsubscribeAll: "https://alerts.example.test/unsubscribe-all" } });
  assert.ok(email.text.includes(record.title));
  assert.ok(email.text.includes(record.detail_page));
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [analytics, app, help, searchPage, teamPage, hosting, workflow, catalogSource] =
  await Promise.all([
    readFile(new URL("assets/analytics.js", root), "utf8"),
    readFile(new URL("assets/app.js", root), "utf8"),
    readFile(new URL("assets/site-help.js", root), "utf8"),
    readFile(new URL("match_explorer.html", root), "utf8"),
    readFile(new URL("team_match.html", root), "utf8"),
    readFile(new URL("docs/HOSTING.md", root), "utf8"),
    readFile(new URL(".github/workflows/refresh-opportunities.yml", root), "utf8"),
    readFile(new URL("data/opportunities.js", root), "utf8"),
  ]);

function analyticsLoads(search) {
  const appended = [];
  const context = {
    location: { search },
    document: {
      createElement: () => ({ dataset: {} }),
      head: { append: node => appended.push(node) },
    },
  };
  vm.runInNewContext(analytics, context, { filename: "analytics.js" });
  return appended;
}

test("parameterized search routes suppress third-party analytics", () => {
  assert.equal(analyticsLoads("?q=confidential+topic").length, 0);
  const clean = analyticsLoads("");
  assert.equal(clean.length, 1);
  assert.equal(clean[0].src, "https://static.cloudflareinsights.com/beacon.min.js");
  assert.match(searchPage, /assets\/analytics\.js\?v=app-1\.2\.2-gate3/);
  assert.doesNotMatch(searchPage, /<script[^>]+static\.cloudflareinsights\.com/);
});

test("custom usage events omit search text and use an origin-only referrer", () => {
  const logger = app.match(/function logUsage\(category\)[\s\S]*?\n  }/)?.[0] || "";
  assert.match(logger, /session: USAGE_SESSION, category: category \|\| "all"/);
  assert.match(logger, /referrerPolicy: "origin"/);
  assert.match(logger, /credentials: "omit"/);
  assert.doesNotMatch(logger, /state\.query|INITIAL_URL_PARAMS|location\.search/);
  for (const source of [searchPage, help, hosting]) {
    assert.match(source, /browser history/i);
    assert.match(source, /random session/i);
    assert.match(source, /network organization/i);
    assert.match(source, /Cloudflare Web Analytics/i);
    assert.match(source, /query parameters|no query parameters/i);
  }
});

test("deadline display resolves shared citations and falls back from note to quote", () => {
  assert.match(app, /function deadlineCitation\(record, deadline\)/);
  assert.match(app, /deadline\?\.evidence_id \|\| deadline\?\.document_evidence_id/);
  assert.match(app, /const note = deadline\.note \|\| citationData\?\.quote \|\| ""/);
  const payload = catalogSource
    .split("globalThis.GRANT_CATALOG=", 2)[1]
    .trim()
    .replace(/;$/, "");
  const catalog = JSON.parse(payload);
  for (const record of catalog.opportunities) {
    const facts = new Set(
      (record.document_evidence?.facts || []).map(fact => String(fact.id)),
    );
    for (const deadline of record.deadlines || []) {
      if (deadline.note && deadline.citation?.quote) {
        assert.notEqual(deadline.note, deadline.citation.quote);
      }
      const reference = deadline.evidence_id || deadline.document_evidence_id;
      if (reference && !deadline.citation) assert.ok(facts.has(String(reference)));
    }
  }
  assert.ok(Buffer.byteLength(catalogSource) <= 22_662_953);
});

test("page-derived fields expose expanded source provenance", () => {
  assert.match(app, /function pageFieldProvenance\(record\)/);
  assert.match(app, /record\.page_field_provenance \|\| \{\}/);
  assert.match(app, /Sources for page-derived fields/);
  assert.match(app, /source\.source_excerpt/);
  assert.match(app, /source\.extraction_method/);
  assert.match(app, /source\.confidence, source\.status/);
  assert.match(app, /source\.fetched_at/);
  assert.match(app, /source\.source_url/);
});

test("Team Match metadata and history use public researcher/team behavior", () => {
  assert.match(teamPage, /<title>Team Match \| Funding Finder<\/title>/);
  assert.match(teamPage, /og:title" content="Team Match \| Funding Finder"/);
  assert.match(teamPage, /Add two to four researchers to find funding opportunities that fit the whole team/);
  assert.doesNotMatch(teamPage, /Faculty × Funding|multiple faculty/);
  assert.doesNotMatch(teamPage, /name="robots" content="noindex/);
  assert.doesNotMatch(teamPage, /history\.scrollRestoration\s*=|window\.scrollTo\(0, 0\)/);
  assert.match(teamPage, /window\.addEventListener\("pagehide", saveTeamHistory\)/);
  assert.match(teamPage, /history\.replaceState\(Object\.assign/);
  assert.match(teamPage, /"Adding " \+ memberName\(member\) \+ " to the team…"/);
  assert.match(teamPage, /Finding enhanced ordering for the locally eligible team matches/);
  assert.match(hosting, /Team Match is also a public, self-canonical product route and is intentionally\s+indexable/);
});

test("refresh alerts summarize current state, reopen, and close on full recovery", () => {
  assert.match(workflow, /name: Resolve recovered refresh alerts/);
  assert.match(workflow, /steps\.additional-sources\.outcome == 'success'/);
  assert.match(workflow, /steps\.document_evidence\.outcome == 'success'/);
  assert.match(workflow, /state_reason: "completed"/);
  assert.ok((workflow.match(/state: "all"/g) || []).length >= 2);
  assert.ok((workflow.match(/state: "open"/g) || []).length >= 3);
  assert.ok((workflow.match(/github\.rest\.issues\.update/g) || []).length >= 3);
});

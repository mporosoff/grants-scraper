import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [app, appCss, hybrid, help, searchPage, teamPage, readme, hosting] = await Promise.all([
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("assets/app.css", root), "utf8"),
  readFile(new URL("assets/search-hybrid.js", root), "utf8"),
  readFile(new URL("assets/site-help.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
  readFile(new URL("README.md", root), "utf8"),
  readFile(new URL("docs/HOSTING.md", root), "utf8"),
]);

test("user-facing copy distinguishes local, hosted, and user-connected processing", () => {
  for (const source of [help, searchPage, readme, hosting]) {
    assert.match(source, /Strong/i);
    assert.match(source, /Potential/i);
    assert.match(source, /hosted|site-managed/i);
  }
  assert.match(help, /submitted search text is sent to the Funding Finder Worker/);
  assert.match(help, /Your CV, full profile, researcher names, and ORCID publication text are not sent/);
  assert.match(help, /Your CV, full profile, researcher names, and ORCID publication text are not sent/);
  assert.match(help, /Hosted AI tools/);
  assert.match(help, /Advanced users may select OpenAI or Anthropic/);
  assert.match(teamPage, /Enhanced ordering may send a bounded aggregate of selected research keywords and theme labels/);
  assert.match(teamPage, /Researcher names and publication text are not sent/);
});

test("AI service and privacy copy stays compact and keeps advanced-key guidance with privacy", () => {
  const start = searchPage.indexOf('<details class="provider-setup">');
  const end = searchPage.indexOf("</details>", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const setup = searchPage.slice(start, end);

  assert.doesNotMatch(setup, /What hosted AI changes|Hosted refinement uses two bounded calls/);
  assert.doesNotMatch(setup, /provider-explanation|cost-note/);
  assert.match(setup, /<p class="key-help"><strong>No API key is required\.<\/strong> Funding Finder routes each feature through its tested hosted model\.<\/p>/);
  assert.match(setup, /<p class="privacy-note">Hosted AI[\s\S]*Advanced users may instead select OpenAI or Anthropic[\s\S]*OpenAI key and project limits[\s\S]*Anthropic key safety and limits<\/a>\.<\/p>/);
  const appCssHash = createHash("sha256").update(appCss).digest("hex");
  assert.match(searchPage, new RegExp(`app\\.css\\?v=${appCssHash}`));
  assert.match(appCss, /\.provider-setup-body\s*\{[^}]*padding:\s*0 15px 11px/s);
  assert.match(appCss, /\.provider-setup \.privacy-note\s*\{[^}]*margin:\s*7px 0 0/s);
});

test("hosted semantic requests contain only query and bounded public passage fields", () => {
  assert.match(hybrid, /post\("embed-query", \{ query: semanticQuery \}, signal\)/);
  assert.match(hybrid, /post\("rerank", \{\s*query: semanticQuery,\s*corpus_sha256:[\s\S]*?candidates: guarded\.map/);
  assert.match(hybrid, /passage_id: item\.passage_id,\s*text_sha256: item\.text_sha256,\s*text: item\.text/);
  assert.doesNotMatch(hybrid, /profile_text|cv_text|researcher_name|orcid_text|publication_text/i);
});

test("query and filters determine membership while sort only orders within tiers", () => {
  const canRun = app.match(/function hybridCanRun[\s\S]*?\n  }/)?.[0] || "";
  const signature = app.match(/function hybridRequestSignature[\s\S]*?\n  }/)?.[0] || "";
  const apply = app.match(/function applyHybridParents[\s\S]*?\n  }/)?.[0] || "";
  assert.doesNotMatch(canRun, /sort/);
  assert.match(signature, /semantic_query/);
  assert.match(signature, /catalog_generation/);
  assert.match(signature, /filters: hybridFilterState\(\)/);
  assert.doesNotMatch(signature, /sort/);
  for (const field of [
    "status-posted",
    "status-forecasted",
    "status-archived",
    "deadline-from",
    "deadline-to",
    "award-min",
    "flag-evidence",
    "flag-preliminary",
    "flag-limited",
    "flag-early-career",
    "flag-no-cost-share",
    "audience-filter",
  ]) assert.match(app, new RegExp(field));
  assert.match(app, /cachedSignature === requestSignature/);
  assert.match(app, /eligibleParentIds = eligibleHybridParentIds\(\)/);
  assert.match(app, /search\(normalizedQuery, \{[\s\S]*?context: "",[\s\S]*?eligibleParentIds,[\s\S]*?signal: controller\.signal/);
  assert.match(apply, /sortMatches\([\s\S]*?state\.sort/);
  assert.match(apply, /state\.matches = \[\.\.\.state\.strongMatches, \.\.\.state\.potentialMatches\]/);
});

test("eligible parent IDs are applied before every bounded retrieval stage", () => {
  assert.match(hybrid, /semanticCandidates\([\s\S]*?eligibleParentIds = null/);
  assert.match(hybrid, /if \(eligible && !eligible\.has\(String\(passage\.parent_id\)\)\) return \[\]/);
  assert.match(hybrid, /buildBm25Candidates\([\s\S]*?eligibleParentIds = null/);
  assert.match(hybrid, /if \(eligible && !eligible\.has\(String\(record\.parent_id\)\)\) return/);
  assert.match(hybrid, /const fused = fuseCandidates\(bm25, semantic\)/);
  assert.match(hybrid, /candidates: guarded\.map/);
});

test("opportunity actions stay concise and wrap safely on narrow cards", () => {
  assert.match(app, />Open opportunity ↗<\/a>/);
  assert.doesNotMatch(app, /Open \$\{recordSourceLabel\} record/);
  assert.match(appCss, /\.source-action\s*\{[^}]*min-width:\s*0/s);
  assert.match(appCss, /\.source-action\s*\{[^}]*overflow-wrap:\s*anywhere/s);
  assert.match(appCss, /\.source-action\s*\{[^}]*white-space:\s*normal/s);
});

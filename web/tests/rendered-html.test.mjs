import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("builds the grant matcher product shell", async () => {
  const [layout, page, client, css] = await Promise.all([
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/GrantMatcherApp.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
  ]);

  assert.match(layout, /title:\s*"UR Grant Matcher"/);
  assert.match(page, /<GrantMatcherApp \/>/);
  assert.match(client, /Funding worth your attention\./);
  assert.match(client, /Research profile/);
  assert.match(client, /Opportunity feed/);
  assert.match(client, /Match explorer/);
  assert.match(client, /Faculty-controlled profiles/);
  assert.match(client, /formatFunding/);
  assert.match(client, /Grant duration/);
  assert.match(client, /Expected awards/);
  assert.doesNotMatch(client, /Import grants\.json|type="file"/);
  assert.match(css, /\.match-card/);
  assert.match(css, /\.grant-facts/);
  assert.match(css, /@media \(max-width: 640px\)/);
  assert.doesNotMatch(client, /OpenAI API key|Anthropic API key|localStorage/i);
  await access(new URL("dist/server/index.js", root));
});

test("uses persistent application storage and removes starter dependencies", async () => {
  const [hosting, client, packageJson, schema, migration, previewFiles] = await Promise.all([
    readFile(new URL(".openai/hosting.json", root), "utf8"),
    readFile(new URL("app/GrantMatcherApp.tsx", root), "utf8"),
    readFile(new URL("package.json", root), "utf8"),
    readFile(new URL("db/schema.ts", root), "utf8"),
    readFile(new URL("drizzle/0001_blue_ezekiel.sql", root), "utf8"),
    readdir(new URL("app/_sites-preview", root)).catch(() => []),
  ]);

  assert.match(hosting, /"d1":\s*"DB"/);
  assert.match(hosting, /"project_id":\s*"appgprj_/);
  assert.match(client, /\/api\/profile/);
  assert.match(client, /\/api\/opportunities\/refresh/);
  assert.match(client, /\/api\/matches/);
  assert.match(schema, /totalProgramFunding/);
  assert.match(schema, /expectedAwards/);
  assert.match(schema, /preliminaryStageType/);
  assert.match(migration, /ADD `duration`/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.deepEqual(previewFiles, []);
});

test("supports public catalog search, cited FOA evidence, reusable profiles, and optional AI refinement", async () => {
  const [prototype, script, profileScript, reviewScript, providerScript] = await Promise.all([
    readFile(new URL("../match_explorer.html", root), "utf8"),
    readFile(new URL("../assets/app.js", root), "utf8"),
    readFile(new URL("../assets/profile.js", root), "utf8"),
    readFile(new URL("../assets/review.js", root), "utf8"),
    readFile(new URL("../assets/ai-provider.js", root), "utf8"),
  ]);

  assert.match(prototype, /id="query"/);
  assert.match(prototype, /id="facet-discipline"/);
  assert.match(prototype, /id="facet-agency"/);
  assert.match(prototype, /id="flag-evidence"/);
  assert.match(prototype, /id="sort"/);
  assert.match(prototype, /id="export-csv"/);
  assert.match(prototype, /id="k-provider"/);
  assert.match(prototype, /id="k-key"/);
  assert.match(prototype, /id="research-profile"/);
  assert.match(prototype, /id="expertise-keywords"/);
  assert.match(prototype, /id="cv-file"/);
  assert.match(prototype, /id="profile-search"/);
  assert.match(prototype, /id="remember-profile"/);
  assert.match(prototype, /id="export-evaluation"/);
  assert.match(prototype, /id="review-candidates"/);
  assert.match(prototype, /id="send-deployment-review"/);
  assert.match(prototype, /id="ai-refine"/);
  assert.match(prototype, /id="chat-form"/);
  assert.match(prototype, /id="result-label"/);
  assert.match(prototype, /Chat with results/);
  assert.match(prototype, /Minimum per-award amount/);
  assert.match(prototype, /not endorsed or certified/);
  assert.doesNotMatch(prototype, /class="chat hidden"/);
  assert.match(prototype, /data\/opportunities\.js/);
  assert.match(prototype, /assets\/profile\.js/);
  assert.match(prototype, /assets\/review\.js/);
  assert.match(prototype, /assets\/ai-provider\.js/);
  assert.match(prototype, /assets\/app\.js/);
  assert.match(providerScript, /gpt-5\.6-luna/);
  assert.match(providerScript, /claude-sonnet-5/);
  assert.match(providerScript, /api\.openai\.com\/v1\/responses/);
  assert.match(providerScript, /api\.anthropic\.com\/v1\/messages/);
  assert.match(script, /globalThis\.FUNDING_AI\.providerJson/);
  assert.match(profileScript, /globalThis\.FUNDING_PROFILE/);
  assert.match(profileScript, /funding-finder\.profile\.v1/);
  assert.match(profileScript, /funding-finder\.feedback\.v1/);
  assert.match(reviewScript, /funding-finder\.deployment-review\.v1/);
  assert.match(script, /profileContext\(\{ includeCv: true \}\)/);
  assert.match(script, /function exportEvaluation/);
  assert.match(script, /function evidenceRows/);
  assert.match(script, /function sendDeploymentReview/);
  assert.match(script, /citation_evidence_ids/);
  assert.match(script, /AI retrieval candidate set/);
  assert.match(script, /result-label/);
  assert.match(script, /MAX_AI_CANDIDATES = 32/);
  assert.match(script, /MAX_CHAT_RESULTS = 20/);
  assert.match(script, /async function refineWithAi/);
  assert.match(script, /async function askResults/);
  assert.match(script, /Open official FOA/);
  assert.match(script, /primary_document_url/);
  assert.match(script, /deadlineEvidenceLabel/);
  assert.doesNotMatch(
    script,
    /Math\.max\([^)]*total_program_funding/s,
  );
  assert.doesNotMatch(script, /localStorage|sessionStorage/);
  assert.doesNotMatch(profileScript, /sessionStorage|k-key|api_key/);
  assert.doesNotMatch(reviewScript, /sessionStorage|k-key|api_key/);
  assert.doesNotMatch(
    prototype + script,
    /GRANT_MATCH_FEED|btn-save-search|saved-searches/,
  );
  assert.doesNotMatch(
    prototype,
    /id="sel-faculty"|id="load-faculty"|id="load-grants"/,
  );
  assert.match(prototype, /type="file"/);
});

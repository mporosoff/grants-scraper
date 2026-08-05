import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);

test("supports one guided funding search, cited FOA evidence, reusable profiles, and optional AI refinement", async () => {
  const [prototype, script, profileScript, reviewScript, credentialsScript, providerScript, css] = await Promise.all([
    readFile(new URL("match_explorer.html", root), "utf8"),
    readFile(new URL("assets/app.js", root), "utf8"),
    readFile(new URL("assets/profile.js", root), "utf8"),
    readFile(new URL("assets/review.js", root), "utf8"),
    readFile(new URL("assets/credentials.js", root), "utf8"),
    readFile(new URL("assets/ai-provider.js", root), "utf8"),
    readFile(new URL("assets/app.css", root), "utf8"),
  ]);

  assert.match(prototype, /id="query"/);
  assert.match(prototype, /id="facet-discipline"/);
  assert.match(prototype, /id="facet-agency"/);
  assert.match(prototype, /id="flag-evidence"/);
  assert.match(prototype, /id="sort"/);
  assert.match(prototype, /id="export-csv"/);
  assert.match(prototype, /id="export-ics"/);
  assert.match(prototype, /id="compare-panel"/);
  assert.match(prototype, /id="k-provider"/);
  assert.match(prototype, /id="k-key"/);
  assert.match(prototype, /id="research-profile"/);
  assert.match(prototype, /id="page-numbers"/);
  assert.match(prototype, /id="expertise-keywords"/);
  assert.match(prototype, /id="cv-file"/);
  assert.match(prototype, /id="save-profile"/);
  assert.match(prototype, /id="use-profile"/);
  assert.match(prototype, /id="find-funding"/);
  assert.match(prototype, /id="save-key"/);
  assert.match(prototype, /id="key-storage-status"/);
  assert.match(prototype, /OpenAI key and project limits/);
  assert.match(prototype, /Anthropic key safety and limits/);
  assert.match(prototype, /id="feedback-tools"/);
  assert.match(prototype, /id="result-assistant"/);
  assert.match(prototype, /id="export-evaluation"/);
  assert.match(prototype, /id="review-candidates"/);
  assert.match(prototype, /id="send-deployment-review"/);
  assert.match(prototype, /id="ai-refine"/);
  assert.match(prototype, /id="chat-form"/);
  assert.match(prototype, /id="chat-thinking"/);
  assert.match(prototype, /id="toggle-chat-size"/);
  assert.match(prototype, /id="chat-submit"/);
  assert.match(prototype, /Enter to send/);
  assert.match(prototype, /id="result-label"/);
  assert.match(prototype, /Chat with your results/);
  assert.match(prototype, /Minimum per-award amount/);
  assert.match(prototype, /not endorsed or certified/);
  assert.doesNotMatch(prototype, /class="chat hidden"/);
  assert.match(prototype, /data\/opportunities\.js/);
  assert.match(prototype, /assets\/profile\.js/);
  assert.match(prototype, /assets\/review\.js/);
  assert.match(prototype, /assets\/ai-provider\.js/);
  assert.match(prototype, /assets\/chat-ui\.js/);
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
  assert.match(credentialsScript, /funding-finder\.credentials\.v1/);
  assert.match(credentialsScript, /localStorage/);
  assert.match(script, /profileContext\(\{ includeCv: true \}\)/);
  assert.match(script, /function exportEvaluation/);
  assert.match(script, /function recordIsCurrent/);
  assert.match(script, /function paginationItems/);
  assert.match(script, /function goToResultsPage/);
  assert.match(script, /data-page=/);
  assert.match(script, /function exportCalendar/);
  assert.match(script, /function renderComparePanel/);
  assert.match(script, /Why this matched/);
  assert.match(script, /Program contact/);
  assert.match(script, /function amendmentOverview/);
  assert.match(script, /function amendmentNotice/);
  assert.match(script, /function structuredDescription/);
  assert.match(script, /<ul>\$\{listItems/);
  assert.match(script, /FOA amended/);
  assert.match(script, /Summary of changes:/);
  assert.match(script, /a field-level diff was not provided/);
  assert.match(script, /function evidenceRows/);
  assert.match(script, /function sendDeploymentReview/);
  assert.match(script, /citation_evidence_ids/);
  assert.match(css, /\.page-number\[aria-current="page"\]/);
  assert.match(css, /\.result-card:nth-child\(even\)/);
  assert.match(css, /\.amendment-notice/);
  assert.match(css, /\.card-contact/);
  assert.match(css, /\.card-actions/);
  assert.match(css, /\.result-feedback-toggle/);
  assert.match(css, /\.full-description p/);
  assert.match(css, /\.full-description li \+ li/);
  assert.doesNotMatch(script, />FOA changed</);
  assert.match(script, /AI retrieval candidate set/);
  assert.match(script, /result-label/);
  assert.match(script, /MAX_AI_CANDIDATES = 32/);
  assert.match(script, /MAX_CHAT_RESULTS = 20/);
  assert.match(script, /async function refineWithAi/);
  assert.match(script, /async function askResults/);
  assert.match(script, /referenced_result_ids/);
  assert.match(script, /focus_result_ids/);
  assert.match(script, /data-chat-jump/);
  assert.match(script, /event\.key !== "Enter"[\s\S]*?askResults\(/);
  assert.match(script, /document\.documentElement\.classList\.add\("chat-expanded"\)/);
  assert.match(script, /document\.documentElement\.classList\.remove\("chat-expanded"\)/);
  assert.doesNotMatch(script, /chat-thinking"\)\.scrollIntoView/);
  assert.match(css, /body\.chat-expanded/);
  assert.match(
    css,
    /\.messages\s*\{[^}]*align-content:\s*start[^}]*overscroll-behavior-y:\s*contain/s,
  );
  assert.match(
    css,
    /html\.chat-expanded,\s*body\.chat-expanded\s*\{[^}]*overflow:\s*hidden[^}]*overscroll-behavior:\s*none/s,
  );
  assert.match(css, /\.chat-thinking/);
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
  assert.doesNotMatch(profileScript, /FUNDING_CREDENTIALS/);
  assert.doesNotMatch(reviewScript, /FUNDING_CREDENTIALS/);
  assert.doesNotMatch(prototype, /Phase 3 deployment/);
  assert.doesNotMatch(prototype, /id="profile-search"|id="remember-profile"/);
  assert.match(prototype, /Your matches will appear here/);
  assert.match(script, /id="browse-all"/);
  assert.match(script, /function browseAllOpportunities/);
  assert.match(css, /\/\* Unified search workflow \*\//);
  assert.match(
    css,
    /\.context-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s,
  );
  assert.match(css, /\.filter-panel\s*\{[^}]*grid-area:\s*auto/s);
  assert.match(css, /\.filter-body\s*\{[^}]*overflow:\s*visible/s);
  assert.match(css, /\.results-column\s*\{[^}]*width:\s*100%/s);
  assert.match(css, /@media \(prefers-color-scheme:\s*dark\)/);
  assert.match(css, /@media \(forced-colors:\s*active\)/);
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

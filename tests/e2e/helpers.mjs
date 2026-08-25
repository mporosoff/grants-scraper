import { expect } from "@playwright/test";

const WORKER_ORIGIN = "https://funding-finder-voyage-search.urochestercheme.workers.dev";
const AWARD_WORKER_ORIGIN = "https://funding-finder-award-api.urochestercheme.workers.dev";

function corsHeaders(extra = {}) {
  return {
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Origin": "*",
    ...extra,
  };
}

export function watchRuntimeErrors(page) {
  const errors = [];
  page.on("pageerror", error => errors.push(`pageerror: ${error.message}`));
  page.on("console", message => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

export function mockHybrid(page, {
  failEmbedCalls = 0,
  failEveryEmbed = false,
  retryAfter = 1,
  reverseRerank = false,
  rerankDelayMs = 0,
  maxRankings = 24,
} = {}) {
  const calls = { embed: [], rerank: [] };
  page.route(`${WORKER_ORIGIN}/**`, async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/embed-query")) {
      const body = request.postDataJSON();
      calls.embed.push(body);
      if (failEveryEmbed || calls.embed.length <= failEmbedCalls) {
        await route.fulfill({
          status: 429,
          headers: corsHeaders({
            "Content-Type": "application/json",
            "Access-Control-Expose-Headers": "Retry-After",
            "Retry-After": String(retryAfter),
          }),
          body: JSON.stringify({ error: { code: "rate_limited" } }),
        });
        return;
      }
      const embedding = Array(1024).fill(0);
      embedding[0] = 1;
      await route.fulfill({
        status: 200,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ embedding, usage: { total_tokens: 1 } }),
      });
      return;
    }
    if (path.endsWith("/rerank")) {
      const body = request.postDataJSON();
      calls.rerank.push(body);
      if (rerankDelayMs) await new Promise(resolve => setTimeout(resolve, rerankDelayMs));
      const order = body.candidates.map((_candidate, index) => index);
      if (reverseRerank) order.reverse();
      const rankings = order.slice(0, maxRankings).map((index, rank) => ({
        index,
        passage_id: body.candidates[index].passage_id,
        relevance_score: 1 - rank / 100,
      }));
      await route.fulfill({
        status: 200,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ rankings, usage: { total_tokens: rankings.length } }),
      });
      return;
    }
    await route.fulfill({
      status: 404,
      headers: corsHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ error: { code: "not_found" } }),
    });
  });
  return calls;
}

export function mockAwards(target, { failNih = false, failNsf = false, hasMoreAtOffsets = [] } = {}) {
  const calls = [];
  target.route(`${AWARD_WORKER_ORIGIN}/**`, async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    const body = request.postDataJSON();
    calls.push(body);
    const retrievedAt = "2026-08-24T20:00:00.000Z";
    const nsf = {
      award_id: "2605508",
      source_record_ids: ["2605508"],
      source: "NSF",
      agency: "National Science Foundation",
      subagency: "Mathematical and Physical Sciences",
      program_name: "Plasma Physics",
      program_codes: ["160Z00"],
      opportunity_numbers: [],
      activity_code: null,
      funding_mechanism: "Grant",
      title: "Collaborative Research: Warm Dense Matter",
      abstract: "This project studies warm dense matter, plasma, and materials under extreme conditions.",
      project_start: "2026-09-01",
      project_end: "2029-08-31",
      award_year: 2026,
      total_award: 686056,
      award_amount_basis: "estimated_total_award",
      institution: { name: "University of Rochester", normalized_name: "University of Rochester", identifiers: { uei: "F27KDXZMF9Y8", ipf: null, other: null } },
      organization_department: null,
      principal_investigators: [{ name: "Vasily Karasiev", role: "Principal Investigator", email: "vkarasev@example.edu", official_contact_url: "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508" }],
      program_contacts: [{ name: "Vladimir Lukin", role: "Program Officer", email: "vlukin@nsf.gov", official_contact_url: "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508" }],
      official_award_url: "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508",
      annual_support: [],
      source_provenance: { source_url: "https://api.nsf.gov/services/v1/awards.json", retrieved_at: retrievedAt, source_record_id: "2605508", adapter_version: "1.0.0" },
    };
    const nih = {
      ...nsf,
      award_id: "R01HL174537",
      source_record_ids: ["10875475"],
      source: "NIH",
      agency: "National Institutes of Health",
      subagency: "National Heart, Lung, and Blood Institute",
      program_name: null,
      program_codes: ["R01", "HL"],
      opportunity_numbers: ["PAR-26-114"],
      activity_code: "R01",
      funding_mechanism: "Research Project Grant",
      title: "Mechanisms of Mitral Valve Prolapse",
      abstract: "This project investigates cellular mechanisms that drive mitral valve prolapse.",
      project_start: "2024-07-01",
      project_end: "2029-06-30",
      award_year: 2026,
      total_award: 2293188,
      award_amount_basis: "returned_support_years",
      organization_department: "Medicine",
      principal_investigators: [{ name: "Stephen Dewhurst", role: "Contact Principal Investigator", email: null, official_contact_url: "https://reporter.nih.gov/project-details/10875475" }],
      program_contacts: [{ name: "Anissa Brown", role: "Program Official", email: null, official_contact_url: "https://reporter.nih.gov/project-details/10875475" }],
      official_award_url: "https://reporter.nih.gov/project-details/10875475",
      annual_support: [{ fiscal_year: 2026, award_amount: 500000 }],
      source_provenance: { source_url: "https://api.reporter.nih.gov/v2/projects/search", retrieved_at: retrievedAt, source_record_id: "10875475", adapter_version: "1.0.0" },
    };
    const results = [];
    const sources = [];
    for (const source of body.sources) {
      const failed = source === "NSF" ? failNsf : failNih;
      if (failed) {
        sources.push({ source, status: "unavailable", error: { code: "source_unavailable" } });
      } else {
        results.push(source === "NSF" ? nsf : nih);
        sources.push({
          source,
          status: "ok",
          adapter_version: "1.1.0",
          cache: "miss",
          total_count: null,
          raw_record_count: 1,
          has_more: hasMoreAtOffsets.includes(body.offset),
          result_count: 1,
          retrieved_at: retrievedAt,
        });
      }
    }
    await route.fulfill({
      status: results.length ? 200 : 503,
      headers: corsHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        schema_version: 1,
        request: body,
        results,
        sources,
        pagination: { limit: body.limit, offset: body.offset },
      }),
    });
  });
  return calls;
}

export async function openFundingFinder(page, { sidecarFailure = false, evaluation = false } = {}) {
  if (sidecarFailure) {
    await page.route("**/data/subtopics.js*", route => route.fulfill({
      status: 404,
      contentType: "text/javascript",
      body: "",
    }));
  }
  const parameters = new URLSearchParams({ "gate4-e2e": "1" });
  if (evaluation) parameters.set("evaluation", "1");
  await page.goto(`/match_explorer.html?${parameters}`);
  await expect(page.locator("#catalog-pill")).toContainText(/current/, { timeout: 30_000 });
  await expect(page.locator("#query")).toBeEnabled();
  await expect(page.locator("#find-funding")).toBeEnabled();
}

export async function openTeamMatch(page, { sidecarFailure = false } = {}) {
  if (sidecarFailure) {
    await page.route("**/data/subtopics.js*", route => route.fulfill({
      status: 404,
      contentType: "text/javascript",
      body: "",
    }));
  }
  await page.goto("/team_match.html?gate4-e2e=1");
  await expect(page.locator("#add-researcher")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#view")).toContainText(/Pick at least two researchers/);
}

export async function runFundingSearch(page, query) {
  await page.locator("#query").fill(query);
  await page.locator("#find-funding").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 30_000 });
}

export async function waitForHybridSettled(page) {
  await expect(page.locator("#potential-status")).toContainText(
    /Potential matching completed|temporarily|needs the topic layer|unavailable/,
    { timeout: 30_000 },
  );
}

export async function downloadText(page, selector) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(selector).click(),
  ]);
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8").replace(/^\uFEFF/, "");
}

export function csvRows(csv) {
  return csv.trim().split(/\r?\n/).slice(1);
}

export async function addDepartmentResearcher(page, optionIndex = 0) {
  await page.locator("#add-researcher").click();
  const options = page.locator('#researcher-choice optgroup[label="Department faculty"] option');
  const option = options.nth(optionIndex);
  const value = await option.getAttribute("value");
  const label = (await option.textContent()).trim();
  await page.locator("#researcher-choice").selectOption(value);
  await page.locator("#choose-researcher").click();
  await expect(page.getByRole("button", { name: `Remove ${label} from team` })).toBeVisible();
  return { label, value };
}

export async function mockOpenAiBroadening(page) {
  const state = { calls: 0, candidate: null };
  await page.route("https://api.openai.com/v1/responses", async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders({ "Access-Control-Allow-Headers": "authorization,content-type" }) });
      return;
    }
    state.calls += 1;
    const body = request.postDataJSON();
    let output;
    if (state.calls === 1) {
      output = {
        interpretation: "Catalysis research broadened to adjacent reaction-engineering terminology.",
        search_terms: ["reaction engineering"],
        avoid_terms: [],
      };
    } else {
      const input = JSON.parse(body.input);
      state.candidate = input.candidate_opportunities.find(item => item.workflow_tier === "ai_candidate");
      output = {
        summary: "The bounded mock selected one newly retrieved candidate to exercise the workflow.",
        matches: state.candidate ? [{
          id: state.candidate.id,
          score: 61,
          verdict: "Possible fit",
          reason: "Selected only to exercise the AI-expanded candidate workflow.",
          concern: "Verify scope in the official notice.",
        }] : [],
        follow_up_suggestions: ["Show this candidate"],
      };
    }
    await route.fulfill({
      status: 200,
      headers: corsHeaders({
        "Access-Control-Allow-Headers": "authorization,content-type",
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({ output_text: JSON.stringify(output) }),
    });
  });
  return state;
}

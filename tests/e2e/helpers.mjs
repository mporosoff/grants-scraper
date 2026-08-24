import { expect } from "@playwright/test";

const WORKER_ORIGIN = "https://funding-finder-voyage-search.urochestercheme.workers.dev";

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

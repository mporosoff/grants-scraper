import { expect } from "@playwright/test";

const WORKER_ORIGIN = "https://funding-finder-voyage-search.urochestercheme.workers.dev";
const AWARD_WORKER_ORIGIN = "https://funding-finder-award-api.urochestercheme.workers.dev";
const ALERTS_WORKER_ORIGIN = "https://funding-finder-alerts.urochestercheme.workers.dev";

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

export function mockAwards(target, {
  awardOverridesBySource = {},
  failDoe = false,
  failNih = false,
  failNsf = false,
  hasMoreBySource = {},
  hasMoreAtOffsets = [],
  resultCountBySourceOffset = {},
  resultCountPerSource = 1,
  responseDelaysBySourceOffset = {},
  sourceFailures = {},
  sourceFailuresByOffset = {},
} = {}) {
  const calls = [];
  target.route(`${AWARD_WORKER_ORIGIN}/**`, async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    const requestUrl = new URL(request.url());
    if (requestUrl.pathname === "/institutions/search" && request.method() === "GET") {
      const query = (requestUrl.searchParams.get("query") || "").toLowerCase();
      const fixtures = {
        mit: [
          ["https://ror.org/042nb2s44", "Massachusetts Institute of Technology", "MIT", "Cambridge"],
          ["https://ror.org/04mtcj695", "University of Southern Mindanao", "MIT", "Kabacan", "Philippines", "PH"],
        ],
        caltech: [["https://ror.org/05dxps055", "California Institute of Technology", "Caltech", "Pasadena"]],
        uva: [
          ["https://ror.org/0153tk833", "University of Virginia", "UVA", "Charlottesville"],
          ["https://ror.org/0432s1v23", "University Vascular Associates", "UVA", "Chattanooga"],
        ],
        rit: [
          ["https://ror.org/00v4yb702", "Rochester Institute of Technology", "RIT", "Rochester"],
          ["https://ror.org/03zmfa837", "Rochester Institute of Technology - Dubai", "RIT", "Dubai", "United Arab Emirates", "AE"],
        ],
        ucla: [
          ["https://ror.org/046rm7j60", "University of California, Los Angeles", "UCLA", "Los Angeles"],
          ["https://ror.org/03qgg3111", "Universidad Centroccidental Lisandro Alvarado", "UCLA", "Barquisimeto", "Venezuela", "VE"],
        ],
        "cold spring harbor": [["https://ror.org/02ar0d825", "Cold Spring Harbor Laboratory", "Cold Spring Harbor", "Cold Spring Harbor"]],
        "cold spring harbor laboratory": [["https://ror.org/02ar0d825", "Cold Spring Harbor Laboratory", "Cold Spring Harbor", "Cold Spring Harbor"]],
      };
      const institutions = (fixtures[query] || []).map(([id, canonicalName, alias, city, country = "United States", countryCode = "US"], index) => ({
        id,
        canonical_name: canonicalName,
        aliases: alias === "Caltech" ? [alias] : [],
        acronyms: alias === "Caltech" ? [] : [alias],
        types: [canonicalName === "University Vascular Associates" ? "healthcare" : "education"],
        status: "active",
        location: { city, country, country_code: countryCode },
        registry: "ROR",
        registry_url: id,
        match: { exact: true, type: alias === "Caltech" ? "alias" : "acronym", score: 130 - index },
      }));
      await route.fulfill({
        status: 200,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          schema_version: 1,
          query: requestUrl.searchParams.get("query"),
          institutions,
          registry: { source: "ROR", status: "available", adapter_version: "1.0.0", license: "CC0-1.0", cache: "miss" },
        }),
      });
      return;
    }
    const body = request.postDataJSON();
    calls.push(body);
    const responseDelay = Math.max(0, Number(responseDelaysBySourceOffset[`${body.sources[0]}:${body.offset}`]) || 0);
    if (responseDelay) await new Promise(resolve => setTimeout(resolve, responseDelay));
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
      abstract: "This project studies CO₂ conversion, warm dense matter, plasma, and materials under extreme conditions.\n\nThis source-provided second paragraph remains separate.",
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
    const doe = {
      ...nsf,
      award_id: "DE-SC0020230",
      source_record_ids: ["DE-SC0020230"],
      source: "DOE",
      agency: "U.S. Department of Energy Office of Science",
      subagency: "Office of Basic Energy Sciences",
      program_name: "Catalysis Science",
      program_codes: ["Catalysis Science"],
      opportunity_numbers: ["DE-FOA-0003612"],
      activity_code: null,
      funding_mechanism: "Financial Assistance",
      title: "Catalytic Activation and Conversion of Carbon Dioxide",
      abstract: "This public PAMS abstract studies catalytic CO₂ conversion.\n\nThe second source paragraph remains separate.",
      project_start: "2019-09-01",
      project_end: "2024-08-31",
      award_year: 2019,
      total_award: 1150000,
      award_amount_basis: "amount_awarded_to_date",
      organization_department: null,
      principal_investigators: [{ name: "Marc Porosoff", role: "Principal Investigator", email: null, official_contact_url: "https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Common/ViewPublicAbstract.aspx?rv=fixture&rtc=24&PRoleId=10" }],
      program_contacts: [{ name: "DOE Program Manager", role: "Program Manager", email: null, official_contact_url: "https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Common/ViewPublicAbstract.aspx?rv=fixture&rtc=24&PRoleId=10" }],
      official_award_url: "https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Common/ViewPublicAbstract.aspx?rv=fixture&rtc=24&PRoleId=10",
      annual_support: [],
      source_provenance: { source_url: "https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Awards/AwardSearchExternal.aspx", retrieved_at: retrievedAt, source_record_id: "DE-SC0020230", adapter_version: "1.0.0" },
    };
    const results = [];
    const sources = [];
    for (const source of body.sources) {
      const failed = source === "NSF" ? failNsf : source === "NIH" ? failNih : failDoe;
      const configuredFailure = sourceFailuresByOffset[`${source}:${body.offset}`]
        || sourceFailures[source]
        || (failed ? { status: "unavailable", code: "source_unavailable" } : null);
      if (configuredFailure) {
        sources.push({
          source,
          status: configuredFailure.status || "unavailable",
          error: { code: configuredFailure.code || "source_unavailable" },
        });
      } else {
        const baseTemplate = source === "NSF" ? nsf : source === "NIH" ? nih : doe;
        const template = { ...baseTemplate, ...(awardOverridesBySource[source] || {}) };
        const configuredCount = resultCountBySourceOffset[`${source}:${body.offset}`] ?? (
          typeof resultCountPerSource === "object"
            ? resultCountPerSource[source]
            : resultCountPerSource
        );
        const resultCount = Math.max(0, Math.min(Number(body.limit) || 1, Number(configuredCount) || 0));
        for (let index = 0; index < resultCount; index += 1) {
          const suffix = body.offset + index;
          results.push(index === 0 && body.offset === 0 ? template : {
            ...template,
            award_id: `${template.award_id}-${suffix}`,
            source_record_ids: [`${template.source_record_ids[0]}-${suffix}`],
          });
        }
        sources.push({
          source,
          status: "ok",
          adapter_version: "1.1.0",
          cache: "miss",
          total_count: null,
          raw_record_count: resultCount,
          has_more: (hasMoreBySource[source] || hasMoreAtOffsets).includes(body.offset),
          result_count: resultCount,
          retrieved_at: retrievedAt,
        });
      }
    }
    await route.fulfill({
      status: results.length ? 200 : sources.every(source => source.status === "unsupported") ? 400 : 503,
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

export function mockAlerts(target, { status = 202, errorCode = "", responseBody = null } = {}) {
  const calls = [];
  target.route(`${ALERTS_WORKER_ORIGIN}/**`, async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    if (new URL(request.url()).pathname === "/subscriptions" && request.method() === "POST") {
      calls.push(request.postDataJSON());
      await route.fulfill({
        status,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: responseBody ?? JSON.stringify(errorCode
          ? { error: { code: errorCode } }
          : { status: "verification_required" }),
      });
      return;
    }
    await route.fulfill({ status: 404, headers: corsHeaders({ "Content-Type": "application/json" }), body: "{}" });
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

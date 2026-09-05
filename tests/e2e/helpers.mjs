import { selectAwardFacet } from "./public-tool-workflow.mjs";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { expect } from "@playwright/test";

const [frozenFundingCatalogSource, searchQuerySource] = await Promise.all([
  readFile(new URL("../fixtures/frozen/funding-catalog.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-query.js", import.meta.url), "utf8"),
]);
const frozenCatalogContext = {};
frozenCatalogContext.globalThis = frozenCatalogContext;
vm.createContext(frozenCatalogContext);
vm.runInContext(searchQuerySource, frozenCatalogContext);
vm.runInContext(frozenFundingCatalogSource, frozenCatalogContext);
const frozenCatalog = frozenCatalogContext.GRANT_CATALOG;
const timestamp = String(frozenCatalog.generated_at).match(
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$/,
);
if (!timestamp) throw new Error("Frozen catalog timestamp must be canonical UTC.");
const frozenAssetVersion = `catalog-${timestamp.slice(1, 4).join("")}T${timestamp.slice(4, 7).join("")}${String(timestamp[7] || "").padEnd(6, "0").slice(0, 6)}Z`;
const frozenStatusIdentity = Object.entries(frozenCatalog.status_counts)
  .filter(([_status, count]) => Number(count) > 0)
  .sort(([left], [right]) => left.localeCompare(right))
  .map(([status, count]) => `${status}=${count}`)
  .join(",");
const frozenCatalogMetadataSource = `globalThis.GRANT_CATALOG_METADATA=${JSON.stringify({
  schema_version: 1,
  catalog_schema_version: frozenCatalog.schema_version,
  generated_at: frozenCatalog.generated_at,
  pipeline_generated_at: frozenCatalog.generated_at,
  record_count: frozenCatalog.record_count,
  status_counts: frozenCatalog.status_counts,
  asset_version: frozenAssetVersion,
  catalog_url: `./data/opportunities.js?v=${frozenAssetVersion}`,
  release_identity: [
    `catalog-v${frozenCatalog.schema_version}`,
    frozenAssetVersion,
    `records=${frozenCatalog.record_count}`,
    `documents=${frozenCatalog.search_index.document_count}`,
    `terms=${Object.keys(frozenCatalog.search_index.postings).length}`,
    `status=${frozenStatusIdentity}`,
  ].join(":"),
})};`;
const frozenSubtopicCatalogSource = `globalThis.SUBTOPIC_CATALOG=${JSON.stringify({
  schema_version: 1,
  generation: { as_of: "2026-09-01" },
  parent_count: 1,
  record_count: 1,
  records: {
    "363616": {
      segmentation_method: "frozen_fixture",
      subtopic_count: 1,
      subtopics: [{
        id: "363616:fixture-child",
        subtopic_id: "363616:fixture-child",
        parent_id: "363616",
        parent_opportunity_number: "26-518",
        title: "Catalysis and Reaction Engineering",
        summary: "Publication-eligible catalysis science and reaction engineering research.",
        description: "Publication-eligible catalysis science and reaction engineering research.",
        child_type: "subject",
        publication_state: "publishable",
        status: "posted",
        topic_areas: ["Catalysis and reaction engineering"],
        program_area_labels: ["Catalysis and reaction engineering"],
      }],
    },
  },
  search_index: {
    algorithm: "bm25",
    document_count: 1,
    average_document_length: 1,
    document_lengths: [1],
    record_ids: ["363616:fixture-child"],
    postings: {},
  },
})};`;

const WORKER_ORIGIN = "https://funding-finder-voyage-search.urochestercheme.workers.dev";
const AWARD_WORKER_ORIGIN = "https://funding-finder-award-api.urochestercheme.workers.dev";
const USA_SPENDING_ORIGIN = "https://api.usaspending.gov";
const ALERTS_WORKER_ORIGIN = "https://funding-finder-alerts.urochestercheme.workers.dev";

function corsHeaders(extra = {}) {
  return {
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Origin": "*",
    ...extra,
  };
}

export function openAiStructuredResponse(value, overrides = {}) {
  return {
    id: "resp_e2e",
    object: "response",
    status: "completed",
    error: null,
    incomplete_details: null,
    output: [{
      id: "msg_e2e",
      type: "message",
      role: "assistant",
      status: "completed",
      content: [{
        type: "output_text",
        text: JSON.stringify(value),
        annotations: [],
      }],
    }],
    store: false,
    ...overrides,
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

export async function mockFrozenFundingCatalog(target) {
  await target.route("**/data/catalog-metadata.js*", route => route.fulfill({
    status: 200,
    contentType: "text/javascript",
    body: frozenCatalogMetadataSource,
  }));
  await target.route("**/data/opportunities.js*", route => route.fulfill({
    status: 200,
    contentType: "text/javascript",
    body: frozenFundingCatalogSource,
  }));
}

export async function mockFrozenFundingSearchPackage(page) {
  await mockFrozenFundingCatalog(page);
  await page.route("**/data/subtopics.js*", route => route.fulfill({
    status: 200,
    contentType: "text/javascript",
    body: frozenSubtopicCatalogSource,
  }));

  let packagePromise = null;
  const buildPackage = () => {
    if (packagePromise) return packagePromise;
    packagePromise = (async () => {
      const { corpus, corpusSha256 } = await page.evaluate(async () => {
        const value = globalThis.FUNDING_HYBRID_SEARCH.buildCorpus({
          parentCatalog: globalThis.GRANT_CATALOG,
          childCatalog: globalThis.FUNDING_RETRIEVAL.createChildCatalog(
            globalThis.SUBTOPIC_CATALOG,
          ),
        });
        return {
          corpus: value,
          corpusSha256: await globalThis.FUNDING_HYBRID_SEARCH.corpusHash(value),
        };
      });
      const vectors = Buffer.alloc(corpus.length * 1024 * 2);
      corpus.forEach((_passage, index) => vectors.writeUInt16LE(0x3c00, index * 1024 * 2));
      const vectorSha256 = createHash("sha256").update(vectors).digest("hex");
      return {
        vectors,
        manifest: {
          schema_version: 1,
          generated_at: "2026-09-01T12:00:00Z",
          model: "voyage-4-lite",
          provider_revision: "frozen-e2e-fixture",
          response_model: "voyage-4-lite",
          input_type: "document",
          source_output_dtype: "float",
          dimension: 1024,
          dtype: "float16-le",
          byte_order: "little-endian",
          passage_count: corpus.length,
          parent_passage_count: corpus.filter(item => item.passage_kind === "parent").length,
          child_passage_count: corpus.filter(item => item.passage_kind !== "parent").length,
          corpus_sha256: corpusSha256,
          vector_sha256: vectorSha256,
          vector_bytes: vectors.length,
          model_space_fingerprint: "0".repeat(64),
          model_space: { canary_set_version: 1, canary_count: 1 },
          passages: corpus.map((passage, vectorRow) => ({
            passage_id: passage.passage_id,
            parent_id: passage.parent_id,
            passage_kind: passage.passage_kind,
            record_id: passage.record_id,
            text_sha256: createHash("sha256").update(passage.text).digest("hex"),
            vector_row: vectorRow,
          })),
        },
      };
    })();
    return packagePromise;
  };

  await page.route("**/data/search-v2-voyage-manifest.json*", async route => {
    const fixture = await buildPackage();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixture.manifest),
    });
  });
  await page.route("**/data/search-v2-voyage-vectors.f16*", async route => {
    const fixture = await buildPackage();
    await route.fulfill({
      status: 200,
      contentType: "application/octet-stream",
      body: fixture.vectors,
    });
  });
}

export function mockAwards(target, {
  awardOverridesBySource = {},
  failDoe = false,
  failDod = false,
  failNih = false,
  failNsf = false,
  hasMoreBySource = {},
  hasMoreAtOffsets = [],
  institutionResponseDelayMs = 0,
  resultCountBySourceOffset = {},
  resultCountPerSource = 1,
  registryRateLimited = false,
  responseDelaysBySourceOffset = {},
  snapshotPageDelayMs = 0,
  snapshotCreateDelayMs = 0,
  snapshotPageExpireAtCall = 0,
  snapshotPageFailAtCalls = [],
  snapshotEvidenceExpireAtCall = 0,
  snapshotBatchExpireAtCall = 0,
  snapshotBatchDelaysMs = [],
  snapshotRetryExpireAtCall = 0,
  failSnapshotCreateForTopics = [],
  failSnapshotInitialPageForTopics = [],
  enforceYearFilters = false,
  programOfficerSourceFailures = {},
  sourceFailures = {},
  sourceFailuresByOffset = {},
} = {}) {
  const calls = [];
  const snapshots = new Map();
  let snapshotSequence = 0;
  let snapshotPageCallCount = 0;
  let snapshotEvidenceCallCount = 0;
  let snapshotBatchCallCount = 0;
  let snapshotRetryCallCount = 0;
  const configuredDodCount = Math.max(0, Number(
    typeof resultCountPerSource === "object" ? resultCountPerSource.DOD : 0,
  ) || 0);
  const dodRowsByGeneratedId = new Map();
  target.route(`${USA_SPENDING_ORIGIN}/**`, async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    const requestUrl = new URL(request.url());
    const configuredFailure = sourceFailures.DOD || (failDod ? { code: "source_unavailable" } : null);
    if (configuredFailure) {
      await route.fulfill({
        status: 503,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ detail: configuredFailure.code || "source_unavailable" }),
      });
      return;
    }
    if (requestUrl.pathname === "/api/v2/search/spending_by_award/" && request.method() === "POST") {
      const body = request.postDataJSON();
      const page = Math.max(1, Number(body.page) || 1);
      const limit = Math.max(1, Number(body.limit) || 25);
      const start = (page - 1) * limit;
      const end = Math.min(start + limit, configuredDodCount);
      const searchTerm = String(body.filters?.recipient_search_text?.[0] || "").trim();
      const recipientUei = /^[A-Z0-9]{12}$/i.test(searchTerm) ? searchTerm.toUpperCase() : "NPU8ULVAAS23";
      const knownRecipientNames = {
        F27KDXZMF9Y8: "University of Rochester",
        NPU8ULVAAS23: "University of Maryland, College Park",
      };
      const recipientName = searchTerm && !/^[A-Z0-9]{12}$/i.test(searchTerm)
        ? searchTerm
        : knownRecipientNames[recipientUei] || "University of Rochester";
      const dateFilter = body.filters?.time_period?.[0];
      const signedYear = Number(String(dateFilter?.start_date || "2026").slice(0, 4)) || 2026;
      const requestedAwardId = String(body.filters?.award_ids?.[0] || "").trim();
      const results = [];
      for (let index = start; index < end; index += 1) {
        const awardId = index === 0 && requestedAwardId
          ? requestedAwardId
          : `FA9550261B${String(195 + index).padStart(3, "0")}`;
        const generatedId = `ASST_NON_${awardId}_097`;
        const row = {
          "Award ID": awardId,
          "Recipient Name": recipientName.toUpperCase(),
          "Recipient UEI": recipientUei,
          "Start Date": `${signedYear}-09-01`,
          "End Date": `${signedYear + 5}-08-31`,
          "Award Amount": 3_000_000 + index,
          "Awarding Agency": "Department of Defense",
          "Awarding Sub Agency": "Department of the Air Force",
          Description: `CENTER OF EXCELLENCE ${index + 1}: MULTISCALE NONEQUILIBRIUM TRANSPORT`,
          "Base Obligation Date": `${signedYear}-08-28`,
          "Award Type": "PROJECT GRANT (B)",
          generated_internal_id: generatedId,
        };
        dodRowsByGeneratedId.set(generatedId, row);
        results.push(row);
      }
      const hasNext = end < configuredDodCount;
      await route.fulfill({
        status: 200,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          spending_level: "awards",
          limit,
          results,
          page_metadata: {
            page,
            total: configuredDodCount,
            hasNext,
            last_record_unique_id: hasNext ? end : null,
            last_record_sort_value: hasNext ? results.at(-1)?.["Award ID"] : null,
          },
        }),
      });
      return;
    }
    const detailMatch = requestUrl.pathname.match(/^\/api\/v2\/awards\/(ASST_[^/]+)\/$/i);
    if (detailMatch && request.method() === "GET") {
      const generatedId = decodeURIComponent(detailMatch[1]);
      const row = dodRowsByGeneratedId.get(generatedId);
      if (!row) {
        await route.fulfill({ status: 404, headers: corsHeaders({ "Content-Type": "application/json" }), body: "{}" });
        return;
      }
      await route.fulfill({
        status: 200,
        headers: corsHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          generated_unique_award_id: generatedId,
          fain: row["Award ID"],
          description: row.Description,
          type: "04",
          total_obligation: row["Award Amount"],
          date_signed: row["Base Obligation Date"],
          period_of_performance: { start_date: row["Start Date"], end_date: row["End Date"] },
          recipient: { recipient_name: row["Recipient Name"], recipient_uei: row["Recipient UEI"] },
          awarding_agency: {
            toptier_agency: { name: "Department of Defense" },
            subtier_agency: { name: "Department of the Air Force" },
            office_agency_name: "FA9550 AFRL AFOSR",
          },
          cfda_info: [{ cfda_number: "12.800", cfda_title: "Air Force Defense Research Sciences Program" }],
          funding_opportunity: { number: "NOFOAFRLAFOSR20250002" },
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, headers: corsHeaders({ "Content-Type": "application/json" }), body: "{}" });
  });
  target.route(`${AWARD_WORKER_ORIGIN}/**`, async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    const requestUrl = new URL(request.url());
    if (requestUrl.pathname === "/institutions/search" && request.method() === "GET") {
      if (registryRateLimited) {
        await route.fulfill({
          status: 429,
          headers: corsHeaders({ "Content-Type": "application/json", "Retry-After": "60" }),
          body: JSON.stringify({
            schema_version: 1,
            query: requestUrl.searchParams.get("query"),
            institutions: [],
            registry: {
              source: "ROR",
              status: "rate_limited",
              adapter_version: "1.3.0",
              error: { code: "rate_limited" },
            },
          }),
        });
        return;
      }
      const registryDelay = Math.max(0, Number(institutionResponseDelayMs) || 0);
      if (registryDelay) await new Promise(resolve => setTimeout(resolve, registryDelay));
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
          registry: { source: "ROR", status: "available", adapter_version: "1.3.0", license: "CC0-1.0", cache: "miss" },
        }),
      });
      return;
    }
    const body = request.postDataJSON();
    calls.push(body);
    const responseDelay = Math.max(0, Number(responseDelaysBySourceOffset[`${body.sources?.[0]}:${body.offset}`]) || 0);
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
      abstract: "This project studies CO₂ (carbon dioxide) conversion, warm dense matter, plasma, and materials under extreme conditions.\n\nThis source-provided second paragraph remains separate.",
      project_start: "2026-09-01",
      project_end: "2029-08-31",
      award_year: 2026,
      total_award: 686056,
      award_amount_basis: "estimated_total_award",
      institution: { name: "University of Rochester", normalized_name: "University of Rochester", identifiers: { uei: "F27KDXZMF9Y8", ipf: null, other: null } },
      organization_department: null,
      principal_investigators: [{ name: "Vasily Karasiev", role: "Principal Investigator", email: "vkarasev@example.edu", official_contact_url: "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508" }],
      program_contacts: [{ name: "Vladimir Lukin", role: "Program Officer", email: "vlukin@nsf.gov", official_contact_url: "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508", source_display_name: "Vladimir Lukin", program_contact_key: "program-contact-v1:vladimir|lukin", program_contact_identity: "NSF:program-contact-v1:vladimir|lukin", searchable_program_contact: true }],
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
      program_contacts: [{ name: "Anissa Brown", role: "Program Official", email: null, official_contact_url: "https://reporter.nih.gov/project-details/10875475", source_display_name: "Anissa Brown", program_contact_key: "program-contact-v1:anissa|brown", program_contact_identity: "NIH:program-contact-v1:anissa|brown", searchable_program_contact: true }],
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
    const dod = {
      ...nsf,
      award_id: "FA9550261B195",
      source_record_ids: ["FA9550261B195", "ASST_NON_FA9550261B195_097"],
      source: "DOD",
      agency: "Department of Defense",
      subagency: "Department of the Air Force",
      program_name: "Air Force Defense Research Sciences Program",
      program_codes: ["12.800"],
      opportunity_numbers: ["NOFOAFRLAFOSR20250002"],
      activity_code: null,
      funding_mechanism: "Project Grant",
      title: "CENTER OF EXCELLENCE: MULTISCALE NONEQUILIBRIUM TRANSPORT",
      abstract: null,
      project_start: "2026-09-01",
      project_end: "2031-08-31",
      award_year: 2026,
      total_award: 3000000,
      award_amount_basis: "total_obligation",
      organization_department: "AIR FORCE OFFICE OF SCIENTIFIC RESEARCH",
      principal_investigators: [],
      program_contacts: [],
      official_award_url: "https://www.usaspending.gov/award/ASST_NON_FA9550261B195_097/",
      annual_support: [],
      source_provenance: { source_url: "https://www.usaspending.gov/award/ASST_NON_FA9550261B195_097/", retrieved_at: retrievedAt, source_record_id: "ASST_NON_FA9550261B195_097", adapter_version: "1.0.0" },
    };
    const templateFor = source => ({ ...(source === "NSF" ? nsf : source === "NIH" ? nih : source === "DOE" ? doe : dod), ...(awardOverridesBySource[source] || {}) });
    const snapshotAggregate = records => {
      const people = new Map();
      const programs = new Map();
      const institutions = new Map();
      const years = new Map();
      const agencyTotals = new Map([["NSF", 0], ["NIH", 0], ["DOE", 0], ["DOD", 0]]);
      records.forEach(record => {
        agencyTotals.set(record.source, (agencyTotals.get(record.source) || 0) + 1);
        if (Number.isInteger(record.award_year)) years.set(record.award_year, (years.get(record.award_year) || 0) + 1);
        for (const person of record.principal_investigators || []) {
          const key = `investigator:${String(person.name).toLowerCase().replace(/\W+/g, "-")}`;
          const current = people.get(key) || { identity_key: key, name: person.name, projects: 0, variants: [], award_keys: [] };
          current.projects += 1;
          current.award_keys.push(`${record.source}:${record.award_id}`);
          if (!current.variants.some(item => item.source === record.source && item.name === person.name)) current.variants.push({ name: person.name, source: record.source, award_id: record.award_id });
          people.set(key, current);
        }
        const programName = record.activity_code || record.program_name || record.program_codes?.[0] || record.subagency;
        if (programName) {
          const key = `${record.source}:${String(programName).toLowerCase().replace(/\W+/g, "-")}`;
          const current = programs.get(key) || { key, source: record.source, label: `${record.source} · ${programName}`, query: programName, projects: 0, award_keys: [] };
          current.projects += 1;
          current.award_keys.push(`${record.source}:${record.award_id}`);
          programs.set(key, current);
        }
        const institutionName = record.institution?.normalized_name || record.institution?.name;
        if (institutionName) {
          const key = `institution:${String(institutionName).toLowerCase().replace(/\W+/g, "-")}`;
          const current = institutions.get(key) || { key, name: institutionName, projects: 0, variants: [], award_keys: [] };
          current.projects += 1;
          current.award_keys.push(`${record.source}:${record.award_id}`);
          if (!current.variants.includes(institutionName)) current.variants.push(institutionName);
          institutions.set(key, current);
        }
      });
      const orderedYears = [...years.entries()].sort(([left], [right]) => left - right);
      return {
        project_count: records.length,
        investigator_count: people.size,
        institution_count: institutions.size,
        program_count: programs.size,
        year_start: orderedYears[0]?.[0] || null,
        year_end: orderedYears.at(-1)?.[0] || null,
        represented_years: orderedYears.map(([year, projects]) => ({ year, projects })),
        agency_totals: [...agencyTotals].map(([source, projects]) => ({ source, projects })),
        investigators: [...people.values()],
        institutions: [...institutions.values()],
        programs: [...programs.values()],
        ordered_refs: records.map((record, index) => ({ position: index + 1, evidence_id: `${record.source}:${record.award_id}`, source: record.source, award_id: record.award_id, title: record.title, award_year: record.award_year })),
      };
    };
    const matchedAggregate = records => {
      const aggregate = snapshotAggregate(records);
      const rank = (values, label) => values
        .map(value => ({ [label]: value[label], projects: value.projects }))
        .sort((left, right) => right.projects - left.projects || String(left[label]).localeCompare(String(right[label]), "en-US"))
        .slice(0, 12);
      return {
        project_count: aggregate.project_count,
        investigator_count: aggregate.investigator_count,
        institution_count: aggregate.institution_count,
        program_count: aggregate.program_count,
        year_start: aggregate.year_start,
        year_end: aggregate.year_end,
        represented_years: aggregate.represented_years,
        agency_totals: aggregate.agency_totals,
        investigators: rank(aggregate.investigators, "name"),
        institutions: rank(aggregate.institutions, "name"),
        programs: rank(aggregate.programs, "label"),
        facet_limit: 12,
        facets_truncated: {
          investigators: aggregate.investigator_count > 12,
          institutions: aggregate.institution_count > 12,
          programs: aggregate.program_count > 12,
        },
      };
    };
    const publicSnapshot = snapshot => ({
      schema_version: 1,
      snapshot_contract_version: 1,
      snapshot_id: snapshot.snapshot_id,
      query_id: snapshot.query_id,
      as_of: snapshot.as_of,
      expires_at: snapshot.expires_at,
      ordering_version: "award-recency-v1",
      batch_ceiling_per_agency: 25,
      request: snapshot.request,
      completeness: snapshot.completeness,
      coverage_state: snapshot.completeness === "complete" ? "complete" : snapshot.records.length ? "partial" : "unavailable",
      exact_total: snapshot.exact_total,
      at_least: snapshot.records.length,
      recency_order: snapshot.completeness === "complete" ? "verified_most_recent_to_older" : "available_snapshot_recent_to_older",
      sources: snapshot.sources,
      mode: snapshot.mode,
      program_officer: snapshot.program_officer,
      abstract_coverage: snapshot.abstract_coverage,
      base_aggregate: snapshot.aggregate,
      initial_batches: snapshot.request.sources.map(source => {
        const results = snapshot.records.filter(record => record.source === source).slice(0, 25);
        const sourceState = snapshot.sources.find(item => item.source === source);
        return { schema_version: 1, snapshot_id: snapshot.snapshot_id, query_id: snapshot.query_id, ordering_version: "award-recency-v1", batch_ceiling: 25, source, offset: 0, actual_added: results.length, loaded_through: results.length, source_total: sourceState.status === "complete" ? sourceState.result_count : null, additional_available: results.length < sourceState.result_count, source_status: sourceState, facet: { type: "all", key: "", label: "All awards" }, results };
      }),
    });
    const snapshotView = (snapshot, facet) => {
      if (!facet || facet.type === "all") return { facet: { type: "all", key: "", label: "All awards" }, records: snapshot.records };
      const groups = facet.type === "investigator" ? snapshot.aggregate.investigators
        : facet.type === "institution" ? snapshot.aggregate.institutions : snapshot.aggregate.programs;
      const group = groups.find(item => (facet.type === "investigator" ? item.identity_key : item.key) === facet.key);
      const allowed = new Set(group?.award_keys || []);
      return { facet: { type: facet.type, key: facet.key, label: facet.type === "program" ? group?.label : group?.name }, records: snapshot.records.filter(record => allowed.has(`${record.source}:${record.award_id}`)) };
    };
    if (requestUrl.pathname === "/awards/snapshots" && request.method() === "POST") {
      if (
        failSnapshotCreateForTopics.includes(body.criteria?.topic)
        || failSnapshotInitialPageForTopics.includes(body.criteria?.topic)
      ) {
        await route.fulfill({
          status: 503,
          headers: corsHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ schema_version: 1, error: { code: "source_unavailable" } }),
        });
        return;
      }
      const sources = body.sources;
      const snapshotCriteria = { ...body.criteria };
      if (snapshotCriteria.mode === "program_officer" && snapshotCriteria.year_preset === "recent5" && !snapshotCriteria.year_start && !snapshotCriteria.year_end) {
        snapshotCriteria.year_start = 2022;
        snapshotCriteria.year_end = 2026;
      }
      const records = [];
      const sourceStates = [];
      for (const source of sources) {
        const configuredFlag = source === "NSF" ? failNsf : source === "NIH" ? failNih : source === "DOE" ? failDoe : source === "DOD" ? failDod : false;
        const recoveringHybridSource = sources.length === 1 && calls.some(call => Array.isArray(call.sources) && call.sources.length > 1 && call.sources.includes(source));
        const failed = configuredFlag && !recoveringHybridSource;
        const configuredFailure = (snapshotCriteria.mode === "program_officer" ? programOfficerSourceFailures[source] : null)
          || sourceFailures[source]
          || (failed ? { status: "unavailable", code: "source_unavailable" } : null);
        if (configuredFailure) {
          sourceStates.push({ source, status: configuredFailure.status || "unavailable", result_count: 0, total_count: null, error: { code: configuredFailure.code || "source_unavailable" } });
          continue;
        }
        const template = templateFor(source);
        const configuredCount = typeof resultCountPerSource === "object"
          ? resultCountPerSource[source]
          : source === "DOD" ? 0 : resultCountPerSource;
        const count = recoveringHybridSource && configuredFlag
          ? Math.max(1, Number(configuredCount) || 0)
          : Math.max(0, Number(configuredCount) || 0);
        for (let index = 0; index < count; index += 1) {
          const record = index === 0 ? template : { ...template, award_id: `${template.award_id}-${index}`, source_record_ids: [`${template.source_record_ids[0]}-${index}`] };
          if (snapshotCriteria.mode !== "program_officer" || record.program_contacts?.some(contact => contact.program_contact_key === snapshotCriteria.program_contact_key)) records.push(record);
        }
        const partial = Array.isArray(hasMoreBySource[source]) ? hasMoreBySource[source].length > 0 : Boolean(hasMoreBySource[source]);
        sourceStates.push({ source, status: partial ? "safety_bounded" : "complete", result_count: count, total_count: partial ? null : count, at_least: count, safety_bound_reached: partial, adapter_version: "1.1.0", retrieved_at: retrievedAt });
      }
      const complete = sourceStates.every(source => source.status === "complete");
      const snapshotId = String(++snapshotSequence).padStart(64, "a");
      const programOfficer = snapshotCriteria.mode === "program_officer" ? { source: sources[0], display_name: snapshotCriteria.program_officer, contact_key: snapshotCriteria.program_contact_key, year_preset: snapshotCriteria.year_preset, year_start: snapshotCriteria.year_start || null, year_end: snapshotCriteria.year_end || null, membership_rule: "exact_same_source_program_contact_key" } : null;
      const snapshot = { snapshot_id: snapshotId, query_id: String(snapshotSequence).padStart(64, "b"), as_of: retrievedAt, expires_at: "2026-08-24T21:00:00.000Z", request: { sources, criteria: snapshotCriteria }, records, sources: sourceStates, completeness: complete ? "complete" : records.length ? "partial" : "unavailable", exact_total: complete ? records.length : null, mode: programOfficer ? "program_officer" : "standard", program_officer: programOfficer };
      snapshot.aggregate = snapshotAggregate(records);
      snapshot.abstract_coverage = { total_records: records.length, records_with_abstract: records.filter(record => record.abstract).length, records_without_abstract: records.filter(record => !record.abstract).length, percentage: records.length ? 100 : 0 };
      snapshots.set(snapshotId, snapshot);
      if (Number(snapshotCreateDelayMs) > 0) await new Promise(resolve => setTimeout(resolve, Number(snapshotCreateDelayMs)));
      await route.fulfill({ status: 200, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(publicSnapshot(snapshot)) });
      return;
    }
    if (requestUrl.pathname === "/awards/snapshots/evidence" && request.method() === "POST") {
      snapshotEvidenceCallCount += 1;
      if (body.plan_format !== "provider-concepts-v1") {
        await route.fulfill({ status: 400, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "invalid_request" } }) });
        return;
      }
      if (snapshotEvidenceCallCount === Number(snapshotEvidenceExpireAtCall)) {
        await route.fulfill({ status: 410, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "snapshot_expired" } }) });
        return;
      }
      const snapshot = snapshots.get(body.snapshot_id);
      if (!snapshot || snapshot.mode !== "program_officer") {
        await route.fulfill({ status: 410, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "snapshot_expired" } }) });
        return;
      }
      const shortConcepts = new Set(["ai", "ml", "ph"]);
      const contextualSingleConcepts = new Map([
        ["b", new Set(["cell", "cells", "lymphocyte", "lymphocytes"])],
        ["c", new Set(["language", "programming"])],
        ["k", new Set(["means"])],
        ["p", new Set(["value", "values"])],
        ["q", new Set(["learning"])],
        ["r", new Set(["computing", "language", "package", "packages", "programming", "software"])],
        ["t", new Set(["cell", "cells", "lymphocyte", "lymphocytes"])],
        ["x", new Set(["ray", "rays"])],
      ]);
      const answerIntents = new Set(["count", "investigators", "institutions", "programs", "years", "awards"]);
      const normalizedEvidenceTokens = value => (String(value || "")
        .normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [])
        .map(token => /^fy(?:19|20)\d{2}$/u.test(token) ? token.slice(2) : token);
      const admissible = (token, tokens, index) => token.length >= 3
        || shortConcepts.has(token)
        || (token.length === 1 && contextualSingleConcepts.get(token)?.has(tokens[index + 1]))
        || (/\p{L}/u.test(token) && /\p{N}/u.test(token));
      const admittedEvidenceTokens = value => {
        const tokens = normalizedEvidenceTokens(value);
        return tokens.filter((token, index) => admissible(token, tokens, index));
      };
      const plan = body.retrieval_plan;
      const exactPlanKeys = plan && typeof plan === "object" && !Array.isArray(plan)
        && Object.keys(plan).sort().join("|") === "concepts|exclusions|intent|phrases";
      const normalizeTerms = (values, minimum, maximum) => {
        if (!Array.isArray(values) || values.length < minimum || values.length > maximum) return null;
        const terms = values.map(value => normalizedEvidenceTokens(value));
        return terms.some(tokens => !tokens.length || tokens.some((token, index) => !admissible(token, tokens, index))) ? null : terms;
      };
      const concepts = exactPlanKeys && answerIntents.has(plan.intent) ? normalizeTerms(plan.concepts, 1, 16) : null;
      const phrases = exactPlanKeys ? normalizeTerms(plan.phrases, 1, 8) : null;
      const exclusions = exactPlanKeys ? normalizeTerms(plan.exclusions, 0, 8) : null;
      if (!concepts || !phrases || !exclusions) {
        await route.fulfill({ status: 400, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "invalid_evidence_request" } }) });
        return;
      }
      const requiredConcepts = [...new Set(concepts.flat())];
      const scored = snapshot.records.map((record, position) => {
        const recordValues = [
          record.title,
          record.abstract,
          record.program_name,
          record.activity_code,
          record.subagency,
          record.award_year,
          ...(record.program_codes || []),
          ...(record.principal_investigators || []).map(person => person.name),
          record.institution?.normalized_name || record.institution?.name,
        ].filter(Boolean);
        const recordTokens = new Set(recordValues.flatMap(admittedEvidenceTokens));
        if (!requiredConcepts.every(concept => recordTokens.has(concept))
          || exclusions.some(exclusion => exclusion.every(token => recordTokens.has(token)))) return null;
        const titleTokens = new Set(admittedEvidenceTokens(record.title));
        const abstractTokens = new Set(admittedEvidenceTokens(record.abstract));
        const score = phrases.reduce((total, phrase) => total
          + phrase.filter(token => titleTokens.has(token)).length * 100
          + phrase.filter(token => abstractTokens.has(token)).length * 28, 0);
        return { record, position, score };
      }).filter(Boolean).sort((left, right) => right.score - left.score || left.position - right.position);
      const matchedRecords = scored.map(item => item.record);
      const awards = scored.slice(0, body.limit).map(({ record, position, score }) => ({ evidence_id: `${record.source}:${record.award_id}`, snapshot_position: position + 1, source: record.source, award_id: record.award_id, title: record.title, program: record.program_name, program_office: record.subagency, year: record.award_year, investigators: record.principal_investigators.map(person => person.name), institution: record.institution.normalized_name, abstract_excerpt: record.abstract, deterministic_score: score, matched_fields: ["title", "abstract"] }));
      await route.fulfill({ status: 200, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, snapshot_id: snapshot.snapshot_id, as_of: snapshot.as_of, expires_at: snapshot.expires_at, mode: snapshot.mode, program_officer: snapshot.program_officer, completeness: snapshot.completeness, coverage_state: snapshot.completeness, exact_total: snapshot.exact_total, at_least: snapshot.records.length, year_scope: { preset: snapshot.program_officer.year_preset, start: snapshot.program_officer.year_start, end: snapshot.program_officer.year_end }, abstract_coverage: snapshot.abstract_coverage, matched_aggregate: matchedAggregate(matchedRecords), retrieval: { scoring_version: "program-officer-evidence-v4", plan_format: "provider-concepts-v1", answer_intent: plan.intent, concept_coverage: "all_provider_concepts_same_record", required_concept_count: requiredConcepts.length, phrase_count: phrases.length, exclusion_count: exclusions.length, records_scanned: snapshot.records.length, records_with_score: scored.length, records_selected: awards.length, serialized_characters: JSON.stringify(awards).length, limits: { concepts: 16, phrases: 8, exclusions: 8, records: 24, abstract_characters_per_record: 800, serialized_characters: 18000 } }, awards }) });
      return;
    }
    if (requestUrl.pathname === "/awards/snapshots/page" && request.method() === "POST") {
      snapshotPageCallCount += 1;
      if (snapshotPageFailAtCalls.includes(snapshotPageCallCount)) {
        await route.fulfill({ status: 503, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "source_unavailable" } }) });
        return;
      }
      if (snapshotPageCallCount === Number(snapshotPageExpireAtCall)) {
        await route.fulfill({ status: 410, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "snapshot_expired" } }) });
        return;
      }
      if (Number(snapshotPageDelayMs) > 0) await new Promise(resolve => setTimeout(resolve, Number(snapshotPageDelayMs)));
      const snapshot = snapshots.get(body.snapshot_id);
      if (!snapshot) {
        await route.fulfill({ status: 410, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "snapshot_expired" } }) });
        return;
      }
      if (body.page === 1 && body.facet?.type === "all" && failSnapshotInitialPageForTopics.includes(snapshot.request.criteria?.topic)) {
        await route.fulfill({
          status: 503,
          headers: corsHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ schema_version: 1, error: { code: "source_unavailable" } }),
        });
        return;
      }
      const view = snapshotView(snapshot, body.facet);
      const start = (body.page - 1) * body.page_size;
      const selected = view.records.slice(start, start + body.page_size);
      const pageCount = Math.max(1, Math.ceil(view.records.length / body.page_size));
      const payload = {
        ...publicSnapshot(snapshot),
        initial_batches: undefined,
        base_aggregate: view.facet.type === "all" ? undefined : snapshot.aggregate,
        aggregate: snapshotAggregate(view.records),
        facet: view.facet,
        exact_total: snapshot.completeness === "complete" ? view.records.length : null,
        at_least: view.records.length,
        pagination: { page: body.page, page_size: body.page_size, start: selected.length ? start + 1 : 0, end: start + selected.length, page_count: snapshot.completeness === "complete" ? pageCount : null, available_page_count: pageCount, has_previous: body.page > 1, has_next: body.page < pageCount },
        batches: ["NSF", "NIH", "DOE", "DOD"].map(source => ({ source, actual_added: selected.filter(record => record.source === source).length, results: selected.filter(record => record.source === source).map((record, index) => ({ ...record, snapshot_position: start + selected.indexOf(record) + 1 })) })).filter(batch => batch.results.length),
      };
      await route.fulfill({ status: 200, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(payload) });
      return;
    }
    if (requestUrl.pathname === "/awards/snapshots/batch" && request.method() === "POST") {
      snapshotBatchCallCount += 1;
      const batchDelay = Math.max(0, Number(snapshotBatchDelaysMs[snapshotBatchCallCount - 1]) || 0);
      if (batchDelay) await new Promise(resolve => setTimeout(resolve, batchDelay));
      if (snapshotBatchCallCount === Number(snapshotBatchExpireAtCall)) {
        await route.fulfill({ status: 410, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "snapshot_expired" } }) });
        return;
      }
      const snapshot = snapshots.get(body.snapshot_id);
      const view = snapshotView(snapshot, body.facet);
      const sourceRecords = view.records.filter(record => record.source === body.source);
      const results = sourceRecords.slice(body.offset, body.offset + 25);
      const sourceState = snapshot.sources.find(item => item.source === body.source);
      await route.fulfill({ status: 200, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, snapshot_id: snapshot.snapshot_id, source: body.source, offset: body.offset, actual_added: results.length, loaded_through: body.offset + results.length, source_total: sourceState.status === "complete" ? sourceRecords.length : null, additional_available: body.offset + results.length < sourceRecords.length, source_status: sourceState, facet: view.facet, results }) });
      return;
    }
    if (requestUrl.pathname === "/awards/snapshots/retry" && request.method() === "POST") {
      snapshotRetryCallCount += 1;
      if (snapshotRetryCallCount === Number(snapshotRetryExpireAtCall)) {
        await route.fulfill({ status: 410, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ schema_version: 1, error: { code: "snapshot_expired" } }) });
        return;
      }
      const snapshot = snapshots.get(body.snapshot_id);
      const alreadyPresent = snapshot.records.some(record => record.source === body.source);
      const records = alreadyPresent ? [...snapshot.records] : [...snapshot.records, templateFor(body.source)];
      const recoveredCount = records.filter(record => record.source === body.source).length;
      const successor = {
        ...snapshot,
        snapshot_id: String(++snapshotSequence).padStart(64, "c"),
        records,
        sources: snapshot.sources.map(source => source.source === body.source
          ? {
              ...source,
              status: "complete",
              result_count: recoveredCount,
              total_count: recoveredCount,
              ...(snapshot.mode === "program_officer" ? { contact_post_validation: {
                version: "program-contact-v1",
                source: body.source,
                display_name: snapshot.program_officer.display_name,
                contact_key: snapshot.program_officer.contact_key,
                returned_count: recoveredCount,
                retained_count: recoveredCount,
                rejected_count: 0,
                complete: true,
              } } : {}),
            }
          : source),
      };
      successor.completeness = successor.sources.every(source => source.status === "complete") ? "complete" : "partial";
      successor.exact_total = successor.completeness === "complete" ? successor.records.length : null;
      successor.aggregate = snapshotAggregate(successor.records);
      snapshots.set(successor.snapshot_id, successor);
      await route.fulfill({ status: 200, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ ...publicSnapshot(successor), retry: { source: body.source, status: "recovered", retained_sources: successor.request.sources.filter(source => source !== body.source) } }) });
      return;
    }
    const results = [];
    const sources = [];
    for (const source of body.sources) {
      const failed = source === "NSF" ? failNsf : source === "NIH" ? failNih : source === "DOE" ? failDoe : source === "DOD" ? failDod : false;
      const configuredFailureEntry = sourceFailuresByOffset[`${source}:${body.offset}`]
        || sourceFailures[source]
        || (failed ? { status: "unavailable", code: "source_unavailable" } : null);
      const configuredFailure = typeof configuredFailureEntry === "function"
        ? configuredFailureEntry({ source, offset: body.offset, body })
        : configuredFailureEntry;
      if (configuredFailure) {
        sources.push({
          source,
          status: configuredFailure.status || "unavailable",
          error: { code: configuredFailure.code || "source_unavailable" },
        });
      } else {
        const baseTemplate = source === "NSF" ? nsf : source === "NIH" ? nih : source === "DOE" ? doe : dod;
        const template = { ...baseTemplate, ...(awardOverridesBySource[source] || {}) };
        const configuredCount = resultCountBySourceOffset[`${source}:${body.offset}`] ?? (
          typeof resultCountPerSource === "object"
            ? resultCountPerSource[source]
            : source === "DOD" ? 0 : resultCountPerSource
        );
        const resultCount = Math.max(0, Math.min(Number(body.limit) || 1, Number(configuredCount) || 0));
        for (let index = 0; index < resultCount; index += 1) {
          const suffix = body.offset + index;
          const candidate = index === 0 && body.offset === 0 ? template : {
            ...template,
            award_id: `${template.award_id}-${suffix}`,
            source_record_ids: [`${template.source_record_ids[0]}-${suffix}`],
          };
          const year = Number(candidate.award_year);
          if (enforceYearFilters && (
            (body.criteria.year_start && (!Number.isInteger(year) || year < body.criteria.year_start))
            || (body.criteria.year_end && (!Number.isInteger(year) || year > body.criteria.year_end))
          )) continue;
          results.push(candidate);
        }
        const returnedCount = results.filter(result => result.source === source).length;
        sources.push({
          source,
          status: "ok",
          adapter_version: "1.1.0",
          cache: "miss",
          total_count: null,
          raw_record_count: resultCount,
          has_more: (hasMoreBySource[source] || hasMoreAtOffsets).includes(body.offset),
          result_count: returnedCount,
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
  await expect(page.locator("#query")).toBeEnabled();
  await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.ensureCatalogReady());
  await expect(page.locator("#catalog-pill")).toContainText(/current/, { timeout: 30_000 });
  await expect(page.locator("#find-funding")).toBeEnabled();
}

export async function openFundingFinderShell(page, { path = "/match_explorer.html" } = {}) {
  await page.goto(path);
  await expect(page.locator("#query")).toBeVisible();
  await expect(page.locator("#query")).toBeEnabled();
  await expect(page.locator("#catalog-pill")).toContainText("updated");
  await expect(page.locator("#catalog-pill")).not.toContainText("loads when needed");
  await expect.poll(() => page.evaluate(() => (
    performance.getEntriesByName("funding-shell-ready", "mark").length
  ))).toBe(1);
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
  await expect.poll(async () => {
    const status = page.locator("#potential-status");
    const text = (await status.textContent() || "").trim();
    if (/temporarily|needs the topic layer|unavailable/i.test(text)) return "settled";
    if (!(await status.evaluate(node => node.classList.contains("hidden")))) return "pending";
    const counts = (await page.locator("#result-tier-counts").textContent() || "").trim();
    return /\d+ strong match(?:es)? · \d+ potential match(?:es)?/i.test(counts)
      ? "settled"
      : "pending";
  }, { timeout: 30_000 }).toBe("settled");
}

export async function downloadText(page, selector) {
  if (selector === "#export-csv") await page.locator('[data-shell-menu="results"]').click();
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

export async function configurePersonalProvider(page, key, provider = "openai") {
  const setup = page.locator(".provider-setup");
  if (!(await setup.evaluate(details => details.open))) {
    await setup.locator(":scope > summary").click();
  }
  await page.locator("#k-provider").selectOption(provider);
  await expect(page.locator("#k-key")).toBeVisible();
  await page.locator("#k-key").fill(key);
}

export async function addDepartmentResearcher(page, researcherName) {
  const picker = page.locator("#researcher-picker");
  if (await picker.isHidden()) await page.locator("#add-researcher").click();
  await expect(page.locator("#faculty-search-status")).toContainText(/Search by name|Hajim facult/, { timeout: 30_000 });
  await page.locator("#faculty-search").fill(researcherName);
  const options = page.locator('#faculty-suggestions [role="option"]:not([aria-disabled="true"])');
  const option = options.filter({ hasText: researcherName }).first();
  await expect(option).toBeVisible({ timeout: 30_000 });
  await expect(option.locator("strong")).toHaveText(researcherName);
  const value = await option.getAttribute("data-faculty-id");
  const entries = page.locator("#pi-grid [data-member-entry]");
  const priorCount = await entries.count();
  await option.click();
  await expect(entries).toHaveCount(priorCount + 1);
  const addedButton = entries.nth(priorCount).locator(".pi-toggle");
  await expect(addedButton).toBeVisible();
  const label = (await addedButton.textContent()).trim();
  return { label, value };
}

export async function chooseInvestigator(page, name) {
  const option = page.locator("#ii-investigators option").filter({ hasText: name }).first();
  const value = await option.getAttribute("value");
  expect(value).toBeTruthy();
  await selectAwardFacet(page, "investigators", value);
}

export async function mockOpenAiBroadening(page, {
  chatResultAction = "none",
  planDelayMs = 0,
  planTerms = null,
} = {}) {
  const state = { calls: 0, candidate: null, requests: [], chatRequests: [] };
  await page.route("https://api.openai.com/v1/responses", async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders({ "Access-Control-Allow-Headers": "authorization,content-type" }) });
      return;
    }
    state.calls += 1;
    const body = request.postDataJSON();
    const input = JSON.parse(body.input);
    const operation = body.text?.format?.name;
    state.requests.push(input);
    let output;
    if (operation === "funding_search_plan_v1") {
      if (planDelayMs) await new Promise(resolve => setTimeout(resolve, planDelayMs));
      output = {
        interpretation: "Catalysis research broadened to adjacent reaction-engineering terminology.",
        search_terms: planTerms || [
          "reaction engineering",
          "heterogeneous catalyst design",
          "electrochemical carbon conversion",
          "carbon dioxide utilization",
          "catalytic reactor systems",
          "surface reaction kinetics",
          "sustainable chemical manufacturing",
          "porous catalytic materials",
          "low carbon fuels synthesis",
          "process intensification catalysis",
        ],
        avoid_terms: [],
      };
    } else if (operation === "funding_refinement_shortlist_v1") {
      state.candidate = input.candidate_opportunities.find(item => (
        item.workflow_tier === "strong" && item.ai_identified === true
      ));
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
    } else if (operation === "funding_result_chat_v1") {
      state.chatRequests.push(input);
      output = {
        answer: "The mock answer is grounded in the supplied bounded result context.",
        referenced_result_ids: input.current_results.slice(0, 8).map(item => item.id),
        citation_evidence_ids: [],
        result_action: chatResultAction,
        focus_result_ids: chatResultAction === "focus" && input.current_results[0]
          ? [input.current_results[0].id]
          : [],
      };
    } else {
      throw new Error(`Unexpected mocked OpenAI operation: ${operation}`);
    }
    await route.fulfill({
      status: 200,
      headers: corsHeaders({
        "Access-Control-Allow-Headers": "authorization,content-type",
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(openAiStructuredResponse(output)),
    });
  });
  return state;
}

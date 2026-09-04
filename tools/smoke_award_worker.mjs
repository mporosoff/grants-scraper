import { searchDodFromBrowser } from "../assets/dod-awards-browser.mjs";
import { DOD_SEARCH_URL } from "../workers/award-api/src/adapters/dod.js";

const baseUrl = String(process.env.AWARD_API_URL || "https://funding-finder-award-api.urochestercheme.workers.dev/").trim();
const origin = "https://mporosoff.github.io";

function failureDetail(payload) {
  const sources = Array.isArray(payload?.sources) ? payload.sources : [];
  const sourceDetails = sources.map(source => [
    source?.source,
    source?.status,
    source?.error?.code,
  ].filter(Boolean).join(":"))
    .filter(Boolean);
  return sourceDetails.join(", ") || payload?.error?.code || "unknown_error";
}

async function jsonRequest(path, options = {}) {
  const response = await fetch(new URL(path, baseUrl), {
    ...options,
    headers: { Origin: origin, ...(options.headers || {}) },
    signal: AbortSignal.timeout(45_000),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status} (${failureDetail(payload)})`);
  }
  return payload;
}

const health = await jsonRequest("health");
if (health.service !== "available" || health.schema_version !== 1) {
  throw new Error("Award Worker health contract did not match Phase 1.");
}
if (health.credentials_required !== false) {
  throw new Error("Award Worker unexpectedly reports a credential requirement.");
}
if (!["NSF", "NIH", "DOE", "DOD"].every(source => health.sources?.includes(source))) {
  throw new Error("Award Worker health did not advertise all four isolated sources.");
}
if (health.source_transports?.NSF !== "worker_proxy"
  || health.source_transports?.NIH !== "worker_proxy"
  || health.source_transports?.DOE !== "worker_proxy"
  || health.source_transports?.DOD !== "browser_direct_cors") {
  throw new Error("Award Worker health did not advertise the production source-transport boundary.");
}
if (health.institution_registry?.source !== "ROR") {
  throw new Error("Award Worker health did not advertise the ROR institution registry boundary.");
}
if (health.institution_registry?.adapter_version !== "1.3.0"
  || health.institution_resolution !== "curated-or-server-validated-ror") {
  throw new Error("Award Worker health did not advertise trusted Phase 3 ROR resolution.");
}
if (health.abuse_control?.ready !== true
  || health.abuse_control?.provider !== "cloudflare-durable-object"
  || health.abuse_control?.storage !== "sqlite"
  || health.abuse_control?.client_identity !== "hmac-derived"
  || health.abuse_control?.window_seconds !== 60
  || health.abuse_control?.limits?.award_source !== 12
  || health.abuse_control?.limits?.ror_search !== 60
  || health.abuse_control?.limits?.ror_resolution !== 20) {
  throw new Error("Award Worker health did not advertise the deployed abuse-control contract.");
}
if (health.normalized_paging?.NSF?.upstream_pages !== 12
  || health.normalized_paging?.NSF?.maximum_identity_queries !== 3
  || health.normalized_paging?.NIH?.upstream_page_size !== 100
  || health.normalized_paging?.DOE?.maximum_normalized_offset !== 100
  || health.normalized_paging?.DOE?.maximum_identity_queries !== 3
  || health.normalized_paging?.DOD?.upstream_page_size !== 25
  || health.normalized_paging?.DOD?.detail_cache_timeout_ms !== 2_000
  || health.normalized_paging?.DOD?.operation_budget_ms !== 100_000
  || health.normalized_paging?.DOD?.source_wrapper_timeout_ms !== 2_000
  || health.source_capabilities?.DOD?.award_scope !== "prime_assistance_awards_04_05_only") {
  throw new Error("Award Worker health did not advertise the bounded normalized paging contract.");
}

const institutions = await jsonRequest("institutions/search?query=MIT");
if (institutions.registry?.source !== "ROR"
  || institutions.registry?.status !== "available"
  || institutions.institutions?.[0]?.canonical_name !== "Massachusetts Institute of Technology"
  || institutions.institutions?.[0]?.id !== "https://ror.org/042nb2s44") {
  throw new Error("The bounded ROR acronym smoke did not resolve MIT deterministically.");
}

for (const body of [
  { sources: ["NSF"], criteria: { award_id: "2605508", institution: "University of Rochester", institution_id: "university-of-rochester" }, limit: 1, offset: 0 },
  { sources: ["NIH"], criteria: { core_project_number: "K12GM106997", institution: "University of Rochester", institution_id: "university-of-rochester" }, limit: 1, offset: 0 },
  { sources: ["DOE"], criteria: { award_id: "DE-SC0020230", institution: "University of Rochester", institution_id: "university-of-rochester" }, limit: 1, offset: 0 },
]) {
  const payload = await jsonRequest("awards/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (payload.schema_version !== 1 || payload.results.length !== 1) {
    throw new Error(`${body.sources[0]} exact-ID smoke did not return one normalized project.`);
  }
  if (payload.results[0].source !== body.sources[0] || !payload.results[0].official_award_url) {
    throw new Error(`${body.sources[0]} exact-ID smoke returned an invalid normalized record.`);
  }
}

const corsResponses = [];
const preflightResponse = await fetch(DOD_SEARCH_URL, {
  method: "OPTIONS",
  headers: {
    Origin: origin,
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
  },
  signal: AbortSignal.timeout(45_000),
});
const preflightOrigin = preflightResponse.headers.get("access-control-allow-origin");
const preflightMethods = new Set(
  String(preflightResponse.headers.get("access-control-allow-methods") || "")
    .split(",")
    .map(value => value.trim().toUpperCase())
    .filter(Boolean),
);
const preflightHeaders = new Set(
  String(preflightResponse.headers.get("access-control-allow-headers") || "")
    .split(",")
    .map(value => value.trim().toLowerCase())
    .filter(Boolean),
);
if (!preflightResponse.ok
  || !["*", origin].includes(preflightOrigin)
  || (!preflightMethods.has("POST") && !preflightMethods.has("*"))
  || (!preflightHeaders.has("content-type") && !preflightHeaders.has("*"))) {
  throw new Error("DOD browser-CORS preflight did not allow the USAspending JSON search request.");
}
const dodPayload = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
  limit: 1,
  fetchImpl: async (url, options = {}) => {
    const headers = new Headers(options.headers);
    headers.set("Origin", origin);
    const response = await fetch(url, { ...options, headers });
    corsResponses.push(response.headers.get("access-control-allow-origin"));
    return response;
  },
});
if (dodPayload.status
  || dodPayload.results?.length !== 1
  || dodPayload.results[0].schema_version !== 1
  || dodPayload.results[0].source !== "DOD"
  || dodPayload.results[0].award_id !== "FA9550261B195"
  || !/UNIVERSITY OF MARYLAND/i.test(dodPayload.results[0].institution?.name || "")
  || !["Project Grant", "Cooperative Agreement"].includes(dodPayload.results[0].funding_mechanism)
  || dodPayload.results[0].award_amount_basis !== "total_obligation"
  || !dodPayload.results[0].opportunity_numbers?.includes("NOFOAFRLAFOSR20250002")
  || !dodPayload.results[0].official_award_url.includes("usaspending.gov/award/")
  || !corsResponses.length
  || corsResponses.some(value => value !== "*")) {
  throw new Error("DOD browser-CORS exact-ID smoke did not return the expected USAspending obligation record.");
}

console.log("Award Worker health, abuse control, trusted ROR identity, normalized paging bounds, exact NSF/NIH/DOE Worker smokes, and the DoD browser-CORS preflight and exact-award smoke passed.");

const baseUrl = String(process.env.AWARD_API_URL || "https://funding-finder-award-api.urochestercheme.workers.dev/").trim();
const origin = "https://mporosoff.github.io";
const startedAt = new Date();
const requests = [];

async function jsonRequest(path, options = {}) {
  const requestStartedAt = performance.now();
  const response = await fetch(new URL(path, baseUrl), {
    ...options,
    headers: { Origin: origin, ...(options.headers || {}) },
    signal: AbortSignal.timeout(120_000),
  });
  const text = await response.text();
  const responseBytes = new TextEncoder().encode(text).byteLength;
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(path + " returned a non-JSON response with status " + response.status);
  }
  requests.push({
    path,
    status: response.status,
    duration_ms: Math.round((performance.now() - requestStartedAt) * 100) / 100,
    response_bytes: responseBytes,
    cf_ray: response.headers.get("cf-ray") || "",
  });
  if (!response.ok) throw new Error(path + " returned " + response.status + ": " + JSON.stringify(payload));
  return payload;
}

function post(path, body) {
  return jsonRequest(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const health = await jsonRequest("health");
const contract = health.complete_result_snapshots;
if (contract?.contract_version !== 1
  || contract.ordering_version !== "award-recency-v1"
  || contract.batch_ceiling_per_agency !== 25
  || JSON.stringify(contract.page_sizes) !== JSON.stringify([10, 25, 50])
  || contract.cache_scope !== "cloudflare-datacenter"
  || contract.failure_policy !== "successful-sources-retained-retry-creates-successor") {
  throw new Error("Unit B snapshot health contract is not active.");
}

const snapshot = await post("awards/snapshots", {
  sources: ["NSF", "NIH", "DOE", "DOD"],
  criteria: {
    institution: "University of Rochester",
    institution_id: "university-of-rochester",
    year_start: 2024,
    year_end: 2026,
  },
});

if (snapshot.snapshot_contract_version !== 1
  || !/^[0-9a-f]{64}$/.test(snapshot.snapshot_id || "")
  || snapshot.batch_ceiling_per_agency !== 25
  || !["complete", "partial", "unavailable"].includes(snapshot.completeness)
  || snapshot.sources?.length !== 4
  || snapshot.initial_batches?.length !== 4
  || snapshot.initial_batches.some(batch => batch.actual_added > 25)) {
  throw new Error("The broad-year Unit B snapshot did not satisfy its bounded public contract.");
}
if (snapshot.completeness === "complete" && snapshot.exact_total !== snapshot.at_least) {
  throw new Error("A complete Unit B snapshot did not expose a coherent exact total.");
}
if (snapshot.completeness !== "complete" && snapshot.exact_total !== null) {
  throw new Error("A non-complete Unit B snapshot exposed an exact total.");
}

const allFacet = { type: "all", key: "" };
const firstPage = await post("awards/snapshots/page", {
  snapshot_id: snapshot.snapshot_id,
  page: 1,
  page_size: 10,
  facet: allFacet,
});
const firstPageKeys = firstPage.batches.flatMap(batch => batch.results.map(item => item.source + ":" + item.award_id));
if (firstPage.pagination?.page !== 1
  || firstPage.pagination?.page_size !== 10
  || firstPageKeys.length > 10
  || new Set(firstPageKeys).size !== firstPageKeys.length
  || !Number.isInteger(firstPage.aggregate?.project_count)
  || !Array.isArray(firstPage.aggregate?.investigators)) {
  throw new Error("The Unit B direct first page was not bounded and deduplicated.");
}

let secondPageVerified = false;
if (firstPage.pagination?.available_page_count > 1) {
  const secondPage = await post("awards/snapshots/page", {
    snapshot_id: snapshot.snapshot_id,
    page: 2,
    page_size: 10,
    facet: allFacet,
  });
  const secondPageKeys = secondPage.batches.flatMap(batch => batch.results.map(item => item.source + ":" + item.award_id));
  if (secondPage.pagination?.page !== 2 || secondPageKeys.some(key => firstPageKeys.includes(key))) {
    throw new Error("The Unit B direct second page duplicated the first page.");
  }
  secondPageVerified = true;
}

let facetVerified = false;
const investigator = firstPage.aggregate.investigators[0];
if (investigator?.identity_key) {
  const facetPage = await post("awards/snapshots/page", {
    snapshot_id: snapshot.snapshot_id,
    page: 1,
    page_size: 25,
    facet: { type: "investigator", key: investigator.identity_key },
  });
  if (facetPage.facet?.key !== investigator.identity_key
    || facetPage.aggregate?.project_count !== investigator.projects
    || facetPage.aggregate.project_count > firstPage.aggregate.project_count) {
    throw new Error("The Unit B server-backed investigator facet was not coherent.");
  }
  facetVerified = true;
}
if (investigator?.identity_key && !facetVerified) {
  throw new Error("The Unit B live investigator facet check did not run.");
}

for (const sourceState of snapshot.sources) {
  const batch = await post("awards/snapshots/batch", {
    snapshot_id: snapshot.snapshot_id,
    source: sourceState.source,
    offset: 0,
    facet: allFacet,
  });
  if (batch.source !== sourceState.source || batch.actual_added > 25 || batch.batch_ceiling !== 25) {
    throw new Error(sourceState.source + " exceeded the Unit B per-action batch ceiling.");
  }
}

const expired = await fetch(new URL("awards/snapshots/page", baseUrl), {
  method: "POST",
  headers: { Origin: origin, "Content-Type": "application/json" },
  body: JSON.stringify({ snapshot_id: "f".repeat(64), page: 1, page_size: 10, facet: allFacet }),
  signal: AbortSignal.timeout(30_000),
});
const expiredPayload = await expired.json();
if (expired.status !== 410 || expiredPayload.error?.code !== "snapshot_expired") {
  throw new Error("The Unit B expired-snapshot recovery contract was not active.");
}

console.log(JSON.stringify({
  smoke: "unit_b_live_award_snapshot",
  started_at: startedAt.toISOString(),
  completed_at: new Date().toISOString(),
  worker_url: baseUrl,
  snapshot: {
    completeness: snapshot.completeness,
    exact_total: snapshot.exact_total,
    at_least: snapshot.at_least,
    source_states: snapshot.sources.map(source => ({
      source: source.source,
      status: source.status,
      result_count: source.result_count,
      upstream_pages: source.upstream_pages ?? null,
      upstream_queries: source.upstream_queries ?? null,
      safety_bound_reached: source.safety_bound_reached === true,
    })),
    second_page_verified: secondPageVerified,
    investigator_facet_verified: facetVerified,
    snapshot_expiry_verified: true,
  },
  client_observed_requests: requests,
  maximum_response_bytes: Math.max(...requests.map(request => request.response_bytes)),
}, null, 2));

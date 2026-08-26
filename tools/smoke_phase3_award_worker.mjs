const baseUrl = String(process.env.AWARD_API_URL || "https://funding-finder-award-api.urochestercheme.workers.dev/").trim();
const origin = "https://mporosoff.github.io";
const startedAt = new Date().toISOString();

async function jsonRequest(path, options = {}) {
  const response = await fetch(new URL(path, baseUrl), {
    ...options,
    headers: { Origin: origin, ...(options.headers || {}) },
    signal: AbortSignal.timeout(60_000),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(path + " returned " + response.status + ": " + JSON.stringify(payload));
  return payload;
}

const health = await jsonRequest("health");
if (health.institution_resolution !== "curated-or-server-validated-ror"
  || health.normalized_paging?.NSF?.upstream_pages !== 12
  || health.normalized_paging?.NIH?.upstream_pages !== 12
  || health.normalized_paging?.DOE?.upstream_pages !== 10) {
  throw new Error("Phase 3 health and paging bounds are not active.");
}

const registry = await jsonRequest("institutions/search?query=University%20of%20Rochester");
const rochester = registry.institutions?.find(item => item.id === "https://ror.org/022kthw22");
if (!rochester || rochester.canonical_name !== "University of Rochester") {
  throw new Error("The bounded live ROR check did not return the University of Rochester identity.");
}

const checks = [
  {
    label: "University of Rochester / Marc Porosoff / NSF",
    body: {
      sources: ["NSF"],
      criteria: {
        institution: "University of Rochester",
        institution_id: "university-of-rochester",
        pi: "Marc Porosoff",
      },
      limit: 10,
      offset: 0,
    },
  },
  {
    label: "University of Rochester / Marc D Porosoff / DOE",
    body: {
      sources: ["DOE"],
      criteria: {
        institution: "University of Rochester",
        institution_id: "university-of-rochester",
        pi: "Marc D Porosoff",
      },
      limit: 10,
      offset: 0,
    },
  },
  {
    label: "University of Rochester / NIH",
    body: {
      sources: ["NIH"],
      criteria: {
        institution: "University of Rochester",
        institution_id: "university-of-rochester",
      },
      limit: 1,
      offset: 0,
    },
  },
];

const evidence = [];
for (const check of checks) {
  const retrievedAt = new Date().toISOString();
  const payload = await jsonRequest("awards/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(check.body),
  });
  const source = payload.sources?.find(item => item.source === check.body.sources[0]);
  if (payload.schema_version !== 1 || source?.status !== "ok" || typeof source.has_more !== "boolean") {
    throw new Error(check.label + " did not return the normalized source contract.");
  }
  if (payload.results.length > check.body.limit
    || payload.results.some(item => item.source !== check.body.sources[0])) {
    throw new Error(check.label + " exceeded its bounded source-isolated result contract.");
  }
  evidence.push({
    label: check.label,
    retrieved_at: retrievedAt,
    result_count: payload.results.length,
    normalized_has_more: source.has_more,
    normalized_total_count: source.total_count ?? null,
    upstream_total_count: source.upstream_total_count ?? null,
    raw_record_count: source.raw_record_count ?? null,
    upstream_pages: source.upstream_pages ?? null,
    safety_bound_reached: source.safety_bound_reached === true,
    source_urls: [...new Set(payload.results.map(item => item.source_provenance?.source_url).filter(Boolean))],
    award_ids: payload.results.map(item => item.award_id),
    investigator_variants: [...new Set(payload.results.flatMap(item => (
      item.principal_investigators || []
    ).map(person => person.name)).filter(Boolean))],
  });
}

console.log(JSON.stringify({
  smoke: "phase3_live_award_worker",
  started_at: startedAt,
  completed_at: new Date().toISOString(),
  worker_url: baseUrl,
  ror_source_url: registry.registry?.source_url || "https://api.ror.org/v2/organizations",
  paging_bounds: health.normalized_paging,
  evidence,
}, null, 2));

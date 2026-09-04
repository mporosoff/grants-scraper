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

const programOfficerEvidenceContract = contract.program_officer_evidence;
if (programOfficerEvidenceContract?.endpoint !== "/awards/snapshots/evidence"
  || programOfficerEvidenceContract.plan_format !== "provider-concepts-v1"
  || programOfficerEvidenceContract.scoring_version !== "program-officer-evidence-v4"
  || programOfficerEvidenceContract.concept_coverage !== "all_provider_concepts_same_record"
  || programOfficerEvidenceContract.maximum_concepts !== 16
  || programOfficerEvidenceContract.maximum_phrases !== 8
  || programOfficerEvidenceContract.maximum_exclusions !== 8
  || programOfficerEvidenceContract.maximum_records !== 24
  || programOfficerEvidenceContract.matched_facet_limit !== 12
  || programOfficerEvidenceContract.abstract_characters_per_record !== 800
  || programOfficerEvidenceContract.indexed_abstract_characters_per_record !== 20_000
  || programOfficerEvidenceContract.serialized_characters !== 18_000) {
  throw new Error("The Program Officer evidence health contract is not active.");
}

const programOfficerVerification = {};
for (const source of ["NSF", "NIH", "DOE"]) {
  const sourceBatch = snapshot.initial_batches.find(batch => batch.source === source);
  const sourceAward = sourceBatch?.results.find(award => (
    award.program_contacts?.some(contact => contact.searchable_program_contact === true)
  ));
  const contact = sourceAward?.program_contacts?.find(item => item.searchable_program_contact === true);
  if (!contact?.source_display_name || !contact?.program_contact_key
    || contact.program_contact_identity !== `${source}:${contact.program_contact_key}`) {
    throw new Error(`${source} did not expose a usable source-native Program Officer contact in the bounded live fixture.`);
  }
  const snapshotsByPreset = {};
  for (const [preset, bounds] of [
    ["recent5", {}],
    ["all", {}],
    ["custom", { year_start: 2024, year_end: 2026 }],
  ]) {
    const value = await post("awards/snapshots", {
      sources: [source],
      criteria: {
        mode: "program_officer",
        program_officer: contact.source_display_name,
        program_contact_key: contact.program_contact_key,
        year_preset: preset,
        ...bounds,
      },
    });
    if (value.mode !== "program_officer"
      || value.program_officer?.source !== source
      || value.program_officer?.display_name !== contact.source_display_name
      || value.program_officer?.contact_key !== contact.program_contact_key
      || value.program_officer?.year_preset !== preset
      || !["complete", "partial", "unavailable"].includes(value.completeness)
      || (value.completeness === "complete") !== Number.isInteger(value.exact_total)
      || (value.completeness !== "complete" && value.exact_total !== null)) {
      throw new Error(`${source} ${preset} Program Officer snapshot metadata was incoherent.`);
    }
    if (preset === "recent5") {
      const snapshotYear = new Date(value.as_of).getUTCFullYear();
      if (value.program_officer.year_start !== snapshotYear - 4 || value.program_officer.year_end !== snapshotYear) {
        throw new Error(`${source} recent-five Program Officer years did not use the snapshot UTC clock.`);
      }
    } else if (preset === "all" && (value.program_officer.year_start !== null || value.program_officer.year_end !== null)) {
      throw new Error(`${source} all-years Program Officer snapshot retained a year bound.`);
    } else if (preset === "custom" && (value.program_officer.year_start !== 2024 || value.program_officer.year_end !== 2026)) {
      throw new Error(`${source} custom Program Officer years were not preserved.`);
    }
    snapshotsByPreset[preset] = value;
  }
  const recent = snapshotsByPreset.recent5;
  const validation = recent.sources[0]?.contact_post_validation;
  if (validation?.version !== "program-contact-v1"
    || validation.source !== source
    || validation.display_name !== contact.source_display_name
    || validation.contact_key !== contact.program_contact_key
    || validation.retained_count !== recent.at_least
    || validation.returned_count < validation.retained_count
    || validation.rejected_count !== validation.returned_count - validation.retained_count
    || validation.complete !== (recent.completeness === "complete")) {
    throw new Error(`${source} exact-contact post-validation evidence was incoherent.`);
  }
  let evidenceSeed = null;
  for (const pageSize of [10, 25, 50]) {
    const page = await post("awards/snapshots/page", {
      snapshot_id: recent.snapshot_id,
      page: 1,
      page_size: pageSize,
      facet: allFacet,
    });
    const records = page.batches.flatMap(batch => batch.results);
    if (page.pagination?.page_size !== pageSize || records.length > pageSize
      || records.some(award => !award.program_contacts?.some(item => (
        item.program_contact_key === contact.program_contact_key
        && item.program_contact_identity === `${source}:${contact.program_contact_key}`
      )))) {
      throw new Error(`${source} Program Officer page ${pageSize} violated exact membership or page bounds.`);
    }
    evidenceSeed ||= records[0] || null;
  }
  if (!evidenceSeed) throw new Error(`${source} recent-five Program Officer snapshot unexpectedly had no retained record.`);
  const evidenceConcept = (String(evidenceSeed.title || "").match(/[\p{L}\p{N}]{3,}/u) || ["research"])[0];
  const evidence = await post("awards/snapshots/evidence", {
    snapshot_id: recent.snapshot_id,
    retrieval_plan: { intent: "awards", concepts: [evidenceConcept], phrases: [evidenceConcept], exclusions: [] },
    plan_format: "provider-concepts-v1",
    limit: 24,
  });
  if (evidence.mode !== "program_officer"
    || evidence.retrieval?.records_scanned !== recent.at_least
    || evidence.retrieval?.records_selected < 1
    || evidence.retrieval.records_selected > 24
    || evidence.matched_aggregate?.project_count !== evidence.retrieval.records_with_score
    || evidence.matched_aggregate.investigators?.length > 12
    || evidence.matched_aggregate.institutions?.length > 12
    || evidence.matched_aggregate.programs?.length > 12
    || evidence.retrieval.serialized_characters > 18_000
    || evidence.awards.some(award => (award.abstract_excerpt || "").length > 800
      || !Number.isInteger(award.snapshot_position)
      || award.snapshot_position < 1
      || award.snapshot_position > recent.at_least)) {
    throw new Error(`${source} full-snapshot Program Officer evidence was not bounded and coherent.`);
  }
  programOfficerVerification[source] = {
    exact_source_display_name: contact.source_display_name,
    contact_key: contact.program_contact_key,
    contact_post_validation: recent.sources[0]?.contact_post_validation,
    recent5: { completeness: recent.completeness, exact_total: recent.exact_total, at_least: recent.at_least, year_start: recent.program_officer.year_start, year_end: recent.program_officer.year_end },
    all: { completeness: snapshotsByPreset.all.completeness, exact_total: snapshotsByPreset.all.exact_total, at_least: snapshotsByPreset.all.at_least },
    custom: { completeness: snapshotsByPreset.custom.completeness, exact_total: snapshotsByPreset.custom.exact_total, at_least: snapshotsByPreset.custom.at_least, year_start: 2024, year_end: 2026 },
    evidence: { records_scanned: evidence.retrieval.records_scanned, records_with_score: evidence.retrieval.records_with_score, records_selected: evidence.retrieval.records_selected, matched_facet_limit: evidence.matched_aggregate.facet_limit, serialized_characters: evidence.retrieval.serialized_characters },
  };
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
  program_officer_verification: programOfficerVerification,
  client_observed_requests: requests,
  maximum_response_bytes: Math.max(...requests.map(request => request.response_bytes)),
}, null, 2));

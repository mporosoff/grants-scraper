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

export function mockAwards(target, {
  awardOverridesBySource = {},
  failDoe = false,
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
  snapshotPageExpireAtCall = 0,
  snapshotPageFailAtCalls = [],
  snapshotBatchExpireAtCall = 0,
  snapshotBatchDelaysMs = [],
  snapshotRetryExpireAtCall = 0,
  failSnapshotCreateForTopics = [],
  failSnapshotInitialPageForTopics = [],
  enforceYearFilters = false,
  sourceFailures = {},
  sourceFailuresByOffset = {},
} = {}) {
  const calls = [];
  const snapshots = new Map();
  let snapshotSequence = 0;
  let snapshotPageCallCount = 0;
  let snapshotBatchCallCount = 0;
  let snapshotRetryCallCount = 0;
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
              adapter_version: "1.2.0",
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
          registry: { source: "ROR", status: "available", adapter_version: "1.2.0", license: "CC0-1.0", cache: "miss" },
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
    const templateFor = source => ({ ...(source === "NSF" ? nsf : source === "NIH" ? nih : doe), ...(awardOverridesBySource[source] || {}) });
    const snapshotAggregate = records => {
      const people = new Map();
      const programs = new Map();
      const years = new Map();
      const agencyTotals = new Map([["NSF", 0], ["NIH", 0], ["DOE", 0]]);
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
      });
      const orderedYears = [...years.entries()].sort(([left], [right]) => left - right);
      return {
        project_count: records.length,
        investigator_count: people.size,
        program_count: programs.size,
        year_start: orderedYears[0]?.[0] || null,
        year_end: orderedYears.at(-1)?.[0] || null,
        represented_years: orderedYears.map(([year, projects]) => ({ year, projects })),
        agency_totals: [...agencyTotals].map(([source, projects]) => ({ source, projects })),
        investigators: [...people.values()],
        programs: [...programs.values()],
        ordered_refs: records.map((record, index) => ({ position: index + 1, evidence_id: `${record.source}:${record.award_id}`, source: record.source, award_id: record.award_id, title: record.title, award_year: record.award_year })),
      };
    };
    const publicSnapshot = snapshot => ({
      schema_version: 1,
      snapshot_contract_version: 1,
      snapshot_id: snapshot.snapshot_id,
      query_id: snapshot.query_id,
      as_of: snapshot.as_of,
      ordering_version: "award-recency-v1",
      batch_ceiling_per_agency: 25,
      request: snapshot.request,
      completeness: snapshot.completeness,
      exact_total: snapshot.exact_total,
      at_least: snapshot.records.length,
      recency_order: snapshot.completeness === "complete" ? "verified_most_recent_to_older" : "available_snapshot_recent_to_older",
      sources: snapshot.sources,
      base_aggregate: snapshot.aggregate,
      initial_batches: snapshot.request.sources.map(source => {
        const results = snapshot.records.filter(record => record.source === source).slice(0, 25);
        const sourceState = snapshot.sources.find(item => item.source === source);
        return { schema_version: 1, snapshot_id: snapshot.snapshot_id, query_id: snapshot.query_id, ordering_version: "award-recency-v1", batch_ceiling: 25, source, offset: 0, actual_added: results.length, loaded_through: results.length, source_total: sourceState.status === "complete" ? sourceState.result_count : null, additional_available: results.length < sourceState.result_count, source_status: sourceState, facet: { type: "all", key: "", label: "All awards" }, results };
      }),
    });
    const snapshotView = (snapshot, facet) => {
      if (!facet || facet.type === "all") return { facet: { type: "all", key: "", label: "All awards" }, records: snapshot.records };
      const groups = facet.type === "investigator" ? snapshot.aggregate.investigators : snapshot.aggregate.programs;
      const group = groups.find(item => (facet.type === "investigator" ? item.identity_key : item.key) === facet.key);
      const allowed = new Set(group?.award_keys || []);
      return { facet: { type: facet.type, key: facet.key, label: facet.type === "investigator" ? group?.name : group?.label }, records: snapshot.records.filter(record => allowed.has(`${record.source}:${record.award_id}`)) };
    };
    if (requestUrl.pathname === "/awards/snapshots" && request.method() === "POST") {
      if (failSnapshotCreateForTopics.includes(body.criteria?.topic)) {
        await route.fulfill({
          status: 503,
          headers: corsHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ schema_version: 1, error: { code: "source_unavailable" } }),
        });
        return;
      }
      const sources = body.sources;
      const records = [];
      const sourceStates = [];
      for (const source of sources) {
        const failed = source === "NSF" ? failNsf : source === "NIH" ? failNih : failDoe;
        const configuredFailure = sourceFailures[source] || (failed ? { status: "unavailable", code: "source_unavailable" } : null);
        if (configuredFailure) {
          sourceStates.push({ source, status: configuredFailure.status || "unavailable", result_count: 0, total_count: null, error: { code: configuredFailure.code || "source_unavailable" } });
          continue;
        }
        const template = templateFor(source);
        const configuredCount = typeof resultCountPerSource === "object" ? resultCountPerSource[source] : resultCountPerSource;
        const count = Math.max(0, Number(configuredCount) || 0);
        for (let index = 0; index < count; index += 1) records.push(index === 0 ? template : { ...template, award_id: `${template.award_id}-${index}`, source_record_ids: [`${template.source_record_ids[0]}-${index}`] });
        const partial = Array.isArray(hasMoreBySource[source]) ? hasMoreBySource[source].length > 0 : Boolean(hasMoreBySource[source]);
        sourceStates.push({ source, status: partial ? "safety_bounded" : "complete", result_count: count, total_count: partial ? null : count, at_least: count, safety_bound_reached: partial, adapter_version: "1.1.0", retrieved_at: retrievedAt });
      }
      const complete = sourceStates.every(source => source.status === "complete");
      const snapshotId = String(++snapshotSequence).padStart(64, "a");
      const snapshot = { snapshot_id: snapshotId, query_id: String(snapshotSequence).padStart(64, "b"), as_of: retrievedAt, request: { sources, criteria: body.criteria }, records, sources: sourceStates, completeness: complete ? "complete" : records.length ? "partial" : "unavailable", exact_total: complete ? records.length : null };
      snapshot.aggregate = snapshotAggregate(records);
      snapshots.set(snapshotId, snapshot);
      await route.fulfill({ status: 200, headers: corsHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(publicSnapshot(snapshot)) });
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
        batches: ["NSF", "NIH", "DOE"].map(source => ({ source, actual_added: selected.filter(record => record.source === source).length, results: selected.filter(record => record.source === source).map((record, index) => ({ ...record, snapshot_position: start + selected.indexOf(record) + 1 })) })).filter(batch => batch.results.length),
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
          ? { ...source, status: "complete", result_count: recoveredCount, total_count: recoveredCount }
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
      const failed = source === "NSF" ? failNsf : source === "NIH" ? failNih : failDoe;
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

export async function chooseInvestigator(page, name) {
  const option = page.locator("#ii-investigators option").filter({ hasText: name }).first();
  const value = await option.getAttribute("value");
  expect(value).toBeTruthy();
  await page.locator("#ii-investigators").selectOption(value);
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

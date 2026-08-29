import { AWARD_SCHEMA_VERSION, cleanText } from "./contract.js";
import { AwardSourceError } from "./http.js";
import { institutionFromRor, resolveInstitution } from "./institutions.js";
import { ROR_ADAPTER_VERSION, resolveRorOrganization, searchRor } from "./ror.js";
import { DOE_ADAPTER_VERSION, DOE_MAX_RESULTS, searchDoe } from "./adapters/doe.js";
import { NIH_ADAPTER_VERSION, searchNih } from "./adapters/nih.js";
import { NSF_ADAPTER_VERSION, searchNsf } from "./adapters/nsf.js";
import { AwardRateLimiter } from "./rate-limit.js";
import {
  AWARD_ORDERING_VERSION,
  SNAPSHOT_BATCH_SIZE,
  SNAPSHOT_PAGE_SIZES,
  buildAwardSnapshot,
  publicSnapshot,
  snapshotPage,
  snapshotSourceBatch,
} from "./snapshot.js";
import { federalFiscalYear } from "./year-filter.js";

const MAX_REQUEST_BYTES = 16_384;
const MAX_OFFSET = 1_000;
const MAX_YEAR_SPAN = 50;
const RATE_LIMIT_WINDOW_SECONDS = 60;
const RATE_LIMIT_HEALTH_TIMEOUT_MS = 2_000;
const WORKER_RESOURCE_BUDGET = Object.freeze({
  target_plan: "workers-paid",
  configured_cpu_ms: 1_000,
  memory_mb: 128,
  platform_subrequests_per_request: 10_000,
  maximum_snapshot_create_subrequests: 50,
  maximum_snapshot_create_cache_api_calls: 10,
  maximum_snapshot_create_upstream_and_guard_subrequests: 40,
  maximum_snapshot_create_subrequests_without_ror_resolution: 46,
});
const PRODUCTION_ORIGIN = "https://mporosoff.github.io";
const SOURCE_NAMES = ["NSF", "NIH", "DOE"];
const ADAPTER_VERSIONS = {
  NSF: NSF_ADAPTER_VERSION,
  NIH: NIH_ADAPTER_VERSION,
  DOE: DOE_ADAPTER_VERSION,
};
const SEARCH_FIELDS = [
  "award_id",
  "core_project_number",
  "opportunity_number",
  "program",
  "program_office",
  "program_codes",
  "topic",
  "institution_id",
  "institution",
  "pi",
  "program_officer",
];
const CRITERIA_FIELDS = [...SEARCH_FIELDS, "year_start", "year_end"];
const SNAPSHOT_ID_PATTERN = /^[a-f0-9]{64}$/;
const SNAPSHOT_PATHS = new Set([
  "/awards/snapshots",
  "/awards/snapshots/page",
  "/awards/snapshots/batch",
  "/awards/snapshots/retry",
]);

function allowedOrigin(value) {
  if (!value) return true;
  if (value === PRODUCTION_ORIGIN) return true;
  try {
    const url = new URL(value);
    return url.protocol === "http:"
      && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname);
  } catch {
    return false;
  }
}

function responseHeaders(origin, extra = {}) {
  return {
    ...(origin ? { "Access-Control-Allow-Origin": origin } : {}),
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    Vary: "Origin",
    ...extra,
  };
}

function json(origin, status, payload, extra = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: responseHeaders(origin, extra),
  });
}

function error(origin, status, code, extra = {}) {
  return json(origin, status, { error: { code } }, extra);
}

function boundedInteger(value, { minimum = 1, maximum = Number.MAX_SAFE_INTEGER } = {}) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= minimum && number <= maximum ? number : null;
}

function serviceConfig(env) {
  const config = {
    enabled: String(env?.AWARD_API_ENABLED || "").toLowerCase() === "true",
    cacheTtl: boundedInteger(env?.CACHE_TTL_SECONDS, { minimum: 60, maximum: 86_400 }),
    maxResults: boundedInteger(env?.MAX_SOURCE_RESULTS, { minimum: 1, maximum: 25 }),
    awardSourceLimit: boundedInteger(env?.AWARD_SOURCE_RATE_LIMIT, { minimum: 1, maximum: 120 }),
    rorSearchLimit: boundedInteger(env?.ROR_SEARCH_RATE_LIMIT, { minimum: 1, maximum: 240 }),
    rorResolveLimit: boundedInteger(env?.ROR_RESOLVE_RATE_LIMIT, { minimum: 1, maximum: 120 }),
    rateLimitSecret: Boolean(String(env?.AWARD_RATE_LIMIT_SECRET || "")),
    rateLimitBinding: Boolean(
      env?.AWARD_RATE_LIMITER
      && typeof env.AWARD_RATE_LIMITER.idFromName === "function"
      && typeof env.AWARD_RATE_LIMITER.get === "function",
    ),
  };
  config.valid = Boolean(
    config.enabled && config.cacheTtl && config.maxResults
    && config.awardSourceLimit && config.rorSearchLimit && config.rorResolveLimit
    && config.rateLimitSecret && config.rateLimitBinding,
  );
  return config;
}

function exactKeys(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

async function parseBody(request) {
  if (!String(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) {
    throw Object.assign(new Error("content type"), { status: 415, code: "json_required" });
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_REQUEST_BYTES) {
    throw Object.assign(new Error("size"), { status: 413, code: "request_too_large" });
  }
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_REQUEST_BYTES) {
    throw Object.assign(new Error("size"), { status: 413, code: "request_too_large" });
  }
  try {
    return JSON.parse(text);
  } catch {
    throw Object.assign(new Error("json"), { status: 400, code: "invalid_json" });
  }
}

function normalizedString(value, maximum) {
  if (typeof value !== "string") return null;
  const text = value.replace(/\s+/g, " ").trim();
  return text && text.length <= maximum ? text : null;
}

function validateCriteria(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  if (Object.keys(value).some(key => !CRITERIA_FIELDS.includes(key))) return null;
  const criteria = {};
  const limits = {
    award_id: 40,
    core_project_number: 30,
    opportunity_number: 80,
    program: 160,
    program_office: 40,
    topic: 500,
    institution_id: 100,
    institution: 300,
    pi: 160,
    program_officer: 160,
  };
  for (const field of SEARCH_FIELDS) {
    if (!(field in value)) continue;
    if (field === "program_codes") {
      if (!Array.isArray(value[field]) || value[field].length < 1 || value[field].length > 24) return null;
      const codes = value[field].map(code => normalizedString(code, 12)?.toUpperCase());
      if (codes.some(code => !code || !/^[A-Z0-9]+$/.test(code))) return null;
      criteria[field] = [...new Set(codes)];
      continue;
    }
    const text = normalizedString(value[field], limits[field]);
    if (!text) return null;
    criteria[field] = ["core_project_number", "opportunity_number"].includes(field)
      ? text.toUpperCase()
      : text;
  }
  for (const field of ["year_start", "year_end"]) {
    if (!(field in value)) continue;
    const year = boundedInteger(value[field], { minimum: 1989, maximum: 2100 });
    if (!year) return null;
    criteria[field] = year;
  }
  if (!SEARCH_FIELDS.some(field => field in criteria)) return null;
  if (criteria.program && criteria.program_codes) return null;
  if (criteria.year_start && criteria.year_end) {
    if (criteria.year_end < criteria.year_start || criteria.year_end - criteria.year_start + 1 > MAX_YEAR_SPAN) {
      return null;
    }
  }
  if (criteria.award_id && !/^[A-Za-z0-9-]+$/.test(criteria.award_id)) return null;
  if (criteria.core_project_number && !/^[A-Z0-9]+$/.test(criteria.core_project_number)) return null;
  if (criteria.opportunity_number && !/^[A-Z0-9-]+$/.test(criteria.opportunity_number)) return null;
  if (criteria.program_office && !/^SC-\d+(?:\.\d+)?$/i.test(criteria.program_office)) return null;
  const institution = resolveInstitution({ id: criteria.institution_id, name: criteria.institution });
  if ((criteria.institution || criteria.institution_id) && !institution) {
    if (!criteria.institution || !/^https:\/\/ror\.org\/0[a-z0-9]{8}$/i.test(criteria.institution_id || "")) return null;
  }
  return {
    publicCriteria: criteria,
    resolvedCriteria: { ...criteria, ...(institution ? { _institution: institution } : {}) },
    institutionRequest: (criteria.institution || criteria.institution_id)
      ? { id: criteria.institution_id, name: criteria.institution, resolved: institution }
      : null,
  };
}

function validateRequest(body, config) {
  if (!exactKeys(body, ["sources", "criteria", "limit", "offset"])) return null;
  if (!Array.isArray(body.sources) || body.sources.length < 1 || body.sources.length > SOURCE_NAMES.length) return null;
  const sources = body.sources.map(value => String(value || "").toUpperCase());
  if (new Set(sources).size !== sources.length || sources.some(source => !SOURCE_NAMES.includes(source))) return null;
  const maximumLimit = sources.includes("DOE")
    ? Math.min(config.maxResults, DOE_MAX_RESULTS)
    : config.maxResults;
  const limit = boundedInteger(body.limit, { maximum: maximumLimit });
  const offset = boundedInteger(body.offset, { minimum: 0, maximum: MAX_OFFSET });
  const criteria = validateCriteria(body.criteria);
  if (!limit || offset === null || !criteria) return null;
  if (criteria.publicCriteria.program_office && (sources.length !== 1 || sources[0] !== "DOE")) return null;
  return { sources, limit, offset, ...criteria };
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function hmacSha256Hex(value, secret) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const digest = await crypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(String(value)),
  );
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function clientAddress(request) {
  return String(
    request.headers.get("cf-connecting-ip")
    || request.headers.get("x-forwarded-for")
    || "unknown",
  ).split(",")[0].trim().slice(0, 120);
}

async function createUpstreamGuard(request, env, current) {
  const actor = await hmacSha256Hex(clientAddress(request), env.AWARD_RATE_LIMIT_SECRET);
  const namespace = env.AWARD_RATE_LIMITER;
  const stub = namespace.get(namespace.idFromName(actor));
  return async (bucket, limit) => {
    let response;
    try {
      response = await stub.fetch("https://award-rate-limit.internal/consume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bucket,
          limit,
          window_seconds: RATE_LIMIT_WINDOW_SECONDS,
          now: current.getTime(),
        }),
      });
    } catch {
      throw new AwardSourceError("abuse_control_unavailable");
    }
    const result = await response.json().catch(() => null);
    if (!response.ok || typeof result?.success !== "boolean") {
      throw new AwardSourceError("abuse_control_unavailable");
    }
    if (!result.success) {
      throw new AwardSourceError("rate_limited", "rate_limited");
    }
    return true;
  };
}

async function probeRateLimiter(env, timeoutMs = RATE_LIMIT_HEALTH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const namespace = env.AWARD_RATE_LIMITER;
    const stub = namespace.get(namespace.idFromName("award-rate-limiter-health"));
    const response = await stub.fetch(new Request("https://award-rate-limit.internal/health", {
      method: "GET",
      signal: controller.signal,
    }));
    const result = await response.json();
    return response.ok && result?.ready === true && result?.storage === "sqlite";
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function sourceCacheRequest(source, request, asOf) {
  const cacheIdentity = {
    source,
    adapter_version: ADAPTER_VERSIONS[source],
    criteria: request.publicCriteria,
    limit: request.limit,
    offset: request.offset,
    scan_all: request.scanAll === true,
    include_abstracts: request.includeAbstracts !== false,
  };
  if (source === "NIH" && request.publicCriteria.year_start && !request.publicCriteria.year_end) {
    cacheIdentity.nih_fiscal_year_ceiling = federalFiscalYear(asOf);
  }
  const identity = await sha256Hex(stableJson(cacheIdentity));
  return new Request(`https://award-cache.internal/v1/${source.toLowerCase()}/${identity}`);
}

async function runSource({ source, request, fetchImpl, cache, cacheTtl, asOf, guard = null, rateLimit = null }) {
  const key = await sourceCacheRequest(source, request, asOf);
  if (cache) {
    try {
      const cached = await cache.match(key);
      if (cached) {
        const payload = await cached.json();
        if (payload?.source === source && Array.isArray(payload.results)) return { ...payload, cache: "hit" };
      }
    } catch {
      // A cache outage must not make either official source unavailable.
    }
  }
  if (guard) await guard(`award:${source}`, rateLimit);
  const options = {
    limit: request.limit,
    offset: request.offset,
    now: () => new Date(asOf),
    scanAll: request.scanAll === true,
    includeAbstracts: request.includeAbstracts !== false,
  };
  const adapters = { NSF: searchNsf, NIH: searchNih, DOE: searchDoe };
  const payload = await adapters[source](fetchImpl, request.resolvedCriteria, options);
  if (cache) {
    try {
      await cache.put(key, new Response(JSON.stringify(payload), {
        headers: {
          "Cache-Control": `public, max-age=${cacheTtl}`,
          "Content-Type": "application/json; charset=utf-8",
        },
      }));
    } catch {
      // Successful live source data remains usable when cache writes fail.
    }
  }
  return { ...payload, cache: cache ? "miss" : "bypass" };
}

async function runInstitutionSearch({ query, fetchImpl, cache, cacheTtl, guard = null, rateLimit = null }) {
  const identity = await sha256Hex(stableJson({
    source: "ROR",
    adapter_version: ROR_ADAPTER_VERSION,
    query: query.toLocaleLowerCase("en-US"),
  }));
  const key = new Request(`https://award-cache.internal/v1/ror/${identity}`);
  if (cache) {
    try {
      const cached = await cache.match(key);
      if (cached) {
        const payload = await cached.json();
        if (payload?.registry?.source === "ROR" && Array.isArray(payload.institutions)) {
          return { ...payload, registry: { ...payload.registry, cache: "hit" } };
        }
      }
    } catch {
      // Registry discovery can continue if the shared cache is unavailable.
    }
  }
  if (guard) await guard("ror:search", rateLimit);
  const result = await searchRor(fetchImpl, query);
  const payload = {
    schema_version: AWARD_SCHEMA_VERSION,
    query: result.query,
    institutions: result.institutions,
    registry: {
      source: result.source,
      status: "available",
      adapter_version: result.adapter_version,
      source_url: result.source_url,
      license: result.license,
      cache: cache ? "miss" : "bypass",
    },
  };
  if (cache) {
    try {
      await cache.put(key, new Response(JSON.stringify(payload), {
        headers: {
          "Cache-Control": `public, max-age=${cacheTtl}`,
          "Content-Type": "application/json; charset=utf-8",
        },
      }));
    } catch {
      // A cache write failure must not discard a valid registry response.
    }
  }
  return payload;
}

async function runInstitutionResolution({ request, fetchImpl, cache, cacheTtl, guard = null, rateLimit = null }) {
  if (request?.resolved) return request.resolved;
  if (!request?.id || !request?.name) return null;
  const identity = await sha256Hex(stableJson({
    source: "ROR-identity",
    adapter_version: ROR_ADAPTER_VERSION,
    id: request.id,
  }));
  const key = new Request(`https://award-cache.internal/v1/ror-identity/${identity}`);
  let organization = null;
  if (cache) {
    try {
      const cached = await cache.match(key);
      if (cached) organization = await cached.json();
    } catch {
      // Exact ROR resolution can continue if the shared cache is unavailable.
    }
  }
  if (!organization) {
    if (guard) await guard("ror:resolve", rateLimit);
    organization = await resolveRorOrganization(fetchImpl, request.id);
    if (cache) {
      try {
        await cache.put(key, new Response(JSON.stringify(organization), {
          headers: {
            "Cache-Control": `public, max-age=${cacheTtl}`,
            "Content-Type": "application/json; charset=utf-8",
          },
        }));
      } catch {
        // A cache write failure must not discard a validated ROR identity.
      }
    }
  }
  return institutionFromRor(organization, request.name);
}

function sourceSummary(payload) {
  return {
    source: payload.source,
    status: "ok",
    adapter_version: payload.adapter_version,
    cache: payload.cache,
    total_count: payload.total_count,
    raw_record_count: payload.raw_record_count,
    upstream_total_count: payload.upstream_total_count,
    upstream_pages: payload.upstream_pages,
    upstream_queries: payload.upstream_queries,
    safety_bound_reached: payload.safety_bound_reached === true,
    has_more: payload.has_more === true,
    result_count: payload.results.length,
    retrieved_at: payload.retrieved_at,
    ...(payload.year_filter ? { year_filter: payload.year_filter } : {}),
    ...(payload.health ? { health: payload.health } : {}),
  };
}

function sourceFailure(source, cause) {
  const sourceError = cause instanceof AwardSourceError
    ? cause
    : new AwardSourceError("source_unavailable");
  return {
    source,
    status: sourceError.kind === "unsupported" ? "unsupported" : "unavailable",
    error: { code: sourceError.code },
  };
}

function validateSnapshotCreate(body, config) {
  if (!exactKeys(body, ["sources", "criteria"])) return null;
  if (!Array.isArray(body.sources) || body.sources.length < 1 || body.sources.length > SOURCE_NAMES.length) return null;
  const sources = body.sources.map(value => String(value || "").toUpperCase());
  if (new Set(sources).size !== sources.length || sources.some(source => !SOURCE_NAMES.includes(source))) return null;
  const criteria = validateCriteria(body.criteria);
  if (!criteria) return null;
  if (criteria.publicCriteria.program_office && (sources.length !== 1 || sources[0] !== "DOE")) return null;
  return {
    sources,
    limit: Math.min(SNAPSHOT_BATCH_SIZE, config.maxResults),
    offset: 0,
    scanAll: true,
    includeAbstracts: false,
    ...criteria,
  };
}

function validateFacet(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value, ["type", "key"])) return null;
  const type = normalizedString(value.type, 20);
  const key = typeof value.key === "string" ? value.key.replace(/\s+/g, " ").trim().slice(0, 300) : null;
  if (!new Set(["all", "investigator", "program"]).has(type) || key === null) return null;
  if (type === "all" && key) return null;
  if (type !== "all" && !key) return null;
  return { type, key };
}

function validateSnapshotId(value) {
  const id = String(value || "").toLowerCase();
  return SNAPSHOT_ID_PATTERN.test(id) ? id : null;
}

function validateSnapshotPage(body) {
  if (!exactKeys(body, ["snapshot_id", "page", "page_size", "facet"])) return null;
  const snapshotId = validateSnapshotId(body.snapshot_id);
  const page = boundedInteger(body.page, { minimum: 1, maximum: 100_000 });
  const pageSize = boundedInteger(body.page_size, { minimum: 1, maximum: 50 });
  const facet = validateFacet(body.facet);
  if (!snapshotId || !page || !SNAPSHOT_PAGE_SIZES.includes(pageSize) || !facet) return null;
  return { snapshotId, page, pageSize, facet };
}

function validateSnapshotBatch(body) {
  if (!exactKeys(body, ["snapshot_id", "source", "offset", "facet"])) return null;
  const snapshotId = validateSnapshotId(body.snapshot_id);
  const source = String(body.source || "").toUpperCase();
  const offset = boundedInteger(body.offset, { minimum: 0, maximum: 100_000 });
  const facet = validateFacet(body.facet);
  if (!snapshotId || !SOURCE_NAMES.includes(source) || offset === null || !facet) return null;
  return { snapshotId, source, offset, facet };
}

function validateSnapshotRetry(body) {
  if (!exactKeys(body, ["snapshot_id", "source"])) return null;
  const snapshotId = validateSnapshotId(body.snapshot_id);
  const source = String(body.source || "").toUpperCase();
  return snapshotId && SOURCE_NAMES.includes(source) ? { snapshotId, source } : null;
}

function snapshotCacheRequest(snapshotId) {
  return new Request(`https://award-snapshot.internal/v1/${snapshotId}`);
}

async function loadSnapshot(cache, snapshotId) {
  if (!cache) return null;
  try {
    const response = await cache.match(snapshotCacheRequest(snapshotId));
    if (!response) return null;
    const snapshot = await response.json();
    return snapshot?.snapshot_contract_version === 1 && snapshot?.snapshot_id === snapshotId
      && Array.isArray(snapshot?.awards) && snapshot?.source_metadata
      ? snapshot
      : null;
  } catch {
    return null;
  }
}

async function storeSnapshot(cache, snapshot, cacheTtl) {
  if (!cache) return false;
  const key = snapshotCacheRequest(snapshot.snapshot_id);
  try {
    await cache.put(key, new Response(JSON.stringify(snapshot), {
      headers: {
        "Cache-Control": `public, max-age=${cacheTtl}`,
        "Content-Type": "application/json; charset=utf-8",
        ETag: `"${snapshot.snapshot_id}"`,
      },
    }));
    const stored = await cache.match(key);
    return Boolean(stored);
  } catch {
    return false;
  }
}

function snapshotRequestIdentity(normalized, asOf) {
  const publicRequest = {
    sources: normalized.sources,
    criteria: normalized.publicCriteria,
    institution_identity: normalized.resolvedCriteria?._institution || null,
    source_adapter_versions: ADAPTER_VERSIONS,
    ordering_version: AWARD_ORDERING_VERSION,
    year_interpretation: {
      minimum_year: 1989,
      maximum_year: 2100,
      nih_federal_fiscal_year: normalized.sources.includes("NIH")
        && normalized.publicCriteria.year_start && !normalized.publicCriteria.year_end
        ? federalFiscalYear(asOf)
        : null,
    },
  };
  return { publicRequest, cacheIdentity: stableJson(publicRequest) };
}

async function runSnapshotSources({ normalized, fetchImpl, cache, cacheTtl, asOf, guard, rateLimit, onlySource = "" }) {
  const selectedSources = onlySource ? [onlySource] : normalized.sources;
  const request = {
    ...normalized,
    publicCriteria: normalized.publicCriteria,
    limit: normalized.limit || SNAPSHOT_BATCH_SIZE,
    offset: 0,
    scanAll: true,
    includeAbstracts: false,
  };
  const settled = await Promise.all(selectedSources.map(async source => {
    try {
      return await runSource({ source, request, fetchImpl, cache, cacheTtl, asOf, guard, rateLimit });
    } catch (cause) {
      return sourceFailure(source, cause);
    }
  }));
  return Object.fromEntries(selectedSources.map((source, index) => [source, settled[index]]));
}

async function resolveRequestInstitution({ normalized, fetchImpl, cache, cacheTtl, guard, rateLimit }) {
  if (!normalized.institutionRequest || normalized.institutionRequest.resolved) return normalized;
  const institution = await runInstitutionResolution({
    request: normalized.institutionRequest,
    fetchImpl,
    cache,
    cacheTtl,
    guard,
    rateLimit,
  });
  if (!institution) throw new AwardSourceError("invalid_request", "unsupported");
  normalized.resolvedCriteria = { ...normalized.resolvedCriteria, _institution: institution };
  return normalized;
}

export function createHandler({
  fetchImpl = fetch,
  cache = null,
  now = () => new Date(),
  rateLimitProbeTimeoutMs = RATE_LIMIT_HEALTH_TIMEOUT_MS,
} = {}) {
  return async function handle(request, env) {
    const origin = request.headers.get("origin") || "";
    if (!allowedOrigin(origin)) return error(origin, 403, "origin_not_allowed");
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: responseHeaders(origin) });
    const requestUrl = new URL(request.url);
    const path = requestUrl.pathname.replace(/\/+$/, "");
    const config = serviceConfig(env);
    if (path === "/health" && request.method === "GET") {
      const abuseControlReady = config.rateLimitBinding && config.rateLimitSecret
        ? await probeRateLimiter(env, rateLimitProbeTimeoutMs)
        : false;
      const serviceReady = config.valid && abuseControlReady;
      return json(origin, serviceReady ? 200 : 503, {
        service: serviceReady ? "available" : "unavailable",
        schema_version: AWARD_SCHEMA_VERSION,
        sources: SOURCE_NAMES,
        adapter_versions: ADAPTER_VERSIONS,
        institution_registry: { source: "ROR", adapter_version: ROR_ADAPTER_VERSION },
        institution_resolution: "curated-or-server-validated-ror",
        normalized_paging: {
          NSF: { upstream_pages: 12, upstream_page_size: 25, maximum_identity_queries: 3 },
          NIH: { upstream_pages: 12, upstream_page_size: 100 },
          DOE: { upstream_pages: 10, maximum_normalized_offset: 100, maximum_identity_queries: 3 },
        },
        complete_result_snapshots: {
          contract_version: 1,
          ordering_version: AWARD_ORDERING_VERSION,
          batch_ceiling_per_agency: SNAPSHOT_BATCH_SIZE,
          page_sizes: SNAPSHOT_PAGE_SIZES,
          cache_ttl_seconds: config.cacheTtl,
          cache_scope: "cloudflare-datacenter",
          failure_policy: "successful-sources-retained-retry-creates-successor",
          resource_budget: WORKER_RESOURCE_BUDGET,
        },
        abuse_control: {
          ready: abuseControlReady,
          provider: "cloudflare-durable-object",
          storage: "sqlite",
          client_identity: "hmac-derived",
          window_seconds: RATE_LIMIT_WINDOW_SECONDS,
          limits: {
            award_source: config.awardSourceLimit,
            ror_search: config.rorSearchLimit,
            ror_resolution: config.rorResolveLimit,
          },
        },
        cache_ttl_seconds: config.cacheTtl,
        credentials_required: false,
      });
    }
    if (!["/institutions/search", "/awards/search"].includes(path) && !SNAPSHOT_PATHS.has(path)) {
      return error(origin, 404, "not_found");
    }
    if (path === "/institutions/search" && request.method !== "GET") {
      return error(origin, 405, "method_not_allowed");
    }
    if (path === "/awards/search" && request.method !== "POST") {
      return error(origin, 405, "method_not_allowed");
    }
    if (SNAPSHOT_PATHS.has(path) && request.method !== "POST") {
      return error(origin, 405, "method_not_allowed");
    }
    if (!config.valid) return error(origin, 503, "service_unavailable");
    const current = now();
    let guard;
    try {
      guard = await createUpstreamGuard(request, env, current);
    } catch {
      return error(origin, 503, "service_unavailable");
    }
    if (path === "/institutions/search") {
      if ([...requestUrl.searchParams.keys()].some(key => key !== "query")) {
        return error(origin, 400, "invalid_request");
      }
      if (requestUrl.searchParams.getAll("query").length !== 1) return error(origin, 400, "invalid_request");
      const query = normalizedString(requestUrl.searchParams.get("query"), 120);
      if (!query || query.length < 2) return error(origin, 400, "invalid_request");
      const cacheStore = cache || globalThis.caches?.default || null;
      try {
        return json(origin, 200, await runInstitutionSearch({
          query,
          fetchImpl,
          cache: cacheStore,
          cacheTtl: config.cacheTtl,
          guard,
          rateLimit: config.rorSearchLimit,
        }));
      } catch (cause) {
        const sourceError = cause instanceof AwardSourceError
          ? cause
          : new AwardSourceError("source_unavailable");
        const rateLimited = sourceError.kind === "rate_limited";
        return json(origin, rateLimited ? 429 : sourceError.kind === "unsupported" ? 400 : 503, {
          schema_version: AWARD_SCHEMA_VERSION,
          query,
          institutions: [],
          registry: {
            source: "ROR",
            status: rateLimited ? "rate_limited" : "unavailable",
            adapter_version: ROR_ADAPTER_VERSION,
            error: { code: sourceError.code },
          },
        }, rateLimited ? { "Retry-After": String(RATE_LIMIT_WINDOW_SECONDS) } : {});
      }
    }
    if (SNAPSHOT_PATHS.has(path)) {
      let body;
      try {
        body = await parseBody(request);
      } catch (cause) {
        return error(origin, cause.status || 400, cause.code || "invalid_request");
      }
      const cacheStore = cache || globalThis.caches?.default || null;
      if (!cacheStore) return error(origin, 503, "snapshot_store_unavailable");
      if (path === "/awards/snapshots") {
        const normalized = validateSnapshotCreate(body, config);
        if (!normalized) return error(origin, 400, "invalid_request");
        try {
          await resolveRequestInstitution({
            normalized,
            fetchImpl,
            cache: cacheStore,
            cacheTtl: config.cacheTtl,
            guard,
            rateLimit: config.rorResolveLimit,
          });
        } catch (cause) {
          if (cause instanceof AwardSourceError && cause.kind === "rate_limited") {
            return error(origin, 429, "rate_limited", { "Retry-After": String(RATE_LIMIT_WINDOW_SECONDS) });
          }
          return error(origin, cause instanceof AwardSourceError && cause.kind === "unsupported" ? 400 : 503,
            cause instanceof AwardSourceError && cause.kind === "unsupported" ? "invalid_request" : "institution_registry_unavailable");
        }
        const asOf = current.toISOString();
        const identity = snapshotRequestIdentity(normalized, asOf);
        const queryId = await sha256Hex(identity.cacheIdentity);
        const snapshotId = await sha256Hex(stableJson({ query_id: queryId, as_of: asOf, ordering_version: AWARD_ORDERING_VERSION }));
        const sourcePayloads = await runSnapshotSources({
          normalized,
          fetchImpl,
          cache: cacheStore,
          cacheTtl: config.cacheTtl,
          asOf,
          guard,
          rateLimit: config.awardSourceLimit,
        });
        const snapshot = buildAwardSnapshot({
          snapshotId,
          queryId,
          asOf,
          request: identity.publicRequest,
          sourcePayloads,
        });
        snapshot.runtime_request = normalized;
        if (!await storeSnapshot(cacheStore, snapshot, config.cacheTtl)) {
          return error(origin, 503, "snapshot_store_unavailable");
        }
        return json(origin, 200, publicSnapshot(snapshot));
      }
      if (path === "/awards/snapshots/page") {
        const action = validateSnapshotPage(body);
        if (!action) return error(origin, 400, "invalid_request");
        const snapshot = await loadSnapshot(cacheStore, action.snapshotId);
        if (!snapshot) return error(origin, 410, "snapshot_expired");
        const payload = snapshotPage(snapshot, action);
        if (!payload) return error(origin, 400, "invalid_page_or_facet");
        payload.view_id = await sha256Hex(stableJson({
          query_id: snapshot.query_id,
          snapshot_id: snapshot.snapshot_id,
          facet: action.facet,
          page_size: action.pageSize,
          ordering_version: snapshot.ordering_version,
        }));
        return json(origin, 200, payload);
      }
      if (path === "/awards/snapshots/batch") {
        const action = validateSnapshotBatch(body);
        if (!action) return error(origin, 400, "invalid_request");
        const snapshot = await loadSnapshot(cacheStore, action.snapshotId);
        if (!snapshot) return error(origin, 410, "snapshot_expired");
        const payload = snapshotSourceBatch(snapshot, action);
        return payload ? json(origin, 200, payload) : error(origin, 400, "invalid_source_or_facet");
      }
      const action = validateSnapshotRetry(body);
      if (!action) return error(origin, 400, "invalid_request");
      const snapshot = await loadSnapshot(cacheStore, action.snapshotId);
      if (!snapshot) return error(origin, 410, "snapshot_expired");
      const normalized = snapshot.runtime_request;
      if (!normalized?.sources?.includes(action.source)) return error(origin, 400, "invalid_source");
      const priorSource = snapshot.sources.find(source => source.source === action.source);
      if (!priorSource || !["unavailable", "rate_limited"].includes(priorSource.status)) {
        return error(origin, 409, "source_not_retryable");
      }
      const successorAsOf = current.toISOString();
      const replacement = await runSnapshotSources({
        normalized,
        fetchImpl,
        cache: cacheStore,
        cacheTtl: config.cacheTtl,
        asOf: successorAsOf,
        guard,
        rateLimit: config.awardSourceLimit,
        onlySource: action.source,
      });
      if (replacement[action.source]?.status) {
        const rateLimited = ["rate_limited", "source_rate_limited"].includes(replacement[action.source].error?.code);
        return json(origin, rateLimited ? 429 : 503, {
          ...publicSnapshot(snapshot),
          retry: replacement[action.source],
        }, rateLimited ? { "Retry-After": String(RATE_LIMIT_WINDOW_SECONDS) } : {});
      }
      const sourcePayloads = Object.fromEntries(snapshot.request.sources.map(source => {
        if (replacement[source]) return [source, replacement[source]];
        const metadata = snapshot.source_metadata[source] || {};
        const results = snapshot.awards.filter(award => String(award?.source || "").toUpperCase() === source);
        return [source, metadata.status ? metadata : { ...metadata, results }];
      }));
      const successorId = await sha256Hex(stableJson({
        predecessor: snapshot.snapshot_id,
        source: action.source,
        recovered_at: successorAsOf,
      }));
      const successorIdentity = snapshotRequestIdentity(normalized, successorAsOf);
      const successor = buildAwardSnapshot({
        snapshotId: successorId,
        queryId: await sha256Hex(successorIdentity.cacheIdentity),
        asOf: successorAsOf,
        request: successorIdentity.publicRequest,
        sourcePayloads,
      });
      successor.runtime_request = normalized;
      successor.predecessor_snapshot_id = snapshot.snapshot_id;
      if (!await storeSnapshot(cacheStore, successor, config.cacheTtl)) {
        return error(origin, 503, "snapshot_store_unavailable");
      }
      return json(origin, 200, {
        ...publicSnapshot(successor),
        retry: { source: action.source, status: "recovered", retained_sources: snapshot.request.sources.filter(source => source !== action.source) },
      });
    }
    let body;
    try {
      body = await parseBody(request);
    } catch (cause) {
      return error(origin, cause.status || 400, cause.code || "invalid_request");
    }
    const normalized = validateRequest(body, config);
    if (!normalized) return error(origin, 400, "invalid_request");
    if (normalized.institutionRequest && !normalized.institutionRequest.resolved) {
      const cacheStore = cache || globalThis.caches?.default || null;
      try {
        const institution = await runInstitutionResolution({
          request: normalized.institutionRequest,
          fetchImpl,
          cache: cacheStore,
          cacheTtl: config.cacheTtl,
          guard,
          rateLimit: config.rorResolveLimit,
        });
        if (!institution) return error(origin, 400, "invalid_request");
        normalized.resolvedCriteria = { ...normalized.resolvedCriteria, _institution: institution };
      } catch (cause) {
        if (cause instanceof AwardSourceError && cause.kind === "rate_limited") {
          return error(origin, 429, "rate_limited", { "Retry-After": String(RATE_LIMIT_WINDOW_SECONDS) });
        }
        if (cause instanceof AwardSourceError && cause.kind === "unsupported") {
          return error(origin, 400, "invalid_request");
        }
        return error(origin, 503, "institution_registry_unavailable");
      }
    }
    const requestState = {
      sources: normalized.sources,
      criteria: normalized.publicCriteria,
      limit: normalized.limit,
      offset: normalized.offset,
    };
    const sourceRequest = { ...normalized, publicCriteria: normalized.publicCriteria };
    const cacheStore = cache || globalThis.caches?.default || null;
    const asOf = current.toISOString();
    const settled = await Promise.all(normalized.sources.map(async source => {
      try {
        return await runSource({
          source,
          request: sourceRequest,
          fetchImpl,
          cache: cacheStore,
          cacheTtl: config.cacheTtl,
          asOf,
          guard,
          rateLimit: config.awardSourceLimit,
        });
      } catch (cause) {
        return sourceFailure(source, cause);
      }
    }));
    const successful = settled.filter(item => item.status === undefined);
    const sources = settled.map(item => item.status === undefined ? sourceSummary(item) : item);
    const payload = {
      schema_version: AWARD_SCHEMA_VERSION,
      request: requestState,
      results: successful.flatMap(item => item.results),
      sources,
      pagination: { limit: normalized.limit, offset: normalized.offset },
    };
    if (successful.length) return json(origin, 200, payload);
    if (sources.every(item => item.error?.code === "rate_limited")) {
      return json(origin, 429, payload, { "Retry-After": String(RATE_LIMIT_WINDOW_SECONDS) });
    }
    return json(origin, sources.every(item => item.status === "unsupported") ? 400 : 503, payload);
  };
}

const handler = createHandler();

export default {
  fetch(request, env) {
    return handler(request, env);
  },
};

export {
  ADAPTER_VERSIONS,
  AwardRateLimiter,
  MAX_REQUEST_BYTES,
  MAX_YEAR_SPAN,
  RATE_LIMIT_WINDOW_SECONDS,
  SNAPSHOT_PATHS,
  createUpstreamGuard,
  loadSnapshot,
  serviceConfig,
  storeSnapshot,
  validateSnapshotBatch,
  validateSnapshotCreate,
  validateSnapshotPage,
  validateSnapshotRetry,
  validateRequest,
  runInstitutionResolution,
};

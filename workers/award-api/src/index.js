import { AWARD_SCHEMA_VERSION, cleanText } from "./contract.js";
import { AwardSourceError } from "./http.js";
import { institutionFromRor, resolveInstitution } from "./institutions.js";
import { ROR_ADAPTER_VERSION, resolveRorOrganization, searchRor } from "./ror.js";
import { DOE_ADAPTER_VERSION, DOE_MAX_RESULTS, searchDoe } from "./adapters/doe.js";
import { NIH_ADAPTER_VERSION, searchNih } from "./adapters/nih.js";
import { NSF_ADAPTER_VERSION, searchNsf } from "./adapters/nsf.js";
import { federalFiscalYear } from "./year-filter.js";

const MAX_REQUEST_BYTES = 16_384;
const MAX_OFFSET = 1_000;
const MAX_YEAR_SPAN = 50;
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

function error(origin, status, code) {
  return json(origin, status, { error: { code } });
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
  };
  config.valid = Boolean(config.enabled && config.cacheTtl && config.maxResults);
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

async function sourceCacheRequest(source, request, asOf) {
  const cacheIdentity = {
    source,
    adapter_version: ADAPTER_VERSIONS[source],
    criteria: request.publicCriteria,
    limit: request.limit,
    offset: request.offset,
  };
  if (source === "NIH" && request.publicCriteria.year_start && !request.publicCriteria.year_end) {
    cacheIdentity.nih_fiscal_year_ceiling = federalFiscalYear(asOf);
  }
  const identity = await sha256Hex(stableJson(cacheIdentity));
  return new Request(`https://award-cache.internal/v1/${source.toLowerCase()}/${identity}`);
}

async function runSource({ source, request, fetchImpl, cache, cacheTtl, asOf }) {
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
  const options = { limit: request.limit, offset: request.offset, now: () => new Date(asOf) };
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

async function runInstitutionSearch({ query, fetchImpl, cache, cacheTtl }) {
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

async function runInstitutionResolution({ request, fetchImpl, cache, cacheTtl }) {
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

export function createHandler({ fetchImpl = fetch, cache = null, now = () => new Date() } = {}) {
  return async function handle(request, env) {
    const origin = request.headers.get("origin") || "";
    if (!allowedOrigin(origin)) return error(origin, 403, "origin_not_allowed");
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: responseHeaders(origin) });
    const requestUrl = new URL(request.url);
    const path = requestUrl.pathname.replace(/\/+$/, "");
    const config = serviceConfig(env);
    if (path === "/health" && request.method === "GET") {
      return json(origin, config.valid ? 200 : 503, {
        service: config.valid ? "available" : "unavailable",
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
        cache_ttl_seconds: config.cacheTtl,
        credentials_required: false,
      });
    }
    if (path === "/institutions/search") {
      if (request.method !== "GET") return error(origin, 405, "method_not_allowed");
      if (!config.valid) return error(origin, 503, "service_unavailable");
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
        }));
      } catch (cause) {
        const sourceError = cause instanceof AwardSourceError
          ? cause
          : new AwardSourceError("source_unavailable");
        return json(origin, sourceError.kind === "unsupported" ? 400 : 503, {
          schema_version: AWARD_SCHEMA_VERSION,
          query,
          institutions: [],
          registry: {
            source: "ROR",
            status: "unavailable",
            adapter_version: ROR_ADAPTER_VERSION,
            error: { code: sourceError.code },
          },
        });
      }
    }
    if (path !== "/awards/search") return error(origin, 404, "not_found");
    if (request.method !== "POST") return error(origin, 405, "method_not_allowed");
    if (!config.valid) return error(origin, 503, "service_unavailable");
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
        });
        if (!institution) return error(origin, 400, "invalid_request");
        normalized.resolvedCriteria = { ...normalized.resolvedCriteria, _institution: institution };
      } catch (cause) {
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
    const asOf = now().toISOString();
    const settled = await Promise.all(normalized.sources.map(async source => {
      try {
        return await runSource({
          source,
          request: sourceRequest,
          fetchImpl,
          cache: cacheStore,
          cacheTtl: config.cacheTtl,
          asOf,
        });
      } catch (cause) {
        const sourceError = cause instanceof AwardSourceError
          ? cause
          : new AwardSourceError("source_unavailable");
        return {
          source,
          status: sourceError.kind === "unsupported" ? "unsupported" : "unavailable",
          error: { code: sourceError.code },
        };
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
  MAX_REQUEST_BYTES,
  MAX_YEAR_SPAN,
  serviceConfig,
  validateRequest,
  runInstitutionResolution,
};

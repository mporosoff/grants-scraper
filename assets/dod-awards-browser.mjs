import {
  DOD_ADAPTER_VERSION,
  DOD_OPERATION_BUDGET_MS,
  searchDod,
} from "../workers/award-api/src/adapters/dod.js";
import { institutionFromRor, resolveInstitution } from "../workers/award-api/src/institutions.js";
import { resolveRorOrganization } from "../workers/award-api/src/ror.js";
import {
  AWARD_ORDERING_VERSION,
  buildAwardSnapshot,
  publicSnapshot,
  snapshotPage,
  snapshotSourceBatch,
} from "../workers/award-api/src/snapshot.js";
import { AwardSourceError } from "../workers/award-api/src/http.js";

const DOD_SOURCE = "DOD";
const LOCAL_SNAPSHOT_PREFIX = "local-dod-";
const LOCAL_SNAPSHOT_STORAGE_PREFIX = "funding-finder.awards.snapshot.v1.";
const LOCAL_SNAPSHOT_TTL_MS = 60 * 60 * 1_000;
const DOD_CACHE_NAME = "funding-finder-dod-v1";
const DOD_BROWSER_CACHE_TIMEOUT_MS = 2_000;
const SOURCE_NAMES = Object.freeze(["NSF", "NIH", "DOE", "DOD"]);

function clean(value, maximum = 500) {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, maximum);
}

function sourceFailure(cause) {
  const error = cause instanceof AwardSourceError
    ? cause
    : Object.assign(new Error("source_unavailable"), { code: "source_unavailable" });
  const rateLimited = ["rate_limited", "source_rate_limited"].includes(error.code) || error.kind === "rate_limited";
  return {
    source: DOD_SOURCE,
    status: error.kind === "unsupported" ? "unsupported" : rateLimited ? "rate_limited" : "unavailable",
    error: { code: clean(error.code, 80) || "source_unavailable" },
  };
}

function sourceSummary(payload) {
  return {
    source: DOD_SOURCE,
    status: "ok",
    adapter_version: payload.adapter_version,
    cache: payload.cache || "browser-direct",
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
    ...(payload.capabilities ? { capabilities: payload.capabilities } : {}),
    transport: "browser_direct_cors",
  };
}

function mergeAbortSignals(first, second) {
  const signals = [first, second].filter(Boolean);
  if (!signals.length) return { signal: undefined, cleanup() {} };
  if (signals.length === 1) return { signal: signals[0], cleanup() {} };
  if (typeof AbortSignal?.any === "function") {
    return { signal: AbortSignal.any(signals), cleanup() {} };
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  for (const signal of signals) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", abort, { once: true });
  }
  return {
    signal: controller.signal,
    cleanup() {
      for (const signal of signals) signal.removeEventListener("abort", abort);
    },
  };
}

function browserFetch(fetchImpl, operationSignal) {
  return async (url, options = {}) => {
    const combined = mergeAbortSignals(options.signal, operationSignal);
    try {
      return await fetchImpl(url, {
        ...options,
        credentials: "omit",
        referrerPolicy: "no-referrer",
        signal: combined.signal,
      });
    } finally {
      combined.cleanup();
    }
  };
}

async function browserDetailCache() {
  try {
    if (typeof globalThis.caches?.open !== "function") return null;
    const cache = await boundedCacheOperation(() => globalThis.caches.open(DOD_CACHE_NAME));
    return {
      async match(request) {
        const response = await cache.match(request);
        if (!response) return undefined;
        const storedAt = Number(response.headers.get("x-funding-finder-cached-at"));
        if (!Number.isFinite(storedAt) || Date.now() - storedAt > LOCAL_SNAPSHOT_TTL_MS) {
          await cache.delete(request).catch(() => false);
          return undefined;
        }
        return response;
      },
      async put(request, response) {
        const headers = new Headers(response.headers);
        headers.set("X-Funding-Finder-Cached-At", String(Date.now()));
        const stored = new Response(await response.clone().arrayBuffer(), {
          status: response.status,
          statusText: response.statusText,
          headers,
        });
        return cache.put(request, stored);
      },
    };
  } catch {
    return null;
  }
}

function stableJson(value) {
  if (value instanceof Set) return stableJson([...value].sort());
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function boundedCacheOperation(operation) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("cache_timeout")), DOD_BROWSER_CACHE_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function sourceCacheRequest(criteria, { limit, offset, scanAll, currentYear }) {
  const digest = await sha256Hex(stableJson({
    source: DOD_SOURCE,
    adapter_version: DOD_ADAPTER_VERSION,
    criteria,
    limit,
    offset,
    scan_all: scanAll === true,
    current_year: currentYear,
  }));
  return new Request(`https://award-cache.internal/v1/dod-browser-source/${digest}`);
}

async function resolvedDodCriteria(criteria, {
  fetchImpl,
  selectedInstitution = null,
  signal = null,
} = {}) {
  const publicCriteria = { ...(criteria || {}) };
  const name = clean(publicCriteria.institution, 300);
  const id = clean(publicCriteria.institution_id, 100);
  if (!name && !id) return publicCriteria;
  let institution = resolveInstitution({ id, name });
  if (!institution && id) {
    let candidate = selectedInstitution
      && selectedInstitution.registryMetadataLoaded === true
      && clean(selectedInstitution.id, 100) === id
      ? selectedInstitution
      : null;
    if (!candidate?.canonical_name || !Array.isArray(candidate.aliases) || !Array.isArray(candidate.acronyms)) {
      candidate = await resolveRorOrganization(browserFetch(fetchImpl, signal), id);
    }
    institution = institutionFromRor(candidate, name);
  }
  if (!institution) throw new AwardSourceError("invalid_institution_identity", "unsupported");
  return { ...publicCriteria, _institution: institution };
}

export async function searchDodFromBrowser(criteria, {
  limit = 25,
  offset = 0,
  scanAll = false,
  selectedInstitution = null,
  signal = null,
  fetchImpl = globalThis.fetch,
  now = () => new Date(),
  monotonicNow = () => performance.now(),
} = {}) {
  if (typeof fetchImpl !== "function") throw new AwardSourceError("source_unavailable");
  try {
    const operationDeadline = monotonicNow() + DOD_OPERATION_BUDGET_MS;
    const current = now();
    const resolved = await resolvedDodCriteria(criteria, {
      fetchImpl,
      selectedInstitution,
      signal,
    });
    const cache = await browserDetailCache();
    const cacheKey = cache ? await sourceCacheRequest(resolved, {
      limit,
      offset,
      scanAll,
      currentYear: current.getUTCFullYear(),
    }) : null;
    if (cache && cacheKey) {
      try {
        const cached = await boundedCacheOperation(async () => {
          const response = await cache.match(cacheKey);
          return response ? response.json() : null;
        });
        if (cached?.cached_at
          && Date.now() - cached.cached_at <= LOCAL_SNAPSHOT_TTL_MS
          && cached.payload?.source === DOD_SOURCE
          && Array.isArray(cached.payload.results)) {
          return { ...cached.payload, cache: "hit" };
        }
      } catch {
        // A browser cache outage cannot make the official public source unavailable.
      }
    }
    const payload = await searchDod(browserFetch(fetchImpl, signal), resolved, {
      limit,
      offset,
      scanAll,
      cache,
      now: () => new Date(current),
      monotonicNow,
      operationDeadline,
    });
    if (cache && cacheKey) {
      try {
        await boundedCacheOperation(() => cache.put(cacheKey, new Response(JSON.stringify({
          cached_at: Date.now(),
          payload,
        }), {
          headers: {
            "Cache-Control": "public, max-age=3600",
            "Content-Type": "application/json; charset=utf-8",
          },
        })));
      } catch {
        // Valid live results remain usable if browser cache storage fails.
      }
    }
    return { ...payload, cache: cache ? "miss" : "bypass" };
  } catch (cause) {
    return sourceFailure(cause);
  }
}

function workerFailureSources(sources, code = "service_unavailable") {
  return sources.map(source => ({
    source,
    status: "unavailable",
    error: { code },
  }));
}

export function mergeSearchPayload({ request, workerPayload = null, dodPayload = null } = {}) {
  const requestedSources = Array.isArray(request?.sources)
    ? request.sources.map(source => clean(source, 10).toUpperCase()).filter(source => SOURCE_NAMES.includes(source))
    : [];
  const workerRequested = requestedSources.filter(source => source !== DOD_SOURCE);
  const workerSources = Array.isArray(workerPayload?.sources)
    ? workerPayload.sources
    : workerFailureSources(workerRequested);
  const dodSource = requestedSources.includes(DOD_SOURCE)
    ? dodPayload?.status ? dodPayload : dodPayload?.results ? sourceSummary(dodPayload) : sourceFailure(null)
    : null;
  const sourcesByName = new Map(workerSources.map(source => [clean(source?.source, 10).toUpperCase(), source]));
  if (dodSource) sourcesByName.set(DOD_SOURCE, dodSource);
  const workerResults = Array.isArray(workerPayload?.results) ? workerPayload.results : [];
  const dodResults = dodPayload?.status ? [] : Array.isArray(dodPayload?.results) ? dodPayload.results : [];
  const resultsBySource = new Map(SOURCE_NAMES.map(source => [source, []]));
  for (const award of [...workerResults, ...dodResults]) {
    const source = clean(award?.source, 10).toUpperCase();
    resultsBySource.get(source)?.push(award);
  }
  return {
    schema_version: 1,
    request: {
      sources: requestedSources,
      criteria: { ...(request?.criteria || {}) },
      limit: Number(request?.limit) || 25,
      offset: Math.max(0, Number(request?.offset) || 0),
    },
    results: requestedSources.flatMap(source => resultsBySource.get(source) || []),
    sources: requestedSources.map(source => sourcesByName.get(source) || {
      source,
      status: "unavailable",
      error: { code: "service_unavailable" },
    }),
    pagination: {
      limit: Number(request?.limit) || 25,
      offset: Math.max(0, Number(request?.offset) || 0),
    },
  };
}

function resultsForSource(snapshot, source) {
  return (snapshot?.initial_batches || [])
    .filter(batch => clean(batch?.source, 10).toUpperCase() === source)
    .flatMap(batch => Array.isArray(batch?.results) ? batch.results : [])
    .map(({ snapshot_position: _snapshotPosition, ...award }) => award);
}

function sourcePayloadFromSnapshot(snapshot, source) {
  const state = snapshot?.sources?.find(item => clean(item?.source, 10).toUpperCase() === source);
  if (!state || ["unavailable", "rate_limited", "unsupported"].includes(state.status)) {
    return state || { source, status: "unavailable", error: { code: "service_unavailable" } };
  }
  const results = resultsForSource(snapshot, source);
  return {
    source,
    adapter_version: state.adapter_version,
    cache: state.cache,
    total_count: state.status === "complete" ? results.length : null,
    raw_record_count: state.raw_record_count,
    upstream_total_count: state.upstream_total_count,
    upstream_pages: state.upstream_pages,
    upstream_queries: state.upstream_queries,
    safety_bound_reached: state.status === "safety_bounded",
    has_more: state.status === "partial",
    retrieved_at: state.retrieved_at,
    year_filter: state.year_filter,
    health: state.health,
    capabilities: state.capabilities,
    results,
  };
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

export async function createHybridSnapshot({ request, workerSnapshot = null, dodPayload = null } = {}) {
  const requestedSources = Array.isArray(request?.sources)
    ? request.sources.map(source => clean(source, 10).toUpperCase()).filter(source => SOURCE_NAMES.includes(source))
    : [];
  const asOf = clean(workerSnapshot?.as_of || dodPayload?.retrieved_at, 40) || new Date().toISOString();
  const sourcePayloads = Object.fromEntries(requestedSources.map(source => [
    source,
    source === DOD_SOURCE
      ? dodPayload?.status ? dodPayload : dodPayload?.results ? { ...dodPayload, cache: dodPayload.cache || "browser-direct" } : sourceFailure(null)
      : sourcePayloadFromSnapshot(workerSnapshot, source),
  ]));
  const identity = JSON.stringify({
    worker_snapshot_id: workerSnapshot?.snapshot_id || null,
    as_of: asOf,
    request,
    dod: dodPayload?.status ? dodPayload : dodPayload?.results?.map(award => [award.award_id, award.source_provenance?.source_record_id]),
  });
  const digest = await sha256Hex(identity);
  const snapshotId = `${LOCAL_SNAPSHOT_PREFIX}${digest.slice(0, 48)}`;
  const queryId = await sha256Hex(JSON.stringify({ request, ordering_version: AWARD_ORDERING_VERSION }));
  const snapshot = buildAwardSnapshot({
    snapshotId,
    queryId,
    asOf,
    request: {
      sources: requestedSources,
      criteria: { ...(request?.criteria || {}) },
      source_adapter_versions: { DOD: DOD_ADAPTER_VERSION },
      ordering_version: AWARD_ORDERING_VERSION,
      delivery: { DOD: "browser_direct_cors" },
    },
    sourcePayloads,
  });
  return { snapshot, public: publicSnapshot(snapshot) };
}

export function isLocalDodSnapshotId(value) {
  return clean(value, 100).startsWith(LOCAL_SNAPSHOT_PREFIX);
}

export function localSnapshotPage(snapshot, options) {
  return snapshotPage(snapshot, options);
}

export function localSnapshotSourceBatch(snapshot, options) {
  return snapshotSourceBatch(snapshot, options);
}

function storage() {
  try {
    return globalThis.sessionStorage || null;
  } catch {
    return null;
  }
}

export function persistLocalSnapshot(snapshot) {
  if (!snapshot || !isLocalDodSnapshotId(snapshot.snapshot_id)) return false;
  try {
    storage()?.setItem(`${LOCAL_SNAPSHOT_STORAGE_PREFIX}${snapshot.snapshot_id}`, JSON.stringify({
      stored_at: Date.now(),
      snapshot,
    }));
    return true;
  } catch {
    return false;
  }
}

export function loadLocalSnapshot(snapshotId) {
  if (!isLocalDodSnapshotId(snapshotId)) return null;
  const key = `${LOCAL_SNAPSHOT_STORAGE_PREFIX}${snapshotId}`;
  try {
    const store = storage();
    const record = JSON.parse(store?.getItem(key) || "null");
    const valid = record?.snapshot?.snapshot_id === snapshotId
      && record.snapshot.snapshot_contract_version === 1
      && Array.isArray(record.snapshot.awards)
      && Number.isFinite(record.stored_at)
      && Date.now() - record.stored_at <= LOCAL_SNAPSHOT_TTL_MS;
    if (valid) return record.snapshot;
    store?.removeItem(key);
  } catch {
    // Session persistence is optional; the visible criteria can rebuild a snapshot.
  }
  return null;
}

export { LOCAL_SNAPSHOT_PREFIX };

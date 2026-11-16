import { sha256Hex } from "./crypto.js";

const SITE = "https://mporosoff.github.io/grants-scraper/";
const SHA = /^[a-f0-9]{40}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const Eastern = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23",
});
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

function expectedSourceDay(now) {
  const parts = Object.fromEntries(Eastern.formatToParts(now).map(({ type, value }) => [type, value]));
  const utcDay = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day));
  const dueDay = Number(parts.hour) < 18 ? utcDay - 86_400_000 : utcDay;
  return new Date(dueDay).toISOString().slice(0, 10);
}

function freshness(sourceAt, now) {
  if (!sourceAt) return "unknown";
  const windowStart = Date.parse(expectedSourceDay(now) + "T10:17:00Z");
  return Date.parse(sourceAt) >= windowStart ? "current" : "stale";
}

async function readAsset(path, limit, key, fetchImpl) {
  const response = await fetchImpl(new URL(path + "?catalog_observation=" + key, SITE), {
    headers: {
      Accept: "application/json, text/plain, application/javascript",
      "Cache-Control": "no-cache",
      "User-Agent": "FundingFinder-CatalogWatch/1.0 (+https://github.com/mporosoff/grants-scraper)",
    },
    redirect: "manual",
    signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok || !response.body) throw new Error("asset_unavailable");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  let count = 0;
  let result = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) return result + decoder.decode();
    count += value.byteLength;
    if (count > limit) {
      await reader.cancel();
      throw new Error("asset_too_large");
    }
    result += decoder.decode(value, { stream: true });
  }
}

export async function observeCatalog(now, fetchImpl = fetch) {
  const observedAt = now.toISOString();
  const report = {
    observed_at: observedAt, availability: "unavailable", freshness: "unknown",
    source_generated_at: null, publication_sha: null, candidate_id: null, record_count: null,
  };
  let assets;
  try {
    const key = String(now.getTime());
    assets = await Promise.all([
      readAsset("pages-release-sha.txt", 256, key, fetchImpl),
      readAsset("release/publication.json", 96 * 1024, key, fetchImpl),
      readAsset("data/catalog-metadata.js", 8 * 1024, key, fetchImpl),
    ]);
  } catch {
    return report;
  }
  report.availability = "unverified";
  try {
    const [marker, receipt, metadata] = assets;
    const publication = JSON.parse(receipt);
    const release = marker.trim();
    if (publication.schema_version !== 1 || !SHA.test(release) || publication.publication_sha !== release
        || !DIGEST.test(publication.candidate_id) || !DIGEST.test(publication.candidate_hashes?.["data/catalog-metadata.js"])
        || await sha256Hex(metadata) !== publication.candidate_hashes["data/catalog-metadata.js"]) return report;
    const envelope = metadata.match(/^\/\*[^]*?\*\/\r?\nglobalThis\.GRANT_CATALOG_METADATA=(\{[^\r\n]+\});\r?\n?$/);
    if (!envelope) return report;
    const catalog = JSON.parse(envelope[1]);
    const sourceAt = catalog.generated_at;
    if (catalog.schema_version !== 1 || !Number.isSafeInteger(catalog.record_count) || catalog.record_count < 1
        || typeof sourceAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(sourceAt)
        || !Number.isFinite(Date.parse(sourceAt)) || Date.parse(sourceAt) > now.getTime()) return report;
    return {
      ...report, availability: "verified", freshness: freshness(sourceAt, now), source_generated_at: sourceAt,
      publication_sha: release, candidate_id: publication.candidate_id, record_count: catalog.record_count,
    };
  } catch {
    return report;
  }
}

export function isCatalogWatchSlot(controller) {
  return controller?.cron === "2-57/5 * * * *" && new Date(controller.scheduledTime).getUTCMinutes() === 52;
}

// Preserve a freshness incident while publication is unverified. A bad probe
// cannot establish that an older known source timestamp has recovered.
export async function saveCatalogObservation(db, slot, report) {
  const row = await db.prepare(`
    INSERT INTO catalog_watch (id, slot_at, report_json, publication_problem_since, stale_since)
    VALUES (1, ?1, ?2, CASE WHEN ?3 = 'verified' THEN NULL ELSE ?1 END, CASE WHEN ?4 = 'stale' THEN ?1 END)
    ON CONFLICT(id) DO UPDATE SET
      slot_at = excluded.slot_at, report_json = excluded.report_json,
      publication_problem_since = CASE WHEN ?3 = 'verified' THEN NULL
        ELSE COALESCE(catalog_watch.publication_problem_since, excluded.slot_at) END,
      stale_since = CASE ?4 WHEN 'current' THEN NULL WHEN 'stale' THEN COALESCE(catalog_watch.stale_since, excluded.slot_at)
        ELSE catalog_watch.stale_since END
    WHERE excluded.slot_at > catalog_watch.slot_at
    RETURNING publication_problem_since, stale_since
  `).bind(slot, JSON.stringify(report), report.availability, report.freshness).first();
  return [
    ...(row?.publication_problem_since === slot ? ["catalog_publication_unverified"] : []),
    ...(row?.stale_since === slot ? ["catalog_freshness_missed"] : []),
  ];
}

export async function runCatalogWatch(controller, db, { now = new Date(), fetchImpl = fetch, log = console.warn } = {}) {
  const slot = new Date(controller.scheduledTime).toISOString();
  const report = await observeCatalog(now, fetchImpl);
  for (const event of await saveCatalogObservation(db, slot, report)) {
    log(JSON.stringify({ event, incident_started_at: slot, ...report }));
  }
}

export async function catalogWatchHealth(db, now) {
  const row = await db.prepare("SELECT report_json, publication_problem_since, stale_since FROM catalog_watch WHERE id = 1").first();
  if (!row) return { status: "unobserved" };
  const report = JSON.parse(row.report_json);
  const age = now.getTime() - Date.parse(report.observed_at);
  if (!Number.isFinite(age) || age < 0 || age > MAX_AGE_MS) {
    return { status: "observation_overdue", observed_at: report.observed_at };
  }
  return {
    status: "observed", ...report, freshness: freshness(report.source_generated_at, now),
    publication_problem_since: row.publication_problem_since, stale_since: row.stale_since,
  };
}

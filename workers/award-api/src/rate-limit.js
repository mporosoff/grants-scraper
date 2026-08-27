const BUCKETS = new Set([
  "award:NSF",
  "award:NIH",
  "award:DOE",
  "ror:search",
  "ror:resolve",
]);

function boundedInteger(value, minimum, maximum) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= minimum && number <= maximum ? number : null;
}

function json(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function rows(cursor) {
  return cursor ? [...cursor] : [];
}

export class AwardRateLimiter {
  constructor(ctx) {
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS counters(
      bucket TEXT PRIMARY KEY,
      window_started_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      request_count INTEGER NOT NULL CHECK(request_count >= 1)
    )`);
  }

  async fetch(request) {
    if (request.method !== "POST") return json(405, { error: { code: "method_not_allowed" } });
    let body;
    try { body = await request.json(); }
    catch { return json(400, { error: { code: "invalid_request" } }); }
    const bucket = String(body?.bucket || "");
    const now = boundedInteger(body?.now, 0, 8_640_000_000_000_000);
    const limit = boundedInteger(body?.limit, 1, 1_000);
    const windowSeconds = boundedInteger(body?.window_seconds, 10, 3_600);
    if (!BUCKETS.has(bucket) || now === null || !limit || !windowSeconds) {
      return json(400, { error: { code: "invalid_request" } });
    }
    const expiresAt = now + windowSeconds * 1_000;
    const accepted = rows(this.sql.exec(
      `INSERT INTO counters(bucket,window_started_at,expires_at,request_count)
       VALUES(?,?,?,1)
       ON CONFLICT(bucket) DO UPDATE SET
         window_started_at=CASE WHEN counters.expires_at<=? THEN excluded.window_started_at ELSE counters.window_started_at END,
         expires_at=CASE WHEN counters.expires_at<=? THEN excluded.expires_at ELSE counters.expires_at END,
         request_count=CASE WHEN counters.expires_at<=? THEN 1 ELSE counters.request_count+1 END
       WHERE counters.expires_at<=? OR counters.request_count<?
       RETURNING expires_at,request_count`,
      bucket, now, expiresAt, now, now, now, now, limit,
    ))[0];
    if (accepted) {
      return json(200, { success: true, retry_after_seconds: 0 });
    }
    const current = rows(this.sql.exec(
      "SELECT expires_at FROM counters WHERE bucket=? LIMIT 1", bucket,
    ))[0];
    const retryAfter = Math.max(1, Math.min(
      windowSeconds,
      Math.ceil((Number(current?.expires_at || expiresAt) - now) / 1_000),
    ));
    return json(200, { success: false, retry_after_seconds: retryAfter });
  }
}

export { BUCKETS };

import assert from "node:assert/strict";

const endpoint = "https://funding-finder-alerts.urochestercheme.workers.dev";
const health = await fetch(`${endpoint}/health`, {
  headers: { Origin: "https://mporosoff.github.io" },
  signal: AbortSignal.timeout(10_000),
});
assert.equal(health.status, 200);
const payload = await health.json();
assert.equal(payload.service, "available");
assert.equal(payload.delivery_ready, true);
assert.equal(payload.schema_version, 3);
assert.equal(payload.database_ready, true);
assert.equal(payload.email_provider, "resend");
assert.equal(payload.email_provider_selected, true);
assert.equal(payload.email_provider_configured, true);
assert.equal(payload.email_template_version, "phase4-operations-20260827");
assert.equal(payload.capability_signing_ready, true);
assert.equal(payload.capability_previous_signing_ready, true);
assert.match(payload.capability_key_id, /^[0-9a-f]{16}$/);
assert.equal(payload.stale_running_runs, 0);
assert.equal(payload.scheduler_ready, true);
assert.equal(typeof payload.last_daily_run_completed_at, "string");
assert.match(payload.last_daily_run_status, /^completed(?:_with_.*)?$/);
assert.equal(payload.outbound_email_enabled, true);

const preflight = await fetch(`${endpoint}/subscriptions`, {
  method: "OPTIONS",
  headers: {
    Origin: "https://mporosoff.github.io",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
  },
  signal: AbortSignal.timeout(10_000),
});
assert.equal(preflight.status, 204);
assert.equal(preflight.headers.get("access-control-allow-origin"), "https://mporosoff.github.io");

const rejected = await fetch(`${endpoint}/health`, {
  headers: { Origin: "https://example.invalid" },
  signal: AbortSignal.timeout(10_000),
});
assert.equal(rejected.status, 403);

console.log(JSON.stringify({
  service: payload.service,
  delivery_ready: payload.delivery_ready,
  schema_version: payload.schema_version,
  scheduler_ready: payload.scheduler_ready,
  cors: "verified",
}));

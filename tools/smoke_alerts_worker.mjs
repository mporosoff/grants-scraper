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
assert.equal(payload.schema_version, 2);
assert.equal(payload.database_ready, true);
assert.equal(payload.email_provider, "resend");
assert.equal(payload.email_provider_selected, true);
assert.equal(payload.email_provider_configured, true);
assert.equal(payload.email_template_version, "phase2-lifecycle-20260825");
assert.equal(payload.outbound_email_enabled, true);
assert.equal(payload.scheduler_ready, true);

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

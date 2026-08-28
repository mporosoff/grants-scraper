import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { ALERT_SCHEMA_VERSION } from "../../workers/alerts/src/contract.js";
import {
  createCapability, sha256Hex, verificationToken as createVerificationToken,
  verifyCapability,
} from "../../workers/alerts/src/crypto.js";
import { digestEmail, eventEmail } from "../../workers/alerts/src/email.js";
import {
  DIGEST_MAX_EVENTS, dispatchNotifications, dispatchVerificationDeliveries, evaluateSubscriptions,
} from "../../workers/alerts/src/evaluator.js";
import {
  createHandler, createScheduledHandler, weeklyDigestEligibilityCutoff, weeklyDigestWindowFor,
} from "../../workers/alerts/src/index.js";
import { MockEmailProvider, ResendEmailProvider } from "../../workers/alerts/src/provider.js";
import { D1AlertStore, RETENTION_DAYS } from "../../workers/alerts/src/store.js";
import {
  loadPublicAssets, parseAssignedJson, StrongMatchEngine,
} from "../../workers/alerts/src/strong-match.js";

const root = new URL("../../", import.meta.url);
const migrationNames = [
  "0001_phase3_alerts.sql", "0002_delivery_claim_lease.sql", "0003_phase2_alert_lifecycle.sql",
  "0004_phase4_alert_operations.sql", "0005_scheduler_progress.sql", "0006_scheduler_fencing.sql",
];
const migrations = await Promise.all(migrationNames.map(name => (
  readFile(new URL(`workers/alerts/migrations/${name}`, root), "utf8")
)));
const fixedNow = new Date("2026-09-01T12:00:00.000Z");
const env = {
  ALERTS_API_ENABLED: "true",
  ALERT_SCHEDULER_ENABLED: "true",
  OUTBOUND_EMAIL_ENABLED: "true",
  EMAIL_PROVIDER: "resend",
  RESEND_API_KEY: "test-only",
  ALERT_CAPABILITY_SECRET: "test-only-capability-secret-with-32-bytes",
  ALERT_CAPABILITY_PREVIOUS_SECRET: "previous-test-only-capability-secret-with-32-bytes",
  PUBLIC_WORKER_ORIGIN: "https://alerts.example.test",
  PUBLIC_APP_ORIGIN: "https://app.example.test",
  DAILY_EMAIL_LIMIT: "100",
};

class D1Statement {
  constructor(database, sql, values = []) {
    this.database = database;
    this.sql = sql;
    this.values = values;
  }
  bind(...values) { return new D1Statement(this.database, this.sql, values); }
  execute() {
    const result = this.database.prepare(this.sql).run(...this.values);
    return { success: true, meta: { changes: Number(result.changes || 0) } };
  }
  async run() { return this.execute(); }
  async first() { return this.database.prepare(this.sql).get(...this.values) || null; }
  async all() { return { results: this.database.prepare(this.sql).all(...this.values) }; }
}

class SqliteD1 {
  constructor(database) {
    this.database = database;
    this.failBatchAt = null;
    this.beforeBatch = null;
  }
  prepare(sql) { return new D1Statement(this.database, sql); }
  async batch(statements) {
    if (this.beforeBatch) {
      const hook = this.beforeBatch;
      this.beforeBatch = null;
      await hook();
    }
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const results = [];
      for (let index = 0; index < statements.length; index += 1) {
        if (index === this.failBatchAt) throw new Error("deterministic batch failure");
        results.push(statements[index].execute());
      }
      this.database.exec("COMMIT");
      return results;
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }
}

function databaseThrough(count = migrations.length) {
  const database = new DatabaseSync(":memory:");
  database.exec("PRAGMA foreign_keys = ON");
  for (const migration of migrations.slice(0, count)) database.exec(migration);
  return database;
}

function insertSubscriber(database, {
  id = "person-1", email = "researcher@example.edu", manageToken = "m".repeat(43),
  suppressedAt = null, suppressionReason = null,
} = {}) {
  database.prepare(
    "INSERT INTO subscribers(id,email,email_normalized,verified_at,manage_token,suppressed_at,suppression_reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
  ).run(id, email, email, fixedNow.toISOString(), manageToken, suppressedAt, suppressionReason, fixedNow.toISOString(), fixedNow.toISOString());
  if (database.prepare("PRAGMA table_info(subscribers)").all().some(column => column.name === "legacy_manage_expires_at")) {
    database.prepare(
      "UPDATE subscribers SET legacy_manage_expires_at = ? WHERE id = ?",
    ).run("2026-11-30T23:59:59.999Z", id);
  }
  return { id, email, manageToken };
}

function insertSubscription(database, {
  id = "watch-1", subscriberId = "person-1", type = "saved_search", active = 0,
  cadence = "weekly", definition = { query: "old" }, definitionHash = "hash-old",
  tokenHash = "token-old", expiresAt = "2026-09-02T12:00:00.000Z",
  verifiedAt = "2026-08-01T00:00:00.000Z", baselineComplete = 1,
  baselineAt = "2026-08-01T00:00:00.000Z", lastEvaluatedAt = "2026-08-20T00:00:00.000Z",
} = {}) {
  database.prepare(
    "INSERT INTO subscriptions(id,subscriber_id,type,active,cadence,definition_json,definition_hash,verification_token_hash,verification_expires_at,verified_at,baseline_at,baseline_complete,last_evaluated_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
  ).run(
    id, subscriberId, type, active, cadence, JSON.stringify(definition), definitionHash,
    tokenHash, expiresAt, verifiedAt, baselineAt, baselineComplete, lastEvaluatedAt,
    baselineAt, baselineAt,
  );
  return id;
}

function setEvaluationCursor(database, {
  id = "watch-1", cursorAt, cursorEventId, windowStartedAt,
  weeklyWindowAt, inputGeneratedAt, sourceGeneratedAt = inputGeneratedAt,
} = {}) {
  database.prepare(
    "UPDATE subscriptions SET evaluation_cursor_at=?, evaluation_cursor_event_id=?, evaluation_window_started_at=?, evaluation_weekly_window_at=?, evaluation_input_generated_at=?, evaluation_source_generated_at=? WHERE id=?",
  ).run(
    cursorAt, cursorEventId, windowStartedAt, weeklyWindowAt,
    inputGeneratedAt, sourceGeneratedAt, id,
  );
}

function insertEvent(database, {
  id, subscriptionId = "watch-1", status = "queued", createdAt = "2026-08-20T00:00:00.000Z",
  kind = "amended", payload = { title: "Funding opportunity" },
} = {}) {
  database.prepare(
    "INSERT INTO notification_events(id,subscription_id,event_key,event_kind,payload_json,status,attempts,next_attempt_at,created_at,claimed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
  ).run(
    id, subscriptionId, `key-${id}`, kind, JSON.stringify(payload), status, 0,
    createdAt, createdAt, status === "sending" ? createdAt : null,
  );
}

function all(database, sql, ...values) { return database.prepare(sql).all(...values); }

async function cycle(overrides = {}) {
  const nonce = overrides.verificationNonce || "v".repeat(43);
  const manageToken = overrides.manageToken || "m".repeat(43);
  const id = overrides.id || "watch-1";
  const subscriberId = overrides.subscriberId || "person-1";
  const token = await createVerificationToken({
    subscriberId, subscriptionId: id, nonce,
  }, env.ALERT_CAPABILITY_SECRET);
  return {
    id, subscriberId, type: "saved_search", cadence: "weekly",
    definitionJson: JSON.stringify({ query: "new" }), definitionHash: "hash-old",
    baselineOpportunityIds: ["new-a", "new-b"], suppressed: false,
    verificationNonce: nonce,
    verificationTokenHash: overrides.verificationTokenHash || await sha256Hex(token),
    verificationExpiresAt: "2026-09-02T12:00:00.000Z",
    verificationEventId: overrides.verificationEventId || "verify-new",
    verificationEventKey: overrides.verificationEventKey || "verification:token-new",
    now: fixedNow.toISOString(), ...overrides,
  };
}

function opportunityBody(email = "researcher@example.edu") {
  return {
    email,
    baseline_opportunity_ids: [],
    subscription: {
      type: "opportunity", cadence: "immediate",
      definition: { opportunity_id: "opp-1", triggers: ["deadline_changed"] },
    },
  };
}

async function post(handler, path, body, activeEnv = env, extraHeaders = {}) {
  return handler(new Request(`https://alerts.example.test${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json", Origin: "https://mporosoff.github.io", ...extraHeaders,
    },
    body: JSON.stringify(body),
  }), activeEnv);
}

class ScriptedProvider {
  constructor(failures = []) {
    this.failures = [...failures];
    this.attempts = [];
    this.messages = [];
    this.configured = true;
  }
  async sendEmail(message, idempotencyKey) {
    this.attempts.push({ message, idempotencyKey });
    const failure = this.failures.shift();
    if (failure) throw Object.assign(new Error("bounded provider failure"), failure);
    const id = `provider-${this.messages.length + 1}`;
    this.messages.push({ ...message, idempotencyKey, id });
    return { id };
  }
}

test("0003 migrates representative production lifecycle rows without changing their state", async () => {
  const database = databaseThrough(2);
  const store = new D1AlertStore(new SqliteD1(database));
  await assert.rejects(store.health(), /message_kind|terminal_at/);
  insertSubscriber(database);
  insertSubscriber(database, {
    id: "person-suppressed", email: "suppressed@example.edu", manageToken: "s".repeat(43),
    suppressedAt: "2026-08-15T00:00:00.000Z", suppressionReason: "email.bounced",
  });
  const states = [
    ["active", "person-1", 1, "2026-08-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z"],
    ["inactive", "person-1", 0, "2026-08-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z"],
    ["unverified", "person-1", 0, null, "2026-09-02T00:00:00.000Z"],
    ["expired", "person-1", 0, null, "2026-08-01T00:00:00.000Z"],
    ["suppressed", "person-suppressed", 0, "2026-08-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z"],
  ];
  for (const [id, subscriberId, active, verifiedAt, expiresAt] of states) {
    insertSubscription(database, {
      id, subscriberId, active, verifiedAt, expiresAt,
      definitionHash: `hash-${id}`, tokenHash: `token-${id}`,
    });
  }
  for (const status of ["queued", "failed", "sending", "sent"]) {
    insertEvent(database, { id: `event-${status}`, subscriptionId: "inactive", status });
  }
  database.exec(migrations[2]);
  assert.equal(await store.health(), true);
  assert.deepEqual(
    all(database, "SELECT id,active,verified_at FROM subscriptions ORDER BY id").map(row => [row.id, row.active, row.verified_at]),
    states.map(([id, , active, verifiedAt]) => [id, active, verifiedAt]).sort((a, b) => a[0].localeCompare(b[0])),
  );
  assert.deepEqual(
    all(database, "SELECT status,message_kind,terminal_at,provider_batch_has_overflow,provider_payload_json FROM notification_events ORDER BY id")
      .map(row => [row.status, row.message_kind, row.terminal_at, row.provider_batch_has_overflow, row.provider_payload_json]),
    ["failed", "queued", "sending", "sent"].map(status => [status, "notification", null, 0, null]),
  );
  const columns = all(database, "PRAGMA table_info(notification_events)").map(row => row.name);
  assert.ok(columns.includes("message_kind"));
  assert.ok(columns.includes("terminal_at"));
  assert.ok(columns.includes("provider_quota_key"));
  assert.ok(columns.includes("provider_quota_reserved_at"));
  assert.ok(columns.includes("provider_batch_has_overflow"));
  assert.ok(columns.includes("provider_payload_json"));
  assert.ok(all(database, "PRAGMA table_info(rate_limits)").map(row => row.name).includes("last_reservation_key"));
});

test("FF-BUG-003 reactivation atomically replaces baseline state and retires old unsent events", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database);
  database.prepare("INSERT INTO subscription_qualifications VALUES(?,?,1,?)").run("watch-1", "stale", fixedNow.toISOString());
  for (const status of ["queued", "failed", "sending", "sent"]) insertEvent(database, { id: `old-${status}`, status });
  const store = new D1AlertStore(new SqliteD1(database));
  const stored = await store.createSubscriptionCycle(await cycle());
  assert.equal(stored.cycleAccepted, true);
  const subscription = database.prepare("SELECT * FROM subscriptions WHERE id='watch-1'").get();
  assert.equal(subscription.active, 0);
  assert.equal(subscription.verified_at, null);
  assert.equal(subscription.baseline_complete, 1);
  assert.equal(subscription.baseline_at, fixedNow.toISOString());
  assert.equal(subscription.last_evaluated_at, null);
  assert.deepEqual(
    all(database, "SELECT opportunity_id FROM subscription_qualifications ORDER BY opportunity_id").map(row => row.opportunity_id),
    ["new-a", "new-b"],
  );
  assert.deepEqual(
    all(database, "SELECT id,status,error_code,terminal_at FROM notification_events WHERE id LIKE 'old-%' ORDER BY id")
      .map(row => [row.id, row.status, row.error_code, Boolean(row.terminal_at)]),
    [
      ["old-failed", "suppressed", "subscription_reactivated", true],
      ["old-queued", "suppressed", "subscription_reactivated", true],
      ["old-sending", "suppressed", "subscription_reactivated", true],
      ["old-sent", "sent", null, false],
    ],
  );
  const verification = database.prepare("SELECT * FROM notification_events WHERE id='verify-new'").get();
  assert.equal(verification.message_kind, "verification");
  assert.equal(verification.status, "queued");
  assert.deepEqual(Object.keys(JSON.parse(verification.payload_json)), ["nonce"]);
  assert.doesNotMatch(verification.payload_json, /"token"/);
});

test("FF-BUG-003 active duplicates stay unchanged and failed baseline batches fail closed", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1, tokenHash: "active-token", baselineAt: "2026-08-01T00:00:00.000Z" });
  database.prepare("INSERT INTO subscription_qualifications VALUES(?,?,1,?)").run("watch-1", "active-baseline", fixedNow.toISOString());
  const d1 = new SqliteD1(database);
  const store = new D1AlertStore(d1);
  const duplicate = await store.createSubscriptionCycle(await cycle());
  assert.equal(duplicate.alreadyActive, true);
  assert.equal(database.prepare("SELECT verification_token_hash FROM subscriptions WHERE id='watch-1'").get().verification_token_hash, "active-token");
  assert.deepEqual(all(database, "SELECT opportunity_id FROM subscription_qualifications").map(row => row.opportunity_id), ["active-baseline"]);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events").get().count, 0);

  database.prepare("UPDATE subscriptions SET active=0 WHERE id='watch-1'").run();
  d1.failBatchAt = 3;
  await assert.rejects(store.createSubscriptionCycle(await cycle()), /deterministic batch failure/);
  const rolledBack = database.prepare("SELECT * FROM subscriptions WHERE id='watch-1'").get();
  assert.equal(rolledBack.verification_token_hash, "active-token");
  assert.equal(rolledBack.baseline_complete, 1);
  assert.deepEqual(all(database, "SELECT opportunity_id FROM subscription_qualifications").map(row => row.opportunity_id), ["active-baseline"]);
});

test("FF-BUG-003 inactive, unverified, paused, and expired rows all start a fresh cycle", async () => {
  const priorStates = [
    { name: "inactive", verifiedAt: "2026-08-01T00:00:00.000Z", expiresAt: "2026-09-02T00:00:00.000Z" },
    { name: "unverified", verifiedAt: null, expiresAt: "2026-09-02T00:00:00.000Z" },
    { name: "paused_after_unsubscribe", verifiedAt: "2026-08-01T00:00:00.000Z", expiresAt: "2026-09-02T00:00:00.000Z" },
    { name: "expired", verifiedAt: null, expiresAt: "2026-08-01T00:00:00.000Z" },
  ];
  for (const prior of priorStates) {
    const database = databaseThrough();
    insertSubscriber(database);
    insertSubscription(database, {
      verifiedAt: prior.verifiedAt, expiresAt: prior.expiresAt,
      tokenHash: `old-${prior.name}`, lastEvaluatedAt: "2026-08-20T00:00:00.000Z",
    });
    database.prepare("INSERT INTO subscription_qualifications VALUES(?,?,1,?)").run("watch-1", `old-${prior.name}`, fixedNow.toISOString());
    const store = new D1AlertStore(new SqliteD1(database));
    const result = await store.createSubscriptionCycle(await cycle({
      verificationTokenHash: `fresh-${prior.name}`,
      verificationEventId: `verify-${prior.name}`,
      verificationEventKey: `verification:fresh-${prior.name}`,
    }));
    assert.equal(result.cycleAccepted, true, prior.name);
    const row = database.prepare("SELECT * FROM subscriptions WHERE id='watch-1'").get();
    assert.equal(row.active, 0, prior.name);
    assert.equal(row.verified_at, null, prior.name);
    assert.equal(row.baseline_complete, 1, prior.name);
    assert.equal(row.last_evaluated_at, null, prior.name);
    assert.deepEqual(
      all(database, "SELECT opportunity_id FROM subscription_qualifications ORDER BY opportunity_id").map(item => item.opportunity_id),
      ["new-a", "new-b"],
      prior.name,
    );
  }
});

test("FF-BUG-003 reactivation serializes with an authorized notification delivery", async () => {
  for (const providerFails of [false, true]) {
    const database = databaseThrough();
    const person = insertSubscriber(database);
    insertSubscription(database, {
      active: 1, cadence: "immediate", definitionHash: "hash-old",
    });
    const d1 = new SqliteD1(database);
    const store = new D1AlertStore(d1);
    await store.enqueueEvent({
      id: "notice-in-flight", subscriptionId: "watch-1", eventKey: "notice-in-flight",
      eventKind: "amended", opportunityId: "opp-1",
      payload: { title: "Authorized update" }, createdAt: fixedNow.toISOString(),
    });
    const provider = {
      configured: true,
      attempts: [],
      async sendEmail(message, idempotencyKey) {
        this.attempts.push({ message, idempotencyKey });
        const replaceCycle = async () => {
          assert.equal(await store.updateSubscription(
            person.manageToken, "watch-1", { active: false }, fixedNow.toISOString(),
          ), true);
          const replacement = await store.createSubscriptionCycle(await cycle({
            verificationNonce: "z".repeat(43), verificationTokenHash: "replacement-token",
            verificationEventId: "verify-replacement", verificationEventKey: "verification:replacement-token",
          }));
          assert.equal(replacement.cycleAccepted, true);
        };
        if (this.attempts.length === 1) {
          if (providerFails) d1.beforeBatch = replaceCycle;
          else await replaceCycle();
        }
        if (providerFails && this.attempts.length === 1) throw Object.assign(new Error("bounded provider failure"), {
          code: "provider_network_failure", providerFailureKind: "network", retryable: true,
        });
        return { id: "provider-in-flight" };
      },
    };
    const result = await dispatchNotifications({ store, provider, env, now: fixedNow });
    assert.equal(result.attemptedCount, 1);
    assert.equal(provider.attempts.length, 1);
    const event = database.prepare("SELECT status,error_code,terminal_at,provider_message_id FROM notification_events WHERE id='notice-in-flight'").get();
    if (providerFails) {
      assert.deepEqual(result, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
      assert.equal(event.status, "failed");
      assert.equal(event.error_code, "provider_outcome_reconcile");
      assert.equal(event.terminal_at, null);
      assert.equal(event.provider_message_id, null);
      assert.equal(database.prepare("SELECT status FROM notification_events WHERE id='verify-replacement'").get().status, "queued");
      const recovered = await dispatchNotifications({
        store, provider, env, now: new Date("2026-09-01T12:06:00.000Z"),
      });
      assert.deepEqual(recovered, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
      assert.equal(provider.attempts.length, 2);
      assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
      Object.assign(event, database.prepare("SELECT status,error_code,terminal_at,provider_message_id FROM notification_events WHERE id='notice-in-flight'").get());
    } else {
      assert.deepEqual(result, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
    }
    assert.equal(event.status, "sent");
    assert.equal(event.error_code, null);
    assert.equal(event.terminal_at, null);
    assert.equal(event.provider_message_id, "provider-in-flight");
    assert.equal(await store.suppressSubscriberByMessage(
      "provider-in-flight", "email.bounced", "webhook-in-flight", fixedNow.toISOString(),
    ), true);
    assert.equal(database.prepare("SELECT status FROM notification_events WHERE id='verify-replacement'").get().status, "suppressed");
  }
});

test("FF-BUG-003 definitive HTTP retry failure retires an in-flight reactivated cycle", async () => {
  const database = databaseThrough();
  const person = insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "immediate", definitionHash: "hash-old",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  await store.enqueueEvent({
    id: "notice-http-in-flight", subscriptionId: "watch-1", eventKey: "notice-http-in-flight",
    eventKind: "amended", opportunityId: "opp-1",
    payload: { title: "Definitive retry response" }, createdAt: fixedNow.toISOString(),
  });
  const provider = {
    configured: true,
    attempts: [],
    async sendEmail(message, idempotencyKey) {
      this.attempts.push({ message, idempotencyKey });
      assert.equal(await store.updateSubscription(
        person.manageToken, "watch-1", { active: false }, fixedNow.toISOString(),
      ), true);
      assert.equal((await store.createSubscriptionCycle(await cycle({
        verificationNonce: "h".repeat(43), verificationTokenHash: "replacement-http-token",
        verificationEventId: "verify-http-replacement", verificationEventKey: "verification:replacement-http-token",
      }))).cycleAccepted, true);
      throw Object.assign(new Error("definitive provider rate limit"), {
        code: "provider_rate_limited", providerFailureKind: "http", providerHttpStatus: 429,
        retryable: true,
      });
    },
  };
  assert.deepEqual(
    await dispatchNotifications({ store, provider, env, now: fixedNow }),
    { attemptedCount: 1, deliveredCount: 0, failedCount: 1 },
  );
  const retired = database.prepare(
    "SELECT status,error_code,terminal_at FROM notification_events WHERE id='notice-http-in-flight'",
  ).get();
  assert.deepEqual(
    [retired.status, retired.error_code, retired.terminal_at],
    ["suppressed", "subscription_reactivated", fixedNow.toISOString()],
  );
  assert.deepEqual(
    await dispatchNotifications({ store, provider, env, now: new Date("2026-09-01T12:06:00.000Z") }),
    { attemptedCount: 0, deliveredCount: 0, failedCount: 0 },
  );
  assert.equal(provider.attempts.length, 1);
  assert.equal(database.prepare("SELECT status FROM notification_events WHERE id='verify-http-replacement'").get().status, "queued");
});

test("FF-BUG-003 evaluation writes are bound to the selected subscription cycle", async () => {
  const database = databaseThrough();
  const person = insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "immediate", definitionHash: "hash-old",
  });
  database.prepare(
    "INSERT INTO subscription_qualifications(subscription_id,opportunity_id,qualified,updated_at) VALUES('watch-1','old-qualified',1,?)",
  ).run("2026-08-20T00:00:00.000Z");
  const store = new D1AlertStore(new SqliteD1(database));
  const readQualifications = store.qualifications.bind(store);
  let replacementCreated = false;
  store.qualifications = async (...args) => {
    const selected = await readQualifications(...args);
    if (!replacementCreated) {
      replacementCreated = true;
      assert.equal(await store.updateSubscription(
        person.manageToken, "watch-1", { active: false }, fixedNow.toISOString(),
      ), true);
      assert.equal((await store.createSubscriptionCycle(await cycle({
        verificationNonce: "e".repeat(43), verificationTokenHash: "replacement-evaluation-token",
        verificationEventId: "verify-evaluation-replacement", verificationEventKey: "verification:replacement-evaluation-token",
      }))).cycleAccepted, true);
    }
    return selected;
  };
  const changedRecord = {
    opportunity_id: "new-qualifier", title: "New qualifier", agency: "NSF",
    close_date: "2026-11-01", funding_opportunity_url: "https://example.test/new-qualifier",
  };
  const assets = {
    catalog: { opportunities: [changedRecord] },
    changes: {
      generated_at: "2026-09-01T11:00:00.000Z",
      events: [{
        id: "new-qualifier-change", type: "new", changed_at: "2026-09-01T10:00:00.000Z",
        opportunity_id: "new-qualifier", detail: "First appeared", record: changedRecord,
      }],
    },
    matcher: {
      matchDetails: () => new Map([["new-qualifier", { reasons: ["A deterministic match."] }]]),
    },
  };
  assert.deepEqual(
    await evaluateSubscriptions({ store, assets, env, now: fixedNow }),
    {
      subscriptionCount: 1, matchedEventCount: 0,
      continuationRequired: false, processedChangeCount: 1,
      rebasedSubscriptionCount: 0,
      evaluationInputGeneratedAt: "2026-09-01T11:00:00.000Z",
      evaluationSourceGeneratedAt: "2026-09-01T11:00:00.000Z",
    },
  );
  assert.equal(replacementCreated, true);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE message_kind='notification'").get().count, 0);
  assert.deepEqual(
    all(database, "SELECT opportunity_id,qualified FROM subscription_qualifications ORDER BY opportunity_id")
      .map(row => [row.opportunity_id, row.qualified]),
    [["new-a", 1], ["new-b", 1]],
  );
  const replacement = database.prepare(
    "SELECT active,verification_token_hash,last_evaluated_at FROM subscriptions WHERE id='watch-1'",
  ).get();
  assert.deepEqual(
    [replacement.active, replacement.verification_token_hash, replacement.last_evaluated_at],
    [0, "replacement-evaluation-token", null],
  );
  assert.ok(await store.verifySubscription("replacement-evaluation-token", fixedNow.toISOString()));
  assets.changes = {
    generated_at: "2026-09-02T11:00:00.000Z",
    events: [{
      id: "new-qualifier-next-cycle", type: "new", changed_at: "2026-09-02T10:00:00.000Z",
      opportunity_id: "new-qualifier", detail: "First appeared after replacement", record: changedRecord,
    }],
  };
  assert.deepEqual(
    await evaluateSubscriptions({ store, assets, env, now: new Date("2026-09-02T12:00:00.000Z") }),
    {
      subscriptionCount: 1, matchedEventCount: 1,
      continuationRequired: false, processedChangeCount: 1,
      rebasedSubscriptionCount: 0,
      evaluationInputGeneratedAt: "2026-09-02T11:00:00.000Z",
      evaluationSourceGeneratedAt: "2026-09-02T11:00:00.000Z",
    },
  );
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE message_kind='notification'").get().count, 1);
  assert.equal(database.prepare(
    "SELECT qualified FROM subscription_qualifications WHERE subscription_id='watch-1' AND opportunity_id='new-qualifier'",
  ).get().qualified, 1);
  assert.equal(database.prepare("SELECT last_evaluated_at FROM subscriptions WHERE id='watch-1'").get().last_evaluated_at, "2026-09-02T11:00:00.000Z");
});

test("FF-BUG-008 verification delivery survives network and 429 retries with provider evidence", async () => {
  for (const failure of [
    { code: "provider_network_failure", retryable: true },
    { code: "provider_rate_limited", retryable: true },
  ]) {
    const database = databaseThrough();
    insertSubscriber(database);
    const store = new D1AlertStore(new SqliteD1(database));
    await store.createSubscriptionCycle(await cycle());
    const provider = new ScriptedProvider([failure]);
    const limitedEnv = { ...env, DAILY_EMAIL_LIMIT: "1" };
    const first = await dispatchVerificationDeliveries({ store, provider, env: limitedEnv, now: fixedNow });
    assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
    const failed = database.prepare("SELECT * FROM notification_events WHERE id='verify-new'").get();
    assert.equal(failed.status, "failed");
    assert.equal(failed.terminal_at, null);
    const retryNow = new Date("2026-09-01T12:06:00.000Z");
    const second = await dispatchVerificationDeliveries({
      store, provider,
      env: { ...limitedEnv, PUBLIC_WORKER_ORIGIN: "https://replacement-alerts.example.test" },
      now: retryNow,
    });
    assert.deepEqual(second, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
    const sent = database.prepare("SELECT * FROM notification_events WHERE id='verify-new'").get();
    assert.equal(sent.status, "sent");
    assert.equal(sent.attempts, 2);
    assert.equal(sent.provider_message_id, "provider-1");
    assert.equal(sent.provider_quota_key, provider.attempts[0].idempotencyKey);
    assert.ok(sent.provider_quota_reserved_at);
    assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
    assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
    assert.equal(provider.attempts[0].message.subject, provider.attempts[1].message.subject);
    assert.equal(provider.attempts[0].message.text, provider.attempts[1].message.text);
    assert.equal(provider.attempts[0].message.html, provider.attempts[1].message.html);
  }
});

test("FF-BUG-008 a refreshed verification key discards its obsolete stored payload", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  const originalNonce = "o".repeat(43);
  await store.createSubscriptionCycle(await cycle({
    verificationNonce: originalNonce,
    verificationExpiresAt: "2026-09-01T13:05:00.000Z",
  }));
  const provider = new ScriptedProvider([{ code: "provider_rate_limited", retryable: true }]);
  const first = await dispatchVerificationDeliveries({ store, provider, env, now: fixedNow });
  assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
  const originalKey = provider.attempts[0].idempotencyKey;
  const originalToken = new URL(
    provider.attempts[0].message.text.match(/Activate it: (\S+)/)[1],
  ).searchParams.get("token");

  const freshNonce = "f".repeat(43);
  const retryNow = new Date("2026-09-01T12:06:00.000Z");
  const second = await dispatchVerificationDeliveries({
    store, provider,
    env: { ...env, PUBLIC_WORKER_ORIGIN: "https://replacement-alerts.example.test" },
    now: retryNow, tokenFactory: () => freshNonce,
  });
  assert.deepEqual(second, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
  const freshToken = await createVerificationToken({
    subscriberId: "person-1", subscriptionId: "watch-1", nonce: freshNonce,
  }, env.ALERT_CAPABILITY_SECRET);
  assert.notEqual(provider.attempts[1].idempotencyKey, originalKey);
  assert.match(provider.attempts[1].message.text, new RegExp(`/verify\\?token=${freshToken}`));
  assert.doesNotMatch(provider.attempts[1].message.text, new RegExp(originalToken));
  assert.match(provider.attempts[1].message.text, /replacement-alerts\.example\.test/);
  const event = database.prepare(
    "SELECT provider_quota_key,provider_payload_json FROM notification_events WHERE id='verify-new'",
  ).get();
  assert.equal(event.provider_quota_key, provider.attempts[1].idempotencyKey);
  assert.match(event.provider_payload_json, new RegExp(freshToken));
});

test("FF-BUG-008 concurrent verification dispatchers claim once and reserve one provider slot", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  await store.createSubscriptionCycle(await cycle());
  const provider = new ScriptedProvider();
  const results = await Promise.all([
    dispatchVerificationDeliveries({ store, provider, env, now: fixedNow }),
    dispatchVerificationDeliveries({ store, provider, env, now: fixedNow }),
  ]);
  assert.equal(results.reduce((sum, item) => sum + item.attemptedCount, 0), 1);
  assert.equal(results.reduce((sum, item) => sum + item.deliveredCount, 0), 1);
  assert.equal(provider.messages.length, 1);
  assert.equal(database.prepare("SELECT attempts FROM notification_events WHERE id='verify-new'").get().attempts, 1);
  assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
});

test("FF-BUG-008 distinct concurrent claims cannot exceed the atomic provider-message cap", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscriber(database, {
    id: "person-2", email: "second@example.edu", manageToken: "q".repeat(43),
  });
  const store = new D1AlertStore(new SqliteD1(database));
  await store.createSubscriptionCycle(await cycle());
  await store.createSubscriptionCycle(await cycle({
    id: "watch-2", subscriberId: "person-2", manageToken: "q".repeat(43),
    definitionHash: "hash-2", verificationEventId: "verify-2",
    verificationEventKey: "verification:token-2", verificationNonce: "w".repeat(43),
  }));
  const scoped = eventId => {
    const value = Object.create(store);
    value.pendingVerificationEvents = async (now, limit) => (
      (await store.pendingVerificationEvents(now, 100))
        .filter(event => event.id === eventId).slice(0, limit)
    );
    return value;
  };
  const provider = new ScriptedProvider();
  const results = await Promise.all([
    dispatchVerificationDeliveries({
      store: scoped("verify-new"), provider, env: { ...env, DAILY_EMAIL_LIMIT: "1" }, now: fixedNow,
    }),
    dispatchVerificationDeliveries({
      store: scoped("verify-2"), provider, env: { ...env, DAILY_EMAIL_LIMIT: "1" }, now: fixedNow,
    }),
  ]);
  assert.equal(results.reduce((sum, item) => sum + item.attemptedCount, 0), 1);
  assert.equal(provider.messages.length, 1);
  assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
  assert.deepEqual(
    all(database, "SELECT status,attempts FROM notification_events ORDER BY id")
      .map(event => [event.status, event.attempts]).sort((left, right) => left[0].localeCompare(right[0])),
    [["queued", 0], ["sent", 1]],
  );
});

test("FF-BUG-008 verification completed before quota reservation consumes no provider slot", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscriber(database, {
    id: "person-2", email: "second@example.edu", manageToken: "q".repeat(43),
  });
  const d1 = new SqliteD1(database);
  const store = new D1AlertStore(d1);
  const firstCycle = await cycle();
  await store.createSubscriptionCycle(firstCycle);
  await store.createSubscriptionCycle(await cycle({
    id: "watch-2", subscriberId: "person-2", manageToken: "q".repeat(43),
    definitionHash: "hash-2", verificationEventId: "verify-z",
    verificationEventKey: "verification:token-2", verificationNonce: "w".repeat(43),
  }));
  const originalClaimCheck = store.verificationClaimIsCurrent.bind(store);
  let completed = false;
  store.verificationClaimIsCurrent = async (...args) => {
    const current = await originalClaimCheck(...args);
    if (current && !completed) {
      completed = true;
      d1.beforeBatch = () => store.verifySubscription(
        firstCycle.verificationTokenHash, fixedNow.toISOString(),
      );
    }
    return current;
  };
  const provider = new ScriptedProvider();
  const limitedEnv = { ...env, DAILY_EMAIL_LIMIT: "1" };
  const raced = await dispatchVerificationDeliveries({
    store, provider, env: limitedEnv, now: fixedNow,
  });
  assert.deepEqual(raced, { attemptedCount: 0, deliveredCount: 0, failedCount: 0 });
  assert.equal(provider.messages.length, 0);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().count, 0);
  assert.equal(database.prepare("SELECT status FROM notification_events WHERE id='verify-new'").get().status, "suppressed");

  const delivered = await dispatchVerificationDeliveries({
    store, provider, env: limitedEnv, now: fixedNow,
  });
  assert.deepEqual(delivered, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
  assert.equal(provider.messages.length, 1);
  assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
});

test("FF-BUG-008 verification completed after network ambiguity still recovers the provider ID", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  const verificationCycle = await cycle();
  await store.createSubscriptionCycle(verificationCycle);
  const provider = new ScriptedProvider([{
    code: "provider_network_failure", retryable: true,
  }]);
  const limitedEnv = { ...env, DAILY_EMAIL_LIMIT: "1" };
  const first = await dispatchVerificationDeliveries({
    store, provider, env: limitedEnv, now: fixedNow,
  });
  assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
  assert.ok(database.prepare("SELECT provider_quota_key FROM notification_events WHERE id='verify-new'").get().provider_quota_key);

  const originalClaimCheck = store.verificationReconciliationClaimIsCurrent.bind(store);
  let completed = false;
  store.verificationReconciliationClaimIsCurrent = async (...args) => {
    const current = await originalClaimCheck(...args);
    if (current && !completed) {
      completed = true;
      await store.verifySubscription(
        verificationCycle.verificationTokenHash, new Date("2026-09-01T12:06:00.000Z").toISOString(),
      );
    }
    return current;
  };
  const retry = await dispatchVerificationDeliveries({
    store, provider, env: limitedEnv, now: new Date("2026-09-01T12:06:00.000Z"),
  });
  assert.deepEqual(retry, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
  assert.equal(provider.attempts.length, 2);
  assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
  assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
  const event = database.prepare("SELECT status,error_code,terminal_at,provider_message_id FROM notification_events WHERE id='verify-new'").get();
  assert.equal(event.status, "sent");
  assert.equal(event.error_code, null);
  assert.equal(event.terminal_at, null);
  assert.equal(event.provider_message_id, "provider-1");
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 1);
});

test("FF-BUG-008 verification reconciliation preserves rotated and legacy token identity", async () => {
  const cases = [
    { name: "rotated", capabilityVersion: 1, signingSecret: env.ALERT_CAPABILITY_PREVIOUS_SECRET },
    { name: "legacy", capabilityVersion: 0, signingSecret: "" },
  ];
  for (const item of cases) {
    const database = databaseThrough();
    const person = insertSubscriber(database);
    database.prepare("UPDATE subscribers SET capability_version = ? WHERE id = ?").run(item.capabilityVersion, person.id);
    const nonce = item.name.slice(0, 1).repeat(43);
    const token = item.signingSecret
      ? await createVerificationToken({ subscriberId: person.id, subscriptionId: "watch-1", nonce }, item.signingSecret)
      : await sha256Hex(`funding-finder-verification-v1|${person.manageToken}|watch-1|${nonce}`);
    const store = new D1AlertStore(new SqliteD1(database));
    await store.createSubscriptionCycle(await cycle({
      verificationNonce: nonce,
      verificationTokenHash: await sha256Hex(token),
      verificationEventId: `verify-${item.name}`,
      verificationEventKey: `verification:${await sha256Hex(token)}`,
    }));
    const provider = new ScriptedProvider([{ code: "provider_network_failure", retryable: true }]);
    const sendEnv = item.signingSecret
      ? { ...env, ALERT_CAPABILITY_SECRET: item.signingSecret, ALERT_CAPABILITY_PREVIOUS_SECRET: "older-test-secret" }
      : { ...env, ALERT_CAPABILITY_SECRET: "", ALERT_CAPABILITY_PREVIOUS_SECRET: "" };
    const first = await dispatchVerificationDeliveries({ store, provider, env: sendEnv, now: fixedNow });
    assert.equal(first.failedCount, 1, item.name);
    const reservedKey = database.prepare(
      "SELECT provider_quota_key FROM notification_events WHERE id = ?",
    ).get(`verify-${item.name}`).provider_quota_key;

    const retried = await dispatchVerificationDeliveries({
      store, provider, env, now: new Date("2026-09-01T12:06:00.000Z"),
    });
    assert.deepEqual(retried, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 }, item.name);
    assert.equal(provider.attempts[0].idempotencyKey, reservedKey, item.name);
    assert.equal(provider.attempts[1].idempotencyKey, reservedKey, item.name);
    assert.equal(provider.attempts[0].message.text, provider.attempts[1].message.text, item.name);
  }
});

test("FF-BUG-008 verification completion serializes with an authorized provider send", async () => {
  for (const finalFailure of [
    null,
    { code: "provider_network_failure", providerFailureKind: "network", retryable: true },
    { code: "provider_rate_limited", providerFailureKind: "http", providerHttpStatus: 429, retryable: true },
  ]) {
    const database = databaseThrough();
    insertSubscriber(database);
    const store = new D1AlertStore(new SqliteD1(database));
    const verificationCycle = await cycle();
    await store.createSubscriptionCycle(verificationCycle);
    const provider = new ScriptedProvider(finalFailure ? [finalFailure] : []);
    const limitedEnv = { ...env, DAILY_EMAIL_LIMIT: "1" };
    const originalReserve = store.reserveProviderMessage.bind(store);
    let completed = false;
    store.reserveProviderMessage = async (...args) => {
      const reserved = await originalReserve(...args);
      if (reserved && !completed) {
        completed = true;
        await store.verifySubscription(
          verificationCycle.verificationTokenHash, "2026-09-01T12:06:00.000Z",
        );
      }
      return reserved;
    };
    const first = await dispatchVerificationDeliveries({
      store, provider, env: limitedEnv, now: fixedNow,
    });
    assert.equal(first.attemptedCount, 1);
    assert.equal(provider.attempts.length, 1);
    assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 1);
    assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
    const event = database.prepare("SELECT status,error_code,terminal_at FROM notification_events WHERE id='verify-new'").get();
    if (finalFailure?.providerFailureKind === "network") {
      assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
      assert.equal(event.status, "failed");
      assert.equal(event.error_code, "verification_outcome_reconcile");
      assert.equal(event.terminal_at, null);
      const recovered = await dispatchVerificationDeliveries({
        store, provider, env: limitedEnv, now: new Date("2026-09-01T12:06:00.000Z"),
      });
      assert.deepEqual(recovered, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
      assert.equal(provider.attempts.length, 2);
      assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
      const sent = database.prepare("SELECT status,error_code,terminal_at,provider_message_id FROM notification_events WHERE id='verify-new'").get();
      assert.equal(sent.status, "sent");
      assert.equal(sent.error_code, null);
      assert.equal(sent.terminal_at, null);
      assert.equal(sent.provider_message_id, "provider-1");
    } else if (finalFailure) {
      assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
      assert.equal(event.status, "suppressed");
      assert.equal(event.error_code, "verification_completed");
      assert.ok(event.terminal_at);
      assert.equal((await dispatchVerificationDeliveries({
        store, provider, env: limitedEnv, now: new Date("2026-09-01T12:20:00.000Z"),
      })).attemptedCount, 0);
    } else {
      assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
      assert.equal(event.status, "sent");
      assert.equal(event.error_code, null);
      assert.equal(event.terminal_at, null);
    }
  }
});

test("FF-BUG-008 refresh cannot overwrite a newer cycle and current claims block re-creation", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  const original = await cycle({ verificationExpiresAt: "2026-09-01T12:30:00.000Z" });
  await store.createSubscriptionCycle(original);
  const [candidate] = await store.pendingVerificationEvents(fixedNow.toISOString(), 1);
  assert.deepEqual(await store.claimEvents([candidate.id], fixedNow.toISOString()), [candidate.id]);

  const attemptedRecreation = await store.createSubscriptionCycle(await cycle({
    verificationTokenHash: "newer-cycle-token",
    verificationEventId: "verify-newer-cycle",
    verificationEventKey: "verification:newer-cycle-token",
  }));
  assert.equal(attemptedRecreation.cycleAccepted, false);
  assert.equal(database.prepare("SELECT verification_token_hash FROM subscriptions WHERE id='watch-1'").get().verification_token_hash, original.verificationTokenHash);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE id='verify-newer-cycle'").get().count, 0);

  database.prepare("UPDATE subscriptions SET verification_token_hash='externally-newer-token' WHERE id='watch-1'").run();
  const refreshed = await store.refreshVerificationEvent(candidate.id, {
    nonce: "r".repeat(43), tokenHash: "refreshed-token",
    expectedTokenHash: original.verificationTokenHash,
    expiresAt: "2026-09-02T12:00:00.000Z", eventKey: "verification:refreshed-token",
    claimedAt: fixedNow.toISOString(), now: fixedNow.toISOString(),
  });
  assert.equal(refreshed, false);
  assert.equal(database.prepare("SELECT verification_token_hash FROM subscriptions WHERE id='watch-1'").get().verification_token_hash, "externally-newer-token");
});

test("FF-BUG-008 stale verification completion cannot activate or suppress a replacement cycle", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const d1 = new SqliteD1(database);
  const store = new D1AlertStore(d1);
  const original = await cycle();
  await store.createSubscriptionCycle(original);
  const replacement = await cycle({
    verificationNonce: "n".repeat(43), verificationTokenHash: "replacement-token",
    verificationEventId: "verify-replacement", verificationEventKey: "verification:replacement-token",
  });
  d1.beforeBatch = () => store.createSubscriptionCycle(replacement);
  const verified = await store.verifySubscription(original.verificationTokenHash, fixedNow.toISOString());
  assert.equal(verified, null);
  const subscription = database.prepare("SELECT active,verification_token_hash,verified_at FROM subscriptions WHERE id='watch-1'").get();
  assert.equal(subscription.active, 0);
  assert.equal(subscription.verification_token_hash, "replacement-token");
  assert.equal(subscription.verified_at, null);
  const replacementEvent = database.prepare("SELECT status,error_code,terminal_at FROM notification_events WHERE id='verify-replacement'").get();
  assert.equal(replacementEvent.status, "queued");
  assert.equal(replacementEvent.error_code, null);
  assert.equal(replacementEvent.terminal_at, null);
});

test("FF-BUG-008 exhausted provider quota releases the claim without recording an attempt", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  await store.createSubscriptionCycle(await cycle());
  database.prepare(
    "INSERT INTO rate_limits(action,client_key,window_started_at,expires_at,request_count) VALUES('email_send','global',?,?,100)",
  ).run(fixedNow.toISOString(), "2026-09-02T12:00:00.000Z");
  const provider = new ScriptedProvider();
  const result = await dispatchVerificationDeliveries({ store, provider, env, now: fixedNow });
  assert.deepEqual(result, { attemptedCount: 0, deliveredCount: 0, failedCount: 0 });
  assert.equal(provider.messages.length, 0);
  const event = database.prepare("SELECT status,attempts,claimed_at FROM notification_events WHERE id='verify-new'").get();
  assert.equal(event.status, "queued");
  assert.equal(event.attempts, 0);
  assert.equal(event.claimed_at, null);
});

test("FF-BUG-008 permanent rejection is terminal and delayed delivery refreshes an expiring token", async () => {
  const rejectedDatabase = databaseThrough();
  insertSubscriber(rejectedDatabase);
  const rejectedStore = new D1AlertStore(new SqliteD1(rejectedDatabase));
  await rejectedStore.createSubscriptionCycle(await cycle());
  const rejectedProvider = new ScriptedProvider([{ code: "provider_rejected", retryable: false }]);
  await dispatchVerificationDeliveries({ store: rejectedStore, provider: rejectedProvider, env, now: fixedNow });
  const terminal = rejectedDatabase.prepare("SELECT * FROM notification_events WHERE id='verify-new'").get();
  assert.equal(terminal.status, "failed");
  assert.equal(terminal.error_code, "provider_rejected");
  assert.ok(terminal.terminal_at);
  assert.equal((await dispatchVerificationDeliveries({ store: rejectedStore, provider: rejectedProvider, env, now: new Date("2026-09-02T12:00:00Z") })).attemptedCount, 0);

  const delayedDatabase = databaseThrough();
  insertSubscriber(delayedDatabase);
  const delayedStore = new D1AlertStore(new SqliteD1(delayedDatabase));
  await delayedStore.createSubscriptionCycle(await cycle({
    verificationExpiresAt: "2026-09-01T12:30:00.000Z", verificationTokenHash: "old-token-hash",
  }));
  const provider = new ScriptedProvider();
  const freshNonce = "n".repeat(43);
  const freshToken = await createVerificationToken({
    subscriberId: "person-1", subscriptionId: "watch-1", nonce: freshNonce,
  }, env.ALERT_CAPABILITY_SECRET);
  await dispatchVerificationDeliveries({
    store: delayedStore, provider, env, now: fixedNow, tokenFactory: () => freshNonce,
  });
  const refreshed = delayedDatabase.prepare("SELECT verification_token_hash,verification_expires_at FROM subscriptions WHERE id='watch-1'").get();
  assert.equal(refreshed.verification_token_hash, await sha256Hex(freshToken));
  assert.equal(refreshed.verification_expires_at, "2026-09-02T12:00:00.000Z");
  assert.match(provider.messages[0].text, new RegExp(`/verify\\?token=${freshToken}`));
});

test("FF-BUG-008 accepted provider failure stays queued and an active duplicate sends no second verification", async () => {
  const database = databaseThrough();
  const store = new D1AlertStore(new SqliteD1(database));
  const provider = new ScriptedProvider([{ code: "provider_network_failure", retryable: true }]);
  let tokenIndex = 0;
  const tokens = ["a".repeat(43), "b".repeat(43), "c".repeat(43), "d".repeat(43)];
  const handler = createHandler({
    storeFactory: () => store, providerFactory: () => provider, now: () => fixedNow,
    tokenFactory: () => tokens[tokenIndex++] || "z".repeat(43),
  });
  const accepted = await post(handler, "/subscriptions", opportunityBody());
  assert.equal(accepted.status, 202);
  assert.deepEqual(await accepted.json(), { status: "verification_required" });
  const failed = database.prepare("SELECT * FROM notification_events WHERE message_kind='verification'").get();
  assert.equal(failed.status, "failed");
  assert.equal(failed.terminal_at, null);

  const retryNow = new Date("2026-09-01T12:06:00.000Z");
  await dispatchVerificationDeliveries({ store, provider, env, now: retryNow });
  assert.equal(provider.messages.length, 1);
  const verifyToken = new URL(provider.messages[0].text.match(/Activate it: (\S+)/)[1]).searchParams.get("token");
  const verifyHandler = createHandler({
    storeFactory: () => store, providerFactory: () => provider, now: () => retryNow,
    tokenFactory: () => tokens[tokenIndex++] || "y".repeat(43),
  });
  assert.equal((await verifyHandler(new Request(`https://alerts.example.test/verify?token=${verifyToken}`), env)).status, 200);
  const duplicate = await post(verifyHandler, "/subscriptions", opportunityBody());
  assert.equal(duplicate.status, 202);
  assert.deepEqual(await duplicate.json(), { status: "verification_required" });
  assert.equal(provider.messages.length, 1);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE message_kind='verification'").get().count, 1);
});

test("FF-BUG-006 multi-alert digest and immediate unsubscribe semantics are exact in HTML and text", () => {
  const base = {
    id: "event-1", subscription_id: "watch-1", subscriber_id: "person-1",
    email: "researcher@example.edu", manage_token: "m".repeat(43),
    event_kind: "amended", payload_json: JSON.stringify({ title: "One" }),
  };
  const digest = digestEmail({ env, events: [base, { ...base, id: "event-2", subscription_id: "watch-2" }] });
  assert.match(digest.text, /Manage all alerts:/);
  assert.match(digest.html, />Manage all alerts</);
  assert.match(digest.text, /Unsubscribe from all Funding Finder email alerts:/);
  assert.match(digest.html, />Unsubscribe from all Funding Finder email alerts</);
  assert.match(digest.headers["List-Unsubscribe"], /scope=all/);
  assert.doesNotMatch(digest.headers["List-Unsubscribe"], /subscription=/);
  const immediate = eventEmail({ env, event: base });
  assert.match(immediate.text, /Unsubscribe from this alert:/);
  assert.match(immediate.html, />Unsubscribe from this alert</);
  assert.match(immediate.headers["List-Unsubscribe"], /subscription=watch-1/);
  assert.doesNotMatch(immediate.headers["List-Unsubscribe"], /scope=all/);
});

test("FF-BUG-006 one-click all-alert unsubscribe deactivates both alerts while single-alert scope leaves the other active", async () => {
  const database = databaseThrough();
  const person = insertSubscriber(database);
  insertSubscription(database, { id: "watch-1", active: 1, definitionHash: "hash-1" });
  insertSubscription(database, { id: "watch-2", active: 1, definitionHash: "hash-2" });
  const store = new D1AlertStore(new SqliteD1(database));
  const handler = createHandler({ storeFactory: () => store, providerFactory: () => new MockEmailProvider(), now: () => fixedNow });
  const single = await handler(new Request(`https://alerts.example.test/unsubscribe?token=${person.manageToken}&subscription=watch-1`, { method: "POST" }), env);
  assert.equal(single.status, 200);
  assert.match(await single.text(), /unsubscribed from this Funding Finder alert/);
  assert.deepEqual(all(database, "SELECT id,active FROM subscriptions ORDER BY id").map(row => [row.id, row.active]), [["watch-1", 0], ["watch-2", 1]]);
  const allResponse = await handler(new Request(`https://alerts.example.test/unsubscribe?token=${person.manageToken}&scope=all`, { method: "POST" }), env);
  assert.equal(allResponse.status, 200);
  assert.match(await allResponse.text(), /unsubscribed from all Funding Finder email alerts/);
  assert.deepEqual(all(database, "SELECT active FROM subscriptions").map(row => row.active), [0, 0]);
  const manage = await handler(new Request(`https://alerts.example.test/manage?token=${person.manageToken}`), env);
  const manageText = await manage.text();
  assert.doesNotMatch(manageText, />Active</);
  assert.match(manageText, /Unsubscribe from all Funding Finder email alerts/);
});

test("FF-BUG-007 health is green only for the complete production delivery matrix", async () => {
  for (const enabled of [false, true]) {
    for (const databaseReady of [false, true]) {
      for (const providerConfigured of [false, true]) {
        for (const outbound of [false, true]) {
          const handler = createHandler({
            storeFactory: () => ({ health: async () => databaseReady }),
            providerFactory: () => ({ configured: providerConfigured }),
          });
          const activeEnv = {
            ...env,
            ALERTS_API_ENABLED: String(enabled),
            OUTBOUND_EMAIL_ENABLED: String(outbound),
          };
          const response = await handler(new Request("https://alerts.example.test/health"), activeEnv);
          const payload = await response.json();
          const ready = enabled && databaseReady && providerConfigured && outbound;
          assert.equal(response.status, ready ? 200 : 503);
          assert.equal(payload.delivery_ready, ready);
          assert.equal(payload.service, ready ? "available" : "unavailable");
          assert.equal(payload.database_ready, databaseReady);
          assert.equal(payload.email_provider_configured, providerConfigured);
          assert.equal(payload.outbound_email_enabled, outbound);
          assert.equal(payload.scheduler_ready, true);
          assert.doesNotMatch(JSON.stringify(payload), /test-only|RESEND_API_KEY/i);
        }
      }
    }
  }
  const handler = createHandler({
    storeFactory: () => ({ health: async () => true }), providerFactory: () => ({ configured: true }),
  });
  const noScheduler = await handler(new Request("https://alerts.example.test/health"), { ...env, ALERT_SCHEDULER_ENABLED: "false" });
  assert.equal(noScheduler.status, 503);
  assert.equal((await noScheduler.json()).scheduler_ready, false);
  const wrongProvider = await handler(new Request("https://alerts.example.test/health"), { ...env, EMAIL_PROVIDER: "mock" });
  assert.equal(wrongProvider.status, 503);
  assert.equal((await wrongProvider.json()).email_provider_selected, false);
  const noPreviousKey = await handler(new Request("https://alerts.example.test/health"), {
    ...env, ALERT_CAPABILITY_PREVIOUS_SECRET: "",
  });
  assert.equal(noPreviousKey.status, 503);
  assert.equal((await noPreviousKey.json()).capability_previous_signing_ready, false);
  const pendingHandler = createHandler({
    storeFactory: () => ({
      health: async () => true,
      operationalHealth: async () => ({
        staleRunningRuns: 0, schedulerRecent: false,
        pendingEvaluationWindows: 2,
        oldestPendingEvaluationWindow: "2026-09-06T13:15:00.000Z",
      }),
    }),
    providerFactory: () => ({ configured: true }),
  });
  const pendingResponse = await pendingHandler(
    new Request("https://alerts.example.test/health"), env,
  );
  const pendingPayload = await pendingResponse.json();
  assert.equal(pendingResponse.status, 503);
  assert.equal(pendingPayload.scheduler_ready, false);
  assert.equal(pendingPayload.pending_evaluation_windows, 2);
  assert.equal(pendingPayload.oldest_pending_evaluation_window, "2026-09-06T13:15:00.000Z");
});

test("FF-BUG-009 suppressed subscribers receive a generic response but cannot become apparently active", async () => {
  const database = databaseThrough();
  const email = "suppressed@example.edu";
  const subscriberId = `person_${(await sha256Hex(email)).slice(0, 24)}`;
  insertSubscriber(database, {
    id: subscriberId, email, manageToken: "s".repeat(43),
    suppressedAt: "2026-08-15T00:00:00.000Z", suppressionReason: "email.bounced",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const provider = new MockEmailProvider();
  let tokenIndex = 0;
  const tokens = ["v".repeat(43), "m".repeat(43)];
  const handler = createHandler({
    storeFactory: () => store, providerFactory: () => provider, now: () => fixedNow,
    tokenFactory: () => tokens[tokenIndex++] || "x".repeat(43),
  });
  const response = await post(handler, "/subscriptions", opportunityBody(email));
  assert.equal(response.status, 202);
  assert.deepEqual(await response.json(), { status: "verification_required" });
  assert.equal(provider.messages.length, 0);
  const verification = database.prepare("SELECT * FROM notification_events WHERE message_kind='verification'").get();
  assert.equal(verification.status, "suppressed");
  assert.equal(verification.error_code, "subscriber_suppressed");
  const subscriptionId = database.prepare("SELECT id FROM subscriptions").get().id;
  const verificationToken = await createVerificationToken({
    subscriberId, subscriptionId, nonce: tokens[0],
  }, env.ALERT_CAPABILITY_SECRET);
  const verify = await handler(new Request(`https://alerts.example.test/verify?token=${verificationToken}`), env);
  assert.equal(verify.status, 200);
  assert.match(await verify.text(), /delivery remains suppressed/i);
  assert.equal(database.prepare("SELECT active FROM subscriptions").get().active, 0);
  assert.equal((await store.activeSubscriptions()).length, 0);
  const manage = await handler(new Request(`https://alerts.example.test/manage?token=${"s".repeat(43)}`), env);
  const manageText = await manage.text();
  assert.match(manageText, /Email delivery is suppressed/);
  assert.match(manageText, /Delivery to this address bounced/);
  assert.doesNotMatch(manageText, />Resume</);

  const normal = await post(handler, "/subscriptions", opportunityBody("new-address@example.edu"));
  assert.equal(normal.status, 202);
  assert.deepEqual(await normal.json(), { status: "verification_required" });
  assert.equal(provider.messages.length, 1);
});

test("FF-BUG-008 verification provider IDs correlate with suppression webhooks", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  await store.createSubscriptionCycle(await cycle());
  const provider = new ScriptedProvider();
  await dispatchVerificationDeliveries({ store, provider, env, now: fixedNow });
  insertEvent(database, { id: "queued-after-verification", createdAt: fixedNow.toISOString() });
  assert.equal(await store.suppressSubscriberByMessage("provider-1", "email.complained", "webhook-1", fixedNow.toISOString()), true);
  assert.ok(database.prepare("SELECT suppressed_at FROM subscribers WHERE id='person-1'").get().suppressed_at);
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 0);
  assert.equal(database.prepare(
    "SELECT terminal_at FROM notification_events WHERE id='queued-after-verification'",
  ).get().terminal_at, fixedNow.toISOString());
  assert.equal(await store.suppressSubscriberByMessage("provider-1", "email.complained", "webhook-1", fixedNow.toISOString()), false);
});

test("FF-BUG-008 recovered provider IDs and pending webhook suppression commit atomically", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1, cadence: "immediate" });
  const d1 = new SqliteD1(database);
  const store = new D1AlertStore(d1);
  await store.enqueueEvent({
    id: "atomic-correlation", subscriptionId: "watch-1", eventKey: "atomic-correlation",
    eventKind: "amended", opportunityId: "opp-atomic",
    payload: { title: "Atomic correlation" }, createdAt: fixedNow.toISOString(),
  });
  assert.equal(await store.suppressSubscriberByMessage(
    "provider-atomic", "email.complained", "webhook-atomic", fixedNow.toISOString(),
  ), false);
  const provider = {
    configured: true,
    attempts: [],
    async sendEmail(message, idempotencyKey) {
      this.attempts.push({ message, idempotencyKey });
      if (this.attempts.length === 1) d1.failBatchAt = 2;
      return { id: "provider-atomic" };
    },
  };
  await assert.rejects(
    dispatchNotifications({ store, provider, env, now: fixedNow }),
    /deterministic batch failure/,
  );
  const rolledBack = database.prepare(
    "SELECT status,provider_message_id,claimed_at FROM notification_events WHERE id='atomic-correlation'",
  ).get();
  assert.deepEqual(
    [rolledBack.status, rolledBack.provider_message_id, rolledBack.claimed_at],
    ["sending", null, fixedNow.toISOString()],
  );
  assert.equal(database.prepare("SELECT suppressed_at FROM subscribers WHERE id='person-1'").get().suppressed_at, null);
  d1.failBatchAt = null;
  const recovered = await dispatchNotifications({
    store, provider, env, now: new Date("2026-09-01T12:16:00.000Z"),
  });
  assert.deepEqual(recovered, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
  assert.equal(provider.attempts.length, 2);
  assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
  assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
  const committed = database.prepare(
    "SELECT status,provider_message_id FROM notification_events WHERE id='atomic-correlation'",
  ).get();
  assert.deepEqual([committed.status, committed.provider_message_id], ["sent", "provider-atomic"]);
  const subscriber = database.prepare(
    "SELECT suppressed_at,suppression_reason FROM subscribers WHERE id='person-1'",
  ).get();
  assert.deepEqual(
    [subscriber.suppressed_at, subscriber.suppression_reason],
    [fixedNow.toISOString(), "email.complained"],
  );
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 0);
});

test("FF-BUG-017 weekly selection is subscriber-fair, capped, mobile-readable, and leaves overflow queued", async () => {
  const database = databaseThrough();
  insertSubscriber(database, { id: "person-a", email: "a@example.edu", manageToken: "a".repeat(43) });
  insertSubscriber(database, { id: "person-b", email: "b@example.edu", manageToken: "b".repeat(43) });
  insertSubscription(database, { id: "watch-a", subscriberId: "person-a", active: 1, definitionHash: "hash-a" });
  insertSubscription(database, { id: "watch-b", subscriberId: "person-b", active: 1, definitionHash: "hash-b" });
  const store = new D1AlertStore(new SqliteD1(database));
  for (let index = 0; index < DIGEST_MAX_EVENTS + 5; index += 1) {
    await store.enqueueEvent({
      id: `a-${String(index).padStart(2, "0")}`, subscriptionId: "watch-a", eventKey: `a-${index}`,
      eventKind: "amended", opportunityId: `a-${index}`,
      payload: { title: `Subscriber A update ${index}` }, createdAt: fixedNow.toISOString(),
    });
  }
  await store.enqueueEvent({
    id: "b-00", subscriptionId: "watch-b", eventKey: "b-0", eventKind: "amended",
    opportunityId: "b-0", payload: { title: "Subscriber B update" }, createdAt: fixedNow.toISOString(),
  });
  const provider = new ScriptedProvider();
  const result = await dispatchNotifications({
    store, provider, env: { ...env, DAILY_EMAIL_LIMIT: "2" }, now: fixedNow, weekly: true,
  });
  assert.deepEqual(result, { attemptedCount: 2, deliveredCount: 2, failedCount: 0 });
  assert.deepEqual(provider.messages.map(message => message.to).sort(), ["a@example.edu", "b@example.edu"]);
  const large = provider.messages.find(message => message.to === "a@example.edu");
  assert.match(large.subject, new RegExp(`${DIGEST_MAX_EVENTS} updates`));
  assert.match(large.text, /Additional updates remain queued for a later digest/);
  assert.match(large.html, /Additional updates remain queued for a later digest/);
  assert.match(large.html, /name="viewport" content="width=device-width,initial-scale=1"/);
  assert.match(large.html, /width:calc\(100% - 24px\)/);
  assert.ok(Buffer.byteLength(large.html) < 200_000);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE subscription_id='watch-a' AND status='queued'").get().count, 5);
  assert.equal(database.prepare("SELECT status FROM notification_events WHERE id='b-00'").get().status, "sent");
});

test("FF-BUG-017 reactivation reconciliation preserves the exact digest group and idempotency", async () => {
  const database = databaseThrough();
  const person = insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "weekly", definitionHash: "hash-old",
  });
  insertSubscription(database, {
    id: "watch-2", subscriberId: person.id, active: 1, cadence: "weekly",
    definitionHash: "hash-two", tokenHash: "token-two",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  for (const [id, subscriptionId] of [["digest-a", "watch-1"], ["digest-b", "watch-2"]]) {
    await store.enqueueEvent({
      id, subscriptionId, eventKey: id, eventKind: "amended",
      opportunityId: id, payload: { title: id }, createdAt: fixedNow.toISOString(),
    });
  }
  const provider = {
    configured: true,
    attempts: [],
    async sendEmail(message, idempotencyKey) {
      this.attempts.push({ message, idempotencyKey });
      if (this.attempts.length === 1) {
        throw Object.assign(new Error("bounded provider failure"), {
          code: "provider_network_failure", providerFailureKind: "network", retryable: true,
        });
      }
      return { id: "provider-digest-reconciled" };
    },
  };
  const first = await dispatchNotifications({ store, provider, env, now: fixedNow, weekly: true });
  assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
  assert.deepEqual(
    all(database, "SELECT status,error_code,terminal_at FROM notification_events WHERE id LIKE 'digest-%' ORDER BY id")
      .map(event => [event.status, event.error_code, event.terminal_at]),
    [
      ["failed", "provider_outcome_reconcile", null],
      ["failed", "provider_outcome_reconcile", null],
    ],
  );
  assert.equal(await store.updateSubscription(
    person.manageToken, "watch-1", { active: false }, fixedNow.toISOString(),
  ), true);
  assert.equal((await store.createSubscriptionCycle(await cycle({
    verificationNonce: "z".repeat(43), verificationTokenHash: "replacement-token",
    verificationEventId: "verify-replacement", verificationEventKey: "verification:replacement-token",
  }))).cycleAccepted, true);
  assert.deepEqual(
    all(database, "SELECT status,error_code,terminal_at FROM notification_events WHERE id LIKE 'digest-%' ORDER BY id")
      .map(event => [event.status, event.error_code, event.terminal_at]),
    [["failed", "provider_outcome_reconcile", null], ["failed", "provider_outcome_reconcile", null]],
  );
  assert.equal(await store.suppressSubscriberByMessage(
    "provider-digest-reconciled", "email.bounced", "webhook-before-correlation", fixedNow.toISOString(),
  ), false);
  assert.equal(database.prepare("SELECT suppressed_at FROM subscribers WHERE id='person-1'").get().suppressed_at, null);
  const recovered = await Promise.all([1, 2].map(() => dispatchNotifications({
    store, provider, env, now: new Date("2026-09-01T12:06:00.000Z"), weekly: false,
  })));
  assert.equal(recovered.reduce((sum, item) => sum + item.attemptedCount, 0), 1);
  assert.equal(recovered.reduce((sum, item) => sum + item.deliveredCount, 0), 1);
  assert.equal(recovered.reduce((sum, item) => sum + item.failedCount, 0), 0);
  assert.equal(provider.attempts.length, 2);
  assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
  assert.match(provider.attempts[1].idempotencyKey, /^digest:/);
  assert.match(provider.attempts[1].message.subject, /weekly digest: 2 updates/);
  assert.deepEqual(
    all(database, "SELECT status,provider_message_id FROM notification_events WHERE id LIKE 'digest-%' ORDER BY id")
      .map(event => [event.status, event.provider_message_id]),
    [["sent", "provider-digest-reconciled"], ["sent", "provider-digest-reconciled"]],
  );
  const suppressed = database.prepare(
    "SELECT suppressed_at,suppression_reason FROM subscribers WHERE id='person-1'",
  ).get();
  assert.deepEqual(
    [suppressed.suppressed_at, suppressed.suppression_reason],
    [fixedNow.toISOString(), "email.bounced"],
  );
  assert.deepEqual(
    all(database, "SELECT id,active FROM subscriptions ORDER BY id").map(row => [row.id, row.active]),
    [["watch-1", 0], ["watch-2", 0]],
  );
  assert.equal(database.prepare("SELECT status FROM notification_events WHERE id='verify-replacement'").get().status, "suppressed");
  assert.equal(database.prepare("SELECT terminal_at FROM notification_events WHERE id='verify-replacement'").get().terminal_at, fixedNow.toISOString());
});

test("FF-BUG-017 a failed digest retries the whole claim with the same idempotency key", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  const store = new D1AlertStore(new SqliteD1(database));
  for (let index = 0; index < DIGEST_MAX_EVENTS + 1; index += 1) {
    const id = `digest-${String(index).padStart(2, "0")}`;
    await store.enqueueEvent({
      id, subscriptionId: "watch-1", eventKey: id, eventKind: "amended",
      opportunityId: id, payload: { title: id }, createdAt: fixedNow.toISOString(),
    });
  }
  const provider = new ScriptedProvider([{ code: "provider_network_failure", retryable: true }]);
  const first = await dispatchNotifications({ store, provider, env, now: fixedNow, weekly: true });
  assert.equal(first.failedCount, 1);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE status='failed'").get().count, DIGEST_MAX_EVENTS);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE status='queued'").get().count, 1);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE provider_batch_has_overflow=1").get().count, DIGEST_MAX_EVENTS);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE provider_payload_json IS NOT NULL").get().count, 1);
  assert.match(provider.attempts[0].message.text, /Additional updates remain queued for a later digest/);
  assert.match(provider.attempts[0].message.html, /Additional updates remain queued for a later digest/);
  const retryNow = new Date("2026-09-01T12:06:00.000Z");
  const second = await dispatchNotifications({
    store, provider,
    env: { ...env, PUBLIC_WORKER_ORIGIN: "https://replacement-alerts.example.test" },
    now: retryNow, weekly: false,
  });
  assert.equal(second.deliveredCount, 1);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE status='sent'").get().count, DIGEST_MAX_EVENTS);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM notification_events WHERE status='queued'").get().count, 1);
  assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
  assert.equal(provider.attempts[0].message.subject, provider.attempts[1].message.subject);
  assert.equal(provider.attempts[0].message.text, provider.attempts[1].message.text);
  assert.equal(provider.attempts[0].message.html, provider.attempts[1].message.html);
});

test("FF-BUG-017 ordinary notification retries replay the payload reserved for their key", async () => {
  for (const weekly of [false, true]) {
    const database = databaseThrough();
    insertSubscriber(database);
    insertSubscription(database, { active: 1, cadence: weekly ? "weekly" : "immediate" });
    const store = new D1AlertStore(new SqliteD1(database));
    for (const id of weekly ? ["retry-a", "retry-b"] : ["retry-a"]) {
      await store.enqueueEvent({
        id, subscriptionId: "watch-1", eventKey: id, eventKind: "amended",
        opportunityId: id, payload: { title: id }, createdAt: fixedNow.toISOString(),
      });
    }
    const provider = new ScriptedProvider([{ code: "provider_rate_limited", retryable: true }]);
    const first = await dispatchNotifications({ store, provider, env, now: fixedNow, weekly });
    assert.deepEqual(first, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
    assert.equal(database.prepare(
      "SELECT COUNT(*) AS count FROM notification_events WHERE provider_payload_json IS NOT NULL",
    ).get().count, 1);

    const second = await dispatchNotifications({
      store, provider,
      env: { ...env, PUBLIC_WORKER_ORIGIN: "https://replacement-alerts.example.test" },
      now: new Date("2026-09-01T12:06:00.000Z"), weekly,
    });
    assert.deepEqual(second, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
    assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
    assert.equal(provider.attempts[0].message.subject, provider.attempts[1].message.subject);
    assert.equal(provider.attempts[0].message.text, provider.attempts[1].message.text);
    assert.equal(provider.attempts[0].message.html, provider.attempts[1].message.html);
    assert.doesNotMatch(provider.attempts[1].message.text, /replacement-alerts\.example\.test/);
  }
});

test("Phase 2 scheduler retries verification and deployment contracts preserve rollback safety", async () => {
  const provider = new ScriptedProvider();
  let verificationDispatches = 0;
  const store = {
    pendingVerificationEvents: async () => { verificationDispatches += 1; return []; },
    startRun: async () => {},
    activeSubscriptions: async () => [],
    pendingEvents: async () => [],
    finishRun: async () => {},
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => provider,
    assetLoader: async () => ({}),
    now: () => fixedNow,
  });
  const result = await scheduled({ scheduledTime: fixedNow.getTime(), cron: "15 13 * * *" }, env);
  assert.equal(result.status, "completed");
  assert.equal(verificationDispatches, 1);

  const [workflow, wrangler, smoke, migration] = await Promise.all([
    readFile(new URL(".github/workflows/deploy-alerts.yml", root), "utf8"),
    readFile(new URL("workers/alerts/wrangler.jsonc", root), "utf8"),
    readFile(new URL("tools/smoke_alerts_worker.mjs", root), "utf8"),
    readFile(new URL("workers/alerts/migrations/0003_phase2_alert_lifecycle.sql", root), "utf8"),
  ]);
  assert.equal(ALERT_SCHEMA_VERSION, 3);
  assert.match(workflow, /delivery_ready/);
  assert.match(workflow, /scheduler_ready/);
  assert.match(workflow, /phase4-operations-20260827/);
  assert.match(workflow, /worker_version_rollback/);
  assert.match(workflow, /recovery_required=true/);
  assert.match(workflow, /scheduler recovery execution succeeds/);
  assert.match(wrangler, /"ALERT_SCHEDULER_ENABLED": "true"/);
  assert.match(wrangler, /"ALERT_SCHEDULER_TIMEOUT_MS": "600000"/);
  assert.match(wrangler, /"ALERT_SCHEDULER_DELIVERY_BATCH": "10"/);
  assert.match(wrangler, /"crons": \["15 13 \* \* \*", "2-57\/5 \* \* \* \*"\]/);
  assert.match(smoke, /delivery_ready/);
  assert.match(migration, /deployment workflow terminalizes unsent verification/);
  assert.doesNotMatch(workflow + wrangler + smoke + migration, /RESEND_API_KEY\s*[:=]\s*["']?re_/i);
});

test("FF-BUG-020 daily evaluation and retry cron minutes cannot collide", async () => {
  const wrangler = JSON.parse(await readFile(new URL("workers/alerts/wrangler.jsonc", root), "utf8"));
  assert.deepEqual(wrangler.triggers.crons, ["15 13 * * *", "2-57/5 * * * *"]);
  const retryMinutes = Array.from({ length: 12 }, (_, index) => 2 + (index * 5));
  assert.deepEqual(retryMinutes, [2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57]);
  assert.equal(retryMinutes.includes(15), false);
});

test("Resend classifies 429 and 5xx as retryable but permanent 4xx as terminal", async () => {
  const message = { to: "x@example.edu", subject: "Subject", text: "Text", html: "<p>Text</p>" };
  for (const [status, code, retryable] of [
    [429, "provider_rate_limited", true],
    [503, "provider_unavailable", true],
    [422, "provider_rejected", false],
  ]) {
    const provider = new ResendEmailProvider({
      apiKey: "private-test-key",
      fetchImpl: async () => new Response(JSON.stringify({ private: "must not escape" }), {
        status, headers: { "Content-Type": "application/json" },
      }),
    });
    await assert.rejects(provider.sendEmail(message, `status-${status}`), error => {
      assert.equal(error.code, code);
      assert.equal(error.retryable, retryable);
      assert.doesNotMatch(error.message, /must not escape/);
      return true;
    });
  }
});

test("0004 migrates representative Phase 3 production state without exposing new raw capabilities", async () => {
  const database = databaseThrough(3);
  insertSubscriber(database);
  insertSubscriber(database, {
    id: "person-suppressed", email: "suppressed@example.edu", manageToken: "s".repeat(43),
    suppressedAt: "2026-08-20T00:00:00.000Z", suppressionReason: "email.bounced",
  });
  insertSubscription(database, { id: "watch-active", active: 1, definitionHash: "hash-active" });
  insertSubscription(database, { id: "watch-inactive", active: 0, definitionHash: "hash-inactive" });
  insertSubscription(database, {
    id: "watch-unverified", active: 0, verifiedAt: null, definitionHash: "hash-unverified",
  });
  insertSubscription(database, {
    id: "watch-suppressed", subscriberId: "person-suppressed", active: 0,
    definitionHash: "hash-suppressed",
  });
  for (const status of ["queued", "failed", "sending", "sent"]) {
    insertEvent(database, {
      id: `legacy-${status}`, subscriptionId: "watch-active", status,
    });
  }
  insertEvent(database, {
    id: "legacy-provider-reconcile", subscriptionId: "watch-active", status: "failed",
  });
  database.prepare(
    "UPDATE notification_events SET error_code='provider_outcome_reconcile',provider_quota_key='quota-legacy',provider_quota_reserved_at='2026-08-26T13:15:00.000Z' WHERE id='legacy-provider-reconcile'",
  ).run();
  const lifecycleBefore = all(database,
    "SELECT id,status,error_code,claimed_at,provider_quota_key FROM notification_events ORDER BY id",
  );
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,status) VALUES('stuck','2026-08-26T13:15:00.000Z','running')",
  ).run();
  database.exec(migrations[3]);
  const subscriber = database.prepare(
    "SELECT capability_version,legacy_manage_expires_at,manage_token FROM subscribers WHERE id='person-1'",
  ).get();
  assert.equal(subscriber.capability_version, 0);
  assert.equal(subscriber.legacy_manage_expires_at, "2026-11-30T23:59:59.999Z");
  assert.equal(subscriber.manage_token, "m".repeat(43));
  const recovered = database.prepare(
    "SELECT status,completed_at,duration_ms,scheduled_at FROM evaluation_runs WHERE id='stuck'",
  ).get();
  assert.equal(recovered.status, "failed_stale_recovered");
  assert.ok(recovered.completed_at);
  assert.ok(recovered.duration_ms > 0);
  assert.equal(recovered.scheduled_at, "2026-08-26T13:15:00.000Z");
  assert.ok(database.prepare(
    "SELECT id FROM evaluation_runs WHERE id='phase4_migration_ready'",
  ).get());
  assert.deepEqual(all(database,
    "SELECT id,status,error_code,claimed_at,provider_quota_key FROM notification_events ORDER BY id",
  ), lifecycleBefore);
  assert.deepEqual(all(database,
    "SELECT id,active,verified_at FROM subscriptions ORDER BY id",
  ).map(row => [row.id, row.active, row.verified_at]), [
    ["watch-active", 1, "2026-08-01T00:00:00.000Z"],
    ["watch-inactive", 0, "2026-08-01T00:00:00.000Z"],
    ["watch-suppressed", 0, "2026-08-01T00:00:00.000Z"],
    ["watch-unverified", 0, null],
  ]);
  assert.equal(database.prepare(
    "SELECT suppression_reason FROM subscribers WHERE id='person-suppressed'",
  ).get().suppression_reason, "email.bounced");
});

test("FF-BUG-010 atomic subscription limits admit exactly the configured concurrent total", async () => {
  const database = databaseThrough();
  const store = new D1AlertStore(new SqliteD1(database));
  const accepted = await Promise.all(Array.from({ length: 8 }, () => (
    store.consumeRateLimit("subscribe", "derived-not-an-ip", 5, 3_600, fixedNow)
  )));
  assert.equal(accepted.filter(Boolean).length, 5);
  assert.equal(database.prepare(
    "SELECT request_count FROM rate_limits WHERE action='subscribe' AND client_key='derived-not-an-ip'",
  ).get().request_count, 5);
  assert.equal(await store.consumeRateLimit("manage", "derived-not-an-ip", 1, 3_600, fixedNow), true);
  assert.equal(await store.consumeRateLimit("manage", "derived-not-an-ip", 1, 3_600, fixedNow), false);
  assert.equal(await store.consumeRateLimit(
    "subscribe", "derived-not-an-ip", 5, 3_600,
    new Date("2026-09-01T13:00:00.001Z"),
  ), true);
  assert.equal(database.prepare(
    "SELECT request_count FROM rate_limits WHERE action='subscribe' AND client_key='derived-not-an-ip'",
  ).get().request_count, 1);
});

test("FF-BUG-010 request limits store only a bounded derived client key", async () => {
  const database = databaseThrough();
  const store = new D1AlertStore(new SqliteD1(database));
  const handler = createHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    now: () => fixedNow,
    tokenFactory: () => "n".repeat(43),
  });
  const rawAddress = "203.0.113.17";
  const response = await post(
    handler, "/subscriptions", opportunityBody("derived-key@example.edu"), env,
    { "cf-connecting-ip": rawAddress },
  );
  assert.equal(response.status, 202);
  const stored = database.prepare(
    "SELECT action,client_key FROM rate_limits WHERE action='subscribe'",
  ).get();
  assert.equal(stored.action, "subscribe");
  assert.match(stored.client_key, /^[a-f0-9]{64}$/);
  assert.notEqual(stored.client_key, rawAddress);
  assert.doesNotMatch(JSON.stringify(all(database, "SELECT * FROM rate_limits")), /203\.0\.113\.17/);
});

test("new subscriptions dispatch their own durable verification event instead of an older backlog row", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const store = new D1AlertStore(new SqliteD1(database));
  await store.createSubscriptionCycle(await cycle({
    verificationEventId: "verify-old-backlog",
    verificationEventKey: "verification:old-backlog",
  }));
  const provider = new ScriptedProvider();
  const handler = createHandler({
    storeFactory: () => store, providerFactory: () => provider,
    now: () => fixedNow, tokenFactory: () => "n".repeat(43),
  });
  const response = await post(handler, "/subscriptions", opportunityBody("new-address@example.edu"));
  assert.equal(response.status, 202);
  assert.deepEqual(await response.json(), { status: "verification_required" });
  assert.equal(provider.messages.length, 1);
  assert.equal(provider.messages[0].to, "new-address@example.edu");
  assert.equal(database.prepare(
    "SELECT status FROM notification_events WHERE id='verify-old-backlog'",
  ).get().status, "queued");
  const delivered = database.prepare(
    "SELECT status,provider_message_id FROM notification_events WHERE id <> 'verify-old-backlog' AND message_kind='verification'",
  ).get();
  assert.deepEqual([delivered.status, delivered.provider_message_id], ["sent", "provider-1"]);
});

test("FF-BUG-018 retention is bounded and preserves recent, active, and retryable state", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  for (const id of ["expired-a", "expired-b"]) {
    database.prepare(
      "INSERT INTO rate_limits(action,client_key,window_started_at,expires_at,request_count) VALUES('verify',?,?,?,1)",
    ).run(id, "2025-01-01T00:00:00.000Z", "2025-01-01T01:00:00.000Z");
  }
  database.prepare(
    "INSERT INTO rate_limits(action,client_key,window_started_at,expires_at,request_count) VALUES('verify','recent','2026-09-01T11:00:00.000Z','2026-09-01T13:00:00.000Z',1)",
  ).run();
  insertEvent(database, { id: "old-sent", status: "sent", createdAt: "2025-01-01T00:00:00.000Z" });
  database.prepare(
    "UPDATE notification_events SET sent_at='2025-01-01T00:00:00.000Z' WHERE id='old-sent'",
  ).run();
  insertEvent(database, { id: "recent-sent", status: "sent", createdAt: fixedNow.toISOString() });
  database.prepare(
    "UPDATE notification_events SET sent_at=? WHERE id='recent-sent'",
  ).run(fixedNow.toISOString());
  insertEvent(database, { id: "old-suppressed", status: "suppressed", createdAt: "2025-01-01T00:00:00.000Z" });
  database.prepare(
    "UPDATE notification_events SET terminal_at='2025-01-01T00:00:00.000Z' WHERE id='old-suppressed'",
  ).run();
  insertEvent(database, { id: "old-verification", status: "failed", createdAt: "2025-01-01T00:00:00.000Z" });
  database.prepare(
    "UPDATE notification_events SET message_kind='verification',terminal_at='2025-01-01T00:00:00.000Z' WHERE id='old-verification'",
  ).run();
  insertEvent(database, { id: "old-retry", status: "failed", createdAt: "2025-01-01T00:00:00.000Z" });
  database.prepare(
    "UPDATE notification_events SET terminal_at=NULL,next_attempt_at='2026-09-02T00:00:00.000Z' WHERE id='old-retry'",
  ).run();
  database.prepare(
    "INSERT INTO provider_events VALUES('provider-old','email.delivered','message-old','2025-01-01T00:00:00.000Z')",
  ).run();
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind) VALUES('run-old','2025-01-01T00:00:00.000Z','2025-01-01T00:00:01.000Z','completed','2025-01-01T00:00:00.000Z',1000,'daily')",
  ).run();
  const store = new D1AlertStore(new SqliteD1(database));
  const first = await store.cleanupOperationalData(fixedNow.toISOString(), 1);
  assert.equal(first.batchSize, 1);
  assert.ok(first.deletedCount >= 4);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM rate_limits WHERE client_key LIKE 'expired-%'").get().count, 1);
  for (let index = 0; index < 3; index += 1) {
    await store.cleanupOperationalData(fixedNow.toISOString(), 1);
  }
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM rate_limits WHERE client_key LIKE 'expired-%'").get().count, 0);
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM notification_events WHERE id IN ('old-sent','old-suppressed','old-verification')",
  ).get().count, 0);
  assert.ok(database.prepare("SELECT id FROM notification_events WHERE id='recent-sent'").get());
  assert.ok(database.prepare("SELECT client_key FROM rate_limits WHERE client_key='recent'").get());
  assert.ok(database.prepare("SELECT id FROM notification_events WHERE id='old-retry'").get());
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 1);
  assert.deepEqual(RETENTION_DAYS, {
    rateLimits: 30, evaluationRuns: 90, terminalDeliveries: 90, providerEvents: 180,
  });
});

test("FF-BUG-019 signed capabilities are purpose-scoped, tamper-resistant, rotatable, and legacy-bounded", async () => {
  const secret = "current-secret-with-sufficient-entropy";
  const previousSecret = "previous-secret-with-sufficient-entropy";
  const manage = await createCapability({ subscriberId: "person-1", purpose: "manage" }, secret);
  assert.equal((await verifyCapability(manage, { secret, purpose: "manage" })).s, "person-1");
  assert.equal(await verifyCapability(manage, { secret, purpose: "unsubscribe_all" }), null);
  assert.equal(await verifyCapability(`${manage.slice(0, -1)}x`, { secret, purpose: "manage" }), null);
  const old = await createCapability({ subscriberId: "person-1", purpose: "manage" }, previousSecret);
  assert.equal((await verifyCapability(old, {
    secret, previousSecret, purpose: "manage",
  })).s, "person-1");

  const database = databaseThrough();
  const store = new D1AlertStore(new SqliteD1(database));
  const created = await store.upsertSubscriber({
    id: "person-new", email: "new@example.edu", manageToken: "retired:person-new",
    now: fixedNow.toISOString(),
  });
  assert.equal(created.capability_version, 1);
  assert.equal(created.manage_token, "retired:person-new");
  assert.equal(await store.subscriberByManageToken("retired:person-new", fixedNow.toISOString()), null);
  insertSubscriber(database, { id: "person-legacy", email: "legacy@example.edu", manageToken: "l".repeat(43) });
  assert.ok(await store.subscriberByManageToken("l".repeat(43), fixedNow.toISOString()));
  assert.equal(await store.subscriberByManageToken(
    "l".repeat(43), "2026-12-01T00:00:00.000Z",
  ), null);
});

test("FF-BUG-019 signed capabilities authorize only their exact manage and unsubscribe routes", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { id: "watch-1", active: 1, definitionHash: "hash-1" });
  insertSubscription(database, { id: "watch-2", active: 1, definitionHash: "hash-2" });
  const store = new D1AlertStore(new SqliteD1(database));
  const handler = createHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    now: () => fixedNow,
  });
  const manage = await createCapability({ subscriberId: "person-1", purpose: "manage" }, env.ALERT_CAPABILITY_SECRET);
  const unsubscribeOne = await createCapability({
    subscriberId: "person-1", purpose: "unsubscribe_one", subscriptionId: "watch-1",
  }, env.ALERT_CAPABILITY_SECRET);
  const unsubscribeAll = await createCapability({
    subscriberId: "person-1", purpose: "unsubscribe_all",
  }, env.ALERT_CAPABILITY_SECRET);

  const managePageResponse = await handler(new Request(
    `https://alerts.example.test/manage?token=${encodeURIComponent(manage)}`,
  ), env);
  assert.equal(managePageResponse.status, 200);
  assert.match(await managePageResponse.text(), /Manage Funding Finder alerts/);

  const pauseResponse = await handler(new Request("https://alerts.example.test/manage", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ token: manage, subscription: "watch-1", active: "0" }),
  }), env);
  assert.equal(pauseResponse.status, 200);
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 0);

  const wrongPurpose = await handler(new Request(
    `https://alerts.example.test/unsubscribe?token=${encodeURIComponent(manage)}&subscription=watch-1`,
    { method: "POST" },
  ), env);
  assert.equal(wrongPurpose.status, 400);

  const oneResponse = await handler(new Request(
    `https://alerts.example.test/unsubscribe?token=${encodeURIComponent(unsubscribeOne)}&subscription=watch-1`,
    { method: "POST" },
  ), env);
  assert.equal(oneResponse.status, 200);
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-2'").get().active, 1);

  const allResponse = await handler(new Request(
    `https://alerts.example.test/unsubscribe?token=${encodeURIComponent(unsubscribeAll)}&scope=all`,
    { method: "POST" },
  ), env);
  assert.equal(allResponse.status, 200);
  assert.deepEqual(all(database, "SELECT active FROM subscriptions ORDER BY id").map(row => row.active), [0, 0]);
});

test("FF-BUG-020 retry runs skip catalog loading and record actual timing plus cleanup failure", async () => {
  const times = [
    new Date("2026-09-01T12:00:01.000Z"),
    new Date("2026-09-01T12:00:03.000Z"),
    new Date("2026-09-01T12:00:05.000Z"),
  ];
  let finished;
  const store = {
    startRun: async () => {},
    pendingVerificationEvents: async () => [],
    pendingNotificationReconciliationBatches: async () => [],
    pendingEvents: async () => [],
    cleanupOperationalData: async () => { throw new Error("bounded cleanup failure"); },
    finishRun: async run => { finished = { ...run }; },
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    assetLoader: async () => { throw new Error("retry runs must not load the catalog"); },
    now: scheduledTime => {
      assert.equal(scheduledTime, undefined);
      return times.shift();
    },
  });
  const result = await scheduled({
    scheduledTime: Date.parse("2026-09-01T12:00:00.000Z"), cron: "*/5 * * * *",
  }, env);
  assert.equal(result.runKind, "retry");
  assert.equal(result.scheduledAt, "2026-09-01T12:00:00.000Z");
  assert.equal(result.startedAt, "2026-09-01T12:00:01.000Z");
  assert.equal(result.completedAt, "2026-09-01T12:00:05.000Z");
  assert.equal(result.durationMs, 4_000);
  assert.equal(result.status, "completed_with_cleanup_failure");
  assert.equal(result.cleanupErrorCode, "cleanup_failed");
  assert.deepEqual(finished, result);
});

test("FF-BUG-020 failed daily runs still record actual completion and duration", async () => {
  const times = [
    new Date("2026-09-01T12:00:01.000Z"),
    new Date("2026-09-01T12:00:04.000Z"),
    new Date("2026-09-01T12:00:07.000Z"),
  ];
  let finished;
  const store = {
    startRun: async () => {},
    pendingVerificationEvents: async () => [],
    pendingNotificationReconciliationBatches: async () => [],
    pendingEvents: async () => [],
    cleanupOperationalData: async () => ({ deletedCount: 2 }),
    finishRun: async run => { finished = { ...run }; },
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    assetLoader: async () => { throw new Error("deterministic catalog failure"); },
    now: () => times.shift(),
  });
  const result = await scheduled({
    scheduledTime: Date.parse("2026-09-01T12:00:00.000Z"), cron: "15 13 * * *",
  }, env);
  assert.equal(result.runKind, "daily");
  assert.equal(result.status, "failed");
  assert.equal(result.startedAt, "2026-09-01T12:00:01.000Z");
  assert.equal(result.completedAt, "2026-09-01T12:00:07.000Z");
  assert.equal(result.durationMs, 6_000);
  assert.equal(result.cleanupDeletedCount, 2);
  assert.deepEqual(finished, result);
});

test("FF-BUG-020 scheduler health requires a recent non-failed daily evaluation", async () => {
  const database = databaseThrough();
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind) VALUES('daily-failed','2026-09-02T11:49:00.000Z','2026-09-02T11:50:00.000Z','failed','2026-09-02T11:45:00.000Z',60000,'daily')",
  ).run();
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind) VALUES('retry-ok','2026-09-02T11:54:00.000Z','2026-09-02T11:55:00.000Z','completed','2026-09-02T11:54:00.000Z',60000,'retry')",
  ).run();
  const store = new D1AlertStore(new SqliteD1(database));
  const failedDaily = await store.operationalHealth("2026-09-02T12:00:00.000Z");
  assert.equal(failedDaily.lastCompletedAt, "2026-09-02T11:55:00.000Z");
  assert.equal(failedDaily.lastStatus, "completed");
  assert.equal(failedDaily.lastDailyCompletedAt, "2026-09-02T11:50:00.000Z");
  assert.equal(failedDaily.lastDailyStatus, "failed");
  assert.equal(failedDaily.schedulerRecent, false);

  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind) VALUES('daily-ok','2026-09-01T11:00:00.000Z','2026-09-01T11:01:00.000Z','completed_with_cleanup_failure','2026-09-01T11:00:00.000Z',60000,'daily')",
  ).run();
  const recovered = await store.operationalHealth("2026-09-02T12:00:00.000Z");
  assert.equal(recovered.lastDailyStatus, "failed");
  assert.equal(recovered.schedulerRecent, false);

  database.prepare("DELETE FROM evaluation_runs WHERE id='daily-failed'").run();
  const recentDaily = await store.operationalHealth("2026-09-02T12:00:00.000Z");
  assert.equal(recentDaily.lastDailyCompletedAt, "2026-09-01T11:01:00.000Z");
  assert.equal(recentDaily.schedulerRecent, true);
  assert.equal((await store.operationalHealth("2026-09-02T13:02:00.000Z")).schedulerRecent, false);
});

test("FF-BUG-020 subsequent runs and health terminalize abandoned scheduler runs", async () => {
  const database = databaseThrough();
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,status,scheduled_at,run_kind) VALUES('stale-daily','2026-09-02T10:00:00.000Z','running','2026-09-02T10:00:00.000Z','daily')",
  ).run();
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,status,scheduled_at,run_kind) VALUES('recent-retry','2026-09-02T11:50:00.000Z','running','2026-09-02T11:50:00.000Z','retry')",
  ).run();
  const store = new D1AlertStore(new SqliteD1(database));
  const health = await store.operationalHealth("2026-09-02T12:00:00.000Z");
  assert.equal(health.staleRunningRuns, 0);
  const recoveredRun = database.prepare(
    "SELECT status,completed_at,duration_ms,stage,error_code FROM evaluation_runs WHERE id='stale-daily'",
  ).get();
  assert.deepEqual(
    [recoveredRun.status, recoveredRun.completed_at, recoveredRun.duration_ms, recoveredRun.stage, recoveredRun.error_code],
    ["failed_stale_recovered", "2026-09-02T12:00:00.000Z", 7_200_000, "stale_recovery", "stale_run_recovered"],
  );
  assert.equal((await store.dailyContinuationState("2026-09-02T12:00:00.000Z")).state, "pending");
  assert.equal(database.prepare("SELECT status FROM evaluation_runs WHERE id='recent-retry'").get().status, "running");

  await store.startRun({
    id: "next-retry", startedAt: "2026-09-02T12:20:01.000Z",
    scheduledAt: "2026-09-02T12:20:00.000Z", runKind: "retry",
  });
  assert.equal(database.prepare("SELECT status FROM evaluation_runs WHERE id='recent-retry'").get().status, "failed_stale_recovered");
  assert.equal(database.prepare("SELECT status FROM evaluation_runs WHERE id='next-retry'").get().status, "running");
});

test("provider and public-asset requests have deterministic bounded deadlines", async () => {
  const hangingFetch = async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  });
  const provider = new ResendEmailProvider({
    apiKey: "test-only", fetchImpl: hangingFetch, timeoutMs: 5,
  });
  await assert.rejects(
    provider.sendEmail({ to: "x@example.edu", subject: "x", text: "x", html: "<p>x</p>" }, "timeout"),
    error => error.code === "provider_network_failure" && error.retryable === true,
  );
  await assert.rejects(
    loadPublicAssets({
      CATALOG_URL: "https://example.test/catalog", SUBTOPICS_URL: "https://example.test/subtopics",
      CHANGES_URL: "https://example.test/changes", ALERT_ASSET_TIMEOUT_MS: "5",
    }, hangingFetch),
    /aborted/i,
  );

  let assetBodyAborted = false;
  const stalledAssetBody = async (_url, options) => ({
    ok: true,
    text: async () => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        assetBodyAborted = true;
        reject(new DOMException("asset body aborted", "AbortError"));
      }, { once: true });
    }),
    json: async () => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        assetBodyAborted = true;
        reject(new DOMException("asset body aborted", "AbortError"));
      }, { once: true });
    }),
  });
  await assert.rejects(
    loadPublicAssets({
      CATALOG_URL: "https://example.test/catalog", SUBTOPICS_URL: "https://example.test/subtopics",
      CHANGES_URL: "https://example.test/changes", ALERT_ASSET_TIMEOUT_MS: "5",
    }, stalledAssetBody),
    error => error.code === "asset_timeout",
  );
  assert.equal(assetBodyAborted, true);

  let providerBodyAborted = false;
  const stalledProviderBody = async (_url, options) => ({
    ok: true, status: 200,
    json: async () => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        providerBodyAborted = true;
        reject(new DOMException("provider body aborted", "AbortError"));
      }, { once: true });
    }),
  });
  const stalledProvider = new ResendEmailProvider({
    apiKey: "test-only", fetchImpl: stalledProviderBody, timeoutMs: 5,
  });
  await assert.rejects(
    stalledProvider.sendEmail({ to: "x@example.edu", subject: "x", text: "x", html: "<p>x</p>" }, "body-timeout"),
    error => error.code === "provider_network_failure" && error.retryable === true,
  );
  assert.equal(providerBodyAborted, true);
});

test("scheduler cancellation propagates through public assets and provider requests", async () => {
  const assetController = new AbortController();
  let assetAborted = 0;
  const stalledAsset = async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => {
      assetAborted += 1;
      reject(new DOMException("asset aborted", "AbortError"));
    }, { once: true });
  });
  const assetPromise = loadPublicAssets({
    CATALOG_URL: "https://example.test/catalog",
    SUBTOPICS_URL: "https://example.test/subtopics",
    CHANGES_URL: "https://example.test/changes",
    ALERT_ASSET_TIMEOUT_MS: "30000",
  }, stalledAsset, { signal: assetController.signal });
  assetController.abort(new Error("scheduler timeout"));
  await assert.rejects(assetPromise, error => error.code === "asset_timeout");
  assert.equal(assetAborted, 3);

  const providerController = new AbortController();
  let providerAborted = false;
  const provider = new ResendEmailProvider({
    apiKey: "test-only", timeoutMs: 30_000,
    fetchImpl: async (_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        providerAborted = true;
        reject(new DOMException("provider aborted", "AbortError"));
      }, { once: true });
    }),
  });
  const providerPromise = provider.sendEmail(
    { to: "x@example.edu", subject: "x", text: "x", html: "<p>x</p>" },
    "scheduler-abort", { signal: providerController.signal },
  );
  providerController.abort(new Error("scheduler timeout"));
  await assert.rejects(providerPromise, error => error.code === "provider_network_failure");
  assert.equal(providerAborted, true);
});

test("0005 preserves representative production state and adds resumable scheduler progress", () => {
  const database = databaseThrough(4);
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind) VALUES('existing-daily','2026-08-28T13:15:00.000Z','2026-08-28T13:15:05.000Z','completed','2026-08-28T13:15:00.000Z',5000,'daily')",
  ).run();
  database.exec(migrations[4]);
  const columns = new Set(database.prepare("PRAGMA table_info(evaluation_runs)").all().map(row => row.name));
  assert.ok(columns.has("stage"));
  assert.ok(columns.has("progress_json"));
  assert.ok(columns.has("evaluation_completed_at"));
  assert.ok(columns.has("evaluation_window_started_at"));
  assert.ok(columns.has("weekly_window_at"));
  assert.ok(columns.has("evaluation_input_generated_at"));
  assert.ok(columns.has("evaluation_source_generated_at"));
  const subscriptionColumns = new Set(database.prepare("PRAGMA table_info(subscriptions)").all().map(row => row.name));
  assert.ok(subscriptionColumns.has("evaluation_cursor_at"));
  assert.ok(subscriptionColumns.has("evaluation_window_started_at"));
  assert.ok(subscriptionColumns.has("evaluation_weekly_window_at"));
  assert.ok(subscriptionColumns.has("evaluation_input_generated_at"));
  assert.ok(subscriptionColumns.has("evaluation_source_generated_at"));
  const eventColumns = new Set(database.prepare("PRAGMA table_info(notification_events)").all().map(row => row.name));
  assert.ok(eventColumns.has("evaluation_window_started_at"));
  assert.ok(eventColumns.has("weekly_window_at"));
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM subscriptions").get().count, 1);
  const run = database.prepare(
    "SELECT status,stage,evaluation_completed_at FROM evaluation_runs WHERE id='existing-daily'",
  ).get();
  assert.deepEqual({ ...run }, {
    status: "completed", stage: "completed",
    evaluation_completed_at: "2026-08-28T13:15:05.000Z",
  });
});

test("0006 preserves outstanding windows while revoking legacy scheduler ownership", () => {
  const database = databaseThrough(5);
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  setEvaluationCursor(database, {
    cursorAt: "2026-08-28T13:00:00.000Z", cursorEventId: "cursor-1",
    windowStartedAt: "2026-08-28T13:15:00.000Z",
    weeklyWindowAt: "2026-08-30T23:59:59.999Z",
    inputGeneratedAt: "2026-08-28T13:14:00.000Z",
  });
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,status,scheduled_at,run_kind,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('legacy-running','2026-08-28T13:15:00.000Z','running','2026-08-28T13:15:00.000Z','daily','subscription_evaluation','2026-08-28T13:15:00.000Z','2026-08-30T23:59:59.999Z','2026-08-28T13:14:00.000Z','2026-08-28T13:14:00.000Z')",
  ).run();
  database.exec(migrations[5]);
  const run = database.prepare(
    "SELECT status,error_code,claim_token,claim_revoked_at FROM evaluation_runs WHERE id='legacy-running'",
  ).get();
  assert.equal(run.status, "failed_stale_recovered");
  assert.equal(run.error_code, "migration_claim_revoked");
  assert.equal(run.claim_token, null);
  assert.ok(run.claim_revoked_at);
  const cursor = database.prepare(
    "SELECT evaluation_cursor_event_id,evaluation_window_started_at FROM subscriptions WHERE id='watch-1'",
  ).get();
  assert.deepEqual({ ...cursor }, {
    evaluation_cursor_event_id: "cursor-1",
    evaluation_window_started_at: "2026-08-28T13:15:00.000Z",
  });
  assert.ok(database.prepare("PRAGMA table_info(subscriptions)").all().some(
    column => column.name === "last_calendar_evaluated_on",
  ));
});

test("unchanged feed generations still evaluate each 30, 14, and 7 day reminder window", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, type: "opportunity", cadence: "immediate",
    definition: { opportunity_id: "opp-reminder", triggers: ["closing_reminders"] },
    lastEvaluatedAt: "2026-08-30T00:00:00.000Z",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const assets = {
    catalog: { opportunities: [{
      opportunity_id: "opp-reminder", title: "Daily reminder", close_date: "2026-10-01",
    }] },
    changes: { schema_version: 1, generated_at: "2026-08-30T00:00:00.000Z", events: [] },
    matcher: { matchIds: () => new Set() },
  };
  for (const value of [
    "2026-08-31", "2026-09-01", "2026-09-02",
    "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-23", "2026-09-24", "2026-09-25",
  ]) {
    const origin = `${value}T13:15:00.000Z`;
    const first = await evaluateSubscriptions({
      store, assets, env, now: new Date(origin),
      evaluationWindowStartedAt: origin,
      evaluationInputGeneratedAt: assets.changes.generated_at,
    });
    assert.equal(first.subscriptionCount, 1);
    const duplicate = await evaluateSubscriptions({
      store, assets, env, now: new Date(origin),
      evaluationWindowStartedAt: origin,
      evaluationInputGeneratedAt: assets.changes.generated_at,
    });
    assert.equal(duplicate.subscriptionCount, 0, "the same daily window is not reevaluated");
  }
  const reminders = database.prepare(
    "SELECT event_key FROM notification_events WHERE event_kind='closing_reminder' ORDER BY created_at,event_key",
  ).all().map(row => row.event_key);
  assert.deepEqual(reminders, [
    "closing:opp-reminder:2026-10-01:30",
    "closing:opp-reminder:2026-10-01:14",
    "closing:opp-reminder:2026-10-01:7",
  ]);
  const state = database.prepare(
    "SELECT last_evaluated_at,last_calendar_evaluated_on FROM subscriptions WHERE id='watch-1'",
  ).get();
  assert.deepEqual({ ...state }, {
    last_evaluated_at: "2026-08-30T00:00:00.000Z",
    last_calendar_evaluated_on: "2026-09-25",
  });
});

test("a daily trigger consumed by an older continuation durably queues its reminder window", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, type: "opportunity", cadence: "immediate",
    definition: { opportunity_id: "opp-deferred-reminder", triggers: ["closing_reminders"] },
    lastEvaluatedAt: "2026-08-30T00:00:00.000Z",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const oldWindow = "2026-08-31T13:15:00.000Z";
  const dailyWindow = "2026-09-01T13:15:00.000Z";
  const generation = "2026-08-30T00:00:00.000Z";
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,scheduled_at,duration_ms,run_kind,status,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('older-incomplete',?,?,?,?, 'daily','incomplete_evaluation','continuation_pending',?,?,?,?)",
  ).run(
    oldWindow, "2026-08-31T13:16:00.000Z", oldWindow, 60_000,
    oldWindow, weeklyDigestWindowFor(new Date(oldWindow)), generation, generation,
  );
  const assets = {
    catalog: { opportunities: [{
      opportunity_id: "opp-deferred-reminder", title: "Deferred daily reminder",
      close_date: "2026-10-01",
    }] },
    changes: { schema_version: 1, generated_at: generation, events: [] },
    matcher: { matchIds: () => new Set() },
  };
  const provider = new MockEmailProvider();
  const runAt = current => createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => provider,
    assetLoader: async () => assets,
    now: () => current,
    clock: () => current.getTime(),
  });
  const daily = new Date(dailyWindow);
  const dailyController = { scheduledTime: daily.getTime(), cron: "15 13 * * *" };
  const adopted = await runAt(daily)(dailyController, env);
  const duplicateDaily = await runAt(daily)(dailyController, env);

  assert.equal(adopted.runKind, "continuation");
  assert.equal(adopted.evaluationWindowStartedAt, oldWindow);
  assert.equal(adopted.status, "completed");
  assert.equal(duplicateDaily.status, "duplicate_skipped");
  assert.deepEqual({ ...(await store.dailyContinuationState("2026-09-01T13:16:00.000Z")) }, {
    state: "pending",
    evaluationCompleted: false,
    evaluationWindowStartedAt: dailyWindow,
    weeklyWindowAt: weeklyDigestWindowFor(daily),
    evaluationInputGeneratedAt: "",
    evaluationSourceGeneratedAt: "",
    evaluationCompletedAt: "",
    discoveredAt: dailyWindow,
    running: false,
    cursorCount: 0,
    outstandingWindowCount: 1,
  });
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM evaluation_runs WHERE status='pending_evaluation' AND evaluation_window_started_at=?",
  ).get(dailyWindow).count, 1);
  assert.equal((await store.operationalHealth("2026-09-01T13:16:00.000Z")).schedulerRecent, false);
  assert.equal(provider.messages.length, 0);

  const retry = new Date("2026-09-01T13:20:00.000Z");
  const retryController = { scheduledTime: retry.getTime(), cron: "2-57/5 * * * *" };
  const resumed = await runAt(retry)(retryController, env);
  const duplicateRetry = await runAt(retry)(retryController, env);
  assert.equal(resumed.runKind, "continuation");
  assert.equal(resumed.evaluationWindowStartedAt, dailyWindow);
  assert.equal(resumed.status, "completed");
  assert.equal(duplicateRetry.status, "duplicate_skipped");
  assert.equal(provider.messages.length, 1);
  assert.deepEqual({ ...database.prepare(
    "SELECT event_key,status,evaluation_window_started_at FROM notification_events WHERE event_kind='closing_reminder'",
  ).get() }, {
    event_key: "closing:opp-deferred-reminder:2026-10-01:30",
    status: "sent",
    evaluation_window_started_at: dailyWindow,
  });
  assert.deepEqual({ ...database.prepare(
    "SELECT status,evaluation_completed_at FROM evaluation_runs WHERE status='completed_with_adoption' AND evaluation_window_started_at=?",
  ).get(dailyWindow) }, {
    status: "completed_with_adoption",
    evaluation_completed_at: retry.toISOString(),
  });
  assert.equal((await store.dailyContinuationState("2026-09-01T13:21:00.000Z")).state, "none");
  assert.equal((await store.operationalHealth("2026-09-01T13:21:00.000Z")).schedulerRecent, true);
});

test("an adopted window excludes later subscriptions and completion never predates their baseline", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  const baselineAt = "2026-09-01T13:16:00.000Z";
  const verifiedAt = "2026-09-01T13:17:00.000Z";
  insertSubscription(database, {
    active: 1, type: "opportunity", cadence: "immediate",
    definition: { opportunity_id: "opp-newer-cycle", triggers: ["amended", "closing_reminders"] },
    baselineAt, verifiedAt, lastEvaluatedAt: null,
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const adoptedInput = "2026-09-01T13:14:00.000Z";
  const adoptedWindow = "2026-09-01T13:15:00.000Z";
  const oldSelection = await store.activeSubscriptionsForEvaluation(
    adoptedInput, 25, adoptedWindow,
  );
  assert.deepEqual(oldSelection, { subscriptions: [], hasMore: false });

  const defensiveCompletion = await store.completeEvaluation(
    "watch-1", adoptedInput, "2026-09-01T13:18:00.000Z",
    {
      verificationTokenHash: "token-old", baselineAt,
      evaluationWindowStartedAt: adoptedWindow,
      evaluationInputGeneratedAt: adoptedInput,
      calendarEvaluationDate: "2026-09-01",
    },
  );
  assert.equal(defensiveCompletion, true);
  assert.equal(database.prepare(
    "SELECT last_evaluated_at FROM subscriptions WHERE id='watch-1'",
  ).get().last_evaluated_at, baselineAt);

  const nextSelection = await store.activeSubscriptionsForEvaluation(
    "2026-09-02T13:14:00.000Z", 25, "2026-09-02T13:15:00.000Z",
  );
  assert.equal(nextSelection.subscriptions.length, 1);
  assert.equal(nextSelection.subscriptions[0].id, "watch-1");
});

test("saved-search evaluation resumes equal-timestamp change batches without duplicates", async () => {
  const subscription = {
    id: "saved-1", type: "saved_search", active: 1,
    definition_json: JSON.stringify({ query: "catalysis" }),
    verification_token_hash: "cycle-token", baseline_at: "2026-08-01T00:00:00.000Z",
    created_at: "2026-08-01T00:00:00.000Z", last_evaluated_at: "2026-08-20T00:00:00.000Z",
    evaluation_cursor_at: null, evaluation_cursor_event_id: null,
  };
  const qualifications = new Map();
  const events = new Set();
  const prepared = [];
  const store = {
    activeSubscriptions: async () => [subscription],
    qualifications: async (_id, ids) => new Map(ids.flatMap(id => (
      qualifications.has(id) ? [[id, qualifications.get(id)]] : []
    ))),
    setQualification: async (_subscriptionId, id, value) => { qualifications.set(id, value); },
    enqueueEvent: async event => {
      const duplicate = events.has(event.eventKey);
      events.add(event.eventKey);
      return !duplicate;
    },
    saveEvaluationCursor: async (_id, cursorAt, cursorEventId) => {
      subscription.evaluation_cursor_at = cursorAt;
      subscription.evaluation_cursor_event_id = cursorEventId;
    },
    completeEvaluation: async (_id, evaluatedAt) => {
      subscription.last_evaluated_at = evaluatedAt;
      subscription.evaluation_cursor_at = null;
      subscription.evaluation_cursor_event_id = null;
    },
  };
  const records = ["a", "b", "c"].map(id => ({ opportunity_id: id, title: `Award ${id}` }));
  const changes = {
    generated_at: "2026-08-28T14:00:00.000Z",
    events: records.map(record => ({
      id: `event-${record.opportunity_id}`, type: "new",
      changed_at: "2026-08-28T13:00:00.000Z",
      opportunity_id: record.opportunity_id, record,
    })),
  };
  const assets = {
    catalog: { opportunities: records }, changes,
    matcher: {
      prepare: ids => prepared.push([...ids]),
      matchDetails: (_definition, _asOf, ids) => new Map(ids.map(id => [id, { reasons: ["Strong match"] }])),
    },
  };
  const first = await evaluateSubscriptions({ store, assets, env, now: fixedNow, changeLimit: 2 });
  assert.equal(first.continuationRequired, true);
  assert.equal(first.processedChangeCount, 2);
  assert.equal(subscription.evaluation_cursor_event_id, "event-b");
  const second = await evaluateSubscriptions({ store, assets, env, now: fixedNow, changeLimit: 2 });
  assert.equal(second.continuationRequired, false);
  assert.equal(second.processedChangeCount, 1);
  assert.equal(subscription.last_evaluated_at, changes.generated_at);
  assert.equal(events.size, 3);
  const duplicate = await evaluateSubscriptions({ store, assets, env, now: fixedNow, changeLimit: 2 });
  assert.equal(duplicate.matchedEventCount, 0);
  assert.equal(events.size, 3);
  assert.deepEqual(prepared, [["a", "b"], ["c"]]);
});

test("daily evaluation runs before delivery backlogs and retry triggers continue incomplete daily work", async () => {
  const order = [];
  const seen = new Set();
  const store = {
    needsDailyContinuation: async () => true,
    startRun: async run => {
      if (seen.has(run.id)) return false;
      seen.add(run.id);
      return true;
    },
    activeSubscriptions: async () => { order.push("evaluate"); return []; },
    pendingVerificationEvents: async () => { order.push("verification"); return []; },
    pendingNotificationReconciliationBatches: async () => [],
    pendingEvents: async () => { order.push("notification"); return []; },
    cleanupOperationalData: async () => ({ deletedCount: 0 }),
    finishRun: async () => {},
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    assetLoader: async () => {
      order.push("assets");
      return { changes: { generated_at: fixedNow.toISOString(), events: [] } };
    },
    now: () => fixedNow,
  });
  const controller = { scheduledTime: fixedNow.getTime(), cron: "2-57/5 * * * *" };
  const first = await scheduled(controller, env);
  assert.equal(first.runKind, "continuation");
  assert.equal(first.status, "completed");
  assert.ok(order.indexOf("evaluate") < order.indexOf("verification"));
  assert.ok(order.indexOf("assets") < order.indexOf("notification"));
  const second = await scheduled(controller, env);
  assert.equal(second.status, "duplicate_skipped");
  assert.equal(order.filter(value => value === "verification").length, 1);
});

test("retry triggers do not collide with a recent running daily evaluation", async () => {
  let deliveryQueries = 0;
  let finished;
  const store = {
    dailyContinuationState: async () => "running",
    startRun: async () => true,
    pendingVerificationEvents: async () => { deliveryQueries += 1; return []; },
    finishRun: async run => { finished = { ...run }; },
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    assetLoader: async () => { throw new Error("a retry must not load assets while daily work is running"); },
    now: () => fixedNow,
  });
  const result = await scheduled(
    { scheduledTime: fixedNow.getTime(), cron: "2-57/5 * * * *" }, env,
  );
  assert.equal(result.runKind, "retry");
  assert.equal(result.status, "completed_skipped_daily_in_progress");
  assert.equal(deliveryQueries, 0);
  assert.deepEqual(finished, result);
});

test("retry runs drain due weekly overflow without sending the new week's events", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1, cadence: "weekly" });
  const store = new D1AlertStore(new SqliteD1(database));
  await store.enqueueEvent({
    id: "weekly-due", subscriptionId: "watch-1", eventKey: "weekly-due",
    eventKind: "amended", opportunityId: "due", payload: { title: "Due update" },
    createdAt: "2026-09-06T16:00:00.000Z",
  });
  await store.enqueueEvent({
    id: "weekly-new", subscriptionId: "watch-1", eventKey: "weekly-new",
    eventKind: "amended", opportunityId: "new", payload: { title: "New-week update" },
    createdAt: "2026-09-07T11:00:00.000Z",
  });
  const current = new Date("2026-09-07T12:00:00.000Z");
  assert.equal(weeklyDigestEligibilityCutoff(current), "2026-09-06T23:59:59.999Z");
  assert.equal(
    weeklyDigestEligibilityCutoff(new Date("2026-09-06T13:14:59.999Z")),
    "2026-08-30T23:59:59.999Z",
  );
  const provider = new MockEmailProvider();
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => provider,
    assetLoader: async () => { throw new Error("an ordinary retry must not load assets"); },
    now: () => current,
  });
  const controller = { scheduledTime: current.getTime(), cron: "2-57/5 * * * *" };
  const result = await scheduled(controller, env);
  const duplicate = await scheduled(controller, env);
  assert.equal(result.runKind, "retry");
  assert.equal(result.deliveredCount, 1);
  assert.equal(duplicate.status, "duplicate_skipped");
  assert.equal(provider.messages.length, 1);
  assert.deepEqual(all(
    database, "SELECT id,status FROM notification_events ORDER BY id",
  ).map(row => ({ ...row })), [
    { id: "weekly-due", status: "sent" },
    { id: "weekly-new", status: "queued" },
  ]);
});

test("an originating Sunday weekly window survives Monday continuations and excludes Monday work", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "weekly", type: "opportunity",
    definition: { opportunity_id: "opp-window", triggers: ["amended"] },
    lastEvaluatedAt: "2026-09-01T00:00:00.000Z",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const sunday = new Date("2026-09-06T13:15:00.000Z");
  const origin = sunday.toISOString();
  const weeklyWindow = "2026-09-06T23:59:59.999Z";
  assert.equal(weeklyDigestWindowFor(sunday), weeklyWindow);
  assert.equal(
    weeklyDigestWindowFor(new Date("2026-09-07T13:15:00.000Z")),
    "2026-09-13T23:59:59.999Z",
  );
  const sundayRecords = Array.from({ length: 51 }, (_value, index) => ({
    opportunity_id: "opp-window", title: `Sunday window update ${index}`,
  }));
  const sundayAssets = {
    catalog: { opportunities: [] },
    changes: {
      generated_at: "2026-09-06T13:14:00.000Z",
      events: sundayRecords.map((record, index) => ({
        id: `sunday-${String(index).padStart(3, "0")}`, type: "amended",
        changed_at: "2026-09-06T13:00:00.000Z", opportunity_id: "opp-window", record,
      })),
    },
  };
  const provider = new MockEmailProvider();
  const providerSend = provider.sendEmail.bind(provider);
  provider.sendEmail = async (...args) => {
    if (!provider.messages.length) {
      const checkpoint = database.prepare(
        "SELECT status,evaluation_completed_at,evaluation_window_started_at,weekly_window_at FROM evaluation_runs WHERE run_kind='continuation' ORDER BY started_at DESC LIMIT 1",
      ).get();
      assert.equal(checkpoint.status, "running");
      assert.ok(checkpoint.evaluation_completed_at);
      assert.equal(checkpoint.evaluation_window_started_at, origin);
      assert.equal(checkpoint.weekly_window_at, weeklyWindow);
    }
    return providerSend(...args);
  };
  const runAt = (current, assets = sundayAssets) => createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => provider,
    assetLoader: async () => assets,
    now: () => current,
    clock: () => current.getTime(),
  });

  const first = await runAt(sunday)(
    { scheduledTime: sunday.getTime(), cron: "15 13 * * *" }, env,
  );
  assert.equal(first.runKind, "daily");
  assert.equal(first.status, "incomplete_evaluation");
  assert.equal(first.evaluationWindowStartedAt, origin);
  assert.equal(first.weeklyWindowAt, weeklyWindow);
  assert.equal(provider.messages.length, 0);
  assert.equal(database.prepare(
    "SELECT evaluation_window_started_at FROM subscriptions WHERE id='watch-1'",
  ).get().evaluation_window_started_at, origin);
  assert.equal((await store.operationalHealth("2026-09-06T13:20:00.000Z")).schedulerRecent, false);

  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,scheduled_at,run_kind,status,stage,evaluation_window_started_at,weekly_window_at) VALUES('stalled-sunday-continuation','2026-09-06T23:40:00.000Z','2026-09-06T23:40:00.000Z','continuation','running','subscription_evaluation',?,?)",
  ).run(origin, weeklyWindow);
  const mondayManual = new Date("2026-09-07T00:05:00.000Z");
  const second = await runAt(mondayManual)(
    { scheduledTime: mondayManual.getTime(), cron: "15 13 * * *" }, env,
  );
  assert.equal(second.runKind, "continuation");
  assert.equal(second.status, "incomplete_evaluation");
  assert.equal(second.evaluationWindowStartedAt, origin);
  assert.equal(second.weeklyWindowAt, weeklyWindow);
  assert.equal(provider.messages.length, 0);
  assert.equal(database.prepare(
    "SELECT status FROM evaluation_runs WHERE id='stalled-sunday-continuation'",
  ).get().status, "failed_stale_recovered");
  assert.equal((await store.operationalHealth("2026-09-07T00:06:00.000Z")).schedulerRecent, false);

  const mondayComplete = new Date("2026-09-07T00:10:00.000Z");
  const completionController = {
    scheduledTime: mondayComplete.getTime(), cron: "2-57/5 * * * *",
  };
  const third = await runAt(mondayComplete)(completionController, env);
  const duplicate = await runAt(mondayComplete)(completionController, env);
  assert.equal(third.runKind, "continuation");
  assert.equal(third.status, "completed");
  assert.equal(third.evaluationWindowStartedAt, origin);
  assert.equal(third.weeklyWindowAt, weeklyWindow);
  assert.equal(duplicate.status, "duplicate_skipped");
  assert.equal(provider.messages.length, 1);
  assert.equal(database.prepare(
    "SELECT evaluation_window_started_at FROM subscriptions WHERE id='watch-1'",
  ).get().evaluation_window_started_at, null);
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM notification_events WHERE evaluation_window_started_at=? AND weekly_window_at=?",
  ).get(origin, weeklyWindow).count, 51);
  assert.equal(
    (await store.operationalHealth("2026-09-07T00:11:00.000Z")).schedulerRecent,
    false,
    "the Monday daily window remains outstanding after the Sunday work completes",
  );

  for (const minute of [15, 20, 25]) {
    const retryAt = new Date(`2026-09-07T00:${minute}:00.000Z`);
    await runAt(retryAt)(
      { scheduledTime: retryAt.getTime(), cron: "2-57/5 * * * *" }, env,
    );
    if (minute === 15) {
      assert.equal(
        (await store.operationalHealth("2026-09-07T00:16:00.000Z")).schedulerRecent,
        true,
        "health becomes ready only after the deferred Monday window completes",
      );
    }
  }
  assert.equal(provider.messages.length, 3);
  assert.equal(new Set(provider.messages.map(message => message.idempotencyKey)).size, 3);
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM notification_events WHERE status='sent'",
  ).get().count, 51);

  const mondayDaily = new Date("2026-09-07T13:15:00.000Z");
  const mondayAssets = {
    catalog: { opportunities: [] },
    changes: {
      generated_at: "2026-09-07T13:14:00.000Z",
      events: [{
        id: "monday-independent", type: "amended",
        changed_at: "2026-09-07T13:00:00.000Z", opportunity_id: "opp-window",
        record: { opportunity_id: "opp-window", title: "Independent Monday update" },
      }],
    },
  };
  const mondayResult = await runAt(mondayDaily, mondayAssets)(
    { scheduledTime: mondayDaily.getTime(), cron: "15 13 * * *" }, env,
  );
  assert.equal(mondayResult.runKind, "daily");
  assert.equal(mondayResult.weeklyWindowAt, "2026-09-13T23:59:59.999Z");
  const mondayRetry = new Date("2026-09-07T13:20:00.000Z");
  await runAt(mondayRetry, mondayAssets)(
    { scheduledTime: mondayRetry.getTime(), cron: "2-57/5 * * * *" }, env,
  );
  assert.equal(provider.messages.length, 3);
  const independent = database.prepare(
    "SELECT status,evaluation_window_started_at,weekly_window_at FROM notification_events WHERE event_key='amended:monday-independent'",
  ).get();
  assert.deepEqual({ ...independent }, {
    status: "queued", evaluation_window_started_at: mondayDaily.toISOString(),
    weekly_window_at: "2026-09-13T23:59:59.999Z",
  });
});

test("an exact manual daily scheduled test is idempotent and executes its candidate once", async () => {
  const seen = new Set();
  let assetLoads = 0;
  let deliveryQueries = 0;
  const store = {
    startRun: async run => {
      if (seen.has(run.id)) return false;
      seen.add(run.id);
      return true;
    },
    activeSubscriptions: async () => [],
    pendingVerificationEvents: async () => { deliveryQueries += 1; return []; },
    pendingNotificationReconciliationBatches: async () => [],
    pendingEvents: async () => [],
    cleanupOperationalData: async () => ({ deletedCount: 0 }),
    finishRun: async () => {},
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    providerFactory: () => new MockEmailProvider(),
    assetLoader: async () => {
      assetLoads += 1;
      return { changes: { generated_at: fixedNow.toISOString(), events: [] } };
    },
    now: () => fixedNow,
  });
  const controller = { scheduledTime: fixedNow.getTime(), cron: "15 13 * * *" };
  const first = await scheduled(controller, env);
  const duplicate = await scheduled(controller, env);
  assert.equal(first.runKind, "daily");
  assert.equal(first.status, "completed");
  assert.equal(duplicate.status, "duplicate_skipped");
  assert.equal(assetLoads, 1);
  assert.equal(deliveryQueries, 1);
});

test("a timed-out run start settles and revokes its late durable claim before returning", async () => {
  let releaseStart;
  let insertedStart;
  let activeClaim = null;
  let assetsLoaded = false;
  const inserted = new Promise(resolve => { insertedStart = resolve; });
  const startRelease = new Promise(resolve => { releaseStart = resolve; });
  const store = {
    startRun: async run => {
      activeClaim = { runId: run.id, token: run.claimToken };
      insertedStart();
      await startRelease;
      return true;
    },
    runClaimIsCurrent: async (runId, token) => (
      activeClaim?.runId === runId && activeClaim?.token === token
    ),
    revokeRunClaim: async (runId, token) => {
      if (activeClaim?.runId !== runId || activeClaim?.token !== token) return false;
      activeClaim = null;
      return true;
    },
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    assetLoader: async () => { assetsLoaded = true; return {}; },
    now: () => fixedNow,
  });
  let settled = false;
  const pending = scheduled(
    { scheduledTime: fixedNow.getTime(), cron: "15 13 * * *" },
    { ...env, ALERT_SCHEDULER_TIMEOUT_MS: "40" },
  ).then(result => { settled = true; return result; });
  await inserted;
  await new Promise(resolve => setTimeout(resolve, 45));
  assert.equal(settled, false, "the handler waits for the mutating start operation to settle");
  assert.ok(activeClaim, "the late insert remains exclusively owned while it settles");
  releaseStart();
  const result = await pending;
  assert.equal(result.status, "incomplete_timeout");
  assert.equal(result.errorCode, "scheduler_deadline_exceeded");
  assert.equal(activeClaim, null, "the late run claim is revoked before the handler returns");
  assert.equal(assetsLoaded, false);
});

test("a stalled subscription query ends inside the overall budget with truthful stage evidence", async () => {
  let claim;
  let revoked = false;
  const store = {
    startRun: async run => { claim = { runId: run.id, token: run.claimToken }; return true; },
    runClaimIsCurrent: async (runId, token) => !revoked && runId === claim.runId && token === claim.token,
    revokeRunClaim: async (runId, token) => {
      if (revoked || runId !== claim.runId || token !== claim.token) return false;
      revoked = true;
      return true;
    },
    activeSubscriptions: async () => new Promise(() => {}),
    cleanupOperationalData: async () => ({ deletedCount: 0 }),
    finishRun: async () => { throw new Error("a revoked run must not finalize again"); },
  };
  const scheduled = createScheduledHandler({
    storeFactory: () => store,
    assetLoader: async () => ({ changes: { generated_at: fixedNow.toISOString(), events: [] } }),
    providerFactory: () => new MockEmailProvider(),
    now: () => fixedNow,
  });
  const result = await scheduled(
    { scheduledTime: fixedNow.getTime(), cron: "15 13 * * *" },
    { ...env, ALERT_SCHEDULER_TIMEOUT_MS: "40" },
  );
  assert.equal(result.status, "incomplete_timeout");
  assert.equal(result.errorCode, "scheduler_deadline_exceeded");
  assert.equal(result.stage, "subscription_evaluation");
  assert.equal(result.cleanupErrorCode, "cleanup_skipped_claim_unavailable");
  assert.equal(revoked, true);
});

test("health stays unavailable for incomplete daily evaluation and recovers after continuation", async () => {
  const database = databaseThrough();
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,error_code,evaluation_window_started_at) VALUES('daily-incomplete','2026-09-02T11:00:00.000Z','2026-09-02T11:01:00.000Z','incomplete_evaluation','2026-09-02T11:00:00.000Z',60000,'daily','subscription_evaluation','evaluation_continuation_required','2026-09-02T11:00:00.000Z')",
  ).run();
  const store = new D1AlertStore(new SqliteD1(database));
  assert.equal((await store.operationalHealth("2026-09-02T12:00:00.000Z")).schedulerRecent, false);
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,evaluation_completed_at,evaluation_window_started_at) VALUES('daily-continuation','2026-09-02T11:05:00.000Z','2026-09-02T11:06:00.000Z','completed','2026-09-02T11:05:00.000Z',60000,'continuation','completed','2026-09-02T11:05:55.000Z','2026-09-02T11:00:00.000Z')",
  ).run();
  const health = await store.operationalHealth("2026-09-02T12:00:00.000Z");
  assert.equal(health.schedulerRecent, true);
  assert.equal(health.lastDailyStatus, "completed");
});

test("outstanding cursor ownership survives before, at, and after the 26-hour recovery horizon", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  const origin = "2026-09-06T13:15:00.000Z";
  const weeklyWindow = "2026-09-06T23:59:59.999Z";
  const inputGeneration = "2026-09-06T13:14:00.000Z";
  setEvaluationCursor(database, {
    cursorAt: "2026-09-06T13:00:00.000Z", cursorEventId: "cursor-25",
    windowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    inputGeneratedAt: inputGeneration,
  });
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('origin-incomplete',?,?,'incomplete_evaluation',?,60000,'daily','continuation_pending',?,?,?,?)",
  ).run(origin, "2026-09-06T13:16:00.000Z", origin, origin, weeklyWindow, inputGeneration, inputGeneration);
  const store = new D1AlertStore(new SqliteD1(database));
  for (const delta of [26 * 60 * 60_000 - 1, 26 * 60 * 60_000, 26 * 60 * 60_000 + 1]) {
    const state = await store.dailyContinuationState(new Date(Date.parse(origin) + delta).toISOString());
    assert.equal(state.state, "pending");
    assert.equal(state.evaluationWindowStartedAt, origin);
    assert.equal(state.weeklyWindowAt, weeklyWindow);
    assert.equal(state.evaluationInputGeneratedAt, inputGeneration);
    assert.equal(state.outstandingWindowCount, 1);
  }
  const muchLater = new Date(Date.parse(origin) + 100 * 86_400_000).toISOString();
  await store.cleanupOperationalData(muchLater, 500);
  assert.ok(database.prepare("SELECT id FROM evaluation_runs WHERE id='origin-incomplete'").get());
  assert.equal((await store.dailyContinuationState(muchLater)).state, "pending");
  const health = await store.operationalHealth(muchLater);
  assert.equal(health.pendingEvaluationWindows, 1);
  assert.equal(health.schedulerRecent, false);
});

test("multiple incomplete windows remain durable and recover oldest-first across Sunday and Monday", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1, cadence: "weekly" });
  insertSubscriber(database, {
    id: "person-2", email: "second@example.edu", manageToken: "n".repeat(43),
  });
  insertSubscription(database, {
    id: "watch-2", subscriberId: "person-2", active: 1, cadence: "weekly",
    tokenHash: "token-second", definitionHash: "hash-second",
  });
  const sundayOrigin = "2026-09-06T13:15:00.000Z";
  const mondayOrigin = "2026-09-07T13:15:00.000Z";
  const sundayInput = "2026-09-06T13:14:00.000Z";
  const mondayInput = "2026-09-07T13:14:00.000Z";
  setEvaluationCursor(database, {
    id: "watch-1", cursorAt: "2026-09-06T13:00:00.000Z", cursorEventId: "sunday-cursor",
    windowStartedAt: sundayOrigin, weeklyWindowAt: "2026-09-06T23:59:59.999Z",
    inputGeneratedAt: sundayInput,
  });
  setEvaluationCursor(database, {
    id: "watch-2", cursorAt: "2026-09-07T13:00:00.000Z", cursorEventId: "monday-cursor",
    windowStartedAt: mondayOrigin, weeklyWindowAt: "2026-09-13T23:59:59.999Z",
    inputGeneratedAt: mondayInput,
  });
  for (const [id, origin, weekly, input] of [
    ["sunday-incomplete", sundayOrigin, "2026-09-06T23:59:59.999Z", sundayInput],
    ["monday-incomplete", mondayOrigin, "2026-09-13T23:59:59.999Z", mondayInput],
  ]) {
    database.prepare(
      "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES(?,?,?,'incomplete_evaluation',?,60000,'daily','continuation_pending',?,?,?,?)",
    ).run(id, origin, new Date(Date.parse(origin) + 60_000).toISOString(), origin, origin, weekly, input, input);
  }
  const store = new D1AlertStore(new SqliteD1(database));
  const afterHorizon = await store.dailyContinuationState("2026-09-08T16:00:00.000Z");
  assert.equal(afterHorizon.evaluationWindowStartedAt, sundayOrigin);
  assert.equal(afterHorizon.weeklyWindowAt, "2026-09-06T23:59:59.999Z");
  assert.equal(afterHorizon.outstandingWindowCount, 2);
  const completedOnce = await store.completeEvaluation(
    "watch-1", sundayInput, "2026-09-08T16:01:00.000Z",
    {
      verificationTokenHash: "token-old", baselineAt: "2026-08-01T00:00:00.000Z",
      evaluationWindowStartedAt: sundayOrigin,
      evaluationInputGeneratedAt: sundayInput,
    },
  );
  const completedTwice = await store.completeEvaluation(
    "watch-1", sundayInput, "2026-09-08T16:01:01.000Z",
    {
      verificationTokenHash: "token-old", baselineAt: "2026-08-01T00:00:00.000Z",
      evaluationWindowStartedAt: sundayOrigin,
      evaluationInputGeneratedAt: sundayInput,
    },
  );
  assert.equal(completedOnce, true);
  assert.equal(completedTwice, false);
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,evaluation_completed_at,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('sunday-complete','2026-09-08T16:01:00.000Z','2026-09-08T16:02:00.000Z','completed','2026-09-08T16:01:00.000Z',60000,'continuation','completed','2026-09-08T16:01:55.000Z',?,?,?,?)",
  ).run(sundayOrigin, "2026-09-06T23:59:59.999Z", sundayInput, sundayInput);
  const next = await store.dailyContinuationState("2026-09-08T16:03:00.000Z");
  assert.equal(next.evaluationWindowStartedAt, mondayOrigin);
  assert.equal(next.outstandingWindowCount, 1);
});

test("cursor rebase coverage uses the current source generation while input remains frozen", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "weekly", type: "opportunity",
    definition: { opportunity_id: "opp-retention-gap", triggers: ["amended"] },
    lastEvaluatedAt: "2026-09-01T13:14:00.000Z",
  });
  const origin = "2026-09-02T13:15:00.000Z";
  const inputGeneration = "2026-09-02T13:14:00.000Z";
  setEvaluationCursor(database, {
    cursorAt: "2026-09-02T13:00:00.000Z", cursorEventId: "missing-cursor",
    windowStartedAt: origin, weeklyWindowAt: "2026-09-06T23:59:59.999Z",
    inputGeneratedAt: inputGeneration, sourceGeneratedAt: inputGeneration,
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const current = new Date("2026-09-10T13:14:00.000Z");
  await assert.rejects(
    evaluateSubscriptions({
      store,
      assets: {
        catalog: { opportunities: [] },
        changes: {
          schema_version: 1, retention_days: 1,
          events: [{
            id: "retained-old-event", type: "amended",
            changed_at: "2026-09-02T12:00:00.000Z", opportunity_id: "opp-retention-gap",
            record: { opportunity_id: "opp-retention-gap", title: "Retained boundary" },
          }],
        },
      },
      env, now: current,
      evaluationWindowStartedAt: origin,
      weeklyWindowAt: "2026-09-06T23:59:59.999Z",
      evaluationInputGeneratedAt: inputGeneration,
    }),
    error => error?.code === "evaluation_rebase_unsafe",
  );
  const cursor = database.prepare(
    "SELECT evaluation_cursor_event_id,evaluation_input_generated_at,evaluation_source_generated_at,last_evaluated_at FROM subscriptions WHERE id='watch-1'",
  ).get();
  assert.deepEqual({ ...cursor }, {
    evaluation_cursor_event_id: "missing-cursor",
    evaluation_input_generated_at: inputGeneration,
    evaluation_source_generated_at: inputGeneration,
    last_evaluated_at: "2026-09-01T13:14:00.000Z",
  });
});

test("a changed input generation safely rebases a missing cursor without loss, duplication, or window leakage", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "weekly", type: "opportunity",
    definition: { opportunity_id: "opp-rebase", triggers: ["amended"] },
    lastEvaluatedAt: "2026-08-01T00:00:00.000Z",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const origin = "2026-09-06T13:15:00.000Z";
  const weeklyWindow = "2026-09-06T23:59:59.999Z";
  const inputGeneration = "2026-09-06T13:14:00.000Z";
  const event = (id, changedAt, title = id) => ({
    id, type: "amended", changed_at: changedAt, opportunity_id: "opp-rebase",
    record: { opportunity_id: "opp-rebase", title },
  });
  const originalAssets = {
    catalog: { opportunities: [{ opportunity_id: "opp-rebase", title: "Original catalog" }] },
    changes: {
      schema_version: 1, generated_at: inputGeneration, retention_days: 90,
      events: ["a", "b", "c"].map(id => event(id, "2026-09-06T13:00:00.000Z")),
    },
  };
  const first = await evaluateSubscriptions({
    store, assets: originalAssets, env, now: new Date(origin), changeLimit: 2,
    evaluationWindowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    evaluationInputGeneratedAt: inputGeneration,
  });
  assert.equal(first.continuationRequired, true);
  assert.equal(database.prepare(
    "SELECT evaluation_cursor_event_id FROM subscriptions WHERE id='watch-1'",
  ).get().evaluation_cursor_event_id, "b");
  const rebasedAssets = {
    catalog: { opportunities: [{ opportunity_id: "opp-rebase", title: "Changed catalog" }] },
    changes: {
      schema_version: 1, generated_at: "2026-09-07T13:14:00.000Z", retention_days: 90,
      events: [
        event("a", "2026-09-06T13:00:00.000Z"),
        event("c", "2026-09-06T13:00:00.000Z"),
        event("monday", "2026-09-07T13:00:00.000Z"),
      ],
    },
  };
  const recovered = await evaluateSubscriptions({
    store, assets: rebasedAssets, env, now: new Date("2026-09-07T14:00:00.000Z"), changeLimit: 25,
    evaluationWindowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    evaluationInputGeneratedAt: inputGeneration,
  });
  assert.equal(recovered.rebasedSubscriptionCount, 1);
  assert.equal(recovered.continuationRequired, false);
  assert.deepEqual(all(
    database,
    "SELECT event_key,weekly_window_at FROM notification_events WHERE message_kind='notification' ORDER BY event_key",
  ).map(row => ({ ...row })), [
    { event_key: "amended:a", weekly_window_at: weeklyWindow },
    { event_key: "amended:b", weekly_window_at: weeklyWindow },
    { event_key: "amended:c", weekly_window_at: weeklyWindow },
  ]);
  const subscription = database.prepare(
    "SELECT last_evaluated_at,evaluation_cursor_at,evaluation_window_started_at FROM subscriptions WHERE id='watch-1'",
  ).get();
  assert.deepEqual({ ...subscription }, {
    last_evaluated_at: inputGeneration,
    evaluation_cursor_at: null,
    evaluation_window_started_at: null,
  });
});

test("concurrent scheduled and manual invocations claim an adopted cursor only once", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, cadence: "immediate", type: "opportunity",
    definition: { opportunity_id: "opp-claim", triggers: ["amended"] },
    lastEvaluatedAt: "2026-08-01T00:00:00.000Z",
  });
  const origin = "2026-09-01T13:15:00.000Z";
  const inputGeneration = "2026-09-01T13:14:00.000Z";
  setEvaluationCursor(database, {
    cursorAt: "2026-09-01T13:00:00.000Z", cursorEventId: "b",
    windowStartedAt: origin, weeklyWindowAt: "2026-09-06T23:59:59.999Z",
    inputGeneratedAt: inputGeneration,
  });
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('claim-origin',?,?,'incomplete_evaluation',?,60000,'daily','continuation_pending',?,'2026-09-06T23:59:59.999Z',?,?)",
  ).run(origin, "2026-09-01T13:16:00.000Z", origin, origin, inputGeneration, inputGeneration);
  const store = new D1AlertStore(new SqliteD1(database));
  const provider = new MockEmailProvider();
  const assets = {
    catalog: { opportunities: [{ opportunity_id: "opp-claim", title: "Claimed" }] },
    changes: {
      schema_version: 1, generated_at: inputGeneration, retention_days: 90,
      events: [
        { id: "b", type: "amended", changed_at: "2026-09-01T13:00:00.000Z", opportunity_id: "opp-claim", record: { opportunity_id: "opp-claim", title: "Already handled" } },
        { id: "c", type: "amended", changed_at: "2026-09-01T13:01:00.000Z", opportunity_id: "opp-claim", record: { opportunity_id: "opp-claim", title: "Recovered" } },
      ],
    },
  };
  let releaseAssets;
  let signalAssetLoad;
  const assetLoaded = new Promise(resolve => { signalAssetLoad = resolve; });
  const heldAssets = new Promise(resolve => { releaseAssets = () => resolve(assets); });
  const recoveryNow = new Date("2026-09-03T16:00:00.000Z");
  const scheduled = createScheduledHandler({
    storeFactory: () => store, providerFactory: () => provider,
    assetLoader: async () => { signalAssetLoad(); return heldAssets; },
    now: () => recoveryNow, clock: () => recoveryNow.getTime(),
  });
  const firstPromise = scheduled(
    { scheduledTime: recoveryNow.getTime(), cron: "2-57/5 * * * *" }, env,
  );
  await assetLoaded;
  const manualNow = new Date(recoveryNow.getTime() + 1_000);
  const manual = createScheduledHandler({
    storeFactory: () => store, providerFactory: () => provider,
    assetLoader: async () => { throw new Error("manual execution must not claim the same cursor"); },
    now: () => manualNow, clock: () => manualNow.getTime(),
  });
  const competing = await manual(
    { scheduledTime: manualNow.getTime(), cron: "15 13 * * *" }, env,
  );
  releaseAssets();
  const recovered = await firstPromise;
  assert.equal(competing.status, "completed_skipped_daily_in_progress");
  assert.equal(recovered.runKind, "continuation");
  assert.equal(recovered.status, "completed");
  assert.equal(provider.messages.length, 1);
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM evaluation_runs WHERE run_kind='continuation'",
  ).get().count, 1);
});

test("stale adoption recovery and health remain truthful until the cursor completes", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  const origin = "2026-09-01T12:00:00.000Z";
  const inputGeneration = "2026-09-01T11:59:00.000Z";
  const weeklyWindow = "2026-09-06T23:59:59.999Z";
  setEvaluationCursor(database, {
    cursorAt: "2026-09-01T11:30:00.000Z", cursorEventId: "cursor",
    windowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    inputGeneratedAt: inputGeneration,
  });
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,status,scheduled_at,run_kind,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('dead-adoption','2026-09-01T12:00:00.000Z','running','2026-09-01T12:00:00.000Z','continuation','subscription_evaluation',?,?,?,?)",
  ).run(origin, weeklyWindow, inputGeneration, inputGeneration);
  const store = new D1AlertStore(new SqliteD1(database));
  const staleHealth = await store.operationalHealth("2026-09-01T12:13:00.000Z");
  assert.equal(staleHealth.schedulerRecent, false);
  assert.equal(staleHealth.pendingEvaluationWindows, 1);
  assert.equal(database.prepare(
    "SELECT status FROM evaluation_runs WHERE id='dead-adoption'",
  ).get().status, "failed_stale_recovered");
  const adoptedRun = {
    id: "adoption-two", startedAt: "2026-09-01T12:14:00.000Z",
    scheduledAt: "2026-09-01T12:14:00.000Z", runKind: "continuation",
    evaluationWindowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    evaluationInputGeneratedAt: inputGeneration,
    evaluationSourceGeneratedAt: inputGeneration,
  };
  assert.equal(await store.startRun(adoptedRun), true);
  assert.equal((await store.dailyContinuationState("2026-09-01T12:15:00.000Z")).state, "running");
  assert.equal((await store.operationalHealth("2026-09-01T12:15:00.000Z")).schedulerRecent, false);
  assert.equal((await store.dailyContinuationState("2026-09-01T12:27:00.001Z")).state, "pending");
  assert.equal(database.prepare(
    "SELECT status FROM evaluation_runs WHERE id='adoption-two'",
  ).get().status, "failed_stale_recovered");
  const failedRun = {
    id: "adoption-failed", startedAt: "2026-09-01T12:28:00.000Z",
    scheduledAt: "2026-09-01T12:28:00.000Z", runKind: "continuation",
    evaluationWindowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    evaluationInputGeneratedAt: inputGeneration,
    evaluationSourceGeneratedAt: inputGeneration,
  };
  assert.equal(await store.startRun(failedRun), true);
  await store.finishRun({
    ...failedRun, completedAt: "2026-09-01T12:29:00.000Z", durationMs: 60_000,
    subscriptionCount: 0, matchedEventCount: 0, attemptedCount: 0,
    deliveredCount: 0, failedCount: 0, cleanupDeletedCount: 0,
    status: "failed", stage: "subscription_evaluation", progress: {},
  });
  assert.equal((await store.operationalHealth("2026-09-01T12:29:30.000Z")).schedulerRecent, false);
  const successfulRun = {
    id: "adoption-complete", startedAt: "2026-09-01T12:30:00.000Z",
    scheduledAt: "2026-09-01T12:30:00.000Z", runKind: "continuation",
    evaluationWindowStartedAt: origin, weeklyWindowAt: weeklyWindow,
    evaluationInputGeneratedAt: inputGeneration,
    evaluationSourceGeneratedAt: inputGeneration,
  };
  assert.equal(await store.startRun(successfulRun), true);
  assert.equal(await store.completeEvaluation(
    "watch-1", inputGeneration, "2026-09-01T12:30:30.000Z",
    {
      verificationTokenHash: "token-old", baselineAt: "2026-08-01T00:00:00.000Z",
      evaluationWindowStartedAt: origin, evaluationInputGeneratedAt: inputGeneration,
    },
  ), true);
  await store.markRunEvaluationComplete(
    successfulRun.id, "2026-09-01T12:30:40.000Z", { continuationRequired: false },
  );
  await store.finishRun({
    ...successfulRun, completedAt: "2026-09-01T12:31:00.000Z", durationMs: 60_000,
    evaluationCompletedAt: "2026-09-01T12:30:40.000Z",
    subscriptionCount: 1, matchedEventCount: 0, attemptedCount: 0,
    deliveredCount: 0, failedCount: 0, cleanupDeletedCount: 0,
    status: "completed", stage: "completed", progress: { continuationRequired: false },
  });
  assert.equal(database.prepare(
    "SELECT evaluation_cursor_at FROM subscriptions WHERE id='watch-1'",
  ).get().evaluation_cursor_at, null);
  const completedHealth = await store.operationalHealth("2026-09-01T12:31:30.000Z");
  assert.equal(completedHealth.pendingEvaluationWindows, 0);
  assert.equal(completedHealth.schedulerRecent, true);
});

test("revoked scheduler fencing makes every late evaluation and delivery write a no-op", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, type: "saved_search", cadence: "immediate",
    definition: { query: "fenced catalysis" }, lastEvaluatedAt: "2026-08-01T00:00:00.000Z",
  });
  const store = new D1AlertStore(new SqliteD1(database));
  const origin = "2026-09-06T13:15:00.000Z";
  const input = "2026-09-06T13:14:00.000Z";
  const weekly = "2026-09-06T23:59:59.999Z";
  const oldClaim = { runId: "old-adopter", token: "old-fence-token" };
  const oldRun = {
    id: oldClaim.runId, claimToken: oldClaim.token, startedAt: origin, scheduledAt: origin,
    runKind: "continuation", evaluationWindowStartedAt: origin, weeklyWindowAt: weekly,
    evaluationInputGeneratedAt: input, evaluationSourceGeneratedAt: input,
  };
  assert.equal(await store.startRun(oldRun), true);
  const cycle = {
    verificationTokenHash: "token-old", baselineAt: "2026-08-01T00:00:00.000Z",
    evaluationWindowStartedAt: origin, weeklyWindowAt: weekly,
    evaluationInputGeneratedAt: input, evaluationSourceGeneratedAt: input,
    calendarEvaluationDate: "2026-09-06", claim: oldClaim,
  };
  assert.equal(await store.enqueueEvent({
    id: "fenced-delivery", subscriptionId: "watch-1", eventKey: "fenced-delivery",
    eventKind: "strong_match", opportunityId: "opp-fenced", payload: { title: "Fenced" },
    evaluationWindowStartedAt: origin, weeklyWindowAt: weekly,
    createdAt: "2026-09-06T13:16:00.000Z", cycle,
  }), true);
  assert.deepEqual(
    await store.claimEvents(["fenced-delivery"], "2026-09-06T13:16:00.000Z", oldClaim),
    ["fenced-delivery"],
  );
  assert.equal(await store.revokeRunClaim(
    oldClaim.runId, oldClaim.token, "2026-09-06T13:17:00.000Z",
  ), true);
  const healthAfterTimeout = await store.operationalHealth("2026-09-06T13:17:01.000Z");
  assert.equal(healthAfterTimeout.schedulerRecent, false);

  const successorClaim = { runId: "successor-adopter", token: "successor-fence-token" };
  const successorRun = {
    ...oldRun, id: successorClaim.runId, claimToken: successorClaim.token,
    startedAt: "2026-09-06T13:18:00.000Z", scheduledAt: "2026-09-06T13:18:00.000Z",
  };
  assert.equal(await store.startRun(successorRun), true);
  assert.equal(await store.enqueueEvent({
    id: "late-event", subscriptionId: "watch-1", eventKey: "late-event",
    eventKind: "strong_match", opportunityId: "opp-late", payload: { title: "Late" },
    evaluationWindowStartedAt: origin, weeklyWindowAt: weekly,
    createdAt: "2026-09-06T13:18:01.000Z", cycle,
  }), false);
  await store.setQualification(
    "watch-1", "opp-late", true, "2026-09-06T13:18:01.000Z", cycle,
  );
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM subscription_qualifications WHERE opportunity_id='opp-late'",
  ).get().count, 0);
  assert.equal(await store.saveEvaluationCursor(
    "watch-1", "2026-09-06T13:10:00.000Z", "late-cursor",
    "2026-09-06T13:18:01.000Z", cycle,
  ), false);
  assert.equal(await store.completeEvaluation(
    "watch-1", input, "2026-09-06T13:18:01.000Z", cycle,
  ), false);
  await store.markEventsSent(
    ["fenced-delivery"], "provider-late", "2026-09-06T13:18:01.000Z", oldClaim,
  );
  assert.equal(database.prepare(
    "SELECT provider_message_id FROM notification_events WHERE id='fenced-delivery'",
  ).get().provider_message_id, null);
  assert.equal(await store.markRunEvaluationComplete(
    oldClaim.runId, "2026-09-06T13:18:01.000Z", {}, oldClaim,
  ), false);
  assert.equal(await store.finishRun({
    ...oldRun, claimToken: oldClaim.token, completedAt: "2026-09-06T13:18:01.000Z",
    durationMs: 181_000, subscriptionCount: 1, matchedEventCount: 1,
    attemptedCount: 1, deliveredCount: 1, failedCount: 0, cleanupDeletedCount: 0,
    status: "completed", stage: "completed", progress: {},
  }), false);

  const successorCycle = { ...cycle, claim: successorClaim };
  assert.equal(await store.completeEvaluation(
    "watch-1", input, "2026-09-06T13:18:30.000Z", successorCycle,
  ), true);
  assert.equal(await store.markRunEvaluationComplete(
    successorClaim.runId, "2026-09-06T13:18:31.000Z", {}, successorClaim,
  ), true);
  assert.equal(await store.finishRun({
    ...successorRun, completedAt: "2026-09-06T13:19:00.000Z", durationMs: 60_000,
    subscriptionCount: 1, matchedEventCount: 0, attemptedCount: 0,
    deliveredCount: 0, failedCount: 0, cleanupDeletedCount: 0,
    status: "completed", stage: "completed", progress: {},
    evaluationCompletedAt: "2026-09-06T13:18:31.000Z",
  }), true);
  const completedHealth = await store.operationalHealth("2026-09-06T13:19:01.000Z");
  assert.equal(completedHealth.pendingEvaluationWindows, 0);
  assert.equal(completedHealth.schedulerRecent, true);
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM evaluation_runs WHERE claim_token IS NOT NULL",
  ).get().count, 0);
});

test("saved-search qualification writes carry the same scheduler fence as their event", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, type: "saved_search", cadence: "immediate",
    definition: { query: "fenced hydrogen" }, lastEvaluatedAt: "2026-08-01T00:00:00.000Z",
  });
  database.prepare(
    "INSERT INTO subscription_qualifications(subscription_id,opportunity_id,qualified,updated_at) VALUES('watch-1','opp-new',0,'2026-08-01T00:00:00.000Z')",
  ).run();
  const store = new D1AlertStore(new SqliteD1(database));
  const claim = { runId: "qualification-run", token: "qualification-token" };
  const origin = "2026-09-01T13:15:00.000Z";
  const input = "2026-09-01T13:14:00.000Z";
  assert.equal(await store.startRun({
    id: claim.runId, claimToken: claim.token, startedAt: origin, scheduledAt: origin,
    runKind: "daily", evaluationWindowStartedAt: origin,
    weeklyWindowAt: "2026-09-06T23:59:59.999Z",
    evaluationInputGeneratedAt: input, evaluationSourceGeneratedAt: input,
  }), true);
  const proxy = new Proxy(store, {
    get(target, property) {
      if (property === "enqueueEvent") {
        return async event => {
          const inserted = await target.enqueueEvent(event);
          await target.revokeRunClaim(
            claim.runId, claim.token, "2026-09-01T13:15:01.000Z",
          );
          return inserted;
        };
      }
      const value = target[property];
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  const opportunity = { opportunity_id: "opp-new", title: "Hydrogen catalysis" };
  await assert.rejects(evaluateSubscriptions({
    store: proxy,
    assets: {
      catalog: { opportunities: [opportunity] },
      changes: {
        schema_version: 1, generated_at: input, retention_days: 90,
        events: [{
          id: "new-event", type: "new", changed_at: "2026-09-01T13:00:00.000Z",
          opportunity_id: "opp-new", record: opportunity,
        }],
      },
      matcher: {
        prepare: () => {},
        matchDetails: () => new Map([["opp-new", { reasons: ["Fenced match"] }]]),
      },
    },
    env, now: new Date(origin), evaluationWindowStartedAt: origin,
    weeklyWindowAt: "2026-09-06T23:59:59.999Z",
    evaluationInputGeneratedAt: input, schedulerClaim: claim,
  }), error => error.code === "scheduler_claim_lost");
  assert.equal(database.prepare(
    "SELECT qualified FROM subscription_qualifications WHERE subscription_id='watch-1' AND opportunity_id='opp-new'",
  ).get().qualified, 0, "the revoked run cannot overwrite qualification state");
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM notification_events WHERE event_key='strong:opp-new:new-event'",
  ).get().count, 1, "the event committed before revocation remains idempotently owned");
});

test("ambiguous provider completion after fence revocation reuses one provider identity", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1, type: "opportunity", cadence: "immediate" });
  insertEvent(database, { id: "ambiguous-event" });
  const store = new D1AlertStore(new SqliteD1(database));
  const oldClaim = { runId: "provider-old", token: "provider-old-token" };
  assert.equal(await store.startRun({
    id: oldClaim.runId, claimToken: oldClaim.token,
    startedAt: "2026-09-01T12:00:00.000Z", scheduledAt: "2026-09-01T12:00:00.000Z",
    runKind: "retry",
  }), true);
  let releaseFirst;
  let providerStarted;
  const started = new Promise(resolve => { providerStarted = resolve; });
  const providerIds = new Map();
  const calls = [];
  const provider = {
    configured: true,
    async sendEmail(_message, key) {
      calls.push(key);
      if (!providerIds.has(key)) providerIds.set(key, `provider-${providerIds.size + 1}`);
      if (calls.length === 1) {
        providerStarted();
        return new Promise(resolve => { releaseFirst = () => resolve({ id: providerIds.get(key) }); });
      }
      return { id: providerIds.get(key) };
    },
  };
  const firstDispatch = dispatchNotifications({
    store, provider, env, now: new Date("2026-09-01T12:00:00.000Z"),
    schedulerClaim: oldClaim,
  });
  await started;
  assert.equal(await store.revokeRunClaim(
    oldClaim.runId, oldClaim.token, "2026-09-01T12:00:01.000Z", "failed_timeout",
  ), true);
  const successorClaim = { runId: "provider-successor", token: "provider-successor-token" };
  assert.equal(await store.startRun({
    id: successorClaim.runId, claimToken: successorClaim.token,
    startedAt: "2026-09-01T12:00:02.000Z", scheduledAt: "2026-09-01T12:00:02.000Z",
    runKind: "retry",
  }), true);
  releaseFirst();
  await firstDispatch;
  const ambiguous = database.prepare(
    "SELECT status,provider_message_id,provider_quota_key FROM notification_events WHERE id='ambiguous-event'",
  ).get();
  assert.equal(ambiguous.status, "sending");
  assert.equal(ambiguous.provider_message_id, null);
  assert.equal(ambiguous.provider_quota_key, "ambiguous-event");
  const recovered = await dispatchNotifications({
    store, provider, env, now: new Date("2026-09-01T12:16:00.000Z"),
    schedulerClaim: successorClaim,
  });
  assert.equal(recovered.deliveredCount, 1);
  assert.deepEqual(calls, ["ambiguous-event", "ambiguous-event"]);
  assert.equal(providerIds.size, 1, "the provider observes one idempotent delivery identity");
  const sent = database.prepare(
    "SELECT status,provider_message_id FROM notification_events WHERE id='ambiguous-event'",
  ).get();
  assert.deepEqual({ ...sent }, { status: "sent", provider_message_id: "provider-1" });
  assert.equal(database.prepare(
    "SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'",
  ).get().request_count, 1, "retry reuses the original quota reservation");
});

test("a timed-out adopter older than 26 hours is fenced while its Sunday successor completes", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, {
    active: 1, type: "opportunity", cadence: "weekly",
    definition: { opportunity_id: "opp-recovery", triggers: ["amended"] },
    lastEvaluatedAt: "2026-08-01T00:00:00.000Z",
  });
  const origin = "2026-09-06T13:15:00.000Z";
  const input = "2026-09-06T13:14:00.000Z";
  const weekly = "2026-09-06T23:59:59.999Z";
  setEvaluationCursor(database, {
    cursorAt: "2026-09-06T13:00:00.000Z", cursorEventId: "cursor",
    windowStartedAt: origin, weeklyWindowAt: weekly, inputGeneratedAt: input,
  });
  database.prepare(
    "INSERT INTO evaluation_runs(id,started_at,completed_at,status,scheduled_at,duration_ms,run_kind,stage,evaluation_window_started_at,weekly_window_at,evaluation_input_generated_at,evaluation_source_generated_at) VALUES('origin-timeout',?,?, 'incomplete_timeout',?,60000,'daily','subscription_evaluation',?,?,?,?)",
  ).run(origin, "2026-09-06T13:16:00.000Z", origin, origin, weekly, input, input);
  const realStore = new D1AlertStore(new SqliteD1(database));
  const staleLoaded = await realStore.activeSubscriptionsForEvaluation(input, 4, origin);
  let releaseStale;
  let firstSelectionStarted;
  const selectionStarted = new Promise(resolve => { firstSelectionStarted = resolve; });
  let selectionCalls = 0;
  const proxy = new Proxy(realStore, {
    get(target, property) {
      if (property === "activeSubscriptionsForEvaluation") {
        return async (...args) => {
          selectionCalls += 1;
          if (selectionCalls === 1) {
            firstSelectionStarted();
            return new Promise(resolve => { releaseStale = () => resolve(staleLoaded); });
          }
          return target.activeSubscriptionsForEvaluation(...args);
        };
      }
      const value = target[property];
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  const record = { opportunity_id: "opp-recovery", title: "Recovered Sunday award" };
  const assets = {
    catalog: { opportunities: [record] },
    changes: {
      schema_version: 1, generated_at: input, retention_days: 90,
      events: [
        { id: "cursor", type: "amended", changed_at: "2026-09-06T13:00:00.000Z", opportunity_id: "opp-recovery", record },
        { id: "recovered", type: "amended", changed_at: "2026-09-06T13:01:00.000Z", opportunity_id: "opp-recovery", detail: "Recovered", record },
      ],
    },
    matcher: { matchIds: () => new Set() },
  };
  const provider = new MockEmailProvider();
  let current = new Date("2026-09-08T16:00:00.000Z");
  const scheduled = createScheduledHandler({
    storeFactory: () => proxy, providerFactory: () => provider,
    assetLoader: async () => assets, now: () => current,
  });
  const firstPromise = scheduled(
    { scheduledTime: current.getTime(), cron: "2-57/5 * * * *" },
    { ...env, ALERT_SCHEDULER_TIMEOUT_MS: "80" },
  );
  await selectionStarted;
  const first = await firstPromise;
  assert.equal(first.status, "incomplete_timeout");
  assert.equal(first.evaluationWindowStartedAt, origin);
  assert.equal(first.weeklyWindowAt, weekly);
  assert.equal((await realStore.operationalHealth("2026-09-08T16:00:01.000Z")).schedulerRecent, false);

  current = new Date("2026-09-08T16:01:00.000Z");
  const successor = await scheduled(
    { scheduledTime: current.getTime(), cron: "2-57/5 * * * *" },
    { ...env, ALERT_SCHEDULER_TIMEOUT_MS: "120000" },
  );
  assert.equal(successor.runKind, "continuation");
  assert.equal(successor.status, "completed");
  assert.equal(successor.evaluationWindowStartedAt, origin);
  assert.equal(successor.weeklyWindowAt, weekly);
  assert.equal(provider.messages.length, 1);
  releaseStale();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(database.prepare(
    "SELECT COUNT(*) AS count FROM notification_events WHERE event_key='amended:recovered'",
  ).get().count, 1);
  const subscription = database.prepare(
    "SELECT evaluation_cursor_at,last_evaluated_at FROM subscriptions WHERE id='watch-1'",
  ).get();
  assert.deepEqual({ ...subscription }, { evaluation_cursor_at: null, last_evaluated_at: input });
  const health = await realStore.operationalHealth("2026-09-08T16:01:01.000Z");
  assert.equal(health.pendingEvaluationWindows, 0);
  assert.equal(health.schedulerRecent, true);
});

test("candidate-scoped Strong matching preserves full-engine admission on the public catalog", async () => {
  const [catalogText, subtopicsText] = await Promise.all([
    readFile(new URL("data/opportunities.js", root), "utf8"),
    readFile(new URL("data/subtopics.js", root), "utf8"),
  ]);
  const catalog = parseAssignedJson(catalogText, "GRANT_CATALOG");
  const subtopics = parseAssignedJson(subtopicsText, "SUBTOPIC_CATALOG");
  const definition = {
    query: "hydrogen catalysis",
    filters: {
      status: { posted: true, forecasted: true, archived: false },
      facets: { source: [], source_type: [], discipline: [], topic: [], agency: [], eligibility: [], funding_instrument: [] },
      deadline: { from: "", through: "" }, minimum_award: 0,
      flags: { evidence: false, preliminary: false, limited: false, early_career: false, no_cost_share: false },
      audience: "all",
    },
    currentness: "current_only", strong_contract_version: "funding-search-v2-strong-1",
    include_potential: false,
  };
  const full = new StrongMatchEngine(catalog, subtopics);
  const fullIds = full.matchIds(definition, "2026-08-28", null);
  const candidateIds = [...new Set([
    ...catalog.opportunities.slice(0, 75).map(record => String(record.opportunity_id)),
    ...[...fullIds].slice(0, 25),
  ])];
  const scoped = new StrongMatchEngine(catalog, subtopics);
  const scopedIds = scoped.matchIds(definition, "2026-08-28", candidateIds);
  assert.deepEqual([...scopedIds].sort(), candidateIds.filter(id => fullIds.has(id)).sort());
});

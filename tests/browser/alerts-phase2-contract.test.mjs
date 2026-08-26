import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { ALERT_SCHEMA_VERSION } from "../../workers/alerts/src/contract.js";
import { sha256Hex } from "../../workers/alerts/src/crypto.js";
import { digestEmail, eventEmail } from "../../workers/alerts/src/email.js";
import {
  DIGEST_MAX_EVENTS, dispatchNotifications, dispatchVerificationDeliveries, evaluateSubscriptions,
} from "../../workers/alerts/src/evaluator.js";
import { createHandler, createScheduledHandler } from "../../workers/alerts/src/index.js";
import { MockEmailProvider, ResendEmailProvider } from "../../workers/alerts/src/provider.js";
import { D1AlertStore } from "../../workers/alerts/src/store.js";

const root = new URL("../../", import.meta.url);
const migrationNames = [
  "0001_phase3_alerts.sql", "0002_delivery_claim_lease.sql", "0003_phase2_alert_lifecycle.sql",
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
  const token = await sha256Hex(`funding-finder-verification-v1|${manageToken}|${id}|${nonce}`);
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

async function post(handler, path, body, activeEnv = env) {
  return handler(new Request(`https://alerts.example.test${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: "https://mporosoff.github.io" },
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
    all(database, "SELECT status,message_kind,terminal_at FROM notification_events ORDER BY id")
      .map(row => [row.status, row.message_kind, row.terminal_at]),
    ["failed", "queued", "sending", "sent"].map(status => [status, "notification", null]),
  );
  const columns = all(database, "PRAGMA table_info(notification_events)").map(row => row.name);
  assert.ok(columns.includes("message_kind"));
  assert.ok(columns.includes("terminal_at"));
  assert.ok(columns.includes("provider_quota_key"));
  assert.ok(columns.includes("provider_quota_reserved_at"));
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
      assert.equal(event.error_code, "subscription_reactivated_reconcile");
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
    { subscriptionCount: 1, matchedEventCount: 0 },
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
    { subscriptionCount: 1, matchedEventCount: 1 },
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
    const second = await dispatchVerificationDeliveries({ store, provider, env: limitedEnv, now: retryNow });
    assert.deepEqual(second, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
    const sent = database.prepare("SELECT * FROM notification_events WHERE id='verify-new'").get();
    assert.equal(sent.status, "sent");
    assert.equal(sent.attempts, 2);
    assert.equal(sent.provider_message_id, "provider-1");
    assert.equal(sent.provider_quota_key, provider.attempts[0].idempotencyKey);
    assert.ok(sent.provider_quota_reserved_at);
    assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
    assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
  }
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

test("FF-BUG-008 verification completed before quota reuse sends no obsolete retry", async () => {
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

  const originalClaimCheck = store.verificationClaimIsCurrent.bind(store);
  let completed = false;
  store.verificationClaimIsCurrent = async (...args) => {
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
  assert.deepEqual(retry, { attemptedCount: 0, deliveredCount: 0, failedCount: 0 });
  assert.equal(provider.attempts.length, 1);
  assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
  const event = database.prepare("SELECT status,error_code,terminal_at FROM notification_events WHERE id='verify-new'").get();
  assert.equal(event.status, "suppressed");
  assert.equal(event.error_code, "verification_completed");
  assert.ok(event.terminal_at);
});

test("FF-BUG-008 verification completion serializes with an authorized provider send", async () => {
  for (const finalFailure of [null, {
    code: "provider_network_failure", retryable: true,
  }]) {
    const database = databaseThrough();
    insertSubscriber(database);
    const store = new D1AlertStore(new SqliteD1(database));
    const verificationCycle = await cycle();
    await store.createSubscriptionCycle(verificationCycle);
    const provider = new ScriptedProvider([
      { code: "provider_network_failure", retryable: true },
      ...(finalFailure ? [finalFailure] : []),
    ]);
    const limitedEnv = { ...env, DAILY_EMAIL_LIMIT: "1" };
    await dispatchVerificationDeliveries({
      store, provider, env: limitedEnv, now: fixedNow,
    });

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
    const retry = await dispatchVerificationDeliveries({
      store, provider, env: limitedEnv, now: new Date("2026-09-01T12:06:00.000Z"),
    });
    assert.equal(retry.attemptedCount, 1);
    assert.equal(provider.attempts.length, 2);
    assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
    assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 1);
    assert.equal(database.prepare("SELECT request_count FROM rate_limits WHERE action='email_send' AND client_key='global'").get().request_count, 1);
    const event = database.prepare("SELECT status,error_code,terminal_at FROM notification_events WHERE id='verify-new'").get();
    if (finalFailure) {
      assert.deepEqual(retry, { attemptedCount: 1, deliveredCount: 0, failedCount: 1 });
      assert.equal(event.status, "suppressed");
      assert.equal(event.error_code, "verification_completed");
      assert.ok(event.terminal_at);
      assert.equal((await dispatchVerificationDeliveries({
        store, provider, env: limitedEnv, now: new Date("2026-09-01T12:20:00.000Z"),
      })).attemptedCount, 0);
    } else {
      assert.deepEqual(retry, { attemptedCount: 1, deliveredCount: 1, failedCount: 0 });
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
  const freshToken = await sha256Hex(`funding-finder-verification-v1|${"m".repeat(43)}|watch-1|${freshNonce}`);
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
  const verificationToken = await sha256Hex(
    `funding-finder-verification-v1|${"s".repeat(43)}|${subscriptionId}|${tokens[0]}`,
  );
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
  assert.equal(await store.suppressSubscriberByMessage("provider-1", "email.complained", "webhook-1", fixedNow.toISOString()), true);
  assert.ok(database.prepare("SELECT suppressed_at FROM subscribers WHERE id='person-1'").get().suppressed_at);
  assert.equal(database.prepare("SELECT active FROM subscriptions WHERE id='watch-1'").get().active, 0);
  assert.equal(await store.suppressSubscriberByMessage("provider-1", "email.complained", "webhook-1", fixedNow.toISOString()), false);
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
        assert.equal(await store.updateSubscription(
          person.manageToken, "watch-1", { active: false }, fixedNow.toISOString(),
        ), true);
        assert.equal((await store.createSubscriptionCycle(await cycle({
          verificationNonce: "z".repeat(43), verificationTokenHash: "replacement-token",
          verificationEventId: "verify-replacement", verificationEventKey: "verification:replacement-token",
        }))).cycleAccepted, true);
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
      ["failed", "subscription_reactivated_reconcile", null],
      ["failed", "subscription_reactivated_reconcile", null],
    ],
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
});

test("FF-BUG-017 a failed digest retries the whole claim with the same idempotency key", async () => {
  const database = databaseThrough();
  insertSubscriber(database);
  insertSubscription(database, { active: 1 });
  const store = new D1AlertStore(new SqliteD1(database));
  for (const id of ["digest-1", "digest-2"]) {
    await store.enqueueEvent({
      id, subscriptionId: "watch-1", eventKey: id, eventKind: "amended",
      opportunityId: id, payload: { title: id }, createdAt: fixedNow.toISOString(),
    });
  }
  const provider = new ScriptedProvider([{ code: "provider_network_failure", retryable: true }]);
  const first = await dispatchNotifications({ store, provider, env, now: fixedNow, weekly: true });
  assert.equal(first.failedCount, 1);
  assert.deepEqual(all(database, "SELECT status FROM notification_events ORDER BY id").map(row => row.status), ["failed", "failed"]);
  const retryNow = new Date("2026-09-01T12:06:00.000Z");
  const second = await dispatchNotifications({ store, provider, env, now: retryNow, weekly: true });
  assert.equal(second.deliveredCount, 1);
  assert.deepEqual(all(database, "SELECT status FROM notification_events ORDER BY id").map(row => row.status), ["sent", "sent"]);
  assert.equal(provider.attempts[0].idempotencyKey, provider.attempts[1].idempotencyKey);
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
  assert.equal(ALERT_SCHEMA_VERSION, 2);
  assert.match(workflow, /delivery_ready/);
  assert.match(workflow, /scheduler_ready/);
  assert.match(workflow, /phase2-lifecycle-20260825/);
  assert.match(workflow, /worker_version_rollback/);
  assert.match(wrangler, /"ALERT_SCHEDULER_ENABLED": "true"/);
  assert.match(wrangler, /"crons": \["15 13 \* \* \*"\]/);
  assert.match(smoke, /delivery_ready/);
  assert.match(migration, /deployment workflow terminalizes unsent verification/);
  assert.doesNotMatch(workflow + wrangler + smoke + migration, /RESEND_API_KEY\s*[:=]\s*["']?re_/i);
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

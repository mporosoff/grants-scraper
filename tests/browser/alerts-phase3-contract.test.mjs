import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { normalizeSubscription } from "../../workers/alerts/src/contract.js";
import { randomToken } from "../../workers/alerts/src/crypto.js";
import { createHandler } from "../../workers/alerts/src/index.js";
import { dispatchNotifications, evaluateSubscriptions } from "../../workers/alerts/src/evaluator.js";
import { MockEmailProvider, ResendEmailProvider } from "../../workers/alerts/src/provider.js";

const fixedNow = new Date("2026-09-01T12:00:00.000Z");
const env = {
  ALERTS_API_ENABLED: "true",
  OUTBOUND_EMAIL_ENABLED: "true",
  EMAIL_PROVIDER: "resend",
  RESEND_API_KEY: "test-only",
  PUBLIC_WORKER_ORIGIN: "https://alerts.example.test",
  PUBLIC_APP_ORIGIN: "https://app.example.test",
  DAILY_EMAIL_LIMIT: "100",
};

class MemoryStore {
  constructor() {
    this.subscribers = new Map();
    this.subscriptions = new Map();
    this.qual = new Map();
    this.events = new Map();
    this.rates = new Map();
  }
  async health() { return true; }
  async consumeRateLimit(action, key, limit) {
    const id = `${action}:${key}`;
    const count = this.rates.get(id) || 0;
    if (count >= limit) return false;
    this.rates.set(id, count + 1);
    return true;
  }
  async upsertSubscriber(value) {
    const existing = [...this.subscribers.values()].find(item => item.email_normalized === value.email);
    if (existing) return existing;
    const row = { ...value, email_normalized: value.email, manage_token: value.manageToken, suppressed_at: null };
    this.subscribers.set(row.id, row);
    return row;
  }
  async findSubscription(subscriberId, type, definitionHash) {
    return [...this.subscriptions.values()].find(item => item.subscriber_id === subscriberId && item.type === type && item.definition_hash === definitionHash) || null;
  }
  async createPendingSubscription(value) {
    const existing = await this.findSubscription(value.subscriberId, value.type, value.definitionHash);
    if (existing) {
      existing.verification_token_hash = value.verificationTokenHash;
      existing.verification_expires_at = value.verificationExpiresAt;
      return { ...existing, created: false, alreadyActive: existing.active === 1 };
    }
    const row = {
      id: value.id, subscriber_id: value.subscriberId, type: value.type,
      active: 0, cadence: value.cadence, definition_json: value.definitionJson,
      definition_hash: value.definitionHash, verification_token_hash: value.verificationTokenHash,
      verification_expires_at: value.verificationExpiresAt, verified_at: null,
      baseline_at: value.now, baseline_complete: 0, last_evaluated_at: null, created_at: value.now,
    };
    this.subscriptions.set(row.id, row);
    return { ...row, created: true, alreadyActive: false };
  }
  async setBaseline(id, opportunityIds) {
    if (!this.qual.has(id)) this.qual.set(id, new Map());
    for (const opportunityId of opportunityIds) this.qual.get(id).set(opportunityId, true);
    this.subscriptions.get(id).baseline_complete = 1;
  }
  async verifySubscription(tokenHash, now) {
    const sub = [...this.subscriptions.values()].find(item => item.verification_token_hash === tokenHash && item.baseline_complete === 1);
    if (!sub || sub.verification_expires_at < now) return null;
    sub.active = 1;
    sub.verified_at = now;
    const person = this.subscribers.get(sub.subscriber_id);
    return { ...sub, email: person.email, manage_token: person.manage_token };
  }
  async subscriberByManageToken(token) {
    return [...this.subscribers.values()].find(item => item.manage_token === token) || null;
  }
  async subscriptionsForSubscriber(id) { return [...this.subscriptions.values()].filter(item => item.subscriber_id === id); }
  async updateSubscription(token, id, changes) {
    const person = await this.subscriberByManageToken(token);
    const sub = this.subscriptions.get(id);
    if (!person || !sub || sub.subscriber_id !== person.id) return false;
    if (typeof changes.active === "boolean") sub.active = changes.active ? 1 : 0;
    if (["immediate", "weekly"].includes(changes.cadence)) sub.cadence = changes.cadence;
    return true;
  }
  async unsubscribe(token, id, now) { return this.updateSubscription(token, id, { active: false }, now); }
  async activeSubscriptions() {
    return [...this.subscriptions.values()].flatMap(sub => {
      const person = this.subscribers.get(sub.subscriber_id);
      return sub.active === 1 && sub.verified_at && !person.suppressed_at
        ? [{ ...sub, email: person.email, manage_token: person.manage_token }]
        : [];
    });
  }
  async qualifications(id, opportunityIds) {
    const current = this.qual.get(id) || new Map();
    return new Map(opportunityIds.flatMap(opportunityId => current.has(opportunityId) ? [[opportunityId, current.get(opportunityId)]] : []));
  }
  async setQualification(id, opportunityId, qualified) {
    if (!this.qual.has(id)) this.qual.set(id, new Map());
    this.qual.get(id).set(opportunityId, qualified);
  }
  async enqueueEvent(event) {
    const duplicate = [...this.events.values()].some(item => item.subscription_id === event.subscriptionId && item.event_key === event.eventKey);
    if (duplicate) return false;
    this.events.set(event.id, {
      id: event.id, subscription_id: event.subscriptionId, event_key: event.eventKey,
      event_kind: event.eventKind, opportunity_id: event.opportunityId,
      payload_json: JSON.stringify(event.payload), status: "queued", attempts: 0,
      next_attempt_at: event.createdAt, created_at: event.createdAt,
    });
    return true;
  }
  async markEvaluated(id, at) { this.subscriptions.get(id).last_evaluated_at = at; }
  async sentCountSince() { return [...this.events.values()].filter(item => item.status === "sent").length; }
  async pendingEvents(cadence, now, limit) {
    const staleBefore = new Date(Date.parse(now) - 15 * 60 * 1_000).toISOString();
    return [...this.events.values()].flatMap(event => {
      const sub = this.subscriptions.get(event.subscription_id);
      const person = this.subscribers.get(sub.subscriber_id);
      const ready = (["queued", "failed"].includes(event.status) && event.next_attempt_at <= now)
        || (event.status === "sending" && event.claimed_at && event.claimed_at <= staleBefore);
      return ready
        && sub.active === 1 && sub.cadence === cadence && !person.suppressed_at
        ? [{ ...event, ...sub, id: event.id, subscription_id: sub.id, subscriber_id: sub.subscriber_id, email: person.email, manage_token: person.manage_token }]
        : [];
    }).slice(0, limit);
  }
  async claimEvents(ids, now = fixedNow.toISOString()) {
    const staleBefore = new Date(Date.parse(now) - 15 * 60 * 1_000).toISOString();
    return ids.flatMap(id => {
      const event = this.events.get(id);
      const claimable = event && (["queued", "failed"].includes(event.status)
        || (event.status === "sending" && event.claimed_at && event.claimed_at <= staleBefore));
      if (!claimable) return [];
      event.status = "sending";
      event.attempts += 1;
      event.claimed_at = now;
      return [id];
    });
  }
  async markEventsSent(ids, providerId, now) { for (const id of ids) Object.assign(this.events.get(id), { status: "sent", provider_message_id: providerId, sent_at: now, claimed_at: null }); }
  async markEventsFailed(ids, code, retry) { for (const id of ids) Object.assign(this.events.get(id), { status: "failed", error_code: code, next_attempt_at: retry, claimed_at: null }); }
  async suppressSubscriberByMessage(providerMessageId, reason, providerEventId, now) {
    this.providerEvents ||= new Set();
    if (this.providerEvents.has(providerEventId)) return false;
    this.providerEvents.add(providerEventId);
    const event = [...this.events.values()].find(item => item.provider_message_id === providerMessageId);
    if (!event) return false;
    const subscription = this.subscriptions.get(event.subscription_id);
    const person = this.subscribers.get(subscription.subscriber_id);
    Object.assign(person, { suppressed_at: now, suppression_reason: reason });
    for (const sub of this.subscriptions.values()) if (sub.subscriber_id === person.id) sub.active = 0;
    return true;
  }
}

function record(overrides = {}) {
  return {
    opportunity_id: "opp-1", opportunity_number: "PD-26-367Y",
    title: "Chemical Process Systems", agency: "National Science Foundation",
    agency_code: "NSF", status: "posted", close_date: "2026-11-01",
    funding_instruments: ["Grant"], applicant_types: [], ...overrides,
  };
}

function assets(overrides = {}) {
  const catalogRecords = overrides.records || [record()];
  return {
    catalog: { opportunities: catalogRecords, generated_at: "2026-09-02T00:00:00Z" },
    changes: { schema_version: 1, generated_at: "2026-09-02T00:00:00Z", events: overrides.events || [] },
    matcher: overrides.matcher || { matchIds: () => new Set(catalogRecords.map(item => item.opportunity_id)) },
  };
}

function subscriptionBody(type, definition, cadence = "immediate", baselineOpportunityIds = []) {
  return {
    email: "researcher@example.edu",
    baseline_opportunity_ids: baselineOpportunityIds,
    subscription: { type, cadence, definition },
  };
}

async function post(handler, path, body) {
  return handler(new Request(`https://alerts.example.test${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", Origin: "https://mporosoff.github.io" },
    body: JSON.stringify(body),
  }), env);
}

async function verifyLatest(handler, provider) {
  const match = provider.messages.at(-1).text.match(/\/verify\?token=([^\s]+)/);
  assert.ok(match);
  const response = await handler(new Request(`https://alerts.example.test/verify?token=${match[1]}`), env);
  assert.equal(response.status, 200);
}

test("rejects private profile material and any Potential-match default", () => {
  const base = {
    type: "saved_search", cadence: "weekly",
    definition: {
      query: "hydrogen catalysis",
      filters: {
        status: { posted: true, forecasted: true, archived: false },
        facets: { source: [], source_type: [], discipline: [], topic: [], agency: [], eligibility: [], funding_instrument: [] },
        deadline: { from: "", through: "" }, minimum_award: 0,
        flags: { evidence: false, preliminary: false, limited: false, early_career: false, no_cost_share: false },
        audience: "all",
      }, currentness: "current_only", strong_contract_version: "funding-search-v2-strong-1", include_potential: false,
    },
  };
  assert.ok(normalizeSubscription(base));
  assert.equal(normalizeSubscription({ ...base, definition: { ...base.definition, profile_text: "private" } }), null);
  assert.equal(normalizeSubscription({ ...base, definition: { ...base.definition, include_potential: true } }), null);
});

test("opportunity lifecycle verifies, sends exactly once, and stops after unsubscribe", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const state = assets();
  let token = 0;
  const handler = createHandler({
    storeFactory: () => store, providerFactory: () => provider, assetLoader: async () => state,
    now: () => fixedNow, tokenFactory: () => `${++token}`.padStart(43, "t"),
  });
  const response = await post(handler, "/subscriptions", subscriptionBody("opportunity", {
    opportunity_id: "opp-1", triggers: ["deadline_changed", "amended", "closing_reminders", "status_changed"],
  }));
  assert.equal(response.status, 202);
  assert.equal(provider.messages.length, 1);
  await verifyLatest(handler, provider);
  const person = [...store.subscribers.values()][0];
  const sub = [...store.subscriptions.values()][0];
  const manage = (body, origin = "https://alerts.example.test") => handler(new Request("https://alerts.example.test/manage", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Origin: origin },
    body: new URLSearchParams({ token: person.manage_token, subscription: sub.id, ...body }),
  }), env);
  assert.equal((await manage({ cadence: "weekly" })).status, 200);
  assert.equal(store.subscriptions.get(sub.id).cadence, "weekly");
  assert.equal((await manage({ active: "0" })).status, 200);
  assert.equal(store.subscriptions.get(sub.id).active, 0);
  assert.equal((await manage({ active: "1" })).status, 200);
  assert.equal(store.subscriptions.get(sub.id).active, 1);
  assert.equal((await manage({ cadence: "immediate" })).status, 200);
  assert.equal(store.subscriptions.get(sub.id).cadence, "immediate");
  assert.equal((await manage({ active: "0" }, "https://example.invalid")).status, 403);
  const opaqueMobileManage = headers => handler(new Request("https://alerts.example.test/manage", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Origin: "null",
      ...headers,
    },
    body: new URLSearchParams({
      token: person.manage_token,
      subscription: sub.id,
      cadence: "weekly",
    }),
  }), env);
  assert.equal((await opaqueMobileManage({
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
  })).status, 200);
  assert.equal(store.subscriptions.get(sub.id).cadence, "weekly");
  assert.equal((await opaqueMobileManage({ "Sec-Fetch-Site": "cross-site" })).status, 403);
  assert.equal((await handler(new Request("https://alerts.example.test/subscriptions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Origin: "null",
      "Sec-Fetch-Site": "same-origin",
      "Sec-Fetch-Mode": "navigate",
      "Sec-Fetch-Dest": "document",
    },
    body: JSON.stringify(subscriptionBody("opportunity", {
      opportunity_id: "opaque-api",
      triggers: ["deadline_changed"],
    })),
  }), env)).status, 403);
  assert.equal((await manage({ cadence: "immediate" })).status, 200);
  state.changes.events = [{
    id: "change-1", type: "deadline_changed", changed_at: "2026-09-02T00:00:00Z",
    opportunity_id: "opp-1", detail: "2026-10-01 → 2026-10-08", record: record({ close_date: "2026-10-08" }),
  }];
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(provider.messages.length, 2);
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(provider.messages.length, 2, "the same event is idempotent");
  const unsub = await handler(new Request(`https://alerts.example.test/unsubscribe?token=${person.manage_token}&subscription=${sub.id}`, { method: "POST" }), env);
  assert.equal(unsub.status, 200);
  assert.match(await unsub.text(), /You have been successfully unsubscribed from Funding Finder\./);
  state.changes.generated_at = "2026-09-03T00:00:00Z";
  state.changes.events.push({ id: "change-2", type: "amended", changed_at: "2026-09-03T00:00:00Z", opportunity_id: "opp-1", detail: "Changed", record: record() });
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(provider.messages.length, 2);
});

test("opportunity watches send the exact 30, 14, and 7 day reminders once", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const person = await store.upsertSubscriber({
    id: "reminder-person", email: "reminder@example.edu", manageToken: "m".repeat(43),
    now: "2026-09-01T12:00:00.000Z",
  });
  store.subscriptions.set("reminder-watch", {
    id: "reminder-watch", subscriber_id: person.id, type: "opportunity", active: 1,
    verified_at: "2026-09-01T12:00:00.000Z", cadence: "immediate",
    definition_json: JSON.stringify({ opportunity_id: "opp-1", triggers: ["closing_reminders"] }),
    baseline_at: "2026-09-01T12:00:00.000Z", last_evaluated_at: null,
  });
  const state = assets({ records: [record({ close_date: "2026-10-01" })] });
  for (const current of [
    new Date("2026-09-01T12:00:00.000Z"),
    new Date("2026-09-17T12:00:00.000Z"),
    new Date("2026-09-24T12:00:00.000Z"),
  ]) {
    await evaluateSubscriptions({ store, assets: state, env, now: current });
    await dispatchNotifications({ store, provider, env, now: current });
    await evaluateSubscriptions({ store, assets: state, env, now: current });
    await dispatchNotifications({ store, provider, env, now: current });
  }
  assert.equal(provider.messages.length, 3);
  assert.deepEqual(
    provider.messages.map(message => message.text.match(/(30|14|7)-day closing reminder/)?.[1]),
    ["30", "14", "7"],
  );
});

test("opportunity watches detect a non-closing status transition", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const person = await store.upsertSubscriber({
    id: "status-person", email: "status@example.edu", manageToken: "m".repeat(43),
    now: fixedNow.toISOString(),
  });
  store.subscriptions.set("status-watch", {
    id: "status-watch", subscriber_id: person.id, type: "opportunity", active: 1,
    verified_at: fixedNow.toISOString(), cadence: "immediate",
    definition_json: JSON.stringify({ opportunity_id: "opp-1", triggers: ["status_changed"] }),
    baseline_at: fixedNow.toISOString(), last_evaluated_at: null,
  });
  const state = assets({
    events: [{
      id: "status-1", type: "status_changed", changed_at: "2026-09-02T00:00:00Z",
      opportunity_id: "opp-1", detail: "forecasted → posted", record: record({ status: "posted" }),
    }],
  });
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(provider.messages.length, 1);
  assert.equal(provider.messages[0].subject, "Funding opportunity status changed");
});

test("saved-search creation baselines existing Strong matches and alerts once for a future qualifier", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const matched = new Set(["existing"]);
  const evaluatedCandidateSets = [];
  const state = assets({
    records: [record({ opportunity_id: "existing" }), record({ opportunity_id: "new", title: "Hydrogen catalysis" })],
    matcher: {
      matchIds: (_definition, _asOf, candidateIds) => {
        evaluatedCandidateSets.push(candidateIds);
        return new Set([...matched].filter(id => candidateIds.includes(id)));
      },
    },
  });
  const handler = createHandler({ storeFactory: () => store, providerFactory: () => provider, assetLoader: async () => state, now: () => fixedNow, tokenFactory: (() => { let value = 0; return () => `${++value}`.padStart(43, "s"); })() });
  const filters = {
    status: { posted: true, forecasted: true, archived: false },
    facets: { source: [], source_type: [], discipline: [], topic: [], agency: [], eligibility: [], funding_instrument: [] },
    deadline: { from: "", through: "" }, minimum_award: 0,
    flags: { evidence: false, preliminary: false, limited: false, early_career: false, no_cost_share: false }, audience: "all",
  };
  assert.equal((await post(handler, "/subscriptions", subscriptionBody("saved_search", {
    query: "hydrogen catalysis", filters, currentness: "current_only",
    strong_contract_version: "funding-search-v2-strong-1", include_potential: false,
  }, "immediate", ["existing"]))).status, 202);
  await verifyLatest(handler, provider);
  assert.equal([...store.qual.values()][0].get("existing"), true);
  assert.equal(store.events.size, 0);
  matched.add("new");
  state.changes.events = [{ id: "new-1", type: "new", changed_at: "2026-09-02T00:00:00Z", opportunity_id: "new", detail: "First appeared", record: state.catalog.opportunities[1] }];
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  assert.deepEqual(evaluatedCandidateSets, [["new"]], "only changed records are evaluated");
  await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(provider.messages.filter(message => message.subject === "New Strong funding match").length, 1);
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(provider.messages.filter(message => message.subject === "New Strong funding match").length, 1);
});

test("program watches use the controlled NSF parent identity and weekly events consolidate", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const current = record({ opportunity_id: "362061", opportunity_number: "PD-26-367Y" });
  const next = record({ opportunity_id: "future-cps", opportunity_number: "PD-27-367Y", title: "New CPS cycle" });
  const state = assets({ records: [current, next] });
  const handler = createHandler({ storeFactory: () => store, providerFactory: () => provider, assetLoader: async () => state, now: () => fixedNow, tokenFactory: (() => { let value = 0; return () => `${++value}`.padStart(43, "p"); })() });
  assert.equal((await post(handler, "/subscriptions", subscriptionBody("program", { program_id: "nsf:cbet:cps" }, "weekly"))).status, 202);
  await verifyLatest(handler, provider);
  state.changes.events = [
    { id: "cycle", type: "new", changed_at: "2026-09-02T00:00:00Z", opportunity_id: "future-cps", detail: "First appeared", record: next },
    { id: "amend", type: "amended", changed_at: "2026-09-02T00:00:01Z", opportunity_id: "future-cps", detail: "Changed", record: next },
  ];
  await evaluateSubscriptions({ store, assets: state, env, now: fixedNow });
  assert.equal((await dispatchNotifications({ store, provider, env, now: fixedNow, weekly: false })).attemptedCount, 0);
  const result = await dispatchNotifications({ store, provider, env, now: fixedNow, weekly: true });
  assert.equal(result.deliveredCount, 1);
  assert.match(provider.messages.at(-1).subject, /weekly digest: 2 updates/);
});

test("provider failure leaves a claimed event retryable", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider({ fail: true });
  const person = await store.upsertSubscriber({ id: "p", email: "x@example.edu", manageToken: "m", now: fixedNow.toISOString() });
  store.subscriptions.set("s", { id: "s", subscriber_id: person.id, type: "opportunity", active: 1, verified_at: fixedNow.toISOString(), cadence: "immediate", definition_json: "{}" });
  await store.enqueueEvent({ id: "e", subscriptionId: "s", eventKey: "k", eventKind: "amended", opportunityId: "o", payload: { title: "Title" }, createdAt: fixedNow.toISOString() });
  const result = await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(result.failedCount, 1);
  assert.equal(store.events.get("e").status, "failed");
  assert.equal(store.events.get("e").provider_message_id, undefined);
});

test("an expired sending claim is safely reclaimed with the original idempotency key", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const person = await store.upsertSubscriber({
    id: "lease-person", email: "lease@example.edu", manageToken: "m".repeat(43),
    now: fixedNow.toISOString(),
  });
  store.subscriptions.set("lease-watch", {
    id: "lease-watch", subscriber_id: person.id, type: "opportunity", active: 1,
    verified_at: fixedNow.toISOString(), cadence: "immediate", definition_json: "{}",
  });
  await store.enqueueEvent({
    id: "lease-event", subscriptionId: "lease-watch", eventKey: "lease-key",
    eventKind: "amended", opportunityId: "opp-1", payload: { title: "Title" },
    createdAt: fixedNow.toISOString(),
  });
  Object.assign(store.events.get("lease-event"), {
    status: "sending",
    attempts: 1,
    claimed_at: new Date(fixedNow.getTime() - 16 * 60 * 1_000).toISOString(),
  });
  const result = await dispatchNotifications({ store, provider, env, now: fixedNow });
  assert.equal(result.deliveredCount, 1);
  assert.equal(store.events.get("lease-event").status, "sent");
  assert.equal(store.events.get("lease-event").attempts, 2);
  assert.equal(provider.messages[0].idempotencyKey, "lease-event");
});

test("the global provider cap queues overflow instead of dropping it", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const person = await store.upsertSubscriber({
    id: "cap-person", email: "cap@example.edu", manageToken: "m".repeat(43),
    now: fixedNow.toISOString(),
  });
  store.subscriptions.set("cap-watch", {
    id: "cap-watch", subscriber_id: person.id, type: "opportunity", active: 1,
    verified_at: fixedNow.toISOString(), cadence: "immediate", definition_json: "{}",
  });
  for (const id of ["cap-1", "cap-2"]) {
    await store.enqueueEvent({
      id, subscriptionId: "cap-watch", eventKey: id, eventKind: "amended",
      opportunityId: id, payload: { title: id }, createdAt: fixedNow.toISOString(),
    });
  }
  const cappedEnv = { ...env, DAILY_EMAIL_LIMIT: "1" };
  assert.equal((await dispatchNotifications({ store, provider, env: cappedEnv, now: fixedNow })).deliveredCount, 1);
  assert.equal((await dispatchNotifications({ store, provider, env: cappedEnv, now: fixedNow })).deliveredCount, 0);
  assert.equal(provider.messages.length, 1);
  assert.equal([...store.events.values()].filter(event => event.status === "queued").length, 1);
});

test("Resend provider uses the verified sender, secret authorization, and provider idempotency", async () => {
  let captured;
  const provider = new ResendEmailProvider({
    apiKey: "private-test-key",
    fetchImpl: async (_url, options) => {
      captured = options;
      return new Response(JSON.stringify({ id: "resend-1" }), { status: 200, headers: { "Content-Type": "application/json" } });
    },
  });
  await provider.sendEmail({ to: "x@example.edu", subject: "Subject", text: "Text", html: "<p>Text</p>" }, "event-1");
  assert.equal(captured.headers.Authorization, "Bearer private-test-key");
  assert.equal(captured.headers["Idempotency-Key"], "event-1");
  assert.equal(JSON.parse(captured.body).from, "Funding Finder <notifications@funding.porosoffresearchgroup.com>");
});

test("Resend provider safely distinguishes HTTP rejection from network failure", async () => {
  const message = { to: "x@example.edu", subject: "Subject", text: "Text", html: "<p>Text</p>" };
  const rejected = new ResendEmailProvider({
    apiKey: "private-test-key",
    fetchImpl: async () => new Response(JSON.stringify({ message: "must stay private" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    }),
  });
  await assert.rejects(rejected.sendEmail(message, "event-http"), error => {
    assert.equal(error.code, "provider_failed");
    assert.equal(error.providerFailureKind, "http");
    assert.equal(error.providerHttpStatus, 401);
    assert.doesNotMatch(error.message, /must stay private/);
    return true;
  });

  const unavailable = new ResendEmailProvider({
    apiKey: "private-test-key",
    fetchImpl: async () => { throw new Error("private network detail"); },
  });
  await assert.rejects(unavailable.sendEmail(message, "event-network"), error => {
    assert.equal(error.code, "provider_network_failure");
    assert.equal(error.providerFailureKind, "network");
    assert.equal(error.providerHttpStatus, undefined);
    assert.doesNotMatch(error.message, /private network detail/);
    return true;
  });
});

test("production handler resolves fetch inside the active request context", async () => {
  const originalFetch = globalThis.fetch;
  const store = new MemoryStore();
  try {
    globalThis.fetch = async () => { throw new TypeError("stale request context"); };
    const handler = createHandler({
      storeFactory: () => store,
      now: () => fixedNow,
      tokenFactory: () => randomToken(),
    });
    globalThis.fetch = async () => new Response(JSON.stringify({ id: "resend-live-context" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const response = await post(handler, "/subscriptions", subscriptionBody("opportunity", {
      opportunity_id: "opp-live-context",
      triggers: ["deadline_changed"],
    }));
    assert.equal(response.status, 202);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("subscription creation is rate limited without exposing account existence", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const state = assets();
  const handler = createHandler({ storeFactory: () => store, providerFactory: () => provider, assetLoader: async () => state, now: () => fixedNow, tokenFactory: () => randomToken() });
  const body = subscriptionBody("opportunity", {
    opportunity_id: "opp-1", triggers: ["deadline_changed"],
  });
  for (let index = 0; index < 5; index += 1) assert.equal((await post(handler, "/subscriptions", body)).status, 202);
  const limited = await post(handler, "/subscriptions", body);
  assert.equal(limited.status, 429);
  assert.deepEqual(await limited.json(), { error: { code: "rate_limited" } });
});

test("authenticated duplicate Resend bounce webhooks suppress future delivery", async () => {
  const store = new MemoryStore();
  const provider = new MockEmailProvider();
  const person = await store.upsertSubscriber({ id: "bounce-person", email: "bounce@example.edu", manageToken: "m".repeat(43), now: fixedNow.toISOString() });
  store.subscriptions.set("bounce-sub", { id: "bounce-sub", subscriber_id: person.id, type: "opportunity", active: 1, verified_at: fixedNow.toISOString(), cadence: "immediate", definition_json: "{}" });
  await store.enqueueEvent({ id: "bounce-event", subscriptionId: "bounce-sub", eventKey: "bounce", eventKind: "amended", opportunityId: "o", payload: { title: "Title" }, createdAt: fixedNow.toISOString() });
  await store.claimEvents(["bounce-event"]);
  await store.markEventsSent(["bounce-event"], "resend-bounce-1", fixedNow.toISOString());
  const secretBytes = new TextEncoder().encode("deterministic-webhook-secret");
  const secret = `whsec_${Buffer.from(secretBytes).toString("base64")}`;
  const payload = JSON.stringify({ type: "email.bounced", data: { email_id: "resend-bounce-1" } });
  const timestamp = String(Math.floor(fixedNow.getTime() / 1_000));
  const svixId = "msg_phase3_bounce";
  const key = await crypto.subtle.importKey("raw", secretBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = Buffer.from(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${svixId}.${timestamp}.${payload}`))).toString("base64");
  const webhookEnv = { ...env, RESEND_WEBHOOK_SECRET: secret };
  const handler = createHandler({ storeFactory: () => store, providerFactory: () => provider, assetLoader: async () => assets(), now: () => fixedNow });
  const request = () => new Request("https://alerts.example.test/webhooks/resend", {
    method: "POST",
    headers: { "svix-id": svixId, "svix-timestamp": timestamp, "svix-signature": `v1,${signature}` },
    body: payload,
  });
  assert.equal((await handler(request(), webhookEnv)).status, 200);
  assert.ok(store.subscribers.get(person.id).suppressed_at);
  assert.equal(store.subscriptions.get("bounce-sub").active, 0);
  assert.equal((await handler(request(), webhookEnv)).status, 200);
  assert.equal(store.providerEvents.size, 1);
});

test("Phase 3 deployment and privacy contracts are committed without Phase 4 scope", async () => {
  const root = new URL("../../", import.meta.url);
  const [page, awards, alerts, worker, migration, leaseMigration, workflow, wrangler, evidence] = await Promise.all([
    readFile(new URL("match_explorer.html", root), "utf8"),
    readFile(new URL("funded_awards.html", root), "utf8"),
    readFile(new URL("assets/alerts.js", root), "utf8"),
    readFile(new URL("workers/alerts/src/index.js", root), "utf8"),
    readFile(new URL("workers/alerts/migrations/0001_phase3_alerts.sql", root), "utf8"),
    readFile(new URL("workers/alerts/migrations/0002_delivery_claim_lease.sql", root), "utf8"),
    readFile(new URL(".github/workflows/deploy-alerts.yml", root), "utf8"),
    readFile(new URL("workers/alerts/wrangler.jsonc", root), "utf8"),
    readFile(new URL("evaluation/alerts_phase3.json", root), "utf8"),
  ]);
  assert.match(page, /Alert me to new Strong matches/);
  assert.match(awards, /Watch this program/);
  assert.match(alerts, /Pursuit status and notes, profile\/CV text, ORCID publication text, uploaded documents, and AI chat stay in this browser/);
  assert.match(worker, /RESEND_WEBHOOK_SECRET/);
  assert.match(migration, /UNIQUE \(subscription_id, event_key\)/);
  assert.match(migration, /subscription_qualifications/);
  assert.match(leaseMigration, /claimed_at/);
  assert.match(leaseMigration, /WHERE status = 'sending'/);
  assert.match(workflow, /d1 migrations apply funding-finder-alerts --remote/);
  assert.match(workflow, /assets\/search-query\.js/);
  assert.match(workflow, /assets\/search-retrieval\.js/);
  assert.match(workflow, /assets\/search-v2-config\.js/);
  assert.match(workflow, /sort_by\(\[\(\.created_on \/\/ ""\), \(\.id \/\/ ""\)\]\)\s*\| last/);
  assert.doesNotMatch(workflow, /\.\[0\]\.versions/);
  assert.match(workflow, /wrangler@4\.125\.0 rollback/);
  assert.match(wrangler, /"crons": \["15 13 \* \* \*"\]/);
  assert.doesNotMatch(wrangler, /RESEND_API_KEY|re_[A-Za-z0-9]/);
  assert.equal(JSON.parse(evidence).phase, 3);
  assert.doesNotMatch(worker + alerts + workflow, /\bDOE\b|award vector|semantic award/i);
});

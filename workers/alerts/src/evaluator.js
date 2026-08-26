import "../../../assets/award-links.js";

import { recordId } from "./contract.js";
import { randomToken, sha256Hex } from "./crypto.js";
import { digestEmail, eventEmail, verificationEmail } from "./email.js";

const LINKS_API = globalThis.FUNDING_AWARD_LINKS;
const CHANGE_KINDS = new Set(["new", "deadline_changed", "amended", "status_changed", "closed_or_removed"]);
export const DIGEST_MAX_EVENTS = 25;
const VERIFICATION_VALIDITY_MS = 24 * 60 * 60_000;
const VERIFICATION_MINIMUM_SEND_WINDOW_MS = 60 * 60_000;

function isoDate(now) {
  return now.toISOString().slice(0, 10);
}

function daysBetween(left, right) {
  const start = Date.parse(`${left}T12:00:00Z`);
  const end = Date.parse(`${right}T12:00:00Z`);
  return Number.isFinite(start) && Number.isFinite(end)
    ? Math.round((end - start) / 86_400_000)
    : null;
}

function safeHttpUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function fundingFinderUrl(record, env) {
  const id = recordId(record);
  const origin = safeHttpUrl(env.PUBLIC_APP_ORIGIN);
  if (!origin || !id) return "";
  const url = new URL("match_explorer.html", origin.endsWith("/") ? origin : `${origin}/`);
  url.searchParams.set("focus", id);
  return url.href;
}

function officialUrl(record) {
  return safeHttpUrl(
    record?.primary_document_url || record?.funding_opportunity_url || record?.detail_page,
  );
}

function programLabel(record) {
  return String(
    LINKS_API.programIdentityForOpportunity(record)?.label
    || record?.opportunity_number
    || "",
  ).replace(/\s+/g, " ").trim().slice(0, 300);
}

function boundedReason(value, maximum = 320) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maximum) return text;
  const prefix = text.slice(0, maximum - 1);
  const boundary = prefix.lastIndexOf(" ");
  return `${prefix.slice(0, boundary >= Math.floor(maximum * 0.7) ? boundary : maximum - 1).trim()}…`;
}

function payloadFor(record, detail, env, whyMatched = []) {
  return {
    title: String(record?.title || "Funding opportunity").slice(0, 600),
    agency: String(record?.agency || "").slice(0, 300),
    program: programLabel(record),
    close_date: String(record?.close_date || "").slice(0, 10),
    detail: String(detail || "").replace(/\s+/g, " ").trim().slice(0, 600),
    why_matched: whyMatched.slice(0, 2).map(value => boundedReason(value)).filter(Boolean),
    funding_finder_url: fundingFinderUrl(record, env),
    official_url: officialUrl(record),
  };
}

async function enqueue(store, subscription, value, now) {
  const id = `evt_${(await sha256Hex(`${subscription.id}|${value.eventKey}`)).slice(0, 32)}`;
  return store.enqueueEvent({
    id,
    subscriptionId: subscription.id,
    eventKey: value.eventKey,
    eventKind: value.eventKind,
    opportunityId: value.opportunityId,
    payload: value.payload,
    createdAt: now.toISOString(),
    cycle: {
      verificationTokenHash: subscription.verification_token_hash,
      baselineAt: subscription.baseline_at,
    },
  });
}

export function baselineIds(subscription, suppliedIds = []) {
  if (subscription.type === "opportunity") return [subscription.definition.opportunity_id];
  if (subscription.type === "program") return [];
  return [...new Set(suppliedIds.map(String).filter(Boolean))];
}

function relevantChanges(subscription, changes) {
  const since = subscription.last_evaluated_at || subscription.baseline_at || subscription.created_at;
  return changes.events.filter(event => (
    CHANGE_KINDS.has(event.type) && String(event.changed_at || "") > String(since || "")
  ));
}

async function evaluateOpportunity(store, subscription, assets, env, now) {
  const definition = JSON.parse(subscription.definition_json);
  const id = definition.opportunity_id;
  const triggers = new Set(definition.triggers);
  let matched = 0;
  for (const event of relevantChanges(subscription, assets.changes)) {
    if (String(event.opportunity_id) !== id) continue;
    const kind = event.type === "closed_or_removed" ? "status_changed" : event.type;
    if (!triggers.has(kind)) continue;
    const inserted = await enqueue(store, subscription, {
      eventKey: `${event.type}:${event.id}`,
      eventKind: kind,
      opportunityId: id,
      payload: payloadFor(event.record, event.detail, env),
    }, now);
    if (inserted) matched += 1;
  }
  if (triggers.has("closing_reminders")) {
    const record = assets.catalog.opportunities.find(item => recordId(item) === id);
    const remaining = record ? daysBetween(isoDate(now), record.close_date) : null;
    const threshold = [7, 14, 30].find(value => remaining === value);
    if (threshold) {
      const inserted = await enqueue(store, subscription, {
        eventKey: `closing:${id}:${record.close_date}:${threshold}`,
        eventKind: "closing_reminder",
        opportunityId: id,
        payload: payloadFor(record, `${threshold}-day closing reminder`, env),
      }, now);
      if (inserted) matched += 1;
    }
  }
  return matched;
}

async function evaluateSavedSearch(store, subscription, assets, env, now) {
  const definition = JSON.parse(subscription.definition_json);
  const changes = relevantChanges(subscription, assets.changes);
  if (!changes.length) return 0;
  const asOf = isoDate(now);
  const changedIds = [...new Set(changes.map(event => String(event.opportunity_id || "")).filter(Boolean))];
  const matchDetails = typeof assets.matcher.matchDetails === "function"
    ? assets.matcher.matchDetails(definition, asOf, changedIds)
    : new Map([...assets.matcher.matchIds(definition, asOf, changedIds)].map(id => [id, { reasons: [] }]));
  const prior = await store.qualifications(subscription.id, changedIds);
  const currentById = new Map(assets.catalog.opportunities.map(record => [recordId(record), record]));
  let matched = 0;
  for (const id of changedIds) {
    const qualifies = matchDetails.has(id);
    const didQualify = prior.get(id) === true;
    if (qualifies && !didQualify) {
      const sourceEvent = changes.find(event => String(event.opportunity_id) === id);
      const record = currentById.get(id) || sourceEvent?.record;
      const inserted = await enqueue(store, subscription, {
        eventKey: `strong:${id}:${sourceEvent?.id || assets.changes.generated_at}`,
        eventKind: "strong_match",
        opportunityId: id,
        payload: payloadFor(record, sourceEvent?.detail || "", env, matchDetails.get(id)?.reasons),
      }, now);
      if (inserted) matched += 1;
    }
    if (qualifies !== didQualify || !prior.has(id)) {
      await store.setQualification(subscription.id, id, qualifies, now.toISOString(), {
        verificationTokenHash: subscription.verification_token_hash,
        baselineAt: subscription.baseline_at,
      });
    }
  }
  return matched;
}

async function evaluateProgram(store, subscription, assets, env, now) {
  const definition = JSON.parse(subscription.definition_json);
  let matched = 0;
  for (const event of relevantChanges(subscription, assets.changes)) {
    if (!LINKS_API.matchesProgramIdentity(definition.program_id, event.record)) continue;
    const eventKind = {
      new: "program_new_cycle",
      amended: "program_amended",
      deadline_changed: "program_deadline_changed",
      status_changed: "program_status_changed",
      closed_or_removed: "program_status_changed",
    }[event.type];
    const inserted = await enqueue(store, subscription, {
      eventKey: `program:${definition.program_id}:${event.id}`,
      eventKind,
      opportunityId: String(event.opportunity_id || ""),
      payload: payloadFor(event.record, event.detail, env),
    }, now);
    if (inserted) matched += 1;
  }
  return matched;
}

export async function evaluateSubscriptions({ store, assets, env, now = new Date() }) {
  const subscriptions = await store.activeSubscriptions();
  let matchedEventCount = 0;
  for (const subscription of subscriptions) {
    let matched = 0;
    if (subscription.type === "opportunity") matched = await evaluateOpportunity(store, subscription, assets, env, now);
    else if (subscription.type === "saved_search") matched = await evaluateSavedSearch(store, subscription, assets, env, now);
    else if (subscription.type === "program") matched = await evaluateProgram(store, subscription, assets, env, now);
    matchedEventCount += matched;
    await store.markEvaluated(
      subscription.id,
      String(assets.changes.generated_at || now.toISOString()),
      now.toISOString(),
      {
        verificationTokenHash: subscription.verification_token_hash,
        baselineAt: subscription.baseline_at,
      },
    );
  }
  return { subscriptionCount: subscriptions.length, matchedEventCount };
}

function retryAt(event, now) {
  const delayMinutes = Math.min(24 * 60, 5 * (2 ** Math.min(8, Number(event.attempts || 0))));
  return new Date(now.getTime() + delayMinutes * 60_000).toISOString();
}

function retryableProviderFailure(error) {
  if (typeof error?.retryable === "boolean") return error.retryable;
  return new Set([
    "provider_network_failure", "provider_rate_limited", "provider_unavailable",
  ]).has(String(error?.code || ""));
}

export async function dispatchNotifications({ store, provider, env, now = new Date(), weekly = false }) {
  if (String(env.OUTBOUND_EMAIL_ENABLED || "").toLowerCase() !== "true") {
    return { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
  }
  const dailyLimit = Math.max(1, Math.min(100, Number(env.DAILY_EMAIL_LIMIT) || 100));
  let remaining = dailyLimit;
  const reconciliation = !weekly && typeof store.pendingNotificationReconciliationBatches === "function"
    ? await store.pendingNotificationReconciliationBatches(now.toISOString(), remaining, DIGEST_MAX_EVENTS)
    : [];
  const pending = weekly
    ? []
    : await store.pendingEvents("immediate", now.toISOString(), Math.max(0, remaining - reconciliation.length));
  let attemptedCount = 0;
  let deliveredCount = 0;
  let failedCount = 0;
  const batches = weekly
    ? await store.pendingDigestEvents(now.toISOString(), remaining, DIGEST_MAX_EVENTS)
    : [
        ...reconciliation,
        ...pending.slice(0, Math.max(0, remaining - reconciliation.length))
          .map(event => ({ events: [event], hasOverflow: false })),
      ];
  for (const batchValue of batches) {
    const batch = batchValue.events;
    const ids = await store.claimEvents(batch.map(event => event.id), now.toISOString());
    const claimed = batch.filter(event => ids.includes(event.id));
    if (!claimed.length) continue;
    const idempotencyKey = batchValue.idempotencyKey || (weekly
      ? `digest:${await sha256Hex(claimed.map(event => event.id).sort().join("|"))}`
      : claimed[0].id);
    if (!await store.reserveProviderMessage(idempotencyKey, ids, dailyLimit, 86_400, now)) {
      await store.releaseClaimedEvents(ids, now.toISOString());
      break;
    }
    attemptedCount += 1;
    const message = weekly || idempotencyKey.startsWith("digest:")
      ? digestEmail({ env, events: claimed, hasOverflow: batchValue.hasOverflow })
      : eventEmail({ env, event: claimed[0] });
    try {
      const delivery = await provider.sendEmail(message, idempotencyKey);
      await store.markEventsSent(ids, delivery.id, now.toISOString());
      deliveredCount += 1;
    } catch (error) {
      const retryable = retryableProviderFailure(error);
      await store.markEventsFailed(
        ids,
        String(error?.code || "provider_failed").slice(0, 80),
        retryable ? retryAt(claimed[0], now) : now.toISOString(),
        retryable ? null : now.toISOString(),
        String(error?.providerFailureKind || ""),
      );
      failedCount += 1;
    }
    remaining -= 1;
    if (!remaining) break;
  }
  return { attemptedCount, deliveredCount, failedCount };
}

export async function dispatchVerificationDeliveries({
  store, provider, env, now = new Date(), tokenFactory = () => randomToken(), limit = null,
}) {
  if (String(env.OUTBOUND_EMAIL_ENABLED || "").toLowerCase() !== "true") {
    return { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
  }
  const dailyLimit = Math.max(1, Math.min(100, Number(env.DAILY_EMAIL_LIMIT) || 100));
  const candidateLimit = Math.max(1, Math.min(dailyLimit, Number(limit) || dailyLimit));
  const pending = await store.pendingVerificationEvents(now.toISOString(), candidateLimit);
  let attemptedCount = 0;
  let deliveredCount = 0;
  let failedCount = 0;
  for (const candidate of pending) {
    const claimedAt = now.toISOString();
    const ids = await store.claimEvents([candidate.id], claimedAt);
    if (!ids.length) continue;
    let nonce = "";
    try { nonce = String(JSON.parse(candidate.payload_json)?.nonce || ""); } catch { /* refresh below */ }
    let token = nonce.length >= 32
      ? await sha256Hex(`funding-finder-verification-v1|${candidate.manage_token}|${candidate.subscription_id}|${nonce}`)
      : "";
    let tokenHash = token ? await sha256Hex(token) : "";
    const expiresAt = Date.parse(candidate.verification_expires_at);
    if (
      token.length < 32
      || tokenHash !== String(candidate.verification_token_hash || "")
      || !Number.isFinite(expiresAt)
      || expiresAt - now.getTime() < VERIFICATION_MINIMUM_SEND_WINDOW_MS
    ) {
      nonce = tokenFactory();
      token = await sha256Hex(`funding-finder-verification-v1|${candidate.manage_token}|${candidate.subscription_id}|${nonce}`);
      tokenHash = await sha256Hex(token);
      const refreshedExpiresAt = new Date(now.getTime() + VERIFICATION_VALIDITY_MS).toISOString();
      const refreshed = await store.refreshVerificationEvent(candidate.id, {
        nonce,
        tokenHash,
        expectedTokenHash: String(candidate.verification_token_hash || ""),
        expiresAt: refreshedExpiresAt,
        eventKey: `verification:${tokenHash}`,
        claimedAt,
        now: claimedAt,
      });
      if (!refreshed) {
        await store.markEventsFailed(ids, "verification_cycle_changed", claimedAt, claimedAt);
        continue;
      }
    } else if (!await store.verificationClaimIsCurrent(
      candidate.id, tokenHash, claimedAt,
    )) {
      await store.markEventsFailed(ids, "verification_cycle_changed", claimedAt, claimedAt);
      continue;
    }
    const idempotencyKey = `verify:${candidate.id}:${tokenHash.slice(0, 24)}`;
    if (!await store.reserveProviderMessage(idempotencyKey, ids, dailyLimit, 86_400, now)) {
      await store.releaseClaimedEvents(ids, claimedAt);
      break;
    }
    attemptedCount += 1;
    try {
      const delivery = await provider.sendEmail(verificationEmail({
        env,
        to: candidate.email,
        token,
        subscriptionId: candidate.subscription_id,
        manageToken: candidate.manage_token,
        type: candidate.type,
      }), idempotencyKey);
      await store.markEventsSent(ids, delivery.id, now.toISOString());
      deliveredCount += 1;
    } catch (error) {
      const retryable = retryableProviderFailure(error);
      await store.markEventsFailed(
        ids,
        String(error?.code || "provider_failed").slice(0, 80),
        retryable ? retryAt(candidate, now) : now.toISOString(),
        retryable ? null : now.toISOString(),
      );
      failedCount += 1;
    }
  }
  return { attemptedCount, deliveredCount, failedCount };
}

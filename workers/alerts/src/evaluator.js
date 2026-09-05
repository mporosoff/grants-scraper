import "../../../assets/award-links.js";

import { recordId } from "./contract.js";
import {
  capabilityUrls, randomToken, sha256Hex, verificationToken as createVerificationToken,
} from "./crypto.js";
import { digestEmail, eventEmail, verificationEmail } from "./email.js";

const LINKS_API = globalThis.FUNDING_AWARD_LINKS;
const CHANGE_KINDS = new Set(["new", "deadline_changed", "amended", "status_changed", "closed_or_removed"]);
export const DIGEST_MAX_EVENTS = 25;
export const EVALUATION_CHANGE_LIMIT = 25;
export const EVALUATION_SUBSCRIPTION_LIMIT = 4;
const VERIFICATION_VALIDITY_MS = 24 * 60 * 60_000;
const VERIFICATION_MINIMUM_SEND_WINDOW_MS = 60 * 60_000;

function isoDate(now) {
  return now.toISOString().slice(0, 10);
}

function throwIfAborted(signal) {
  if (!signal?.aborted) return;
  throw signal.reason instanceof Error
    ? signal.reason
    : Object.assign(new Error("Alert scheduler operation was aborted."), { code: "scheduler_aborted" });
}

async function assertSchedulerClaim(store, claim, signal) {
  throwIfAborted(signal);
  if (!claim?.runId || !claim?.token || typeof store.runClaimIsCurrent !== "function") return;
  if (!await store.runClaimIsCurrent(claim.runId, claim.token)) {
    throw Object.assign(new Error("Alert scheduler ownership changed."), {
      code: "scheduler_claim_lost",
    });
  }
  throwIfAborted(signal);
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

async function enqueue(store, subscription, value, now, evaluationContext = {}) {
  const id = `evt_${(await sha256Hex(`${subscription.id}|${value.eventKey}`)).slice(0, 32)}`;
  return store.enqueueEvent({
    id,
    subscriptionId: subscription.id,
    eventKey: value.eventKey,
    eventKind: value.eventKind,
    opportunityId: value.opportunityId,
    payload: value.payload,
    createdAt: now.toISOString(),
    evaluationWindowStartedAt: evaluationContext.evaluationWindowStartedAt || null,
    weeklyWindowAt: evaluationContext.weeklyWindowAt || null,
    cycle: {
      verificationTokenHash: subscription.verification_token_hash,
      baselineAt: subscription.baseline_at,
      evaluationWindowStartedAt: evaluationContext.evaluationWindowStartedAt || null,
      claim: evaluationContext.schedulerClaim || null,
    },
  });
}

export function baselineIds(subscription, suppliedIds = []) {
  if (subscription.type === "opportunity") return subscription.definition.opportunity_ids || [subscription.definition.opportunity_id];
  if (subscription.type === "program") return [];
  return [...new Set(suppliedIds.map(String).filter(Boolean))];
}

function evaluationError(code, message) {
  return Object.assign(new Error(message), { code });
}

function relevantChanges(
  subscription, changes, limit = EVALUATION_CHANGE_LIMIT,
  inputGeneratedAt = "", sourceGeneratedAt = "",
  evaluationWindowStartedAt = "", weeklyWindowAt = "",
) {
  const since = subscription.last_evaluated_at || subscription.baseline_at || subscription.created_at;
  let cursorAt = String(subscription.evaluation_cursor_at || "");
  let cursorEventId = String(subscription.evaluation_cursor_event_id || "");
  const sourceGeneration = String(changes.generated_at || sourceGeneratedAt || "");
  const inputGeneration = String(inputGeneratedAt || sourceGeneration);
  const inputTime = Date.parse(inputGeneration);
  const sourceTime = Date.parse(sourceGeneration);
  const sinceTime = Date.parse(String(since || ""));
  if (
    cursorAt
    && subscription.evaluation_window_started_at
    && String(subscription.evaluation_window_started_at) !== String(evaluationWindowStartedAt || "")
  ) {
    throw evaluationError("evaluation_window_mismatch", "The outstanding cursor belongs to another evaluation window.");
  }
  if (
    cursorAt
    && subscription.evaluation_input_generated_at
    && String(subscription.evaluation_input_generated_at) !== inputGeneration
  ) {
    throw evaluationError("evaluation_input_mismatch", "The outstanding cursor has a different immutable input boundary.");
  }
  if (
    cursorAt
    && subscription.evaluation_weekly_window_at
    && String(subscription.evaluation_weekly_window_at) !== String(weeklyWindowAt || "")
  ) {
    throw evaluationError("evaluation_weekly_window_mismatch", "The outstanding cursor has a different weekly window.");
  }
  if (!Number.isFinite(inputTime) || !Number.isFinite(sourceTime) || !Number.isFinite(sinceTime)) {
    throw evaluationError("evaluation_generation_invalid", "Alert evaluation input generation is invalid.");
  }
  if (sourceTime < inputTime) {
    throw evaluationError(
      "evaluation_generation_behind",
      "The available change feed predates the outstanding evaluation boundary.",
    );
  }
  const boundedEvents = changes.events.filter(event => (
    CHANGE_KINDS.has(event.type)
    && Number.isFinite(Date.parse(String(event.changed_at || "")))
    && Date.parse(String(event.changed_at || "")) <= inputTime
  ));
  const cursorTime = Date.parse(cursorAt);
  let rebased = false;
  if (cursorAt && !boundedEvents.some(event => (
    Date.parse(String(event.changed_at || "")) === cursorTime
    && String(event.id || "") === cursorEventId
  ))) {
    const retentionDays = Number(changes.retention_days);
    const coverageStart = Number.isFinite(retentionDays) && retentionDays > 0
      ? new Date(sourceTime - retentionDays * 86_400_000).toISOString()
      : "";
    if (!coverageStart || !Number.isFinite(sinceTime) || sinceTime < Date.parse(coverageStart)) {
      throw evaluationError(
        "evaluation_rebase_unsafe",
        "The outstanding cursor cannot be safely rebased inside the retained change-feed window.",
      );
    }
    cursorAt = "";
    cursorEventId = "";
    rebased = true;
  }
  const ordered = boundedEvents.filter(event => (
    Date.parse(String(event.changed_at || "")) > sinceTime
    && (!cursorAt
      || Date.parse(String(event.changed_at || "")) > cursorTime
      || (
        Date.parse(String(event.changed_at || "")) === cursorTime
        && String(event.id || "") > cursorEventId
      ))
  )).sort((left, right) => (
    Date.parse(String(left.changed_at || "")) - Date.parse(String(right.changed_at || ""))
    || String(left.id || "").localeCompare(String(right.id || ""))
  ));
  const events = ordered.slice(0, Math.max(1, limit));
  const last = events.at(-1) || null;
  return {
    events,
    complete: ordered.length <= events.length,
    cursorAt: String(last?.changed_at || cursorAt),
    cursorEventId: String(last?.id || cursorEventId),
    rebased,
  };
}

async function evaluateOpportunity(store, subscription, assets, env, now, changes, evaluationContext) {
  const definition = JSON.parse(subscription.definition_json);
  const ids = new Set(definition.opportunity_ids || [definition.opportunity_id]);
  const triggers = new Set(definition.triggers);
  let matched = 0;
  for (const event of changes) {
    const id = String(event.opportunity_id);
    if (!ids.has(id)) continue;
    const kind = event.type === "closed_or_removed" ? "status_changed" : event.type;
    if (!triggers.has(kind)) continue;
    const inserted = await enqueue(store, subscription, {
      eventKey: `${event.type}:${event.id}`,
      eventKind: kind,
      opportunityId: id,
      payload: payloadFor(event.record, event.detail, env),
    }, now, evaluationContext);
    if (inserted) matched += 1;
  }
  if (triggers.has("closing_reminders")) {
    for (const id of ids) {
      const record = assets.catalog.opportunities.find(item => recordId(item) === id);
      const remaining = record
        ? daysBetween(isoDate(evaluationContext.evaluationAsOf || now), record.close_date)
        : null;
      const threshold = [7, 14, 30].find(value => remaining === value);
      if (threshold) {
        const inserted = await enqueue(store, subscription, {
          eventKey: `closing:${id}:${record.close_date}:${threshold}`,
          eventKind: "closing_reminder",
          opportunityId: id,
          payload: payloadFor(record, `${threshold}-day closing reminder`, env),
        }, now, evaluationContext);
        if (inserted) matched += 1;
      }
    }
  }
  return matched;
}

async function evaluateSavedSearch(store, subscription, assets, env, now, changes, evaluationContext) {
  const definition = JSON.parse(subscription.definition_json);
  if (!changes.length) return 0;
  const asOf = isoDate(evaluationContext.evaluationAsOf || now);
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
      }, now, evaluationContext);
      if (inserted) matched += 1;
    }
    if (qualifies !== didQualify || !prior.has(id)) {
      await store.setQualification(subscription.id, id, qualifies, now.toISOString(), {
        verificationTokenHash: subscription.verification_token_hash,
        baselineAt: subscription.baseline_at,
        claim: evaluationContext.schedulerClaim || null,
      });
    }
  }
  return matched;
}

async function evaluateProgram(store, subscription, assets, env, now, changes, evaluationContext) {
  const definition = JSON.parse(subscription.definition_json);
  let matched = 0;
  for (const event of changes) {
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
    }, now, evaluationContext);
    if (inserted) matched += 1;
  }
  return matched;
}

export async function evaluateSubscriptions({
  store, assets, env, now = new Date(),
  subscriptionLimit = EVALUATION_SUBSCRIPTION_LIMIT,
  changeLimit = EVALUATION_CHANGE_LIMIT,
  evaluationWindowStartedAt = null,
  weeklyWindowAt = null,
  evaluationInputGeneratedAt = null,
  schedulerClaim = null,
  signal = null,
} = {}) {
  await assertSchedulerClaim(store, schedulerClaim, signal);
  const changes = assets?.changes && Array.isArray(assets.changes.events)
    ? assets.changes
    : { generated_at: now.toISOString(), events: [] };
  const sourceGeneratedAt = String(changes.generated_at || now.toISOString());
  const generatedAt = String(evaluationInputGeneratedAt || sourceGeneratedAt);
  const boundedSubscriptionLimit = Math.max(1, Math.min(25, Number(subscriptionLimit) || EVALUATION_SUBSCRIPTION_LIMIT));
  const boundedChangeLimit = Math.max(1, Math.min(50, Number(changeLimit) || EVALUATION_CHANGE_LIMIT));
  const loaded = typeof store.activeSubscriptionsForEvaluation === "function"
    ? await store.activeSubscriptionsForEvaluation(
        generatedAt, boundedSubscriptionLimit, evaluationWindowStartedAt,
      )
    : await store.activeSubscriptions();
  const sourceSubscriptions = Array.isArray(loaded) ? loaded : loaded.subscriptions;
  const subscriptions = (sourceSubscriptions || []).slice(0, boundedSubscriptionLimit);
  const batches = subscriptions.map(subscription => ({
    subscription,
    ...relevantChanges(
      subscription, changes, boundedChangeLimit, generatedAt,
      sourceGeneratedAt,
      evaluationWindowStartedAt, weeklyWindowAt,
    ),
  }));
  const matcherCandidates = [...new Set(batches.flatMap(batch => (
    batch.subscription.type === "saved_search"
      ? batch.events.map(event => String(event.opportunity_id || "")).filter(Boolean)
      : []
  )))];
  if (matcherCandidates.length && typeof assets.matcher?.prepare === "function") {
    assets.matcher.prepare(matcherCandidates);
  }
  let matchedEventCount = 0;
  let continuationRequired = Boolean(!Array.isArray(loaded) && loaded?.hasMore);
  const evaluationAsOf = Number.isFinite(Date.parse(String(evaluationWindowStartedAt || "")))
    ? new Date(evaluationWindowStartedAt)
    : now;
  const evaluationContext = {
    evaluationWindowStartedAt, weeklyWindowAt,
    evaluationInputGeneratedAt: generatedAt,
    evaluationSourceGeneratedAt: sourceGeneratedAt,
    evaluationAsOf,
    schedulerClaim,
  };
  for (const batch of batches) {
    await assertSchedulerClaim(store, schedulerClaim, signal);
    const { subscription } = batch;
    let matched = 0;
    if (subscription.type === "opportunity") matched = await evaluateOpportunity(store, subscription, assets, env, now, batch.events, evaluationContext);
    else if (subscription.type === "saved_search") matched = await evaluateSavedSearch(store, subscription, assets, env, now, batch.events, evaluationContext);
    else if (subscription.type === "program") matched = await evaluateProgram(store, subscription, assets, env, now, batch.events, evaluationContext);
    matchedEventCount += matched;
    const cycle = {
      verificationTokenHash: subscription.verification_token_hash,
      baselineAt: subscription.baseline_at,
      evaluationWindowStartedAt,
      weeklyWindowAt,
      evaluationInputGeneratedAt: generatedAt,
      evaluationSourceGeneratedAt: sourceGeneratedAt,
      calendarEvaluationDate: isoDate(evaluationAsOf),
      claim: schedulerClaim,
    };
    if (batch.complete) {
      const complete = typeof store.completeEvaluation === "function"
        ? store.completeEvaluation.bind(store)
        : store.markEvaluated.bind(store);
      await complete(subscription.id, generatedAt, now.toISOString(), cycle);
    } else {
      continuationRequired = true;
      if (typeof store.saveEvaluationCursor === "function") {
        await store.saveEvaluationCursor(
          subscription.id, batch.cursorAt, batch.cursorEventId, now.toISOString(), cycle,
        );
      } else {
        await store.markEvaluated(subscription.id, batch.cursorAt, now.toISOString(), cycle);
      }
    }
    await assertSchedulerClaim(store, schedulerClaim, signal);
  }
  return {
    subscriptionCount: subscriptions.length,
    matchedEventCount,
    continuationRequired,
    processedChangeCount: batches.reduce((sum, batch) => sum + batch.events.length, 0),
    rebasedSubscriptionCount: batches.filter(batch => batch.rebased).length,
    evaluationInputGeneratedAt: generatedAt,
    evaluationSourceGeneratedAt: sourceGeneratedAt,
  };
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

function providerFailureKind(error) {
  if (error?.providerFailureKind) return String(error.providerFailureKind);
  return String(error?.code || "") === "provider_network_failure" ? "network" : "";
}

function storedProviderMessage(value) {
  if (!value) return null;
  try {
    const message = typeof value === "string" ? JSON.parse(value) : value;
    if (![message?.to, message?.subject, message?.html, message?.text].every(item => typeof item === "string")) {
      return null;
    }
    return message;
  } catch {
    return null;
  }
}

async function deliveryCapabilityLinks(env, event) {
  return env.ALERT_CAPABILITY_SECRET
    ? capabilityUrls(env, event.subscriber_id, event.subscription_id)
    : null;
}

export async function dispatchNotifications({
  store, provider, env, now = new Date(), weekly = false, limit = null,
  eligibleBefore = null,
  schedulerClaim = null, signal = null,
}) {
  await assertSchedulerClaim(store, schedulerClaim, signal);
  if (String(env.OUTBOUND_EMAIL_ENABLED || "").toLowerCase() !== "true") {
    return { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
  }
  const dailyLimit = Math.max(1, Math.min(100, Number(env.DAILY_EMAIL_LIMIT) || 100));
  let remaining = Math.max(1, Math.min(dailyLimit, Number(limit) || dailyLimit));
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
    ? await store.pendingDigestEvents(
        now.toISOString(), remaining, DIGEST_MAX_EVENTS, eligibleBefore,
      )
    : [
        ...reconciliation,
        ...pending.slice(0, Math.max(0, remaining - reconciliation.length))
          .map(event => ({ events: [event], hasOverflow: false })),
      ];
  for (const batchValue of batches) {
    await assertSchedulerClaim(store, schedulerClaim, signal);
    const batch = batchValue.events;
    const ids = await store.claimEvents(batch.map(event => event.id), now.toISOString(), schedulerClaim);
    const claimed = batch.filter(event => ids.includes(event.id));
    if (!claimed.length) continue;
    const idempotencyKey = batchValue.idempotencyKey || (weekly
      ? `digest:${await sha256Hex(claimed.map(event => event.id).sort().join("|"))}`
      : claimed[0].id);
    const renderedMessage = weekly || idempotencyKey.startsWith("digest:")
      ? digestEmail({
          env, events: claimed, hasOverflow: batchValue.hasOverflow,
          capabilityLinks: await deliveryCapabilityLinks(env, claimed[0]),
        })
      : eventEmail({
          env, event: claimed[0],
          capabilityLinks: await deliveryCapabilityLinks(env, claimed[0]),
        });
    const reservedPayload = batchValue.providerPayloadJson
      || claimed.find(event => (
        event.provider_quota_key === idempotencyKey && event.provider_payload_json
      ))?.provider_payload_json;
    const message = storedProviderMessage(reservedPayload) || renderedMessage;
    if (!await store.reserveProviderMessage(
      idempotencyKey, ids, dailyLimit, 86_400, now, batchValue.hasOverflow, message,
      schedulerClaim,
    )) {
      await store.releaseClaimedEvents(ids, now.toISOString(), schedulerClaim);
      break;
    }
    attemptedCount += 1;
    let delivery;
    try {
      delivery = await provider.sendEmail(message, idempotencyKey, { signal });
    } catch (error) {
      const retryable = retryableProviderFailure(error);
      await store.markEventsFailed(
        ids,
        String(error?.code || "provider_failed").slice(0, 80),
        retryable ? retryAt(claimed[0], now) : now.toISOString(),
        retryable ? null : now.toISOString(),
        providerFailureKind(error),
        schedulerClaim,
      );
      failedCount += 1;
      remaining -= 1;
      if (!remaining) break;
      continue;
    }
    await store.markEventsSent(ids, delivery.id, now.toISOString(), schedulerClaim);
    deliveredCount += 1;
    remaining -= 1;
    if (!remaining) break;
  }
  return { attemptedCount, deliveredCount, failedCount };
}

export async function dispatchVerificationDeliveries({
  store, provider, env, now = new Date(), tokenFactory = () => randomToken(), limit = null,
  eventIds = null,
  schedulerClaim = null, signal = null,
}) {
  await assertSchedulerClaim(store, schedulerClaim, signal);
  if (String(env.OUTBOUND_EMAIL_ENABLED || "").toLowerCase() !== "true") {
    return { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
  }
  const dailyLimit = Math.max(1, Math.min(100, Number(env.DAILY_EMAIL_LIMIT) || 100));
  const candidateLimit = Math.max(1, Math.min(dailyLimit, Number(limit) || dailyLimit));
  const pending = await store.pendingVerificationEvents(now.toISOString(), candidateLimit, eventIds);
  let attemptedCount = 0;
  let deliveredCount = 0;
  let failedCount = 0;
  for (const candidate of pending) {
    await assertSchedulerClaim(store, schedulerClaim, signal);
    const claimedAt = now.toISOString();
    const ids = await store.claimEvents([candidate.id], claimedAt, schedulerClaim);
    if (!ids.length) continue;
    let nonce = "";
    try { nonce = String(JSON.parse(candidate.payload_json)?.nonce || ""); } catch { /* refresh below */ }
    const reconciliation = candidate.error_code === "verification_outcome_reconcile";
    const legacyVerificationFor = value => sha256Hex(
      `funding-finder-verification-v1|${candidate.manage_token}|${candidate.subscription_id}|${value}`,
    );
    const signedVerificationFor = (value, secret) => secret
      ? createVerificationToken({
          subscriberId: candidate.subscriber_id,
          subscriptionId: candidate.subscription_id,
          nonce: value,
        }, secret)
      : Promise.resolve("");
    const verificationFor = value => env.ALERT_CAPABILITY_SECRET
      ? signedVerificationFor(value, env.ALERT_CAPABILITY_SECRET)
      : legacyVerificationFor(value);
    let token = nonce.length >= 32 ? await verificationFor(nonce) : "";
    let tokenHash = token ? await sha256Hex(token) : "";
    let idempotencyKey = `verify:${candidate.id}:${tokenHash.slice(0, 24)}`;
    const expiresAt = Date.parse(candidate.verification_expires_at);
    if (reconciliation) {
      const signedSecrets = [...new Set([
        String(env.ALERT_CAPABILITY_SECRET || ""),
        String(env.ALERT_CAPABILITY_PREVIOUS_SECRET || ""),
      ].filter(Boolean))];
      const reconciliationTokens = [
        ...(Number(candidate.capability_version || 0) === 0 && nonce.length >= 32
          ? [await legacyVerificationFor(nonce)]
          : []),
        ...await Promise.all(signedSecrets.map(secret => signedVerificationFor(nonce, secret))),
      ];
      const reconciled = (await Promise.all(reconciliationTokens.filter(value => value.length >= 32).map(async value => {
        const hash = await sha256Hex(value);
        return { token: value, tokenHash: hash, idempotencyKey: `verify:${candidate.id}:${hash.slice(0, 24)}` };
      }))).find(value => value.idempotencyKey === candidate.provider_quota_key);
      token = reconciled?.token || "";
      tokenHash = reconciled?.tokenHash || "";
      idempotencyKey = reconciled?.idempotencyKey || "";
      if (
        token.length < 32
        || candidate.provider_quota_key !== idempotencyKey
        || !await store.verificationReconciliationClaimIsCurrent(candidate.id, claimedAt, schedulerClaim)
      ) {
        await store.markEventsFailed(ids, "verification_reconciliation_invalid", claimedAt, claimedAt, "", schedulerClaim);
        continue;
      }
    } else if (
      token.length < 32
      || tokenHash !== String(candidate.verification_token_hash || "")
      || !Number.isFinite(expiresAt)
      || expiresAt - now.getTime() < VERIFICATION_MINIMUM_SEND_WINDOW_MS
    ) {
      nonce = tokenFactory();
      token = await verificationFor(nonce);
      tokenHash = await sha256Hex(token);
      idempotencyKey = `verify:${candidate.id}:${tokenHash.slice(0, 24)}`;
      const refreshedExpiresAt = new Date(now.getTime() + VERIFICATION_VALIDITY_MS).toISOString();
      const refreshed = await store.refreshVerificationEvent(candidate.id, {
        nonce,
        tokenHash,
        expectedTokenHash: String(candidate.verification_token_hash || ""),
        expiresAt: refreshedExpiresAt,
        eventKey: `verification:${tokenHash}`,
        claimedAt,
        now: claimedAt,
        scheduler: schedulerClaim,
      });
      if (!refreshed) {
        await store.markEventsFailed(ids, "verification_cycle_changed", claimedAt, claimedAt, "", schedulerClaim);
        continue;
      }
    } else if (!await store.verificationClaimIsCurrent(
      candidate.id, tokenHash, claimedAt, schedulerClaim,
    )) {
      await store.markEventsFailed(ids, "verification_cycle_changed", claimedAt, claimedAt, "", schedulerClaim);
      continue;
    }
    const renderedMessage = verificationEmail({
      env,
      to: candidate.email,
      token,
      subscriptionId: candidate.subscription_id,
      manageToken: candidate.manage_token,
      capabilityLinks: await deliveryCapabilityLinks(env, candidate),
      type: candidate.type,
    });
    const reservedPayload = candidate.provider_quota_key === idempotencyKey
      ? candidate.provider_payload_json
      : null;
    const message = storedProviderMessage(reservedPayload) || renderedMessage;
    if (!await store.reserveProviderMessage(
      idempotencyKey, ids, dailyLimit, 86_400, now, false, message,
      schedulerClaim,
    )) {
      await store.releaseClaimedEvents(ids, claimedAt, schedulerClaim);
      break;
    }
    attemptedCount += 1;
    let delivery;
    try {
      delivery = await provider.sendEmail(message, idempotencyKey, { signal });
    } catch (error) {
      const retryable = retryableProviderFailure(error);
      await store.markEventsFailed(
        ids,
        String(error?.code || "provider_failed").slice(0, 80),
        retryable ? retryAt(candidate, now) : now.toISOString(),
        retryable ? null : now.toISOString(),
        providerFailureKind(error),
        schedulerClaim,
      );
      failedCount += 1;
      continue;
    }
    await store.markEventsSent(ids, delivery.id, now.toISOString(), schedulerClaim);
    deliveredCount += 1;
  }
  return { attemptedCount, deliveredCount, failedCount };
}

import "../../../assets/award-links.js";

import { recordId } from "./contract.js";
import { sha256Hex } from "./crypto.js";
import { digestEmail, eventEmail } from "./email.js";

const LINKS_API = globalThis.FUNDING_AWARD_LINKS;
const CHANGE_KINDS = new Set(["new", "deadline_changed", "amended", "status_changed", "closed_or_removed"]);

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

function publicUrl(record, env) {
  const id = recordId(record);
  const official = String(
    record?.primary_document_url || record?.funding_opportunity_url || record?.detail_page || "",
  ).trim();
  return official || `${String(env.PUBLIC_APP_ORIGIN).replace(/\/$/, "")}/match_explorer.html?focus=${encodeURIComponent(id)}`;
}

function payloadFor(record, detail, env) {
  return {
    title: String(record?.title || "Funding opportunity").slice(0, 600),
    agency: String(record?.agency || "").slice(0, 300),
    close_date: String(record?.close_date || "").slice(0, 10),
    detail: String(detail || "").replace(/\s+/g, " ").trim().slice(0, 600),
    url: publicUrl(record, env),
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
  const strongIds = assets.matcher.matchIds(definition, asOf, changedIds);
  const prior = await store.qualifications(subscription.id, changedIds);
  const currentById = new Map(assets.catalog.opportunities.map(record => [recordId(record), record]));
  let matched = 0;
  for (const id of changedIds) {
    const qualifies = strongIds.has(id);
    const didQualify = prior.get(id) === true;
    if (qualifies && !didQualify) {
      const sourceEvent = changes.find(event => String(event.opportunity_id) === id);
      const record = currentById.get(id) || sourceEvent?.record;
      const inserted = await enqueue(store, subscription, {
        eventKey: `strong:${id}:${sourceEvent?.id || assets.changes.generated_at}`,
        eventKind: "strong_match",
        opportunityId: id,
        payload: payloadFor(record, "Newly qualifies under the existing Strong-match contract", env),
      }, now);
      if (inserted) matched += 1;
    }
    if (qualifies !== didQualify || !prior.has(id)) {
      await store.setQualification(subscription.id, id, qualifies, now.toISOString());
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
    );
  }
  return { subscriptionCount: subscriptions.length, matchedEventCount };
}

function retryAt(event, now) {
  const delayMinutes = Math.min(24 * 60, 5 * (2 ** Math.min(8, Number(event.attempts || 0))));
  return new Date(now.getTime() + delayMinutes * 60_000).toISOString();
}

export async function dispatchNotifications({ store, provider, env, now = new Date(), weekly = false }) {
  if (String(env.OUTBOUND_EMAIL_ENABLED || "").toLowerCase() !== "true") {
    return { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
  }
  const dailyLimit = Math.max(1, Math.min(100, Number(env.DAILY_EMAIL_LIMIT) || 100));
  let remaining = dailyLimit;
  const pending = await store.pendingEvents(weekly ? "weekly" : "immediate", now.toISOString(), weekly ? 500 : remaining);
  let attemptedCount = 0;
  let deliveredCount = 0;
  let failedCount = 0;
  const batches = weekly
    ? [...pending.reduce((groups, event) => {
        if (!groups.has(event.subscriber_id)) groups.set(event.subscriber_id, []);
        groups.get(event.subscriber_id).push(event);
        return groups;
      }, new Map()).values()].slice(0, remaining)
    : pending.slice(0, remaining).map(event => [event]);
  for (const batch of batches) {
    if (!await store.consumeRateLimit("email_send", "global", dailyLimit, 86_400, now)) break;
    const ids = await store.claimEvents(batch.map(event => event.id), now.toISOString());
    const claimed = batch.filter(event => ids.includes(event.id));
    if (!claimed.length) continue;
    attemptedCount += 1;
    const idempotencyKey = weekly
      ? `digest:${await sha256Hex(claimed.map(event => event.id).sort().join("|"))}`
      : claimed[0].id;
    const message = weekly ? digestEmail({ env, events: claimed }) : eventEmail({ env, event: claimed[0] });
    try {
      const delivery = await provider.sendEmail(message, idempotencyKey);
      await store.markEventsSent(ids, delivery.id, now.toISOString());
      deliveredCount += 1;
    } catch (error) {
      await store.markEventsFailed(ids, String(error?.code || "provider_failed").slice(0, 80), retryAt(claimed[0], now));
      failedCount += 1;
    }
    remaining -= 1;
    if (!remaining) break;
  }
  return { attemptedCount, deliveredCount, failedCount };
}

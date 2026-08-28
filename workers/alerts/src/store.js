function rows(result) {
  return result?.results || [];
}

const DELIVERY_LEASE_MS = 15 * 60 * 1_000;
export const RETENTION_DAYS = Object.freeze({
  rateLimits: 30,
  evaluationRuns: 90,
  terminalDeliveries: 90,
  providerEvents: 180,
});

function staleClaimCutoff(now) {
  const timestamp = Date.parse(now);
  return new Date((Number.isFinite(timestamp) ? timestamp : Date.now()) - DELIVERY_LEASE_MS).toISOString();
}

function schedulerClaim(claim) {
  const runId = String(claim?.runId || "");
  const token = String(claim?.token || "");
  return runId && token
    ? {
        sql: " AND EXISTS (SELECT 1 FROM evaluation_runs scheduler_claim WHERE scheduler_claim.id = ? AND scheduler_claim.status = 'running' AND scheduler_claim.claim_token = ?)",
        values: [runId, token],
      }
    : { sql: "", values: [] };
}

export class D1AlertStore {
  constructor(database) {
    if (!database?.prepare) throw new Error("Alerts D1 binding is unavailable.");
    this.db = database;
  }

  async consumeRateLimit(action, clientKey, limit, windowSeconds, now) {
    const timestamp = now.toISOString();
    const expires = new Date(now.getTime() + windowSeconds * 1_000).toISOString();
    const accepted = await this.db.prepare(
      "INSERT INTO rate_limits(action, client_key, window_started_at, expires_at, request_count) VALUES(?, ?, ?, ?, 1) ON CONFLICT(action, client_key) DO UPDATE SET window_started_at = CASE WHEN rate_limits.expires_at <= ? THEN excluded.window_started_at ELSE rate_limits.window_started_at END, expires_at = CASE WHEN rate_limits.expires_at <= ? THEN excluded.expires_at ELSE rate_limits.expires_at END, request_count = CASE WHEN rate_limits.expires_at <= ? THEN 1 ELSE rate_limits.request_count + 1 END WHERE rate_limits.expires_at <= ? OR rate_limits.request_count < ? RETURNING request_count",
    ).bind(
      action, clientKey, timestamp, expires,
      timestamp, timestamp, timestamp, timestamp, limit,
    ).first();
    return Boolean(accepted);
  }

  async reserveProviderMessage(
    messageKey, eventIds, limit, windowSeconds, now, hasOverflow = false, providerPayload = null,
    scheduler = null,
  ) {
    if (!messageKey || !eventIds.length) return false;
    const placeholders = eventIds.map(() => "?").join(",");
    const timestamp = now.toISOString();
    const expires = new Date(now.getTime() + windowSeconds * 1_000).toISOString();
    const payloadJson = JSON.stringify(providerPayload || {});
    const claim = schedulerClaim(scheduler);
    const claimableCount = `SELECT COUNT(*) FROM notification_events WHERE id IN (${placeholders}) AND status = 'sending' AND terminal_at IS NULL${claim.sql}`;
    const matchingReservationCount = `SELECT COUNT(*) FROM notification_events WHERE id IN (${placeholders}) AND provider_quota_key = ?`;
    await this.db.batch([
      this.db.prepare(
        `INSERT INTO rate_limits(action, client_key, window_started_at, expires_at, request_count, last_reservation_key) SELECT 'email_send', 'global', ?, ?, 1, ? WHERE (${claimableCount}) = ? AND (${matchingReservationCount}) <> ? ON CONFLICT(action, client_key) DO UPDATE SET window_started_at = CASE WHEN rate_limits.expires_at <= ? THEN excluded.window_started_at ELSE rate_limits.window_started_at END, expires_at = CASE WHEN rate_limits.expires_at <= ? THEN excluded.expires_at ELSE rate_limits.expires_at END, request_count = CASE WHEN rate_limits.expires_at <= ? THEN 1 ELSE rate_limits.request_count + 1 END, last_reservation_key = excluded.last_reservation_key WHERE (rate_limits.expires_at <= ? OR rate_limits.request_count < ?) AND (${claimableCount}) = ? AND (${matchingReservationCount}) <> ?`,
      ).bind(
        timestamp, expires, messageKey,
        ...eventIds, ...claim.values, eventIds.length, ...eventIds, messageKey, eventIds.length,
        timestamp, timestamp, timestamp, timestamp, limit,
        ...eventIds, ...claim.values, eventIds.length, ...eventIds, messageKey, eventIds.length,
      ),
      this.db.prepare(
        `UPDATE notification_events SET provider_payload_json = CASE WHEN id = (SELECT MIN(id) FROM notification_events WHERE id IN (${placeholders})) THEN CASE WHEN provider_quota_key = ? THEN COALESCE(provider_payload_json, ?) ELSE ? END ELSE NULL END, provider_batch_has_overflow = CASE WHEN provider_quota_key = ? THEN provider_batch_has_overflow ELSE ? END, provider_quota_key = ?, provider_quota_reserved_at = ? WHERE id IN (${placeholders}) AND status = 'sending' AND terminal_at IS NULL AND EXISTS (SELECT 1 FROM rate_limits WHERE action = 'email_send' AND client_key = 'global' AND last_reservation_key = ?)${claim.sql}`,
      ).bind(
        ...eventIds, messageKey, payloadJson, payloadJson, messageKey, hasOverflow ? 1 : 0,
        messageKey, timestamp, ...eventIds, messageKey, ...claim.values,
      ),
    ]);
    const reserved = await this.db.prepare(
      `SELECT COUNT(*) AS total, SUM(CASE WHEN provider_quota_key = ? AND status = 'sending' AND terminal_at IS NULL THEN 1 ELSE 0 END) AS matched FROM notification_events WHERE id IN (${placeholders})${claim.sql}`,
    ).bind(messageKey, ...eventIds, ...claim.values).first();
    return Number(reserved?.total || 0) === eventIds.length
      && Number(reserved?.matched || 0) === eventIds.length;
  }

  async findSubscription(subscriberId, type, definitionHash) {
    return this.db.prepare(
      "SELECT * FROM subscriptions WHERE subscriber_id = ? AND type = ? AND definition_hash = ?",
    ).bind(subscriberId, type, definitionHash).first();
  }

  async upsertSubscriber({ id, email, manageToken, now }) {
    await this.db.prepare(
      "INSERT INTO subscribers(id, email, email_normalized, manage_token, created_at, updated_at, capability_version, legacy_manage_expires_at) VALUES(?, ?, ?, ?, ?, ?, 1, NULL) ON CONFLICT(email_normalized) DO UPDATE SET email = excluded.email, updated_at = excluded.updated_at",
    ).bind(id, email, email, manageToken, now, now).run();
    return this.db.prepare(
      "SELECT * FROM subscribers WHERE email_normalized = ?",
    ).bind(email).first();
  }

  async createSubscriptionCycle(value) {
    const baseline = [...new Set(value.baselineOpportunityIds || [])].filter(Boolean);
    const cyclePredicate = "id = ? AND active = 0 AND verification_token_hash = ?";
    const verificationStatus = value.suppressed ? "suppressed" : "queued";
    const terminalAt = value.suppressed ? value.now : null;
    const errorCode = value.suppressed ? "subscriber_suppressed" : null;
    await this.db.batch([
      this.db.prepare(
        "INSERT INTO subscriptions(id, subscriber_id, type, active, cadence, definition_json, definition_hash, verification_token_hash, verification_expires_at, verified_at, baseline_at, baseline_complete, last_evaluated_at, last_notified_at, created_at, updated_at) VALUES(?, ?, ?, 0, ?, ?, ?, ?, ?, NULL, ?, 0, NULL, NULL, ?, ?) ON CONFLICT(id) DO UPDATE SET cadence = excluded.cadence, definition_json = excluded.definition_json, verification_token_hash = excluded.verification_token_hash, verification_expires_at = excluded.verification_expires_at, verified_at = NULL, baseline_at = excluded.baseline_at, baseline_complete = 0, last_evaluated_at = NULL, last_calendar_evaluated_on = NULL, evaluation_cursor_at = NULL, evaluation_cursor_event_id = NULL, evaluation_window_started_at = NULL, evaluation_weekly_window_at = NULL, evaluation_input_generated_at = NULL, evaluation_source_generated_at = NULL, last_notified_at = NULL, updated_at = excluded.updated_at WHERE subscriptions.active = 0 AND NOT EXISTS (SELECT 1 FROM notification_events n WHERE n.subscription_id = subscriptions.id AND n.message_kind = 'verification' AND n.status = 'sending' AND n.terminal_at IS NULL)",
      ).bind(
        value.id, value.subscriberId, value.type, value.cadence, value.definitionJson,
        value.definitionHash, value.verificationTokenHash, value.verificationExpiresAt,
        value.now, value.now, value.now,
      ),
      this.db.prepare(
        `UPDATE notification_events SET status = CASE WHEN status = 'sending' AND provider_quota_key IS NOT NULL THEN 'sending' WHEN status = 'failed' AND error_code IN ('provider_outcome_reconcile', 'verification_outcome_reconcile') AND provider_quota_key IS NOT NULL THEN 'failed' ELSE 'suppressed' END, error_code = CASE WHEN status = 'sending' AND provider_quota_key IS NOT NULL THEN 'subscription_reactivated_in_flight' WHEN status = 'failed' AND error_code IN ('provider_outcome_reconcile', 'verification_outcome_reconcile') AND provider_quota_key IS NOT NULL THEN error_code ELSE 'subscription_reactivated' END, claimed_at = CASE WHEN status = 'sending' AND provider_quota_key IS NOT NULL THEN claimed_at ELSE NULL END, terminal_at = CASE WHEN status = 'failed' AND error_code IN ('provider_outcome_reconcile', 'verification_outcome_reconcile') AND provider_quota_key IS NOT NULL THEN NULL ELSE ? END WHERE subscription_id = ? AND status IN ('queued', 'failed', 'sending') AND EXISTS (SELECT 1 FROM subscriptions WHERE ${cyclePredicate})`,
      ).bind(value.now, value.id, value.id, value.verificationTokenHash),
      this.db.prepare(
        `DELETE FROM subscription_qualifications WHERE subscription_id = ? AND EXISTS (SELECT 1 FROM subscriptions WHERE ${cyclePredicate})`,
      ).bind(value.id, value.id, value.verificationTokenHash),
      this.db.prepare(
        `INSERT INTO subscription_qualifications(subscription_id, opportunity_id, qualified, updated_at) SELECT ?, CAST(value AS TEXT), 1, ? FROM json_each(?) WHERE EXISTS (SELECT 1 FROM subscriptions WHERE ${cyclePredicate})`,
      ).bind(value.id, value.now, JSON.stringify(baseline), value.id, value.verificationTokenHash),
      this.db.prepare(
        `UPDATE subscriptions SET baseline_complete = 1, updated_at = ? WHERE ${cyclePredicate}`,
      ).bind(value.now, value.id, value.verificationTokenHash),
      this.db.prepare(
        `INSERT OR IGNORE INTO notification_events(id, subscription_id, event_key, event_kind, opportunity_id, payload_json, status, attempts, next_attempt_at, created_at, message_kind, terminal_at, error_code) SELECT ?, ?, ?, 'verification', NULL, ?, ?, 0, ?, ?, 'verification', ?, ? WHERE EXISTS (SELECT 1 FROM subscriptions WHERE ${cyclePredicate} AND baseline_complete = 1)`,
      ).bind(
        value.verificationEventId, value.id, value.verificationEventKey,
        JSON.stringify({ nonce: value.verificationNonce }), verificationStatus,
        value.now, value.now, terminalAt, errorCode, value.id, value.verificationTokenHash,
      ),
    ]);
    const stored = await this.db.prepare("SELECT * FROM subscriptions WHERE id = ?").bind(value.id).first();
    const cycleAccepted = Boolean(
      stored
      && Number(stored.active) === 0
      && Number(stored.baseline_complete) === 1
      && stored.verification_token_hash === value.verificationTokenHash,
    );
    return {
      ...stored,
      cycleAccepted,
      alreadyActive: Boolean(stored && Number(stored.active) === 1 && !cycleAccepted),
    };
  }

  async verifySubscription(tokenHash, now) {
    const subscription = await this.db.prepare(
      "SELECT s.*, u.email, u.manage_token, u.suppressed_at FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.verification_token_hash = ? AND s.baseline_complete = 1",
    ).bind(tokenHash).first();
    if (!subscription || subscription.verification_expires_at < now) return null;
    await this.db.batch([
      this.db.prepare(
        "UPDATE subscriptions SET active = CASE WHEN EXISTS (SELECT 1 FROM subscribers WHERE id = subscriptions.subscriber_id AND suppressed_at IS NOT NULL) THEN 0 ELSE 1 END, verified_at = COALESCE(verified_at, ?), updated_at = ? WHERE id = ? AND verification_token_hash = ? AND verification_expires_at >= ? AND baseline_complete = 1",
      ).bind(now, now, subscription.id, tokenHash, now),
      this.db.prepare(
        "UPDATE subscribers SET verified_at = COALESCE(verified_at, ?), updated_at = ? WHERE id = ? AND EXISTS (SELECT 1 FROM subscriptions WHERE id = ? AND verification_token_hash = ? AND verification_expires_at >= ? AND baseline_complete = 1 AND verified_at IS NOT NULL)",
      ).bind(now, now, subscription.subscriber_id, subscription.id, tokenHash, now),
      this.db.prepare(
        "UPDATE notification_events SET status = CASE WHEN error_code = 'verification_outcome_reconcile' THEN status WHEN status = 'sending' THEN 'sending' ELSE 'suppressed' END, error_code = CASE WHEN error_code = 'verification_outcome_reconcile' THEN error_code WHEN status = 'sending' THEN 'verification_completed_in_flight' ELSE 'verification_completed' END, claimed_at = CASE WHEN error_code = 'verification_outcome_reconcile' OR status = 'sending' THEN claimed_at ELSE NULL END, terminal_at = CASE WHEN error_code = 'verification_outcome_reconcile' THEN NULL ELSE ? END WHERE subscription_id = ? AND message_kind = 'verification' AND status IN ('queued', 'failed', 'sending') AND EXISTS (SELECT 1 FROM subscriptions WHERE id = ? AND verification_token_hash = ? AND verification_expires_at >= ? AND baseline_complete = 1 AND verified_at IS NOT NULL)",
      ).bind(now, subscription.id, subscription.id, tokenHash, now),
    ]);
    const verified = await this.db.prepare(
      "SELECT s.*, u.email, u.manage_token, u.suppressed_at FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.id = ? AND s.verification_token_hash = ? AND s.verification_expires_at >= ? AND s.baseline_complete = 1 AND s.verified_at IS NOT NULL",
    ).bind(subscription.id, tokenHash, now).first();
    if (!verified) return null;
    const suppressed = Boolean(verified.suppressed_at);
    return {
      ...verified,
      deliverySuppressed: suppressed,
    };
  }

  async subscriberById(id) {
    return this.db.prepare("SELECT * FROM subscribers WHERE id = ?").bind(id).first();
  }

  async subscriberByManageToken(token, now = new Date().toISOString()) {
    return this.db.prepare(
      "SELECT * FROM subscribers WHERE capability_version = 0 AND manage_token = ? AND legacy_manage_expires_at >= ?",
    ).bind(token, now).first();
  }

  async subscriptionsForSubscriber(subscriberId) {
    return rows(await this.db.prepare(
      "SELECT * FROM subscriptions WHERE subscriber_id = ? ORDER BY created_at DESC",
    ).bind(subscriberId).all());
  }

  async updateSubscription(manageToken, subscriptionId, { active, cadence }, now) {
    const subscriber = await this.subscriberByManageToken(manageToken, now);
    if (!subscriber) return false;
    return this.updateSubscriptionForSubscriber(subscriber.id, subscriptionId, { active, cadence }, now);
  }

  async updateSubscriptionForSubscriber(subscriberId, subscriptionId, { active, cadence }, now) {
    const subscriber = await this.subscriberById(subscriberId);
    if (!subscriber) return false;
    if (active === true && subscriber.suppressed_at) return false;
    const values = [];
    const setters = [];
    if (typeof active === "boolean") {
      setters.push("active = ?");
      values.push(active ? 1 : 0);
      if (!active) setters.push(
        "evaluation_cursor_at = NULL",
        "evaluation_cursor_event_id = NULL",
        "evaluation_window_started_at = NULL",
        "evaluation_weekly_window_at = NULL",
        "evaluation_input_generated_at = NULL",
        "evaluation_source_generated_at = NULL",
      );
    }
    if (["immediate", "weekly"].includes(cadence)) { setters.push("cadence = ?"); values.push(cadence); }
    if (!setters.length) return false;
    values.push(now, subscriptionId, subscriber.id);
    const result = await this.db.prepare(
      `UPDATE subscriptions SET ${setters.join(", ")}, updated_at = ? WHERE id = ? AND subscriber_id = ?`,
    ).bind(...values).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async unsubscribe(manageToken, subscriptionId, now) {
    return this.updateSubscription(manageToken, subscriptionId, { active: false }, now);
  }

  async unsubscribeAll(manageToken, now) {
    const subscriber = await this.subscriberByManageToken(manageToken, now);
    if (!subscriber) return false;
    return this.unsubscribeAllForSubscriber(subscriber.id, now);
  }

  async unsubscribeForSubscriber(subscriberId, subscriptionId, now) {
    return this.updateSubscriptionForSubscriber(subscriberId, subscriptionId, { active: false }, now);
  }

  async unsubscribeAllForSubscriber(subscriberId, now) {
    await this.db.prepare(
      "UPDATE subscriptions SET active = 0, evaluation_cursor_at = NULL, evaluation_cursor_event_id = NULL, evaluation_window_started_at = NULL, evaluation_weekly_window_at = NULL, evaluation_input_generated_at = NULL, evaluation_source_generated_at = NULL, updated_at = ? WHERE subscriber_id = ?",
    ).bind(now, subscriberId).run();
    return true;
  }

  async suppressSubscriberByMessage(providerMessageId, reason, providerEventId, now) {
    const duplicate = await this.db.prepare(
      "SELECT provider_event_id FROM provider_events WHERE provider_event_id = ?",
    ).bind(providerEventId).first();
    if (duplicate) return false;
    const event = await this.db.prepare(
      "SELECT s.subscriber_id FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id WHERE n.provider_message_id = ? LIMIT 1",
    ).bind(providerMessageId).first();
    await this.db.batch([
      this.db.prepare(
        "INSERT OR IGNORE INTO provider_events(provider_event_id, event_type, provider_message_id, received_at) VALUES(?, ?, ?, ?)",
      ).bind(providerEventId, reason, providerMessageId || null, now),
      this.db.prepare(
        "UPDATE subscribers SET suppressed_at = COALESCE(suppressed_at, ?), suppression_reason = COALESCE(suppression_reason, ?), updated_at = ? WHERE id = ?",
      ).bind(now, reason, now, event?.subscriber_id || ""),
      this.db.prepare("UPDATE subscriptions SET active = 0, evaluation_cursor_at = NULL, evaluation_cursor_event_id = NULL, evaluation_window_started_at = NULL, evaluation_weekly_window_at = NULL, evaluation_input_generated_at = NULL, evaluation_source_generated_at = NULL, updated_at = ? WHERE subscriber_id = ?")
        .bind(now, event?.subscriber_id || ""),
      this.db.prepare(
        "UPDATE notification_events SET status = 'suppressed', error_code = ?, terminal_at = COALESCE(terminal_at, ?), claimed_at = NULL WHERE status IN ('queued', 'failed') AND subscription_id IN (SELECT id FROM subscriptions WHERE subscriber_id = ?)",
      ).bind(reason, now, event?.subscriber_id || ""),
    ]);
    return Boolean(event);
  }

  async recordProviderEvent(providerEventId, eventType, providerMessageId, now) {
    const result = await this.db.prepare(
      "INSERT OR IGNORE INTO provider_events(provider_event_id, event_type, provider_message_id, received_at) VALUES(?, ?, ?, ?)",
    ).bind(providerEventId, eventType, providerMessageId || null, now).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async activeSubscriptions() {
    return rows(await this.db.prepare(
      "SELECT s.*, u.email, u.manage_token FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.active = 1 AND s.verified_at IS NOT NULL AND u.suppressed_at IS NULL ORDER BY s.id",
    ).all());
  }

  async activeSubscriptionsForEvaluation(generatedAt, limit = 4, evaluationWindowStartedAt = null) {
    const bounded = Math.max(1, Math.min(25, Number(limit) || 4));
    const calendarDate = String(evaluationWindowStartedAt || "").slice(0, 10);
    const values = rows(await this.db.prepare(
      "SELECT s.*, u.email, u.manage_token FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.active = 1 AND s.verified_at IS NOT NULL AND u.suppressed_at IS NULL AND (s.evaluation_cursor_at IS NOT NULL OR (MAX(s.baseline_at, s.verified_at) <= ? AND COALESCE(s.last_evaluated_at, '') < ?) OR (s.type = 'opportunity' AND MAX(s.baseline_at, s.verified_at) <= ? AND COALESCE(s.last_calendar_evaluated_on, '') < ? AND EXISTS (SELECT 1 FROM json_each(json_extract(s.definition_json, '$.triggers')) WHERE value = 'closing_reminders'))) AND (s.evaluation_cursor_at IS NULL OR s.evaluation_window_started_at IS NULL OR s.evaluation_window_started_at = ?) ORDER BY CASE WHEN s.evaluation_cursor_at IS NOT NULL THEN 0 ELSE 1 END, s.id LIMIT ?",
    ).bind(
      generatedAt, generatedAt, evaluationWindowStartedAt || "", calendarDate,
      evaluationWindowStartedAt, bounded + 1,
    ).all());
    return { subscriptions: values.slice(0, bounded), hasMore: values.length > bounded };
  }

  async qualifications(subscriptionId, opportunityIds) {
    const output = new Map();
    for (const id of opportunityIds || []) {
      const row = await this.db.prepare(
        "SELECT qualified FROM subscription_qualifications WHERE subscription_id = ? AND opportunity_id = ?",
      ).bind(subscriptionId, id).first();
      if (row) output.set(id, Number(row.qualified) === 1);
    }
    return output;
  }

  async setQualification(subscriptionId, opportunityId, qualified, now, cycle = null) {
    if (!cycle) {
      await this.db.prepare(
        "INSERT INTO subscription_qualifications(subscription_id, opportunity_id, qualified, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(subscription_id, opportunity_id) DO UPDATE SET qualified = excluded.qualified, updated_at = excluded.updated_at",
      ).bind(subscriptionId, opportunityId, qualified ? 1 : 0, now).run();
      return;
    }
    const claim = schedulerClaim(cycle?.claim);
    const currentCycle = `SELECT 1 FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.id = ? AND s.active = 1 AND s.verified_at IS NOT NULL AND s.verification_token_hash = ? AND s.baseline_at = ? AND u.suppressed_at IS NULL${claim.sql}`;
    await this.db.prepare(
      `INSERT INTO subscription_qualifications(subscription_id, opportunity_id, qualified, updated_at) SELECT ?, ?, ?, ? WHERE EXISTS (${currentCycle}) ON CONFLICT(subscription_id, opportunity_id) DO UPDATE SET qualified = excluded.qualified, updated_at = excluded.updated_at WHERE EXISTS (${currentCycle})`,
    ).bind(
      subscriptionId, opportunityId, qualified ? 1 : 0, now,
      subscriptionId, cycle.verificationTokenHash, cycle.baselineAt, ...claim.values,
      subscriptionId, cycle.verificationTokenHash, cycle.baselineAt, ...claim.values,
    ).run();
  }

  async enqueueEvent(event) {
    const values = [
      event.id, event.subscriptionId, event.eventKey, event.eventKind,
      event.opportunityId || null, JSON.stringify(event.payload),
      event.evaluationWindowStartedAt || null, event.weeklyWindowAt || null,
      event.createdAt, event.createdAt,
    ];
    const claim = schedulerClaim(event.cycle?.claim);
    const result = event.cycle
      ? await this.db.prepare(
        `INSERT OR IGNORE INTO notification_events(id, subscription_id, event_key, event_kind, opportunity_id, payload_json, evaluation_window_started_at, weekly_window_at, status, attempts, next_attempt_at, created_at, message_kind) SELECT ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, 'notification' WHERE EXISTS (SELECT 1 FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.id = ? AND s.active = 1 AND s.verified_at IS NOT NULL AND s.verification_token_hash = ? AND s.baseline_at = ? AND u.suppressed_at IS NULL${claim.sql})`,
      ).bind(
        ...values, event.subscriptionId,
        event.cycle.verificationTokenHash, event.cycle.baselineAt, ...claim.values,
      ).run()
      : await this.db.prepare(
        "INSERT OR IGNORE INTO notification_events(id, subscription_id, event_key, event_kind, opportunity_id, payload_json, evaluation_window_started_at, weekly_window_at, status, attempts, next_attempt_at, created_at, message_kind) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, 'notification')",
      ).bind(...values).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async markEvaluated(subscriptionId, evaluatedAt, now, cycle = null) {
    return this.completeEvaluation(subscriptionId, evaluatedAt, now, cycle);
  }

  async completeEvaluation(subscriptionId, evaluatedAt, now, cycle = null) {
    const claim = schedulerClaim(cycle?.claim);
    const predicate = cycle
      ? `id = ? AND active = 1 AND verified_at IS NOT NULL AND verification_token_hash = ? AND baseline_at = ? AND (? IS NULL OR evaluation_window_started_at IS NULL OR evaluation_window_started_at = ?) AND (? IS NULL OR evaluation_input_generated_at IS NULL OR evaluation_input_generated_at = ?) AND (COALESCE(last_evaluated_at, '') < ? OR COALESCE(last_calendar_evaluated_on, '') < ?) AND EXISTS (SELECT 1 FROM subscribers WHERE id = subscriptions.subscriber_id AND suppressed_at IS NULL)${claim.sql}`
      : "id = ?";
    const values = cycle
      ? [
          evaluatedAt, cycle.calendarEvaluationDate || "", now,
          subscriptionId, cycle.verificationTokenHash, cycle.baselineAt,
          cycle.evaluationWindowStartedAt, cycle.evaluationWindowStartedAt,
          cycle.evaluationInputGeneratedAt, cycle.evaluationInputGeneratedAt,
          evaluatedAt, cycle.calendarEvaluationDate || "", ...claim.values,
        ]
      : [evaluatedAt, cycle?.calendarEvaluationDate || "", now, subscriptionId];
    const result = await this.db.prepare(
      `UPDATE subscriptions SET last_evaluated_at = MAX(COALESCE(last_evaluated_at, ''), ?, baseline_at), last_calendar_evaluated_on = MAX(COALESCE(last_calendar_evaluated_on, ''), ?), evaluation_cursor_at = NULL, evaluation_cursor_event_id = NULL, evaluation_window_started_at = NULL, evaluation_weekly_window_at = NULL, evaluation_input_generated_at = NULL, evaluation_source_generated_at = NULL, updated_at = ? WHERE ${predicate}`,
    ).bind(...values).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async saveEvaluationCursor(subscriptionId, cursorAt, cursorEventId, now, cycle = null) {
    const claim = schedulerClaim(cycle?.claim);
    const predicate = cycle
      ? `id = ? AND active = 1 AND verified_at IS NOT NULL AND verification_token_hash = ? AND baseline_at = ? AND (? IS NULL OR evaluation_window_started_at IS NULL OR evaluation_window_started_at = ?) AND (? IS NULL OR evaluation_input_generated_at IS NULL OR evaluation_input_generated_at = ?) AND EXISTS (SELECT 1 FROM subscribers WHERE id = subscriptions.subscriber_id AND suppressed_at IS NULL)${claim.sql}`
      : "id = ?";
    const values = cycle
      ? [
          cursorAt, cursorEventId, cycle.evaluationWindowStartedAt,
          cycle.weeklyWindowAt, cycle.evaluationInputGeneratedAt,
          cycle.evaluationSourceGeneratedAt, now,
          subscriptionId, cycle.verificationTokenHash, cycle.baselineAt,
          cycle.evaluationWindowStartedAt, cycle.evaluationWindowStartedAt,
          cycle.evaluationInputGeneratedAt, cycle.evaluationInputGeneratedAt,
          ...claim.values,
        ]
      : [cursorAt, cursorEventId, null, null, null, null, now, subscriptionId];
    const result = await this.db.prepare(
      `UPDATE subscriptions SET evaluation_cursor_at = ?, evaluation_cursor_event_id = ?, evaluation_window_started_at = ?, evaluation_weekly_window_at = ?, evaluation_input_generated_at = ?, evaluation_source_generated_at = ?, updated_at = ? WHERE ${predicate}`,
    ).bind(...values).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async sentCountSince(since) {
    const row = await this.db.prepare(
      "SELECT COUNT(*) AS count FROM notification_events WHERE status = 'sent' AND sent_at >= ?",
    ).bind(since).first();
    return Number(row?.count || 0);
  }

  async pendingEvents(cadence, now, limit) {
    const staleBefore = staleClaimCutoff(now);
    return rows(await this.db.prepare(
      "SELECT n.*, s.type, s.cadence, s.definition_json, s.subscriber_id, u.email, u.manage_token FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.terminal_at IS NULL AND COALESCE(n.error_code, '') <> 'provider_outcome_reconcile' AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND s.active = 1 AND s.verified_at IS NOT NULL AND s.cadence = ? AND u.suppressed_at IS NULL ORDER BY n.created_at, n.id LIMIT ?",
    ).bind(now, staleBefore, cadence, limit).all());
  }

  async pendingDigestEvents(now, subscriberLimit, eventLimit, eligibleBefore = null) {
    const staleBefore = staleClaimCutoff(now);
    const cutoff = eligibleBefore || null;
    const subscribers = rows(await this.db.prepare(
      "SELECT s.subscriber_id, MIN(n.created_at) AS first_created_at FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.terminal_at IS NULL AND COALESCE(n.error_code, '') <> 'provider_outcome_reconcile' AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND (n.evaluation_window_started_at IS NULL OR EXISTS (SELECT 1 FROM evaluation_runs r WHERE r.evaluation_window_started_at = n.evaluation_window_started_at AND r.evaluation_completed_at IS NOT NULL)) AND (? IS NULL OR COALESCE(n.weekly_window_at, n.created_at) <= ?) AND s.active = 1 AND s.verified_at IS NOT NULL AND s.cadence = 'weekly' AND u.suppressed_at IS NULL GROUP BY s.subscriber_id ORDER BY first_created_at, s.subscriber_id LIMIT ?",
    ).bind(now, staleBefore, cutoff, cutoff, subscriberLimit).all());
    const batches = [];
    for (const subscriber of subscribers) {
      const eligible = rows(await this.db.prepare(
        "SELECT n.*, s.type, s.cadence, s.definition_json, s.subscriber_id, u.email, u.manage_token FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.terminal_at IS NULL AND COALESCE(n.error_code, '') <> 'provider_outcome_reconcile' AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND (n.evaluation_window_started_at IS NULL OR EXISTS (SELECT 1 FROM evaluation_runs r WHERE r.evaluation_window_started_at = n.evaluation_window_started_at AND r.evaluation_completed_at IS NOT NULL)) AND (? IS NULL OR COALESCE(n.weekly_window_at, n.created_at) <= ?) AND s.active = 1 AND s.verified_at IS NOT NULL AND s.cadence = 'weekly' AND s.subscriber_id = ? AND u.suppressed_at IS NULL ORDER BY n.created_at, n.id LIMIT ?",
      ).bind(
        now, staleBefore, cutoff, cutoff, subscriber.subscriber_id, eventLimit + 1,
      ).all());
      if (eligible.length) batches.push({
        events: eligible.slice(0, eventLimit),
        hasOverflow: eligible.length > eventLimit,
      });
    }
    return batches;
  }

  async pendingNotificationReconciliationBatches(now, messageLimit, eventLimit) {
    const staleBefore = staleClaimCutoff(now);
    const keys = rows(await this.db.prepare(
      "SELECT n.provider_quota_key, MIN(n.created_at) AS first_created_at, MAX(n.provider_batch_has_overflow) AS has_overflow, MAX(n.provider_payload_json) AS provider_payload_json FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.provider_quota_key IS NOT NULL AND n.error_code = 'provider_outcome_reconcile' AND n.terminal_at IS NULL AND ((n.status = 'failed' AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND u.suppressed_at IS NULL GROUP BY n.provider_quota_key HAVING MAX(n.provider_payload_json) IS NOT NULL ORDER BY first_created_at, n.provider_quota_key LIMIT ?",
    ).bind(now, staleBefore, messageLimit).all());
    const batches = [];
    for (const key of keys) {
      const eligible = rows(await this.db.prepare(
        "SELECT n.*, s.type, s.cadence, s.definition_json, s.subscriber_id, u.email, u.manage_token FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.provider_quota_key = ? AND n.error_code = 'provider_outcome_reconcile' AND n.terminal_at IS NULL AND ((n.status = 'failed' AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND u.suppressed_at IS NULL ORDER BY n.created_at, n.id LIMIT ?",
      ).bind(key.provider_quota_key, now, staleBefore, eventLimit).all());
      if (eligible.length) batches.push({
        events: eligible,
        hasOverflow: Number(key.has_overflow) === 1,
        idempotencyKey: key.provider_quota_key,
        providerPayloadJson: key.provider_payload_json,
        reconciliation: true,
      });
    }
    return batches;
  }

  async pendingVerificationEvents(now, limit, eventIds = null) {
    const staleBefore = staleClaimCutoff(now);
    const ids = Array.isArray(eventIds) ? [...new Set(eventIds.map(String).filter(Boolean))] : [];
    const eventPredicate = ids.length
      ? ` AND n.id IN (${ids.map(() => "?").join(",")})`
      : "";
    return rows(await this.db.prepare(
      `SELECT n.*, s.type, s.subscriber_id, s.verification_expires_at, s.verification_token_hash, u.email, u.capability_version FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'verification' AND n.terminal_at IS NULL AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND (s.active = 0 OR n.error_code = 'verification_outcome_reconcile') AND u.suppressed_at IS NULL${eventPredicate} ORDER BY n.created_at, n.id LIMIT ?`,
    ).bind(now, staleBefore, ...ids, limit).all());
  }

  async claimEvents(ids, now, scheduler = null) {
    if (!ids.length) return [];
    const staleBefore = staleClaimCutoff(now);
    const placeholders = ids.map(() => "?").join(",");
    const claimable = "terminal_at IS NULL AND (status IN ('queued', 'failed') OR (status = 'sending' AND claimed_at IS NOT NULL AND claimed_at <= ?))";
    const claim = schedulerClaim(scheduler);
    const result = await this.db.prepare(
      `UPDATE notification_events SET status = 'sending', attempts = attempts + 1, claimed_at = ? WHERE id IN (${placeholders}) AND ${claimable}${claim.sql} AND (SELECT COUNT(*) FROM notification_events WHERE id IN (${placeholders}) AND ${claimable}${claim.sql}) = ?`,
    ).bind(
      now, ...ids, staleBefore, ...claim.values,
      ...ids, staleBefore, ...claim.values, ids.length,
    ).run();
    return Number(result?.meta?.changes || 0) === ids.length ? [...ids] : [];
  }

  async markEventsSent(ids, providerMessageId, now, scheduler = null) {
    if (!ids.length) return;
    const claim = schedulerClaim(scheduler);
    const suppressionEvidence = "SELECT pe.event_type, pe.received_at FROM provider_events pe WHERE pe.provider_message_id = ? AND pe.event_type IN ('email.bounced', 'email.complained', 'email.suppressed') ORDER BY pe.received_at, pe.provider_event_id LIMIT 1";
    const correlatedSubscriber = "SELECT s.subscriber_id FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id WHERE n.provider_message_id = ? LIMIT 1";
    await this.db.batch([
      ...ids.map(id => this.db.prepare(
        `UPDATE notification_events SET status = 'sent', provider_message_id = ?, sent_at = ?, error_code = NULL, claimed_at = NULL, terminal_at = NULL WHERE id = ? AND status = 'sending'${claim.sql}`,
      ).bind(providerMessageId, now, id, ...claim.values)),
      this.db.prepare(
        `UPDATE subscriptions SET last_notified_at = ?, updated_at = ? WHERE id IN (SELECT subscription_id FROM notification_events WHERE message_kind = 'notification' AND id IN (${ids.map(() => "?").join(",")}))${claim.sql}`,
      ).bind(now, now, ...ids, ...claim.values),
      this.db.prepare(
        `UPDATE subscribers SET suppressed_at = COALESCE(suppressed_at, (SELECT received_at FROM (${suppressionEvidence}))), suppression_reason = COALESCE(suppression_reason, (SELECT event_type FROM (${suppressionEvidence}))), updated_at = ? WHERE id = (${correlatedSubscriber}) AND EXISTS (${suppressionEvidence})${claim.sql}`,
      ).bind(providerMessageId, providerMessageId, now, providerMessageId, providerMessageId, ...claim.values),
      this.db.prepare(
        `UPDATE subscriptions SET active = 0, updated_at = ? WHERE subscriber_id = (${correlatedSubscriber}) AND EXISTS (${suppressionEvidence})${claim.sql}`,
      ).bind(now, providerMessageId, providerMessageId, ...claim.values),
      this.db.prepare(
        `UPDATE notification_events SET status = 'suppressed', error_code = (SELECT event_type FROM (${suppressionEvidence})), terminal_at = COALESCE(terminal_at, (SELECT received_at FROM (${suppressionEvidence}))), claimed_at = NULL WHERE status IN ('queued', 'failed') AND subscription_id IN (SELECT id FROM subscriptions WHERE subscriber_id = (${correlatedSubscriber})) AND EXISTS (${suppressionEvidence})${claim.sql}`,
      ).bind(providerMessageId, providerMessageId, providerMessageId, providerMessageId, ...claim.values),
    ]);
  }

  async markEventsFailed(ids, errorCode, nextAttemptAt, terminalAt = null, providerFailureKind = "", scheduler = null) {
    if (!ids.length) return;
    const claim = schedulerClaim(scheduler);
    if (terminalAt === null) {
      if (providerFailureKind === "network") {
        const placeholders = ids.map(() => "?").join(",");
        await this.db.batch([
          this.db.prepare(
            `UPDATE notification_events SET status = 'failed', error_code = CASE WHEN message_kind = 'verification' THEN 'verification_outcome_reconcile' ELSE 'provider_outcome_reconcile' END, next_attempt_at = ?, claimed_at = NULL, terminal_at = NULL WHERE provider_quota_key IN (SELECT provider_quota_key FROM notification_events WHERE id IN (${placeholders}) AND status = 'sending' AND provider_quota_key IS NOT NULL) AND status = 'sending'${claim.sql}`,
          ).bind(nextAttemptAt, ...ids, ...claim.values),
          ...ids.map(id => this.db.prepare(
            `UPDATE notification_events SET status = CASE WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN 'suppressed' ELSE 'failed' END, error_code = CASE WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN substr(error_code, 1, length(error_code) - 10) ELSE ? END, next_attempt_at = ?, claimed_at = NULL, terminal_at = CASE WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN terminal_at ELSE NULL END WHERE id = ? AND status = 'sending' AND error_code NOT IN ('provider_outcome_reconcile', 'verification_outcome_reconcile')${claim.sql}`,
          ).bind(errorCode, nextAttemptAt, id, ...claim.values)),
        ]);
        return;
      }
      await this.db.batch(ids.map(id => this.db.prepare(
        `UPDATE notification_events SET status = CASE WHEN error_code IN ('provider_outcome_reconcile', 'verification_outcome_reconcile') THEN 'failed' WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN 'suppressed' ELSE 'failed' END, error_code = CASE WHEN error_code IN ('provider_outcome_reconcile', 'verification_outcome_reconcile') THEN error_code WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN substr(error_code, 1, length(error_code) - 10) ELSE ? END, next_attempt_at = ?, claimed_at = NULL, terminal_at = CASE WHEN error_code IN ('provider_outcome_reconcile', 'verification_outcome_reconcile') THEN NULL WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN terminal_at ELSE NULL END WHERE id = ? AND status = 'sending'${claim.sql}`,
      ).bind(errorCode, nextAttemptAt, id, ...claim.values)));
      return;
    }
    await this.db.batch(ids.map(id => this.db.prepare(
      `UPDATE notification_events SET status = CASE WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN 'suppressed' ELSE 'failed' END, error_code = CASE WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN substr(error_code, 1, length(error_code) - 10) ELSE ? END, next_attempt_at = ?, claimed_at = NULL, terminal_at = CASE WHEN terminal_at IS NOT NULL AND substr(error_code, -10) = '_in_flight' THEN terminal_at ELSE ? END WHERE id = ? AND status = 'sending'${claim.sql}`,
    ).bind(errorCode, nextAttemptAt, terminalAt, id, ...claim.values)));
  }

  async releaseClaimedEvents(ids, nextAttemptAt, scheduler = null) {
    if (!ids.length) return;
    const claim = schedulerClaim(scheduler);
    await this.db.batch(ids.map(id => this.db.prepare(
      `UPDATE notification_events SET status = CASE WHEN terminal_at IS NULL THEN 'queued' ELSE 'suppressed' END, attempts = CASE WHEN terminal_at IS NULL THEN MAX(0, attempts - 1) ELSE attempts END, next_attempt_at = ?, claimed_at = NULL, error_code = CASE WHEN terminal_at IS NULL THEN error_code WHEN substr(error_code, -10) = '_in_flight' THEN substr(error_code, 1, length(error_code) - 10) ELSE error_code END WHERE id = ? AND status = 'sending'${claim.sql}`,
    ).bind(nextAttemptAt, id, ...claim.values)));
  }

  async verificationClaimIsCurrent(eventId, tokenHash, claimedAt, scheduler = null) {
    const claim = schedulerClaim(scheduler);
    const event = await this.db.prepare(
      `SELECT n.id FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.id = ? AND n.message_kind = 'verification' AND n.status = 'sending' AND n.claimed_at = ? AND n.terminal_at IS NULL AND s.active = 0 AND s.verification_token_hash = ? AND u.suppressed_at IS NULL${claim.sql}`,
    ).bind(eventId, claimedAt, tokenHash, ...claim.values).first();
    return Boolean(event);
  }

  async verificationReconciliationClaimIsCurrent(eventId, claimedAt, scheduler = null) {
    const claim = schedulerClaim(scheduler);
    const event = await this.db.prepare(
      `SELECT n.id FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.id = ? AND n.message_kind = 'verification' AND n.status = 'sending' AND n.claimed_at = ? AND n.terminal_at IS NULL AND n.error_code = 'verification_outcome_reconcile' AND u.suppressed_at IS NULL${claim.sql}`,
    ).bind(eventId, claimedAt, ...claim.values).first();
    return Boolean(event);
  }

  async refreshVerificationEvent(eventId, {
    nonce, tokenHash, expectedTokenHash, expiresAt, eventKey, claimedAt, now, scheduler = null,
  }) {
    const claim = schedulerClaim(scheduler);
    await this.db.batch([
      this.db.prepare(
        `UPDATE subscriptions SET active = 0, verified_at = NULL, verification_token_hash = ?, verification_expires_at = ?, updated_at = ? WHERE id = (SELECT subscription_id FROM notification_events WHERE id = ? AND message_kind = 'verification' AND status = 'sending' AND claimed_at = ? AND terminal_at IS NULL) AND active = 0 AND verification_token_hash = ? AND EXISTS (SELECT 1 FROM subscribers WHERE id = subscriptions.subscriber_id AND suppressed_at IS NULL)${claim.sql}`,
      ).bind(tokenHash, expiresAt, now, eventId, claimedAt, expectedTokenHash, ...claim.values),
      this.db.prepare(
        `UPDATE notification_events SET event_key = ?, payload_json = ?, next_attempt_at = ?, error_code = NULL WHERE id = ? AND message_kind = 'verification' AND status = 'sending' AND claimed_at = ? AND terminal_at IS NULL AND EXISTS (SELECT 1 FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.id = notification_events.subscription_id AND s.active = 0 AND s.verification_token_hash = ? AND u.suppressed_at IS NULL)${claim.sql}`,
      ).bind(eventKey, JSON.stringify({ nonce }), now, eventId, claimedAt, tokenHash, ...claim.values),
    ]);
    return this.verificationClaimIsCurrent(eventId, tokenHash, claimedAt, scheduler);
  }

  async startRun(run) {
    await this.recoverStaleRuns(run.startedAt);
    const startStatement = this.db.prepare(
      "INSERT OR IGNORE INTO evaluation_runs(id, started_at, scheduled_at, run_kind, status, stage, stage_started_at, last_heartbeat_at, progress_json, evaluation_window_started_at, weekly_window_at, evaluation_input_generated_at, evaluation_source_generated_at, claim_token, claim_revoked_at) VALUES(?, ?, ?, ?, 'running', 'starting', ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
    ).bind(
      run.id, run.startedAt, run.scheduledAt, run.runKind,
      run.startedAt, run.startedAt, JSON.stringify({ processedSubscriptions: 0, processedChanges: 0 }),
      run.evaluationWindowStartedAt || null, run.weeklyWindowAt || null,
      run.evaluationInputGeneratedAt || null, run.evaluationSourceGeneratedAt || null,
      String(run.claimToken || run.id),
    );
    if (run.deferredDailyWindow?.evaluationWindowStartedAt) {
      const deferred = run.deferredDailyWindow;
      const [result] = await this.db.batch([
        startStatement,
        this.db.prepare(
          "INSERT OR IGNORE INTO evaluation_runs(id, started_at, scheduled_at, run_kind, status, stage, stage_started_at, last_heartbeat_at, progress_json, evaluation_window_started_at, weekly_window_at, claim_token, claim_revoked_at) VALUES(?, ?, ?, 'daily', 'pending_evaluation', 'queued', ?, ?, ?, ?, ?, NULL, NULL)",
        ).bind(
          deferred.id, deferred.queuedAt, deferred.scheduledAt,
          deferred.queuedAt, deferred.queuedAt,
          JSON.stringify({ processedSubscriptions: 0, processedChanges: 0, deferredByWindow: run.evaluationWindowStartedAt || null }),
          deferred.evaluationWindowStartedAt, deferred.weeklyWindowAt,
        ),
      ]);
      return Number(result?.meta?.changes || 0) > 0;
    }
    const result = await startStatement.run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async recoverStaleRuns(now) {
    const staleBefore = new Date(Date.parse(now) - 12 * 60_000).toISOString();
    const result = await this.db.prepare(
      "UPDATE evaluation_runs SET completed_at = ?, duration_ms = MAX(0, CAST(ROUND((julianday(?) - julianday(started_at)) * 86400000) AS INTEGER)), status = 'failed_stale_recovered', error_code = 'stale_run_recovered', stage = CASE WHEN stage = 'starting' THEN 'stale_recovery' ELSE stage END, last_heartbeat_at = ?, claim_token = NULL, claim_revoked_at = ? WHERE status = 'running' AND started_at < ?",
    ).bind(now, now, now, now, staleBefore).run();
    return Number(result?.meta?.changes || 0);
  }

  async runClaimIsCurrent(runId, token) {
    const row = await this.db.prepare(
      "SELECT id FROM evaluation_runs WHERE id = ? AND status = 'running' AND claim_token = ?",
    ).bind(runId, token).first();
    return Boolean(row);
  }

  async revokeRunClaim(
    runId, token, now, status = "incomplete_timeout", errorCode = "scheduler_deadline_exceeded",
  ) {
    const result = await this.db.prepare(
      "UPDATE evaluation_runs SET completed_at = ?, duration_ms = MAX(0, CAST(ROUND((julianday(?) - julianday(started_at)) * 86400000) AS INTEGER)), status = ?, error_code = ?, last_heartbeat_at = ?, claim_token = NULL, claim_revoked_at = ? WHERE id = ? AND status = 'running' AND claim_token = ?",
    ).bind(now, now, status, errorCode, now, now, runId, token).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async outstandingEvaluationWindows() {
    const cursorWindows = rows(await this.db.prepare(
      "SELECT s.evaluation_window_started_at, MAX(s.evaluation_weekly_window_at) AS weekly_window_at, MAX(s.evaluation_input_generated_at) AS evaluation_input_generated_at, MAX(s.evaluation_source_generated_at) AS evaluation_source_generated_at, MIN(s.updated_at) AS discovered_at, COUNT(*) AS cursor_count FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.active = 1 AND s.verified_at IS NOT NULL AND u.suppressed_at IS NULL AND s.evaluation_cursor_at IS NOT NULL AND s.evaluation_window_started_at IS NOT NULL GROUP BY s.evaluation_window_started_at",
    ).all());
    const runWindows = rows(await this.db.prepare(
      "SELECT COALESCE(evaluation_window_started_at, scheduled_at) AS evaluation_window_started_at, MAX(weekly_window_at) AS weekly_window_at, MAX(evaluation_input_generated_at) AS evaluation_input_generated_at, MAX(evaluation_source_generated_at) AS evaluation_source_generated_at, MIN(started_at) AS discovered_at, MAX(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running, MAX(evaluation_completed_at) AS evaluation_completed_at FROM evaluation_runs WHERE run_kind IN ('daily','continuation') AND COALESCE(evaluation_window_started_at, scheduled_at) IS NOT NULL GROUP BY COALESCE(evaluation_window_started_at, scheduled_at) HAVING MAX(CASE WHEN status LIKE 'completed%' AND (evaluation_completed_at IS NOT NULL OR evaluation_input_generated_at IS NULL) THEN 1 ELSE 0 END) = 0",
    ).all());
    const byWindow = new Map();
    for (const value of [...runWindows, ...cursorWindows]) {
      const key = String(value.evaluation_window_started_at || "");
      if (!key) continue;
      const existing = byWindow.get(key) || {
        evaluationWindowStartedAt: key,
        weeklyWindowAt: "",
        evaluationInputGeneratedAt: "",
        evaluationSourceGeneratedAt: "",
        evaluationCompletedAt: "",
        discoveredAt: "",
        running: false,
        cursorCount: 0,
      };
      existing.weeklyWindowAt = String(value.weekly_window_at || existing.weeklyWindowAt || "");
      existing.evaluationInputGeneratedAt = String(
        value.evaluation_input_generated_at || existing.evaluationInputGeneratedAt || "",
      );
      existing.evaluationSourceGeneratedAt = String(
        value.evaluation_source_generated_at || existing.evaluationSourceGeneratedAt || "",
      );
      existing.evaluationCompletedAt = String(
        value.evaluation_completed_at || existing.evaluationCompletedAt || "",
      );
      const discoveredAt = String(value.discovered_at || "");
      if (discoveredAt && (!existing.discoveredAt || discoveredAt < existing.discoveredAt)) {
        existing.discoveredAt = discoveredAt;
      }
      existing.running = existing.running || Number(value.running || 0) > 0;
      existing.cursorCount = Math.max(existing.cursorCount, Number(value.cursor_count || 0));
      byWindow.set(key, existing);
    }
    return [...byWindow.values()].sort((left, right) => (
      left.evaluationWindowStartedAt.localeCompare(right.evaluationWindowStartedAt)
      || left.discoveredAt.localeCompare(right.discoveredAt)
    ));
  }

  async dailyContinuationState(now) {
    await this.recoverStaleRuns(now);
    const windows = await this.outstandingEvaluationWindows();
    const oldest = windows[0];
    if (!oldest) return { state: "none", outstandingWindowCount: 0 };
    const details = { ...oldest, outstandingWindowCount: windows.length };
    return oldest.running
      ? { state: "running", ...details }
      : { state: "pending", evaluationCompleted: Boolean(oldest.evaluationCompletedAt), ...details };
  }

  async needsDailyContinuation(now) {
    return (await this.dailyContinuationState(now)).state === "pending";
  }

  async markRunEvaluationComplete(runId, completedAt, progress = null, scheduler = null) {
    const claim = schedulerClaim(scheduler);
    const result = await this.db.prepare(
      `UPDATE evaluation_runs SET evaluation_completed_at = ?, last_heartbeat_at = ?, progress_json = ? WHERE id = ? AND status = 'running'${claim.sql}`,
    ).bind(completedAt, completedAt, progress ? JSON.stringify(progress) : null, runId, ...claim.values).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async bindRunEvaluationInput(
    runId, evaluationWindowStartedAt, inputGeneratedAt, sourceGeneratedAt, now, scheduler = null,
  ) {
    const claim = schedulerClaim(scheduler);
    await this.db.prepare(
      `UPDATE evaluation_runs SET evaluation_input_generated_at = COALESCE(evaluation_input_generated_at, ?), evaluation_source_generated_at = ?, last_heartbeat_at = ? WHERE id = ? AND status = 'running' AND evaluation_window_started_at = ? AND (evaluation_input_generated_at IS NULL OR evaluation_input_generated_at = ?)${claim.sql}`,
    ).bind(
      inputGeneratedAt, sourceGeneratedAt, now, runId,
      evaluationWindowStartedAt, inputGeneratedAt, ...claim.values,
    ).run();
    const row = await this.db.prepare(
      `SELECT evaluation_input_generated_at, evaluation_source_generated_at FROM evaluation_runs WHERE id = ? AND status = 'running'${claim.sql}`,
    ).bind(runId, ...claim.values).first();
    return Boolean(
      row
      && String(row.evaluation_input_generated_at || "") === String(inputGeneratedAt || "")
      && String(row.evaluation_source_generated_at || "") === String(sourceGeneratedAt || ""),
    );
  }

  async updateRunProgress(runId, { stage, stageStartedAt, heartbeatAt, progress = null, errorCode = null } = {}, scheduler = null) {
    const claim = schedulerClaim(scheduler);
    const result = await this.db.prepare(
      `UPDATE evaluation_runs SET stage = ?, stage_started_at = ?, last_heartbeat_at = ?, progress_json = ?, error_code = ? WHERE id = ? AND status = 'running'${claim.sql}`,
    ).bind(
      String(stage || "unknown").slice(0, 80),
      stageStartedAt,
      heartbeatAt,
      progress ? JSON.stringify(progress) : null,
      errorCode ? String(errorCode).slice(0, 80) : null,
      runId, ...claim.values,
    ).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async finishRun(run) {
    const finishStatement = this.db.prepare(
      "UPDATE evaluation_runs SET completed_at = ?, duration_ms = ?, subscription_count = ?, matched_event_count = ?, attempted_count = ?, delivered_count = ?, failed_count = ?, cleanup_deleted_count = ?, cleanup_error_code = ?, status = ?, stage = ?, stage_started_at = ?, last_heartbeat_at = ?, progress_json = ?, error_code = ?, evaluation_completed_at = ?, evaluation_window_started_at = ?, weekly_window_at = ?, evaluation_input_generated_at = ?, evaluation_source_generated_at = ?, claim_token = NULL, claim_revoked_at = ? WHERE id = ? AND status = 'running' AND claim_token = ?",
    ).bind(
      run.completedAt, run.durationMs, run.subscriptionCount, run.matchedEventCount,
      run.attemptedCount, run.deliveredCount, run.failedCount,
      run.cleanupDeletedCount, run.cleanupErrorCode || null, run.status,
      run.stage || "completed", run.stageStartedAt || run.completedAt, run.completedAt,
      JSON.stringify(run.progress || {}), run.errorCode || null,
      run.evaluationCompletedAt || null, run.evaluationWindowStartedAt || null,
      run.weeklyWindowAt || null, run.evaluationInputGeneratedAt || null,
      run.evaluationSourceGeneratedAt || null, run.completedAt, run.id,
      String(run.claimToken || run.id),
    );
    const [result] = await this.db.batch([
      finishStatement,
      this.db.prepare(
        "UPDATE evaluation_runs SET completed_at = ?, duration_ms = MAX(0, CAST(ROUND((julianday(?) - julianday(started_at)) * 86400000) AS INTEGER)), status = 'completed_with_adoption', stage = 'completed', stage_started_at = ?, last_heartbeat_at = ?, evaluation_completed_at = ?, claim_revoked_at = ? WHERE status = 'pending_evaluation' AND evaluation_window_started_at = ? AND EXISTS (SELECT 1 FROM evaluation_runs owner WHERE owner.id = ? AND owner.status LIKE 'completed%' AND owner.evaluation_completed_at IS NOT NULL)",
      ).bind(
        run.completedAt, run.completedAt, run.completedAt, run.completedAt,
        run.evaluationCompletedAt || null, run.completedAt,
        run.evaluationWindowStartedAt || null, run.id,
      ),
    ]);
    return Number(result?.meta?.changes || 0) > 0;
  }

  async cleanupOperationalData(now, batchSize = 100, scheduler = null) {
    const limit = Math.max(1, Math.min(500, Number(batchSize) || 100));
    const claim = schedulerClaim(scheduler);
    const before = days => new Date(Date.parse(now) - days * 86_400_000).toISOString();
    const statements = [
      ["DELETE FROM rate_limits WHERE rowid IN (SELECT rowid FROM rate_limits WHERE expires_at < ? ORDER BY expires_at LIMIT ?)", before(RETENTION_DAYS.rateLimits)],
      ["DELETE FROM evaluation_runs WHERE rowid IN (SELECT r.rowid FROM evaluation_runs r WHERE r.completed_at IS NOT NULL AND r.completed_at < ? AND r.status <> 'running' AND (r.run_kind NOT IN ('daily','continuation') OR COALESCE(r.evaluation_window_started_at, r.scheduled_at) IS NULL OR EXISTS (SELECT 1 FROM evaluation_runs done WHERE COALESCE(done.evaluation_window_started_at, done.scheduled_at) = COALESCE(r.evaluation_window_started_at, r.scheduled_at) AND done.status LIKE 'completed%' AND (done.evaluation_completed_at IS NOT NULL OR done.evaluation_input_generated_at IS NULL))) ORDER BY r.completed_at LIMIT ?)", before(RETENTION_DAYS.evaluationRuns)],
      ["DELETE FROM provider_events WHERE rowid IN (SELECT rowid FROM provider_events WHERE received_at < ? ORDER BY received_at LIMIT ?)", before(RETENTION_DAYS.providerEvents)],
      ["DELETE FROM notification_events WHERE rowid IN (SELECT rowid FROM notification_events WHERE ((status = 'sent' AND sent_at < ?) OR (status IN ('suppressed','failed') AND terminal_at IS NOT NULL AND terminal_at < ?)) ORDER BY COALESCE(sent_at, terminal_at, created_at) LIMIT ?)", before(RETENTION_DAYS.terminalDeliveries), before(RETENTION_DAYS.terminalDeliveries)],
    ];
    let deletedCount = 0;
    for (const [sql, ...values] of statements) {
      const result = await this.db.prepare(`${sql}${claim.sql}`).bind(...values, limit, ...claim.values).run();
      deletedCount += Number(result?.meta?.changes || 0);
    }
    return { deletedCount, batchSize: limit };
  }

  async operationalHealth(now) {
    const staleBefore = new Date(Date.parse(now) - 12 * 60_000).toISOString();
    const dailyBefore = new Date(Date.parse(now) - 26 * 60 * 60_000).toISOString();
    await this.recoverStaleRuns(now);
    const outstandingWindows = await this.outstandingEvaluationWindows();
    const row = await this.db.prepare(
      "SELECT (SELECT COUNT(*) FROM evaluation_runs WHERE status = 'running' AND started_at < ?) AS stale_running_runs, (SELECT completed_at FROM evaluation_runs WHERE completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) AS last_completed_at, (SELECT status FROM evaluation_runs WHERE completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) AS last_status, (SELECT duration_ms FROM evaluation_runs WHERE completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) AS last_duration_ms, (SELECT stage FROM evaluation_runs ORDER BY started_at DESC LIMIT 1) AS last_stage, (SELECT error_code FROM evaluation_runs ORDER BY started_at DESC LIMIT 1) AS last_error_code, (SELECT completed_at FROM evaluation_runs WHERE run_kind IN ('daily','continuation') AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) AS last_daily_completed_at, (SELECT status FROM evaluation_runs WHERE run_kind IN ('daily','continuation') AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) AS last_daily_status, (SELECT COALESCE(evaluation_completed_at, CASE WHEN status LIKE 'completed%' THEN completed_at END) FROM evaluation_runs WHERE run_kind IN ('daily','continuation') AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1) AS last_daily_evaluation_completed_at",
    ).bind(staleBefore).first();
    const lastCompletedAt = String(row?.last_completed_at || "");
    const lastDailyCompletedAt = String(row?.last_daily_completed_at || "");
    const lastDailyStatus = String(row?.last_daily_status || "");
    const dailyCompletedSuccessfully = Boolean(row?.last_daily_evaluation_completed_at)
      && (lastDailyStatus === "completed" || lastDailyStatus.startsWith("completed_with_"));
    return {
      staleRunningRuns: Number(row?.stale_running_runs || 0),
      lastCompletedAt,
      lastStatus: String(row?.last_status || ""),
      lastDurationMs: row?.last_duration_ms == null ? null : Number(row.last_duration_ms),
      lastStage: String(row?.last_stage || ""),
      lastErrorCode: String(row?.last_error_code || ""),
      lastDailyCompletedAt,
      lastDailyStatus,
      pendingEvaluationWindows: outstandingWindows.length,
      oldestPendingEvaluationWindow: outstandingWindows[0]?.evaluationWindowStartedAt || "",
      schedulerRecent: Boolean(
        dailyCompletedSuccessfully
        && outstandingWindows.length === 0
        && lastDailyCompletedAt >= dailyBefore
        && lastDailyCompletedAt <= now,
      ),
    };
  }

  async health() {
    const row = await this.db.prepare(
      "SELECT (SELECT COUNT(*) FROM (SELECT id FROM subscriptions LIMIT 1)) AS subscription_rows, (SELECT COUNT(*) FROM (SELECT message_kind, terminal_at, provider_quota_key, provider_quota_reserved_at, provider_batch_has_overflow, provider_payload_json FROM notification_events LIMIT 1)) AS event_rows, (SELECT COUNT(*) FROM (SELECT last_reservation_key FROM rate_limits LIMIT 1)) AS rate_rows",
    ).first();
    return Boolean(row);
  }
}

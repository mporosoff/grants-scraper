function rows(result) {
  return result?.results || [];
}

const DELIVERY_LEASE_MS = 15 * 60 * 1_000;

function staleClaimCutoff(now) {
  const timestamp = Date.parse(now);
  return new Date((Number.isFinite(timestamp) ? timestamp : Date.now()) - DELIVERY_LEASE_MS).toISOString();
}

export class D1AlertStore {
  constructor(database) {
    if (!database?.prepare) throw new Error("Alerts D1 binding is unavailable.");
    this.db = database;
  }

  async consumeRateLimit(action, clientKey, limit, windowSeconds, now) {
    const current = await this.db.prepare(
      "SELECT request_count, expires_at FROM rate_limits WHERE action = ? AND client_key = ?",
    ).bind(action, clientKey).first();
    const expires = new Date(now.getTime() + windowSeconds * 1_000).toISOString();
    if (!current || current.expires_at <= now.toISOString()) {
      await this.db.prepare(
        "INSERT INTO rate_limits(action, client_key, window_started_at, expires_at, request_count) VALUES(?, ?, ?, ?, 1) ON CONFLICT(action, client_key) DO UPDATE SET window_started_at = excluded.window_started_at, expires_at = excluded.expires_at, request_count = 1",
      ).bind(action, clientKey, now.toISOString(), expires).run();
      return true;
    }
    if (Number(current.request_count) >= limit) return false;
    await this.db.prepare(
      "UPDATE rate_limits SET request_count = request_count + 1 WHERE action = ? AND client_key = ?",
    ).bind(action, clientKey).run();
    return true;
  }

  async findSubscription(subscriberId, type, definitionHash) {
    return this.db.prepare(
      "SELECT * FROM subscriptions WHERE subscriber_id = ? AND type = ? AND definition_hash = ?",
    ).bind(subscriberId, type, definitionHash).first();
  }

  async upsertSubscriber({ id, email, manageToken, now }) {
    await this.db.prepare(
      "INSERT INTO subscribers(id, email, email_normalized, manage_token, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(email_normalized) DO UPDATE SET email = excluded.email, updated_at = excluded.updated_at",
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
        "INSERT INTO subscriptions(id, subscriber_id, type, active, cadence, definition_json, definition_hash, verification_token_hash, verification_expires_at, verified_at, baseline_at, baseline_complete, last_evaluated_at, last_notified_at, created_at, updated_at) VALUES(?, ?, ?, 0, ?, ?, ?, ?, ?, NULL, ?, 0, NULL, NULL, ?, ?) ON CONFLICT(id) DO UPDATE SET cadence = excluded.cadence, definition_json = excluded.definition_json, verification_token_hash = excluded.verification_token_hash, verification_expires_at = excluded.verification_expires_at, verified_at = NULL, baseline_at = excluded.baseline_at, baseline_complete = 0, last_evaluated_at = NULL, last_notified_at = NULL, updated_at = excluded.updated_at WHERE subscriptions.active = 0 AND NOT EXISTS (SELECT 1 FROM notification_events n WHERE n.subscription_id = subscriptions.id AND n.message_kind = 'verification' AND n.status = 'sending' AND n.terminal_at IS NULL)",
      ).bind(
        value.id, value.subscriberId, value.type, value.cadence, value.definitionJson,
        value.definitionHash, value.verificationTokenHash, value.verificationExpiresAt,
        value.now, value.now, value.now,
      ),
      this.db.prepare(
        `UPDATE notification_events SET status = 'suppressed', error_code = 'subscription_reactivated', claimed_at = NULL, terminal_at = ? WHERE subscription_id = ? AND status IN ('queued', 'failed', 'sending') AND EXISTS (SELECT 1 FROM subscriptions WHERE ${cyclePredicate})`,
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
    const suppressed = Boolean(subscription.suppressed_at);
    await this.db.batch([
      this.db.prepare(
        "UPDATE subscriptions SET active = ?, verified_at = COALESCE(verified_at, ?), updated_at = ? WHERE id = ?",
      ).bind(suppressed ? 0 : 1, now, now, subscription.id),
      this.db.prepare(
        "UPDATE subscribers SET verified_at = COALESCE(verified_at, ?), updated_at = ? WHERE id = ?",
      ).bind(now, now, subscription.subscriber_id),
      this.db.prepare(
        "UPDATE notification_events SET status = 'suppressed', error_code = 'verification_completed', claimed_at = NULL, terminal_at = ? WHERE subscription_id = ? AND message_kind = 'verification' AND status IN ('queued', 'failed', 'sending')",
      ).bind(now, subscription.id),
    ]);
    return {
      ...subscription,
      active: suppressed ? 0 : 1,
      verified_at: subscription.verified_at || now,
      deliverySuppressed: suppressed,
    };
  }

  async subscriberByManageToken(token) {
    return this.db.prepare("SELECT * FROM subscribers WHERE manage_token = ?").bind(token).first();
  }

  async subscriptionsForSubscriber(subscriberId) {
    return rows(await this.db.prepare(
      "SELECT * FROM subscriptions WHERE subscriber_id = ? ORDER BY created_at DESC",
    ).bind(subscriberId).all());
  }

  async updateSubscription(manageToken, subscriptionId, { active, cadence }, now) {
    const subscriber = await this.subscriberByManageToken(manageToken);
    if (!subscriber) return false;
    if (active === true && subscriber.suppressed_at) return false;
    const values = [];
    const setters = [];
    if (typeof active === "boolean") { setters.push("active = ?"); values.push(active ? 1 : 0); }
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
    const subscriber = await this.subscriberByManageToken(manageToken);
    if (!subscriber) return false;
    await this.db.prepare(
      "UPDATE subscriptions SET active = 0, updated_at = ? WHERE subscriber_id = ?",
    ).bind(now, subscriber.id).run();
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
    await this.db.prepare(
      "INSERT INTO provider_events(provider_event_id, event_type, provider_message_id, received_at) VALUES(?, ?, ?, ?)",
    ).bind(providerEventId, reason, providerMessageId || null, now).run();
    if (!event) return false;
    await this.db.batch([
      this.db.prepare(
        "UPDATE subscribers SET suppressed_at = ?, suppression_reason = ?, updated_at = ? WHERE id = ?",
      ).bind(now, reason, now, event.subscriber_id),
      this.db.prepare("UPDATE subscriptions SET active = 0, updated_at = ? WHERE subscriber_id = ?")
        .bind(now, event.subscriber_id),
      this.db.prepare(
        "UPDATE notification_events SET status = 'suppressed', error_code = ? WHERE status IN ('queued', 'failed') AND subscription_id IN (SELECT id FROM subscriptions WHERE subscriber_id = ?)",
      ).bind(reason, event.subscriber_id),
    ]);
    return true;
  }

  async activeSubscriptions() {
    return rows(await this.db.prepare(
      "SELECT s.*, u.email, u.manage_token FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.active = 1 AND s.verified_at IS NOT NULL AND u.suppressed_at IS NULL ORDER BY s.id",
    ).all());
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

  async setQualification(subscriptionId, opportunityId, qualified, now) {
    await this.db.prepare(
      "INSERT INTO subscription_qualifications(subscription_id, opportunity_id, qualified, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(subscription_id, opportunity_id) DO UPDATE SET qualified = excluded.qualified, updated_at = excluded.updated_at",
    ).bind(subscriptionId, opportunityId, qualified ? 1 : 0, now).run();
  }

  async enqueueEvent(event) {
    const result = await this.db.prepare(
      "INSERT OR IGNORE INTO notification_events(id, subscription_id, event_key, event_kind, opportunity_id, payload_json, status, attempts, next_attempt_at, created_at, message_kind) VALUES(?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, 'notification')",
    ).bind(
      event.id, event.subscriptionId, event.eventKey, event.eventKind,
      event.opportunityId || null, JSON.stringify(event.payload), event.createdAt, event.createdAt,
    ).run();
    return Number(result?.meta?.changes || 0) > 0;
  }

  async markEvaluated(subscriptionId, evaluatedAt, now) {
    await this.db.prepare(
      "UPDATE subscriptions SET last_evaluated_at = ?, updated_at = ? WHERE id = ?",
    ).bind(evaluatedAt, now, subscriptionId).run();
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
      "SELECT n.*, s.type, s.cadence, s.definition_json, s.subscriber_id, u.email, u.manage_token FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.terminal_at IS NULL AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND s.active = 1 AND s.verified_at IS NOT NULL AND s.cadence = ? AND u.suppressed_at IS NULL ORDER BY n.created_at, n.id LIMIT ?",
    ).bind(now, staleBefore, cadence, limit).all());
  }

  async pendingDigestEvents(now, subscriberLimit, eventLimit) {
    const staleBefore = staleClaimCutoff(now);
    const subscribers = rows(await this.db.prepare(
      "SELECT s.subscriber_id, MIN(n.created_at) AS first_created_at FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.terminal_at IS NULL AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND s.active = 1 AND s.verified_at IS NOT NULL AND s.cadence = 'weekly' AND u.suppressed_at IS NULL GROUP BY s.subscriber_id ORDER BY first_created_at, s.subscriber_id LIMIT ?",
    ).bind(now, staleBefore, subscriberLimit).all());
    const batches = [];
    for (const subscriber of subscribers) {
      const eligible = rows(await this.db.prepare(
        "SELECT n.*, s.type, s.cadence, s.definition_json, s.subscriber_id, u.email, u.manage_token FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'notification' AND n.terminal_at IS NULL AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND s.active = 1 AND s.verified_at IS NOT NULL AND s.cadence = 'weekly' AND s.subscriber_id = ? AND u.suppressed_at IS NULL ORDER BY n.created_at, n.id LIMIT ?",
      ).bind(now, staleBefore, subscriber.subscriber_id, eventLimit + 1).all());
      if (eligible.length) batches.push({
        events: eligible.slice(0, eventLimit),
        hasOverflow: eligible.length > eventLimit,
      });
    }
    return batches;
  }

  async pendingVerificationEvents(now, limit) {
    const staleBefore = staleClaimCutoff(now);
    return rows(await this.db.prepare(
      "SELECT n.*, s.type, s.subscriber_id, s.verification_expires_at, s.verification_token_hash, u.email, u.manage_token FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.message_kind = 'verification' AND n.terminal_at IS NULL AND ((n.status IN ('queued', 'failed') AND n.next_attempt_at <= ?) OR (n.status = 'sending' AND n.claimed_at IS NOT NULL AND n.claimed_at <= ?)) AND s.active = 0 AND u.suppressed_at IS NULL ORDER BY n.created_at, n.id LIMIT ?",
    ).bind(now, staleBefore, limit).all());
  }

  async claimEvents(ids, now) {
    const staleBefore = staleClaimCutoff(now);
    const claimed = [];
    for (const id of ids) {
      const result = await this.db.prepare(
        "UPDATE notification_events SET status = 'sending', attempts = attempts + 1, claimed_at = ? WHERE id = ? AND terminal_at IS NULL AND (status IN ('queued', 'failed') OR (status = 'sending' AND claimed_at IS NOT NULL AND claimed_at <= ?))",
      ).bind(now, id, staleBefore).run();
      if (Number(result?.meta?.changes || 0) > 0) claimed.push(id);
    }
    return claimed;
  }

  async markEventsSent(ids, providerMessageId, now) {
    if (!ids.length) return;
    await this.db.batch(ids.map(id => this.db.prepare(
      "UPDATE notification_events SET status = 'sent', provider_message_id = ?, sent_at = ?, error_code = NULL, claimed_at = NULL WHERE id = ? AND status = 'sending'",
    ).bind(providerMessageId, now, id)));
    await this.db.prepare(
      `UPDATE subscriptions SET last_notified_at = ?, updated_at = ? WHERE id IN (SELECT subscription_id FROM notification_events WHERE message_kind = 'notification' AND id IN (${ids.map(() => "?").join(",")}))`,
    ).bind(now, now, ...ids).run();
  }

  async markEventsFailed(ids, errorCode, nextAttemptAt, terminalAt = null) {
    if (!ids.length) return;
    await this.db.batch(ids.map(id => this.db.prepare(
      "UPDATE notification_events SET status = 'failed', error_code = ?, next_attempt_at = ?, claimed_at = NULL, terminal_at = ? WHERE id = ? AND status = 'sending'",
    ).bind(errorCode, nextAttemptAt, terminalAt, id)));
  }

  async releaseClaimedEvents(ids, nextAttemptAt) {
    if (!ids.length) return;
    await this.db.batch(ids.map(id => this.db.prepare(
      "UPDATE notification_events SET status = 'queued', attempts = MAX(0, attempts - 1), next_attempt_at = ?, claimed_at = NULL WHERE id = ? AND status = 'sending'",
    ).bind(nextAttemptAt, id)));
  }

  async verificationClaimIsCurrent(eventId, tokenHash, claimedAt) {
    const event = await this.db.prepare(
      "SELECT n.id FROM notification_events n JOIN subscriptions s ON s.id = n.subscription_id JOIN subscribers u ON u.id = s.subscriber_id WHERE n.id = ? AND n.message_kind = 'verification' AND n.status = 'sending' AND n.claimed_at = ? AND n.terminal_at IS NULL AND s.active = 0 AND s.verification_token_hash = ? AND u.suppressed_at IS NULL",
    ).bind(eventId, claimedAt, tokenHash).first();
    return Boolean(event);
  }

  async refreshVerificationEvent(eventId, {
    nonce, tokenHash, expectedTokenHash, expiresAt, eventKey, claimedAt, now,
  }) {
    await this.db.batch([
      this.db.prepare(
        "UPDATE subscriptions SET active = 0, verified_at = NULL, verification_token_hash = ?, verification_expires_at = ?, updated_at = ? WHERE id = (SELECT subscription_id FROM notification_events WHERE id = ? AND message_kind = 'verification' AND status = 'sending' AND claimed_at = ? AND terminal_at IS NULL) AND active = 0 AND verification_token_hash = ? AND EXISTS (SELECT 1 FROM subscribers WHERE id = subscriptions.subscriber_id AND suppressed_at IS NULL)",
      ).bind(tokenHash, expiresAt, now, eventId, claimedAt, expectedTokenHash),
      this.db.prepare(
        "UPDATE notification_events SET event_key = ?, payload_json = ?, next_attempt_at = ?, error_code = NULL WHERE id = ? AND message_kind = 'verification' AND status = 'sending' AND claimed_at = ? AND terminal_at IS NULL AND EXISTS (SELECT 1 FROM subscriptions s JOIN subscribers u ON u.id = s.subscriber_id WHERE s.id = notification_events.subscription_id AND s.active = 0 AND s.verification_token_hash = ? AND u.suppressed_at IS NULL)",
      ).bind(eventKey, JSON.stringify({ nonce }), now, eventId, claimedAt, tokenHash),
    ]);
    return this.verificationClaimIsCurrent(eventId, tokenHash, claimedAt);
  }

  async startRun(run) {
    await this.db.prepare(
      "INSERT INTO evaluation_runs(id, started_at, status) VALUES(?, ?, 'running')",
    ).bind(run.id, run.startedAt).run();
  }

  async finishRun(run) {
    await this.db.prepare(
      "UPDATE evaluation_runs SET completed_at = ?, subscription_count = ?, matched_event_count = ?, attempted_count = ?, delivered_count = ?, failed_count = ?, status = ? WHERE id = ?",
    ).bind(
      run.completedAt, run.subscriptionCount, run.matchedEventCount,
      run.attemptedCount, run.deliveredCount, run.failedCount, run.status, run.id,
    ).run();
  }

  async health() {
    const row = await this.db.prepare(
      "SELECT (SELECT COUNT(*) FROM (SELECT id FROM subscriptions LIMIT 1)) AS subscription_rows, (SELECT COUNT(*) FROM (SELECT message_kind, terminal_at FROM notification_events LIMIT 1)) AS event_rows",
    ).first();
    return Boolean(row);
  }
}

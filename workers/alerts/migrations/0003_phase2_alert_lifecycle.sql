-- Phase 2 extends the existing notification ledger instead of creating a
-- parallel verification-mail queue. Existing rows remain notification rows.
-- The defaults keep older Worker inserts schema-compatible. Before a Worker-
-- version rollback, the deployment workflow terminalizes unsent verification
-- rows because pre-Phase-2 dispatch code does not understand message_kind.
ALTER TABLE notification_events
  ADD COLUMN message_kind TEXT NOT NULL DEFAULT 'notification'
  CHECK (message_kind IN ('notification', 'verification'));

ALTER TABLE notification_events
  ADD COLUMN terminal_at TEXT;

ALTER TABLE notification_events
  ADD COLUMN provider_quota_key TEXT;

ALTER TABLE notification_events
  ADD COLUMN provider_quota_reserved_at TEXT;

-- Idempotent digest reconciliation must replay the original body, including
-- whether additional events remained queued beyond the 25-event message cap.
ALTER TABLE notification_events
  ADD COLUMN provider_batch_has_overflow INTEGER NOT NULL DEFAULT 0
  CHECK (provider_batch_has_overflow IN (0, 1));

-- A provider idempotency key must replay the exact rendered request even when
-- a retry crosses a Worker/template or public-origin deployment.
ALTER TABLE notification_events
  ADD COLUMN provider_payload_json TEXT;

ALTER TABLE rate_limits
  ADD COLUMN last_reservation_key TEXT;

CREATE INDEX IF NOT EXISTS events_message_dispatch_idx
  ON notification_events(message_kind, status, next_attempt_at, created_at);

CREATE INDEX IF NOT EXISTS events_weekly_fair_idx
  ON notification_events(status, next_attempt_at, subscription_id, created_at);

CREATE INDEX IF NOT EXISTS events_provider_quota_idx
  ON notification_events(provider_quota_key);

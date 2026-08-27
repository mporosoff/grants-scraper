-- Phase 4 adds bounded operational evidence and versioned capability metadata.
-- Existing manage links remain available only through the documented transition
-- window; new subscribers use stateless HMAC capabilities and store no raw token.
ALTER TABLE subscribers
  ADD COLUMN capability_version INTEGER NOT NULL DEFAULT 0
  CHECK (capability_version IN (0, 1));

ALTER TABLE subscribers
  ADD COLUMN legacy_manage_expires_at TEXT;

UPDATE subscribers
SET legacy_manage_expires_at = '2026-11-30T23:59:59.999Z'
WHERE capability_version = 0 AND legacy_manage_expires_at IS NULL;

ALTER TABLE evaluation_runs ADD COLUMN scheduled_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN duration_ms INTEGER;
ALTER TABLE evaluation_runs ADD COLUMN run_kind TEXT NOT NULL DEFAULT 'daily';
ALTER TABLE evaluation_runs ADD COLUMN cleanup_deleted_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE evaluation_runs ADD COLUMN cleanup_error_code TEXT;

UPDATE evaluation_runs
SET scheduled_at = COALESCE(scheduled_at, started_at),
    completed_at = COALESCE(completed_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    duration_ms = COALESCE(
      duration_ms,
      MAX(0, CAST((julianday(COALESCE(completed_at, 'now')) - julianday(started_at)) * 86400000 AS INTEGER))
    ),
    status = CASE WHEN status = 'running' THEN 'failed_stale_recovered' ELSE status END
WHERE scheduled_at IS NULL OR duration_ms IS NULL OR status = 'running';

INSERT OR IGNORE INTO evaluation_runs(
  id, started_at, completed_at, scheduled_at, duration_ms, run_kind, status
) VALUES(
  'phase4_migration_ready',
  strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  0,
  'migration',
  'completed'
);

CREATE INDEX IF NOT EXISTS rate_limits_expiry_idx
  ON rate_limits(expires_at);
CREATE INDEX IF NOT EXISTS evaluation_runs_retention_idx
  ON evaluation_runs(completed_at, status);
CREATE INDEX IF NOT EXISTS provider_events_retention_idx
  ON provider_events(received_at);
CREATE INDEX IF NOT EXISTS notification_events_retention_idx
  ON notification_events(status, terminal_at, sent_at, created_at);
CREATE INDEX IF NOT EXISTS subscribers_legacy_capability_idx
  ON subscribers(capability_version, legacy_manage_expires_at, manage_token);

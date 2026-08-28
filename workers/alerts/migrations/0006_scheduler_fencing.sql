-- Fence every scheduler-owned mutation and evaluate calendar-dependent alerts daily.
ALTER TABLE evaluation_runs ADD COLUMN claim_token TEXT;
ALTER TABLE evaluation_runs ADD COLUMN claim_revoked_at TEXT;

ALTER TABLE subscriptions ADD COLUMN last_calendar_evaluated_on TEXT;

-- A deployment cannot safely inherit ownership from an older Worker that did not
-- attach fencing tokens to its writes. Preserve its evaluation window for adoption.
UPDATE evaluation_runs
SET completed_at = COALESCE(completed_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    duration_ms = COALESCE(
      duration_ms,
      MAX(0, CAST((julianday('now') - julianday(started_at)) * 86400000 AS INTEGER))
    ),
    status = 'failed_stale_recovered',
    error_code = 'migration_claim_revoked',
    claim_revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE status = 'running';

CREATE INDEX IF NOT EXISTS evaluation_runs_claim_token_idx
  ON evaluation_runs(id, status, claim_token);
CREATE INDEX IF NOT EXISTS subscriptions_calendar_evaluation_idx
  ON subscriptions(active, last_calendar_evaluated_on, id);

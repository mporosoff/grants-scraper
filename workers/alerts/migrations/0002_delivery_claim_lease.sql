ALTER TABLE notification_events ADD COLUMN claimed_at TEXT;

UPDATE notification_events
SET status = 'failed',
    error_code = 'claim_recovered',
    next_attempt_at = COALESCE(next_attempt_at, created_at)
WHERE status = 'sending';

CREATE INDEX IF NOT EXISTS events_claim_idx
  ON notification_events(status, claimed_at);

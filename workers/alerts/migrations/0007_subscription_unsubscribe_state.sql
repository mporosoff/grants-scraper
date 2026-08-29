-- Pausing and unsubscribing are distinct lifecycle decisions. Existing rows
-- remain manageable; only a successful unsubscribe records this timestamp.
ALTER TABLE subscriptions
  ADD COLUMN unsubscribed_at TEXT;

CREATE INDEX IF NOT EXISTS subscriptions_manageable_idx
  ON subscriptions(subscriber_id, unsubscribed_at, created_at);

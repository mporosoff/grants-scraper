PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subscribers (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  email_normalized TEXT NOT NULL UNIQUE,
  verified_at TEXT,
  manage_token TEXT NOT NULL UNIQUE,
  suppressed_at TEXT,
  suppression_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  subscriber_id TEXT NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('opportunity', 'saved_search', 'program')),
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
  cadence TEXT NOT NULL CHECK (cadence IN ('immediate', 'weekly')),
  definition_json TEXT NOT NULL,
  definition_hash TEXT NOT NULL,
  verification_token_hash TEXT NOT NULL,
  verification_expires_at TEXT NOT NULL,
  verified_at TEXT,
  baseline_at TEXT NOT NULL,
  baseline_complete INTEGER NOT NULL DEFAULT 0 CHECK (baseline_complete IN (0, 1)),
  last_evaluated_at TEXT,
  last_notified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (subscriber_id, type, definition_hash)
);

CREATE TABLE IF NOT EXISTS subscription_qualifications (
  subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  opportunity_id TEXT NOT NULL,
  qualified INTEGER NOT NULL CHECK (qualified IN (0, 1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (subscription_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS notification_events (
  id TEXT PRIMARY KEY,
  subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  event_key TEXT NOT NULL,
  event_kind TEXT NOT NULL,
  opportunity_id TEXT,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'suppressed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  provider_message_id TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  UNIQUE (subscription_id, event_key)
);

CREATE TABLE IF NOT EXISTS rate_limits (
  action TEXT NOT NULL,
  client_key TEXT NOT NULL,
  window_started_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  request_count INTEGER NOT NULL,
  PRIMARY KEY (action, client_key)
);

CREATE TABLE IF NOT EXISTS provider_events (
  provider_event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  provider_message_id TEXT,
  received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  subscription_count INTEGER NOT NULL DEFAULT 0,
  matched_event_count INTEGER NOT NULL DEFAULT 0,
  attempted_count INTEGER NOT NULL DEFAULT 0,
  delivered_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS subscriptions_active_idx
  ON subscriptions(active, cadence, last_evaluated_at);
CREATE INDEX IF NOT EXISTS events_dispatch_idx
  ON notification_events(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS events_provider_message_idx
  ON notification_events(provider_message_id);
CREATE INDEX IF NOT EXISTS subscribers_manage_idx
  ON subscribers(manage_token);
CREATE INDEX IF NOT EXISTS subscribers_suppressed_idx
  ON subscribers(suppressed_at);

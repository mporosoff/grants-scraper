-- Bound daily evaluation across invocations and retain privacy-safe scheduler progress.
ALTER TABLE subscriptions ADD COLUMN evaluation_cursor_at TEXT;
ALTER TABLE subscriptions ADD COLUMN evaluation_cursor_event_id TEXT;
ALTER TABLE subscriptions ADD COLUMN evaluation_window_started_at TEXT;
ALTER TABLE subscriptions ADD COLUMN evaluation_weekly_window_at TEXT;
ALTER TABLE subscriptions ADD COLUMN evaluation_input_generated_at TEXT;
ALTER TABLE subscriptions ADD COLUMN evaluation_source_generated_at TEXT;

ALTER TABLE notification_events ADD COLUMN evaluation_window_started_at TEXT;
ALTER TABLE notification_events ADD COLUMN weekly_window_at TEXT;

ALTER TABLE evaluation_runs ADD COLUMN stage TEXT NOT NULL DEFAULT 'starting';
ALTER TABLE evaluation_runs ADD COLUMN stage_started_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN last_heartbeat_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN progress_json TEXT;
ALTER TABLE evaluation_runs ADD COLUMN error_code TEXT;
ALTER TABLE evaluation_runs ADD COLUMN evaluation_completed_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN evaluation_window_started_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN weekly_window_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN evaluation_input_generated_at TEXT;
ALTER TABLE evaluation_runs ADD COLUMN evaluation_source_generated_at TEXT;

UPDATE evaluation_runs
SET stage = CASE
      WHEN status = 'running' THEN 'stale_recovery'
      WHEN run_kind = 'daily' AND status LIKE 'completed%' THEN 'completed'
      ELSE COALESCE(stage, 'completed')
    END,
    stage_started_at = COALESCE(stage_started_at, started_at),
    last_heartbeat_at = COALESCE(last_heartbeat_at, completed_at, started_at),
    evaluation_completed_at = CASE
      WHEN run_kind = 'daily' AND status LIKE 'completed%'
        THEN COALESCE(evaluation_completed_at, completed_at)
      ELSE evaluation_completed_at
    END;

CREATE INDEX IF NOT EXISTS subscriptions_evaluation_progress_idx
  ON subscriptions(active, evaluation_window_started_at, evaluation_cursor_at, evaluation_input_generated_at, last_evaluated_at, id);
CREATE INDEX IF NOT EXISTS evaluation_runs_daily_progress_idx
  ON evaluation_runs(run_kind, status, started_at, evaluation_completed_at, evaluation_window_started_at);
CREATE UNIQUE INDEX IF NOT EXISTS evaluation_runs_active_window_claim_idx
  ON evaluation_runs((1))
  WHERE status = 'running' AND run_kind IN ('daily', 'continuation');
CREATE INDEX IF NOT EXISTS notification_events_weekly_window_idx
  ON notification_events(weekly_window_at, evaluation_window_started_at, status, created_at);

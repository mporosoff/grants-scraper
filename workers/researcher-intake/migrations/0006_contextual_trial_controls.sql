-- Restricted trial switches; no public serving or recurring spending allowance.
CREATE TABLE IF NOT EXISTS contextual_trial_controls (
  release_id TEXT PRIMARY KEY,
  cached_enabled INTEGER NOT NULL CHECK(cached_enabled IN (0,1)),
  new_paid_enabled INTEGER NOT NULL CHECK(new_paid_enabled IN (0,1)),
  updated_at TEXT NOT NULL
);

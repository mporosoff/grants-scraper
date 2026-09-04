CREATE TABLE IF NOT EXISTS researcher_submissions (
  submission_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_hash TEXT NOT NULL,
  receipt_token_hash TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  submission_type TEXT NOT NULL CHECK (submission_type IN ('profile_correction', 'new_researcher_nomination')),
  source_surface TEXT NOT NULL CHECK (source_surface IN ('faculty_interests', 'team_match')),
  researcher_id TEXT,
  base_registry_generation TEXT NOT NULL,
  proposed_profile_json TEXT NOT NULL,
  contact_email TEXT,
  submitter_note TEXT,
  privacy_notice_version TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending', 'under_review', 'changes_requested', 'approved', 'publishing', 'published', 'rejected', 'publication_failed', 'superseded')),
  revision INTEGER NOT NULL DEFAULT 1,
  approved_profile_json TEXT,
  administrator_email TEXT,
  administrator_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  approved_at TEXT,
  publication_started_at TEXT,
  published_at TEXT,
  published_commit_sha TEXT,
  published_registry_generation TEXT,
  deployment_result TEXT,
  public_verified_at TEXT,
  failure_code TEXT
);

CREATE INDEX IF NOT EXISTS researcher_submissions_queue_idx
  ON researcher_submissions(state, created_at);
CREATE INDEX IF NOT EXISTS researcher_submissions_researcher_idx
  ON researcher_submissions(researcher_id, created_at);

CREATE TABLE IF NOT EXISTS researcher_submission_transitions (
  transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  actor TEXT NOT NULL,
  revision INTEGER NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (submission_id) REFERENCES researcher_submissions(submission_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS researcher_submission_transitions_submission_idx
  ON researcher_submission_transitions(submission_id, transition_id);

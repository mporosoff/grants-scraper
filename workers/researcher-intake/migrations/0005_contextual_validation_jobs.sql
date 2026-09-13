-- Namespaced finite validation only; no changes to submission/publication tables.
CREATE TABLE contextual_validation_jobs (
  job_id TEXT PRIMARY KEY,
  release_id TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  state TEXT NOT NULL,
  active_slot INTEGER,
  run_id TEXT,
  code_sha TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX contextual_one_active_job
  ON contextual_validation_jobs(active_slot) WHERE active_slot IS NOT NULL;

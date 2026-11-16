CREATE TABLE IF NOT EXISTS catalog_watch (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  slot_at TEXT NOT NULL,
  report_json TEXT NOT NULL,
  publication_problem_since TEXT,
  stale_since TEXT
);

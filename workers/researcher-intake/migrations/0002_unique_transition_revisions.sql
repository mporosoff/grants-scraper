CREATE UNIQUE INDEX IF NOT EXISTS researcher_submission_transitions_revision_idx
  ON researcher_submission_transitions(submission_id, revision);

ALTER TABLE researcher_submissions ADD COLUMN catalog_action TEXT
  CHECK (catalog_action IN ('retired', 'departed', 'inactive'));

CREATE UNIQUE INDEX researcher_active_catalog_removal_idx
  ON researcher_submissions(researcher_id)
  WHERE catalog_action IS NOT NULL AND state NOT IN ('published', 'rejected', 'superseded');

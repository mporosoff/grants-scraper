-- Schema only: installation changes no job, slot, control, or ledger.
-- The sole explicit operator INSERT atomically archives and releases Math.
CREATE TABLE contextual_service_dispositions (
  version TEXT NOT NULL CHECK(version='iteration2-service-slot-disposition-v1'),
  job_id TEXT PRIMARY KEY CHECK(job_id='816dd6d3cb281f5c7ebb1a1f7d166a5a7b37eb7c76885ab4e87e219217e67591'),
  original_row_json TEXT NOT NULL CHECK(original_row_json='{"active_slot":1,"code_sha":"43c109c7616ccefb63122aaf73d3c12f69748901","created_at":"2026-09-21T21:08:56.488Z","job_id":"816dd6d3cb281f5c7ebb1a1f7d166a5a7b37eb7c76885ab4e87e219217e67591","person_id":"","release_id":"f8e9e544e08db863f79eb72737cb5434ea71b150c7ebbc00f5314452207074a2","result_json":null,"run_id":"35655451108","scope_id":"341997","state":"in_progress","updated_at":"2026-09-21T21:09:17.140Z"}'),
  evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND json_extract(evidence_json,'$.version')='iteration2-service-slot-disposition-v1' AND json_extract(evidence_json,'$.plan_sha256')='658a61eb37535b7d5f8ea9cc05e09498b605aea7bb647561f3cae0bc4edda3e7'),
  evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64 AND evidence_sha256 NOT GLOB '*[^a-f0-9]*'),
  applied_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TRIGGER contextual_service_disposition_install
AFTER INSERT ON contextual_service_dispositions
BEGIN
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM contextual_validation_jobs WHERE
    job_id='816dd6d3cb281f5c7ebb1a1f7d166a5a7b37eb7c76885ab4e87e219217e67591' AND
    release_id='f8e9e544e08db863f79eb72737cb5434ea71b150c7ebbc00f5314452207074a2' AND
    scope_id='341997' AND
    person_id='' AND
    state='in_progress' AND
    active_slot=1 AND
    run_id='35655451108' AND
    code_sha='43c109c7616ccefb63122aaf73d3c12f69748901' AND
    result_json IS NULL AND
    created_at='2026-09-21T21:08:56.488Z' AND
    updated_at='2026-09-21T21:09:17.140Z') THEN RAISE(ABORT,'exact_math_service_row_required') END;
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM contextual_trial_controls
    WHERE release_id='f8e9e544e08db863f79eb72737cb5434ea71b150c7ebbc00f5314452207074a2' AND cached_enabled=1 AND new_paid_enabled=0)
    THEN RAISE(ABORT,'service_disposition_paid_must_be_off') END;
  SELECT CASE WHEN (SELECT count(*) FROM contextual_validation_jobs WHERE active_slot IS NOT NULL)<>1
    THEN RAISE(ABORT,'service_disposition_exclusive_slot_required') END;
  UPDATE contextual_validation_jobs SET state='recovery_required',active_slot=NULL
    WHERE job_id='816dd6d3cb281f5c7ebb1a1f7d166a5a7b37eb7c76885ab4e87e219217e67591' AND
    release_id='f8e9e544e08db863f79eb72737cb5434ea71b150c7ebbc00f5314452207074a2' AND
    scope_id='341997' AND
    person_id='' AND
    state='in_progress' AND
    active_slot=1 AND
    run_id='35655451108' AND
    code_sha='43c109c7616ccefb63122aaf73d3c12f69748901' AND
    result_json IS NULL AND
    created_at='2026-09-21T21:08:56.488Z' AND
    updated_at='2026-09-21T21:09:17.140Z';
END;
CREATE TRIGGER contextual_service_disposition_immutable_update
BEFORE UPDATE ON contextual_service_dispositions
BEGIN SELECT RAISE(ABORT,'service_disposition_immutable'); END;
CREATE TRIGGER contextual_service_disposition_immutable_delete
BEFORE DELETE ON contextual_service_dispositions
BEGIN SELECT RAISE(ABORT,'service_disposition_immutable'); END;

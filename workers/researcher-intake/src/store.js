function parseJson(value, fallback = null) {
  try { return JSON.parse(String(value || "")); } catch { return fallback; }
}

export class ResearcherSubmissionStore {
  constructor(db) { this.db = db; }

  async byIdempotencyKey(key) {
    return this.db.prepare("SELECT * FROM researcher_submissions WHERE idempotency_key = ?").bind(key).first();
  }

  async byId(id) {
    return this.db.prepare("SELECT * FROM researcher_submissions WHERE submission_id = ?").bind(id).first();
  }

  async create(row) {
    const statements = [
      this.db.prepare(`INSERT INTO researcher_submissions (
        submission_id, idempotency_key, payload_hash, receipt_token_hash, schema_version,
        submission_type, source_surface, researcher_id, base_registry_generation,
        proposed_profile_json, contact_email, submitter_note, privacy_notice_version,
        state, revision, created_at, updated_at
      ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?)`)
        .bind(
          row.submissionId, row.idempotencyKey, row.payloadHash, row.receiptTokenHash,
          row.submissionType, row.sourceSurface, row.researcherId,
          row.baseRegistryGeneration, JSON.stringify(row.proposedProfile),
          row.contactEmail || null, row.submitterNote || null, row.privacyNoticeVersion,
          row.createdAt, row.createdAt,
        ),
      this.db.prepare(`INSERT INTO researcher_submission_transitions
        (submission_id, from_state, to_state, actor, revision, reason, created_at)
        VALUES (?, NULL, 'pending', 'public_submitter', 1, NULL, ?)`)
        .bind(row.submissionId, row.createdAt),
    ];
    await this.db.batch(statements);
    return this.byId(row.submissionId);
  }

  async publicStatus(id, receiptTokenHash) {
    return this.db.prepare(`SELECT submission_id, submission_type, source_surface, state, revision,
      created_at, updated_at, published_at, published_commit_sha, published_registry_generation,
      deployment_result, public_verified_at, failure_code
      FROM researcher_submissions WHERE submission_id = ? AND receipt_token_hash = ?`)
      .bind(id, receiptTokenHash).first();
  }

  async listQueue(limit = 100) {
    const result = await this.db.prepare(`SELECT submission_id, submission_type, source_surface,
      researcher_id, proposed_profile_json, base_registry_generation, state, revision,
      created_at, updated_at, failure_code
      FROM researcher_submissions
      WHERE state NOT IN ('published', 'rejected', 'superseded')
      ORDER BY created_at ASC LIMIT ?`).bind(limit).all();
    return (result.results || []).map(row => ({ ...row, proposed_profile: parseJson(row.proposed_profile_json, {}) }));
  }

  async adminDetail(id) {
    const row = await this.byId(id);
    if (!row) return null;
    const transitions = await this.db.prepare(`SELECT from_state, to_state, actor, revision, reason, created_at
      FROM researcher_submission_transitions WHERE submission_id = ? ORDER BY transition_id ASC`).bind(id).all();
    return {
      ...row,
      proposed_profile: parseJson(row.proposed_profile_json, {}),
      approved_profile: parseJson(row.approved_profile_json, null),
      transitions: transitions.results || [],
    };
  }

  async transition({ id, fromStates, toState, expectedRevision, actor, reason, approvedProfile, now }) {
    const current = await this.byId(id);
    if (!current || current.revision !== expectedRevision || !fromStates.includes(current.state)) return null;
    const placeholders = fromStates.map(() => "?").join(", ");
    const nextRevision = expectedRevision + 1;
    const update = this.db.prepare(`UPDATE researcher_submissions SET
      state = ?, revision = ?, updated_at = ?, administrator_email = ?, administrator_reason = ?,
      approved_profile_json = COALESCE(?, approved_profile_json),
      approved_at = CASE WHEN ? = 'approved' THEN ? ELSE approved_at END,
      failure_code = CASE WHEN ? = 'publication_failed' THEN failure_code ELSE NULL END
      WHERE submission_id = ? AND revision = ? AND state IN (${placeholders})`)
      .bind(
        toState, nextRevision, now, actor, reason || null,
        approvedProfile ? JSON.stringify(approvedProfile) : null,
        toState, now, toState, id, expectedRevision, ...fromStates,
      );
    const result = await update.run();
    if (Number(result.meta?.changes || 0) !== 1) return null;
    await this.db.prepare(`INSERT INTO researcher_submission_transitions
      (submission_id, from_state, to_state, actor, revision, reason, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)`)
      .bind(id, current.state, toState, actor, nextRevision, reason || null, now).run();
    return this.byId(id);
  }

  async markPublishing(id, expectedRevision, actor, now) {
    const row = await this.transition({
      id, fromStates: ["approved", "publication_failed"], toState: "publishing",
      expectedRevision, actor, reason: "Registry-only publication dispatched", now,
    });
    if (row) await this.db.prepare("UPDATE researcher_submissions SET publication_started_at = ? WHERE submission_id = ?").bind(now, id).run();
    return row;
  }

  async markPublished(id, values, now) {
    const current = await this.byId(id);
    if (!current || current.state !== "publishing" || current.revision !== values.expectedRevision) return null;
    const nextRevision = current.revision + 1;
    const result = await this.db.prepare(`UPDATE researcher_submissions SET state = 'published', revision = ?, updated_at = ?,
      published_at = ?, published_commit_sha = ?, published_registry_generation = ?, deployment_result = ?,
      public_verified_at = ?, failure_code = NULL, contact_email = NULL, submitter_note = NULL
      WHERE submission_id = ? AND state = 'publishing' AND revision = ?`)
      .bind(nextRevision, now, now, values.commitSha, values.registryGeneration, values.deploymentResult, values.verifiedAt, id, current.revision).run();
    if (Number(result.meta?.changes || 0) !== 1) return null;
    await this.db.prepare(`INSERT INTO researcher_submission_transitions
      (submission_id, from_state, to_state, actor, revision, reason, created_at)
      VALUES (?, 'publishing', 'published', 'publication_workflow', ?, ?, ?)`)
      .bind(id, nextRevision, values.commitSha, now).run();
    return this.byId(id);
  }

  async markPublicationFailed(id, values, now) {
    const current = await this.byId(id);
    if (!current || current.state !== "publishing" || current.revision !== values.expectedRevision) return null;
    const nextRevision = current.revision + 1;
    const result = await this.db.prepare(`UPDATE researcher_submissions SET state = 'publication_failed', revision = ?,
      updated_at = ?, failure_code = ?, deployment_result = ? WHERE submission_id = ? AND state = 'publishing' AND revision = ?`)
      .bind(nextRevision, now, values.failureCode, values.deploymentResult || null, id, current.revision).run();
    if (Number(result.meta?.changes || 0) !== 1) return null;
    await this.db.prepare(`INSERT INTO researcher_submission_transitions
      (submission_id, from_state, to_state, actor, revision, reason, created_at)
      VALUES (?, 'publishing', 'publication_failed', 'publication_workflow', ?, ?, ?)`)
      .bind(id, nextRevision, values.failureCode, now).run();
    return this.byId(id);
  }

  async cleanup(now, rejectedRetentionDays, contactRetentionDays) {
    const rejectedCutoff = new Date(new Date(now).getTime() - rejectedRetentionDays * 86400000).toISOString();
    const contactCutoff = new Date(new Date(now).getTime() - contactRetentionDays * 86400000).toISOString();
    const results = await this.db.batch([
      this.db.prepare(`DELETE FROM researcher_submissions
        WHERE state IN ('rejected', 'superseded') AND updated_at < ?`).bind(rejectedCutoff),
      this.db.prepare(`UPDATE researcher_submissions SET contact_email = NULL, submitter_note = NULL
        WHERE contact_email IS NOT NULL AND updated_at < ?`).bind(contactCutoff),
    ]);
    return results.reduce((sum, result) => sum + Number(result.meta?.changes || 0), 0);
  }
}

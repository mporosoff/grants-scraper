function parseJson(value, fallback = null) {
  try { return JSON.parse(String(value || "")); } catch { return fallback; }
}

export class ResearcherSubmissionStore {
  constructor(db) { this.db = db; }

  auditStatement({ id, fromState, toState, actor, revision, reason, now }) {
    return this.db.prepare(`INSERT INTO researcher_submission_transitions
      (submission_id, from_state, to_state, actor, revision, reason, created_at)
      SELECT ?, ?, ?, ?, ?, ?, ?
      WHERE EXISTS (
        SELECT 1 FROM researcher_submissions
        WHERE submission_id = ? AND state = ? AND revision = ? AND updated_at = ?
      )`)
      .bind(
        id, fromState, toState, actor, revision, reason || null, now,
        id, toState, revision, now,
      );
  }

  async commitStateChange(update, audit, id) {
    const [updateResult, auditResult] = await this.db.batch([update, audit]);
    const updated = Number(updateResult.meta?.changes || 0);
    const audited = Number(auditResult.meta?.changes || 0);
    if (updated === 0 && audited === 0) return null;
    if (updated !== 1 || audited !== 1) throw new Error("Researcher submission state and audit history diverged.");
    return this.byId(id);
  }

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

  async transition({
    id, fromStates, toState, expectedRevision, actor, reason, approvedProfile,
    publicationStartedAt = null, now,
  }) {
    const current = await this.byId(id);
    if (!current || current.revision !== expectedRevision || !fromStates.includes(current.state)) return null;
    const placeholders = fromStates.map(() => "?").join(", ");
    const nextRevision = expectedRevision + 1;
    const update = this.db.prepare(`UPDATE researcher_submissions SET
      state = ?, revision = ?, updated_at = ?, administrator_email = ?, administrator_reason = ?,
      approved_profile_json = COALESCE(?, approved_profile_json),
      approved_at = CASE WHEN ? = 'approved' THEN ? ELSE approved_at END,
      publication_started_at = COALESCE(?, publication_started_at),
      failure_code = CASE WHEN ? = 'publication_failed' THEN failure_code ELSE NULL END,
      publication_target_pr_url = CASE WHEN ? = 'publishing' THEN NULL ELSE publication_target_pr_url END,
      publication_target_registry_generation = CASE WHEN ? = 'publishing' THEN NULL ELSE publication_target_registry_generation END
      WHERE submission_id = ? AND revision = ? AND state IN (${placeholders})`)
      .bind(
        toState, nextRevision, now, actor, reason || null,
        approvedProfile ? JSON.stringify(approvedProfile) : null,
        toState, now, publicationStartedAt, toState, toState, toState,
        id, expectedRevision, ...fromStates,
      );
    const audit = this.auditStatement({
      id, fromState: current.state, toState, actor, revision: nextRevision, reason, now,
    });
    return this.commitStateChange(update, audit, id);
  }

  async markPublishing(id, expectedRevision, actor, now, approvedProfile = null, reason = "") {
    const row = await this.transition({
      id, fromStates: ["approved", "publication_failed"], toState: "publishing",
      expectedRevision, actor, reason: reason || "Registry-only publication dispatched",
      approvedProfile, publicationStartedAt: now, now,
    });
    return row;
  }

  async recordPublicationTarget(id, values, now) {
    const current = await this.byId(id);
    if (current?.state === "publishing"
        && current.revision === values.expectedRevision
        && current.publication_target_pr_url === values.prUrl
        && current.publication_target_registry_generation === values.registryGeneration) {
      return current;
    }
    if (!current || current.state !== "publishing" || current.revision !== values.expectedRevision
        || current.publication_target_pr_url || current.publication_target_registry_generation) return null;
    const result = await this.db.prepare(`UPDATE researcher_submissions SET
      publication_target_pr_url = ?, publication_target_registry_generation = ?, updated_at = ?
      WHERE submission_id = ? AND state = 'publishing' AND revision = ?
        AND publication_target_pr_url IS NULL AND publication_target_registry_generation IS NULL`)
      .bind(values.prUrl, values.registryGeneration, now, id, values.expectedRevision).run();
    if (Number(result.meta?.changes || 0) === 1) return this.byId(id);
    const raced = await this.byId(id);
    return raced?.state === "publishing"
      && raced.revision === values.expectedRevision
      && raced.publication_target_pr_url === values.prUrl
      && raced.publication_target_registry_generation === values.registryGeneration
      ? raced : null;
  }

  async rebase({ id, expectedRevision, nextGeneration, actor, reason, now }) {
    const fromStates = ["pending", "under_review", "changes_requested", "approved", "publication_failed"];
    const current = await this.byId(id);
    if (!current || current.revision !== expectedRevision || !fromStates.includes(current.state)
        || current.base_registry_generation === nextGeneration) return null;
    const placeholders = fromStates.map(() => "?").join(", ");
    const nextRevision = expectedRevision + 1;
    const auditReason = reason || `Rebased from registry ${current.base_registry_generation} to ${nextGeneration}; administrator re-review required`;
    const update = this.db.prepare(`UPDATE researcher_submissions SET
      state = 'under_review', base_registry_generation = ?, revision = ?, updated_at = ?,
      administrator_email = ?, administrator_reason = ?, approved_profile_json = NULL, approved_at = NULL,
      publication_started_at = NULL, publication_target_pr_url = NULL,
      publication_target_registry_generation = NULL, failure_code = NULL, deployment_result = NULL
      WHERE submission_id = ? AND revision = ? AND state IN (${placeholders})
        AND base_registry_generation <> ?`)
      .bind(nextGeneration, nextRevision, now, actor, auditReason, id, expectedRevision, ...fromStates, nextGeneration);
    const audit = this.auditStatement({
      id, fromState: current.state, toState: "under_review", actor,
      revision: nextRevision, reason: auditReason, now,
    });
    return this.commitStateChange(update, audit, id);
  }

  async markPublished(id, values, now) {
    const current = await this.byId(id);
    if (current?.state === "published"
        && current.revision === values.expectedRevision + 1
        && current.published_commit_sha === values.commitSha
        && current.published_registry_generation === values.registryGeneration) {
      return current;
    }
    if (!current || current.state !== "publishing" || current.revision !== values.expectedRevision) return null;
    const nextRevision = current.revision + 1;
    const update = this.db.prepare(`UPDATE researcher_submissions SET state = 'published', revision = ?, updated_at = ?,
      published_at = ?, published_commit_sha = ?, published_registry_generation = ?, deployment_result = ?,
      public_verified_at = ?, failure_code = NULL, contact_email = NULL, submitter_note = NULL
      WHERE submission_id = ? AND state = 'publishing' AND revision = ?`)
      .bind(nextRevision, now, now, values.commitSha, values.registryGeneration, values.deploymentResult, values.verifiedAt, id, current.revision);
    const audit = this.auditStatement({
      id, fromState: "publishing", toState: "published", actor: values.actor || "publication_workflow",
      revision: nextRevision, reason: values.commitSha, now,
    });
    return this.commitStateChange(update, audit, id);
  }

  async markPublicationFailed(id, values, now) {
    const current = await this.byId(id);
    if (!current || current.state !== "publishing" || current.revision !== values.expectedRevision) return null;
    const nextRevision = current.revision + 1;
    const update = this.db.prepare(`UPDATE researcher_submissions SET state = 'publication_failed', revision = ?,
      updated_at = ?, failure_code = ?, deployment_result = ? WHERE submission_id = ? AND state = 'publishing' AND revision = ?`)
      .bind(nextRevision, now, values.failureCode, values.deploymentResult || null, id, current.revision);
    const audit = this.auditStatement({
      id, fromState: "publishing", toState: "publication_failed", actor: values.actor || "publication_workflow",
      revision: nextRevision, reason: values.failureCode, now,
    });
    return this.commitStateChange(update, audit, id);
  }

  async cleanup(now, rejectedRetentionDays, contactRetentionDays) {
    const rejectedCutoff = new Date(new Date(now).getTime() - rejectedRetentionDays * 86400000).toISOString();
    const contactCutoff = new Date(new Date(now).getTime() - contactRetentionDays * 86400000).toISOString();
    const results = await this.db.batch([
      this.db.prepare(`DELETE FROM researcher_submissions
        WHERE state IN ('rejected', 'superseded') AND updated_at < ?`).bind(rejectedCutoff),
      this.db.prepare(`UPDATE researcher_submissions SET contact_email = NULL, submitter_note = NULL
        WHERE (contact_email IS NOT NULL OR submitter_note IS NOT NULL) AND created_at < ?`).bind(contactCutoff),
    ]);
    return results.reduce((sum, result) => sum + Number(result.meta?.changes || 0), 0);
  }
}

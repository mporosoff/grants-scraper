import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { enforceClaimContinuity, enforceSubmittedRelationship, validateAdminProfile, validateSubmission } from "../../workers/researcher-intake/src/contract.js";
import { createHandler, reconcilePublication, seedApprovedProfile } from "../../workers/researcher-intake/src/index.js";
import { ResearcherSubmissionStore } from "../../workers/researcher-intake/src/store.js";

const root = new URL("../../", import.meta.url);
const [workerSource, storeSource, migration, transitionMigration, targetMigration, workflow, refreshWorkflow, deploymentWorkflow, wrangler] = await Promise.all([
  readFile(new URL("workers/researcher-intake/src/index.js", root), "utf8"),
  readFile(new URL("workers/researcher-intake/src/store.js", root), "utf8"),
  readFile(new URL("workers/researcher-intake/migrations/0001_researcher_submissions.sql", root), "utf8"),
  readFile(new URL("workers/researcher-intake/migrations/0002_unique_transition_revisions.sql", root), "utf8"),
  readFile(new URL("workers/researcher-intake/migrations/0003_publication_recovery_target.sql", root), "utf8"),
  readFile(new URL(".github/workflows/publish-researcher-registry.yml", root), "utf8"),
  readFile(new URL(".github/workflows/refresh-opportunities.yml", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-researcher-intake.yml", root), "utf8"),
  readFile(new URL("workers/researcher-intake/wrangler.jsonc", root), "utf8"),
]);

function submission(overrides = {}) {
  return {
    schema_version: 1,
    idempotency_key: "12345678-1234-4234-8234-123456789abc",
    submission_type: "new_researcher_nomination",
    source_surface: "faculty_interests",
    researcher_id: null,
    base_registry_generation: "a".repeat(64),
    proposed_profile: {
      display_name: "Ada Lovelace", orcid_id: "0000-0002-1825-0097", home_unit: "External",
      relationship_note: "External collaborator", research_summary: "Computational methods.",
      claims: ["Analytical engines"], source_urls: ["https://example.edu/ada"],
    },
    submitter: { contact_email: "ada@example.edu", note: "Review" },
    consent: { submitted_for_admin_review: true, privacy_notice_version: "2026-09-03" },
    ...overrides,
  };
}

class MemoryStore {
  constructor() { this.rows = new Map(); }
  async byIdempotencyKey(key) { return [...this.rows.values()].find(row => row.idempotency_key === key) || null; }
  async create(input) {
    const row = {
      submission_id: input.submissionId, idempotency_key: input.idempotencyKey, payload_hash: input.payloadHash,
      receipt_token_hash: input.receiptTokenHash, submission_type: input.submissionType,
      source_surface: input.sourceSurface, researcher_id: input.researcherId,
      base_registry_generation: input.baseRegistryGeneration, state: "pending", revision: 1,
      created_at: input.createdAt, updated_at: input.createdAt,
    };
    this.rows.set(row.submission_id, row);
    return row;
  }
}

function environment() {
  return {
    PUBLIC_APP_ORIGIN: "https://mporosoff.github.io",
    RECEIPT_TOKEN_SECRET: "test-secret-that-is-long-and-random-enough",
    SUBMISSION_RATE_LIMITER: { async limit() { return { success: true }; } },
  };
}

function base64url(value) {
  return Buffer.from(typeof value === "string" ? value : JSON.stringify(value)).toString("base64url");
}

class D1Statement {
  constructor(database, sql, values = []) { this.database = database; this.sql = sql; this.values = values; }
  bind(...values) { return new D1Statement(this.database, this.sql, values); }
  execute() {
    const result = this.database.prepare(this.sql).run(...this.values);
    return { success: true, meta: { changes: Number(result.changes || 0) } };
  }
  async run() { return this.execute(); }
  async first() { return this.database.prepare(this.sql).get(...this.values) || null; }
  async all() { return { results: this.database.prepare(this.sql).all(...this.values) }; }
}

class SqliteD1 {
  constructor(database) { this.database = database; }
  prepare(sql) { return new D1Statement(this.database, sql); }
  async batch(statements) {
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const results = statements.map(statement => statement.execute());
      this.database.exec("COMMIT");
      return results;
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }
}

test("server contract rejects unknown fields and identity contradictions", () => {
  assert.throws(() => validateSubmission({ ...submission(), browser_local_team: ["private"] }), /unsupported fields/);
  assert.throws(() => validateSubmission({ ...submission(), researcher_id: "urh-000001" }), /cannot claim an existing identity/);
  const correction = validateSubmission({ ...submission(), submission_type: "profile_correction", researcher_id: "urh-000001" });
  assert.equal(correction.researcher_id, "urh-000001");
});

test("administrator policy cannot elevate hidden or inactive researchers automatically", () => {
  const base = {
    display_name: "Ada Lovelace", sort_name: "Lovelace, Ada", aliases: [], orcid_id: "",
    home_unit: "External", relationship: "external_collaborator", pool_visibility: "hidden",
    auto_proposable: true, status: "active", research_summary: "", source_urls: ["https://example.edu/ada"],
    source_checked_date: "2026-09-03", claims: [],
  };
  assert.throws(() => validateAdminProfile(base, ""), /cannot be automatically proposed/);
  const external = { ...base, auto_proposable: false, relationship: "hajim_core_faculty" };
  assert.throws(
    () => enforceSubmittedRelationship(validateAdminProfile(external, ""), { relationship_note: "External collaborator" }),
    /cannot be published as core or internal faculty/,
  );
  const dateProfile = { ...base, auto_proposable: false };
  assert.throws(() => validateAdminProfile({ ...dateProfile, source_checked_date: "2026-02-30" }, ""), /valid YYYY-MM-DD calendar date/);
  assert.throws(() => validateAdminProfile({
    ...dateProfile,
    claims: [{
      claim_id: "", revision: 1, status: "active", label: "Analytical engines",
      category: "Computational methods", categories: ["Computational methods"], type: "Capability",
      evidence: "Published analytical engine research.", source_urls: ["https://example.edu/ada"],
      verified_on: "2026-99-99", evidence_level: "administrator_reviewed", legacy_claim_ids: [],
    }],
  }, ""), /valid YYYY-MM-DD calendar date/);
  const validClaim = {
    claim_id: "", revision: 1, status: "active", label: "Analytical engines",
    category: "Computational methods", categories: ["Computational methods"], type: "Capability",
    evidence: "Published analytical engine research.", source_urls: ["https://example.edu/ada"],
    verified_on: "2026-09-03", evidence_level: "administrator_reviewed", legacy_claim_ids: [],
  };
  for (const revision of [0, -1, 1.5, "1"]) {
    assert.throws(
      () => validateAdminProfile({ ...dateProfile, claims: [{ ...validClaim, revision }] }, ""),
      /positive integer/,
    );
  }
  assert.throws(
    () => validateAdminProfile({
      ...dateProfile, claims: [{ ...validClaim, claim_id: "urh-999999-c001" }],
    }, ""),
    /cannot preassign claim identifiers/,
  );
  assert.throws(
    () => validateAdminProfile({ ...dateProfile, claims: [{ ...validClaim, legacy_claim_ids: "ada:CV001" }] }, ""),
    /bounded list of globally unique strings/,
  );
  assert.throws(
    () => validateAdminProfile({
      ...dateProfile,
      claims: [
        { ...validClaim, legacy_claim_ids: ["ada:CV001"] },
        { ...validClaim, label: "Symbolic computing", legacy_claim_ids: ["ADA:cv001"] },
      ],
    }, ""),
    /globally unique strings/,
  );
  assert.throws(
    () => validateAdminProfile({ ...dateProfile, claims: [{ ...validClaim, legacy_claim_ids: ["ada:CV001"] }] }, "", ["ADA:cv001"]),
    /globally unique strings/,
  );
  assert.throws(
    () => validateAdminProfile({ ...dateProfile, orcid_id: "0000-0002-1825-0097", claims: [] }, "", [], ["0000-0002-1825-0097"]),
    /already belongs to another researcher/,
  );
});

test("correction approval defaults apply submitted additions and retirements", () => {
  const current = {
    name: "Ada Lovelace", aliases: [], orcid_id: "0000-0002-1825-0097", home_unit: "Computing",
    relationship: "internal_affiliated_researcher", pool_visibility: "institution",
    auto_proposable: true, status: "active", research_summary: "Existing summary",
    source_urls: ["https://example.edu/old"],
    claims: [
      {
        claim_id: "urh-000001-c001", revision: 1, status: "active", label: "Analytical engines",
        category: "Computing", categories: ["Computing"], type: "Capability",
        evidence: "Published analytical engine research.", source_urls: ["https://example.edu/old"],
        evidence_level: "direct", legacy_claim_ids: ["ada-lovelace:CV001"],
      },
      {
        claim_id: "urh-000001-c002", revision: 1, status: "retired", label: "Formal logic",
        category: "Computing", categories: ["Computing"], type: "Capability",
        evidence: "Published formal logic research.", source_urls: ["https://example.edu/old"],
        evidence_level: "direct", legacy_claim_ids: [],
      },
    ],
  };
  const seeded = seedApprovedProfile({
    current_profile: current,
    proposed_profile: {
      display_name: "Ada Lovelace", orcid_id: "", home_unit: "Computing",
      research_summary: "Updated summary", claims: ["Formal logic", "Program synthesis"],
      source_urls: ["https://example.edu/new"],
    },
  }, "2026-09-03");
  assert.deepEqual(
    seeded.claims.map(claim => [claim.label, claim.status]),
    [["Analytical engines", "retired"], ["Formal logic", "active"], ["Program synthesis", "active"]],
  );
  assert.deepEqual(seeded.claims[2].categories, ["Interdisciplinary research"]);
  assert.deepEqual(seeded.claims[2].source_urls, ["https://example.edu/new"]);
  assert.equal(seeded.orcid_id, "");
  const cleared = seedApprovedProfile({
    current_profile: current,
    proposed_profile: {
      display_name: "Ada Lovelace", orcid_id: "", home_unit: "Computing",
      research_summary: "", claims: ["Formal logic"], source_urls: ["https://example.edu/new"],
    },
  }, "2026-09-03");
  assert.equal(cleared.orcid_id, "");
  assert.equal(cleared.research_summary, "");
  const validated = validateAdminProfile(seeded, "urh-000001");
  assert.equal(validated.claims[2].claim_id, "");
  assert.doesNotThrow(() => enforceClaimContinuity(validated, current));
  assert.throws(
    () => enforceClaimContinuity({ ...validated, claims: validated.claims.slice(1) }, current),
    /marked retired instead of being removed/,
  );
  assert.throws(
    () => enforceClaimContinuity({
      ...validated,
      claims: validated.claims.map((claim, index) => index === 2 ? { ...claim, claim_id: "urh-000001-c999" } : claim),
    }, current),
    /New claims must leave the claim identifier empty/,
  );
  assert.throws(
    () => enforceClaimContinuity({
      ...validated,
      claims: validated.claims.map((claim, index) => index === 0 ? { ...claim, legacy_claim_ids: [] } : claim),
    }, current),
    /remain attached to their original claim/,
  );
  assert.throws(
    () => enforceClaimContinuity({
      ...validated,
      claims: validated.claims.map((claim, index) => index === 2 ? { ...claim, legacy_claim_ids: ["invented:CV001"] } : claim),
    }, current),
    /New claims cannot assign legacy claim identifiers/,
  );
});

test("public creation is rate bounded, idempotent, and returns the same private receipt", async () => {
  const store = new MemoryStore();
  const handler = createHandler({ storeFactory: () => store, now: () => new Date("2026-09-03T12:00:00Z") });
  const request = () => new Request("https://worker.example/submissions", {
    method: "POST", headers: { Origin: "https://mporosoff.github.io", "Content-Type": "application/json", "CF-Connecting-IP": "192.0.2.1" },
    body: JSON.stringify(submission()),
  });
  const first = await handler(request(), environment(), { waitUntil() {} });
  const firstBody = await first.json();
  assert.equal(first.status, 201);
  assert.match(firstBody.submission_id, /^rs_[a-f0-9]{24}$/);
  assert.match(firstBody.status_url, /\?token=[a-f0-9]{64}$/);
  const second = await handler(request(), environment(), { waitUntil() {} });
  const secondBody = await second.json();
  assert.equal(second.status, 200);
  assert.equal(secondBody.submission_id, firstBody.submission_id);
  assert.equal(secondBody.status_url, firstBody.status_url);
  assert.equal(store.rows.size, 1);
});

test("concurrent idempotent inserts recover the winning receipt and reject different content", async () => {
  class ConcurrentInsertStore extends MemoryStore {
    constructor(winningPayloadHash = null) { super(); this.winningPayloadHash = winningPayloadHash; }
    async create(input) {
      await super.create({ ...input, payloadHash: this.winningPayloadHash || input.payloadHash });
      throw new Error("UNIQUE constraint failed: researcher_submissions.idempotency_key");
    }
  }
  const request = () => new Request("https://worker.example/submissions", {
    method: "POST", headers: { Origin: "https://mporosoff.github.io", "Content-Type": "application/json", "CF-Connecting-IP": "192.0.2.1" },
    body: JSON.stringify(submission()),
  });
  const matchingStore = new ConcurrentInsertStore();
  const matchingHandler = createHandler({ storeFactory: () => matchingStore, now: () => new Date("2026-09-03T12:00:00Z") });
  const recovered = await matchingHandler(request(), environment(), { waitUntil() {} });
  const recoveredBody = await recovered.json();
  assert.equal(recovered.status, 200);
  assert.equal(recoveredBody.duplicate, true);
  assert.match(recoveredBody.status_url, new RegExp(`/status/${recoveredBody.submission_id}\\?token=[a-f0-9]{64}$`));

  const conflictingStore = new ConcurrentInsertStore("f".repeat(64));
  const conflictingHandler = createHandler({ storeFactory: () => conflictingStore, now: () => new Date("2026-09-03T12:00:00Z") });
  const conflict = await conflictingHandler(request(), environment(), { waitUntil() {} });
  assert.equal(conflict.status, 409);
  assert.equal((await conflict.json()).error.code, "idempotency_conflict");
});

test("accepted local development origins receive matching CORS headers", async () => {
  const handler = createHandler({ storeFactory: () => new MemoryStore() });
  for (const origin of ["http://localhost:8000", "http://127.0.0.1:5500"]) {
    const response = await handler(new Request("https://worker.example/submissions", {
      method: "OPTIONS", headers: { Origin: origin },
    }), environment());
    assert.equal(response.status, 204);
    assert.equal(response.headers.get("access-control-allow-origin"), origin);
    assert.equal(response.headers.get("vary"), "Origin");
  }
});

test("admin and publication routes fail closed without their independent credentials", async () => {
  const handler = createHandler({ storeFactory: () => new MemoryStore() });
  const admin = await handler(new Request("https://worker.example/admin"), environment());
  assert.equal(admin.status, 403);
  const publication = await handler(new Request("https://worker.example/internal/publications/rs_aaaaaaaaaaaaaaaaaaaaaaaa"), environment());
  assert.equal(publication.status, 403);
});

test("administrator access cryptographically verifies issuer, audience, expiry, and email", async () => {
  const pair = await crypto.subtle.generateKey({
    name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256",
  }, true, ["sign", "verify"]);
  const publicKey = await crypto.subtle.exportKey("jwk", pair.publicKey);
  publicKey.kid = "test-access-key";
  publicKey.alg = "RS256";
  const header = base64url({ alg: "RS256", kid: publicKey.kid });
  const payload = base64url({
    iss: "https://funding-finder.cloudflareaccess.com", aud: ["researcher-admin-aud"],
    exp: Math.floor(Date.now() / 1000) + 300, email: "admin@example.edu",
  });
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5", pair.privateKey, new TextEncoder().encode(`${header}.${payload}`),
  );
  const assertion = `${header}.${payload}.${Buffer.from(signature).toString("base64url")}`;
  const handler = createHandler({
    storeFactory: () => new MemoryStore(),
    fetchImpl: async url => {
      assert.equal(url, "https://funding-finder.cloudflareaccess.com/cdn-cgi/access/certs");
      return new Response(JSON.stringify({ keys: [publicKey] }), { status: 200 });
    },
  });
  const env = {
    ...environment(), ADMIN_EMAILS: "admin@example.edu",
    ACCESS_TEAM_DOMAIN: "https://funding-finder.cloudflareaccess.com", ACCESS_AUD: "researcher-admin-aud",
  };
  const response = await handler(new Request("https://worker.example/admin", {
    headers: { "Cf-Access-Jwt-Assertion": assertion },
  }), env);
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Researcher submissions/);
});

test("queue schema, worker config, and publication workflow preserve the registry-only boundary", () => {
  for (const state of ["pending", "under_review", "changes_requested", "approved", "publishing", "published", "rejected", "publication_failed", "superseded"]) {
    assert.match(migration, new RegExp(`'${state}'`));
  }
  assert.match(transitionMigration, /UNIQUE INDEX IF NOT EXISTS researcher_submission_transitions_revision_idx/);
  assert.match(targetMigration, /publication_target_pr_url/);
  assert.match(targetMigration, /publication_target_registry_generation/);
  assert.match(wrangler, /SUBMISSION_RATE_LIMITER/);
  assert.match(workerSource, /cf-access-jwt-assertion/);
  assert.match(workerSource, /crypto\.subtle\.verify/);
  assert.match(workerSource, /cdn-cgi\/access\/certs/);
  assert.match(workerSource, /ACCESS_AUD/);
  assert.match(workerSource, /GITHUB_DISPATCH_TOKEN/);
  assert.doesNotMatch(workerSource, /GITHUB_PUBLICATION_TOKEN/);
  assert.match(deploymentWorkflow, /RESEARCHER_GITHUB_DISPATCH_TOKEN/);
  assert.doesNotMatch(deploymentWorkflow, /RESEARCHER_GITHUB_PUBLICATION_TOKEN/);
  assert.match(deploymentWorkflow, /GITHUB_PUBLICATION_TOKEN:null/);
  assert.match(workflow, /RESEARCHER_GITHUB_PUBLICATION_TOKEN/);
  const publicationGroup = workflow.match(/concurrency:\n  group: ([^\n]+)/)?.[1];
  const refreshGroup = refreshWorkflow.match(/concurrency:\n  group: ([^\n]+)/)?.[1];
  assert.equal(publicationGroup, "funding-finder-coordinated-release");
  assert.equal(publicationGroup, refreshGroup);
  assert.match(workerSource, /submission_id: row\.submission_id, approved_revision: row\.revision/);
  assert.doesNotMatch(workerSource.slice(workerSource.indexOf("client_payload"), workerSource.indexOf("client_payload") + 260), /approved_profile|repository_path|command/);
  assert.match(workflow, /Refuse every non-allowlisted path/);
  assert.match(workflow, /config\/researcher_registry\.json/);
  assert.match(workflow, /Mark the queue record published only after live verification/);
  assert.match(workflow, /Record the recoverable publication target before merge/);
  assert.match(workflow, /\/internal\/publications\/\$SUBMISSION_ID\/target/);
  assert.match(workflow, /Reconcile a failed publication without misreporting a merged change/);
  assert.match(workflow, /if \[ -n "\$merge_sha" \]; then/);
  assert.match(workflow, /queue record remains in publishing state for operator recovery/);
  assert.match(workflow, /gh pr close "\$PUBLICATION_PR_URL"/);
  assert.match(workflow, /--json state,mergeCommit/);
  assert.doesNotMatch(workflow, /--disable-auto|autoMergeRequest/);
  assert.match(workflow, /registry PR is not confirmed closed and safe from a later merge/);
  const failureCallback = workflow.slice(workflow.indexOf("publication-failed.json"));
  assert.match(failureCallback, /for attempt in \$\(seq 1 6\)/);
  assert.match(failureCallback, /curl --fail --silent --show-error/);
  assert.doesNotMatch(failureCallback, /\/internal\/publications\/\$SUBMISSION_ID\/fail" \|\| true/);
  assert.ok(workflow.indexOf('gh pr close "$PUBLICATION_PR_URL"') < workflow.indexOf('[ "$pr_state" != "CLOSED" ]'));
  assert.ok(workflow.indexOf('[ "$pr_state" != "CLOSED" ]') < workflow.indexOf('"$INTAKE_ORIGIN/internal/publications/$SUBMISSION_ID/fail"'));
  assert.ok(workflow.indexOf('echo "url=$pr_url"') < workflow.indexOf("Enable checks-gated auto-merge"));
  assert.ok(workflow.indexOf("Record the recoverable publication target before merge") < workflow.indexOf("Enable checks-gated auto-merge"));
  assert.match(workerSource, /body\.action === "rebase"/);
  assert.match(workerSource, /store\.rebase/);
  assert.match(workerSource, /approved_profile: detail\.approved_profile \|\| seedApprovedProfile/);
  assert.doesNotMatch(workerSource, /function defaultProfile\(/);
  assert.match(workerSource, /\["approved", "publication_failed"\]\.includes\(current\.state\)/);
  assert.match(workerSource, /body\.action === "reconcile_publish"/);
  assert.match(workerSource, /data-action="reconcile_publish"/);
  assert.match(workerSource, /publication_target_registry_generation/);
  assert.match(storeSource, /"changes_requested", "approved", "publication_failed"/);
  assert.doesNotMatch(workflow, /playwright|test:e2e/);
});

test("a failed stale publication can be rebased only through an audited re-review transition", async () => {
  const database = new DatabaseSync(":memory:");
  database.exec("PRAGMA foreign_keys = ON");
  database.exec(migration);
  database.exec(transitionMigration);
  database.exec(targetMigration);
  const store = new ResearcherSubmissionStore(new SqliteD1(database));
  const created = await store.create({
    submissionId: "rs_aaaaaaaaaaaaaaaaaaaaaaaa", idempotencyKey: "12345678-1234-4234-8234-123456789abc",
    payloadHash: "d".repeat(64), receiptTokenHash: "e".repeat(64), submissionType: "new_researcher_nomination",
    sourceSurface: "faculty_interests", researcherId: null, baseRegistryGeneration: "a".repeat(64),
    proposedProfile: submission().proposed_profile, contactEmail: "ada@example.edu", submitterNote: "Review",
    privacyNoticeVersion: "2026-09-03", createdAt: "2026-09-03T12:00:00.000Z",
  });
  const approved = await store.transition({
    id: created.submission_id, fromStates: ["pending"], toState: "approved", expectedRevision: created.revision,
    actor: "admin@example.edu", reason: "Approved", approvedProfile: { display_name: "Ada Lovelace" }, now: "2026-09-03T12:01:00.000Z",
  });
  const publishing = await store.markPublishing(approved.submission_id, approved.revision, "admin@example.edu", "2026-09-03T12:02:00.000Z");
  const failed = await store.markPublicationFailed(publishing.submission_id, {
    expectedRevision: publishing.revision, failureCode: "stale_registry_generation", deploymentResult: "workflow_failed",
  }, "2026-09-03T12:03:00.000Z");
  const rebased = await store.rebase({
    id: failed.submission_id, expectedRevision: failed.revision, nextGeneration: "b".repeat(64),
    actor: "admin@example.edu", reason: "", now: "2026-09-03T12:04:00.000Z",
  });
  assert.equal(rebased.state, "under_review");
  assert.equal(rebased.revision, failed.revision + 1);
  assert.equal(rebased.base_registry_generation, "b".repeat(64));
  assert.equal(rebased.failure_code, null);
  assert.equal(rebased.deployment_result, null);
  assert.equal(rebased.publication_started_at, null);
  assert.equal(rebased.approved_at, null);
  assert.equal(rebased.approved_profile_json, null);
  const transitions = database.prepare("SELECT from_state, to_state, revision, reason FROM researcher_submission_transitions WHERE submission_id = ? ORDER BY transition_id").all(rebased.submission_id);
  assert.deepEqual({ ...transitions.at(-1) }, {
    from_state: "publication_failed", to_state: "under_review", revision: rebased.revision,
    reason: `Rebased from registry ${"a".repeat(64)} to ${"b".repeat(64)}; administrator re-review required`,
  });
  assert.equal(transitions.length, rebased.revision);
  assert.equal(new Set(transitions.map(row => row.revision)).size, transitions.length);
});

test("state updates roll back when their audit insert fails", async () => {
  const database = new DatabaseSync(":memory:");
  database.exec("PRAGMA foreign_keys = ON");
  database.exec(migration);
  database.exec(transitionMigration);
  database.exec(targetMigration);
  const normalStore = new ResearcherSubmissionStore(new SqliteD1(database));
  const created = await normalStore.create({
    submissionId: "rs_bbbbbbbbbbbbbbbbbbbbbbbb", idempotencyKey: "22345678-1234-4234-8234-123456789abc",
    payloadHash: "d".repeat(64), receiptTokenHash: "e".repeat(64), submissionType: "new_researcher_nomination",
    sourceSurface: "faculty_interests", researcherId: null, baseRegistryGeneration: "a".repeat(64),
    proposedProfile: submission().proposed_profile, contactEmail: "ada@example.edu", submitterNote: "Review",
    privacyNoticeVersion: "2026-09-03", createdAt: "2026-09-03T12:00:00.000Z",
  });
  class FailingAuditD1 extends SqliteD1 {
    async batch(statements) {
      this.database.exec("BEGIN IMMEDIATE");
      try {
        statements[0].execute();
        throw new Error("simulated audit failure");
      } finally {
        this.database.exec("ROLLBACK");
      }
    }
  }
  const store = new ResearcherSubmissionStore(new FailingAuditD1(database));
  await assert.rejects(
    store.transition({
      id: created.submission_id, fromStates: ["pending"], toState: "under_review",
      expectedRevision: created.revision, actor: "admin@example.edu", reason: "Review",
      now: "2026-09-03T12:01:00.000Z",
    }),
    /simulated audit failure/,
  );
  const unchanged = database.prepare("SELECT state, revision FROM researcher_submissions WHERE submission_id = ?").get(created.submission_id);
  assert.deepEqual({ ...unchanged }, { state: "pending", revision: 1 });
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM researcher_submission_transitions WHERE submission_id = ?").get(created.submission_id).count, 1);
});

test("an approved record can resume publication or rebase after a transient transition failure", async () => {
  const database = new DatabaseSync(":memory:");
  database.exec("PRAGMA foreign_keys = ON");
  database.exec(migration);
  database.exec(transitionMigration);
  database.exec(targetMigration);
  const normalStore = new ResearcherSubmissionStore(new SqliteD1(database));
  async function approvedRecord(id, key) {
    const created = await normalStore.create({
      submissionId: id, idempotencyKey: key, payloadHash: "d".repeat(64), receiptTokenHash: "e".repeat(64),
      submissionType: "new_researcher_nomination", sourceSurface: "faculty_interests", researcherId: null,
      baseRegistryGeneration: "a".repeat(64), proposedProfile: submission().proposed_profile,
      contactEmail: "ada@example.edu", submitterNote: "Review", privacyNoticeVersion: "2026-09-03",
      createdAt: "2026-09-03T12:00:00.000Z",
    });
    return normalStore.transition({
      id: created.submission_id, fromStates: ["pending"], toState: "approved",
      expectedRevision: created.revision, actor: "admin@example.edu", reason: "Approved",
      approvedProfile: { display_name: "Ada Lovelace" }, now: "2026-09-03T12:01:00.000Z",
    });
  }
  class FailingAuditD1 extends SqliteD1 {
    async batch(statements) {
      this.database.exec("BEGIN IMMEDIATE");
      try {
        statements[0].execute();
        throw new Error("simulated publishing transition failure");
      } finally {
        this.database.exec("ROLLBACK");
      }
    }
  }

  const resumable = await approvedRecord("rs_dddddddddddddddddddddddd", "42345678-1234-4234-8234-123456789abc");
  const failingStore = new ResearcherSubmissionStore(new FailingAuditD1(database));
  await assert.rejects(
    failingStore.markPublishing(resumable.submission_id, resumable.revision, "admin@example.edu", "2026-09-03T12:02:00.000Z"),
    /simulated publishing transition failure/,
  );
  const stillApproved = await normalStore.byId(resumable.submission_id);
  assert.equal(stillApproved.state, "approved");
  assert.equal(stillApproved.revision, resumable.revision);
  const publishing = await normalStore.markPublishing(stillApproved.submission_id, stillApproved.revision, "admin@example.edu", "2026-09-03T12:03:00.000Z");
  assert.equal(publishing.state, "publishing");
  const targeted = await normalStore.recordPublicationTarget(publishing.submission_id, {
    expectedRevision: publishing.revision,
    prUrl: "https://github.com/mporosoff/grants-scraper/pull/999",
    registryGeneration: "c".repeat(64),
  }, "2026-09-03T12:03:10.000Z");
  assert.equal(targeted.publication_target_registry_generation, "c".repeat(64));
  assert.equal((await normalStore.recordPublicationTarget(publishing.submission_id, {
    expectedRevision: publishing.revision,
    prUrl: "https://github.com/mporosoff/grants-scraper/pull/999",
    registryGeneration: "c".repeat(64),
  }, "2026-09-03T12:03:20.000Z")).revision, publishing.revision);
  const failed = await normalStore.markPublicationFailed(publishing.submission_id, {
    expectedRevision: publishing.revision, failureCode: "pull_request_closed",
    deploymentResult: "pull_request_closed_without_merge",
  }, "2026-09-03T12:03:30.000Z");
  const retried = await normalStore.markPublishing(failed.submission_id, failed.revision, "admin@example.edu", "2026-09-03T12:03:40.000Z");
  assert.equal(retried.publication_target_pr_url, null);
  assert.equal(retried.publication_target_registry_generation, null);

  const stale = await approvedRecord("rs_eeeeeeeeeeeeeeeeeeeeeeee", "52345678-1234-4234-8234-123456789abc");
  const rebased = await normalStore.rebase({
    id: stale.submission_id, expectedRevision: stale.revision, nextGeneration: "b".repeat(64),
    actor: "admin@example.edu", reason: "", now: "2026-09-03T12:04:00.000Z",
  });
  assert.equal(rebased.state, "under_review");
  assert.equal(rebased.approved_profile_json, null);
});

test("publishing reconciliation requires a merged pull request and the exact live generation", async () => {
  const targetGeneration = "c".repeat(64);
  const mergeCommit = "b".repeat(40);
  const current = {
    submission_id: "rs_ffffffffffffffffffffffff", state: "publishing", revision: 3,
    publication_target_pr_url: "https://github.com/mporosoff/grants-scraper/pull/999",
    publication_target_registry_generation: targetGeneration,
  };
  const env = {
    GITHUB_REPOSITORY: "mporosoff/grants-scraper", GITHUB_DISPATCH_TOKEN: "github-token",
    REGISTRY_MANIFEST_URL: "https://site.example/data/researcher_registry_manifest.json",
  };
  function fetchFor({ merged = true, generation = targetGeneration } = {}) {
    return async url => {
      if (url === "https://api.github.com/repos/mporosoff/grants-scraper/pulls/999") {
        return new Response(JSON.stringify({ state: "closed", merged, merge_commit_sha: merged ? mergeCommit : null }));
      }
      if (url === env.REGISTRY_MANIFEST_URL) {
        return new Response(JSON.stringify({ registry_generation: generation }));
      }
      throw new Error(`Unexpected URL ${url}`);
    };
  }
  const publishedCalls = [];
  const store = {
    async markPublished(id, values) {
      publishedCalls.push({ id, values });
      return { ...current, state: "published", revision: 4 };
    },
  };
  const published = await reconcilePublication({
    store, current, expectedRevision: 3, actor: "admin@example.edu", env,
    fetchImpl: fetchFor(), timestamp: "2026-09-03T12:05:00.000Z",
  });
  assert.equal(published.state, "published");
  assert.equal(publishedCalls[0].values.commitSha, mergeCommit);
  assert.equal(publishedCalls[0].values.registryGeneration, targetGeneration);
  assert.equal(publishedCalls[0].values.actor, "admin@example.edu");

  await assert.rejects(
    reconcilePublication({
      store, current, expectedRevision: 3, actor: "admin@example.edu", env,
      fetchImpl: fetchFor({ generation: "a".repeat(64) }), timestamp: "2026-09-03T12:06:00.000Z",
    }),
    /not served yet/,
  );
  assert.equal(publishedCalls.length, 1);

  const failureCalls = [];
  const failed = await reconcilePublication({
    store: {
      async markPublicationFailed(id, values) {
        failureCalls.push({ id, values });
        return { ...current, state: "publication_failed", revision: 4 };
      },
    },
    current, expectedRevision: 3, actor: "admin@example.edu", env,
    fetchImpl: fetchFor({ merged: false }), timestamp: "2026-09-03T12:07:00.000Z",
  });
  assert.equal(failed.state, "publication_failed");
  assert.equal(failureCalls[0].values.actor, "admin@example.edu");
});

test("publication completion is idempotent after a network-ambiguous callback", async () => {
  const published = {
    submission_id: "rs_aaaaaaaaaaaaaaaaaaaaaaaa",
    state: "published",
    revision: 4,
    published_commit_sha: "b".repeat(40),
    published_registry_generation: "c".repeat(64),
  };
  const store = new ResearcherSubmissionStore({});
  store.byId = async () => published;
  const result = await store.markPublished(published.submission_id, {
    expectedRevision: 3,
    commitSha: published.published_commit_sha,
    registryGeneration: published.published_registry_generation,
    deploymentResult: "github_pages_succeeded_after_reconciliation",
    verifiedAt: "2026-09-03T12:00:00Z",
  }, "2026-09-03T12:01:00Z");
  assert.equal(result, published);
});

test("retention clears private fields from collection time despite later activity", async () => {
  assert.match(storeSource, /contact_email IS NOT NULL OR submitter_note IS NOT NULL/);
  assert.match(storeSource, /AND created_at < \?/);
  const database = new DatabaseSync(":memory:");
  database.exec("PRAGMA foreign_keys = ON");
  database.exec(migration);
  database.exec(transitionMigration);
  database.exec(targetMigration);
  const store = new ResearcherSubmissionStore(new SqliteD1(database));
  const created = await store.create({
    submissionId: "rs_cccccccccccccccccccccccc", idempotencyKey: "32345678-1234-4234-8234-123456789abc",
    payloadHash: "d".repeat(64), receiptTokenHash: "e".repeat(64), submissionType: "new_researcher_nomination",
    sourceSurface: "faculty_interests", researcherId: null, baseRegistryGeneration: "a".repeat(64),
    proposedProfile: submission().proposed_profile, contactEmail: "ada@example.edu", submitterNote: "Review",
    privacyNoticeVersion: "2026-09-03", createdAt: "2026-01-01T00:00:00.000Z",
  });
  await store.transition({
    id: created.submission_id, fromStates: ["pending"], toState: "under_review",
    expectedRevision: created.revision, actor: "admin@example.edu", reason: "Review",
    now: "2026-03-30T00:00:00.000Z",
  });
  await store.cleanup("2026-04-02T00:00:00.000Z", 90, 90);
  const retained = await store.byId(created.submission_id);
  assert.equal(retained.state, "under_review");
  assert.equal(retained.contact_email, null);
  assert.equal(retained.submitter_note, null);
});

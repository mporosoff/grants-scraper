import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { enforceSubmittedRelationship, validateAdminProfile, validateSubmission } from "../../workers/researcher-intake/src/contract.js";
import { createHandler } from "../../workers/researcher-intake/src/index.js";

const root = new URL("../../", import.meta.url);
const [workerSource, migration, workflow, wrangler] = await Promise.all([
  readFile(new URL("workers/researcher-intake/src/index.js", root), "utf8"),
  readFile(new URL("workers/researcher-intake/migrations/0001_researcher_submissions.sql", root), "utf8"),
  readFile(new URL(".github/workflows/publish-researcher-registry.yml", root), "utf8"),
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
  assert.match(wrangler, /SUBMISSION_RATE_LIMITER/);
  assert.match(workerSource, /cf-access-jwt-assertion/);
  assert.match(workerSource, /crypto\.subtle\.verify/);
  assert.match(workerSource, /cdn-cgi\/access\/certs/);
  assert.match(workerSource, /ACCESS_AUD/);
  assert.match(workerSource, /GITHUB_PUBLICATION_TOKEN/);
  assert.match(workerSource, /submission_id: row\.submission_id, approved_revision: row\.revision/);
  assert.doesNotMatch(workerSource.slice(workerSource.indexOf("client_payload"), workerSource.indexOf("client_payload") + 260), /approved_profile|repository_path|command/);
  assert.match(workflow, /Refuse every non-allowlisted path/);
  assert.match(workflow, /config\/researcher_registry\.json/);
  assert.match(workflow, /Mark the queue record published only after live verification/);
  assert.doesNotMatch(workflow, /playwright|test:e2e/);
});

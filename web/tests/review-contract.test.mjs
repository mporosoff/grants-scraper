import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../../assets/review.js", import.meta.url),
  "utf8",
);

function loadReviewApi() {
  const context = {
    Date,
    JSON,
    Math,
    Number,
    Object,
    Set,
    String,
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.FUNDING_REVIEW;
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
    dump() {
      return Object.fromEntries(values);
    },
  };
}

test("autosaves source reviews and bounded deployment metadata", () => {
  const api = loadReviewApi();
  const storage = memoryStorage();
  const review = api.emptyReview("2026-07-26T12:00:00Z");
  review.participant_code = "chem-eng-01";
  review.overall_note = "Citation opened to the expected page.";
  review.source_reviews["ABC-123"] = {
    opportunity_id: "ABC-123",
    opportunity_number: "FOA-123",
    title: "Example opportunity",
    agency: "Example Agency",
    status: "accurate",
    field: "deadline",
    note: "The full application date matched.",
    document_url: "https://example.test/nofo.pdf",
    document_sha256: "abc",
    document_version: 2,
    evidence_ids: ["evidence-1"],
    api_key: "must-not-persist",
  };
  review.environment = {
    viewport: "desktop",
    locale: "en-US",
    timezone: "America/New_York",
    file_share_supported: true,
    user_agent: "must-not-persist",
  };

  const result = api.saveReview(review, storage);
  assert.equal(result.saved, true);
  const raw = storage.dump()[api.REVIEW_STORAGE_KEY];
  assert.doesNotMatch(raw, /must-not-persist|api_key|user_agent/);
  const loaded = api.loadReview(storage);
  assert.equal(loaded.source_reviews["ABC-123"].status, "accurate");
  assert.equal(loaded.source_reviews["ABC-123"].field, "deadline");
  assert.equal(loaded.environment.viewport, "desktop");
});

test("exports a privacy-safe handoff package without research or chat text", () => {
  const api = loadReviewApi();
  let review = api.emptyReview("2026-07-26T12:00:00Z");
  review.source_reviews["ABC-123"] = {
    opportunity_id: "ABC-123",
    title: "Example opportunity",
    status: "incorrect",
    field: "funding",
    note: "The notice listed a different ceiling.",
  };
  review = api.recordUsage(review, "official_source_opens");
  review = api.recordUsage(review, "citation_opens", 2);
  const payload = api.buildPackage(review, {
    catalog: {
      schema_version: 3,
      generated_at: "2026-07-26T12:00:00Z",
      document_evidence_generated_at: "2026-07-26T13:00:00Z",
      record_count: 1465,
    },
    app_version: "phase3-v1",
    canonical_url: "https://mporosoff.github.io/grants-scraper/",
    match_feedback: [{
      opportunity_id: "ABC-123",
      title: "Example opportunity",
      label: "useful",
      reason: "topic_fit",
      query: "private unpublished research",
      note: "private note",
      profile_fingerprint: "private-fingerprint",
      api_key: "secret",
    }],
    chat: "private chat",
    research_description: "private unpublished research",
  });
  const serialized = JSON.stringify(payload);

  assert.equal(payload.review.usage.official_source_opens, 1);
  assert.equal(payload.review.usage.citation_opens, 2);
  assert.equal(payload.review.source_reviews.length, 1);
  assert.equal(payload.match_feedback.length, 1);
  assert.doesNotMatch(
    serialized,
    /private unpublished research|private chat|private note|secret|fingerprint/,
  );
  assert.match(
    api.handoffSummary(payload, "review.json"),
    /Source facts reviewed: 1/,
  );
});

test("rejects unsupported review labels and can clear saved progress", () => {
  const api = loadReviewApi();
  const storage = memoryStorage();
  api.saveReview({
    source_reviews: {
      valid: {
        opportunity_id: "valid",
        status: "could_not_verify",
        field: "status",
      },
      invalid: {
        opportunity_id: "invalid",
        status: "approved",
      },
    },
  }, storage);
  const loaded = api.loadReview(storage);
  assert.equal(loaded.source_reviews.valid.status, "could_not_verify");
  assert.equal(loaded.source_reviews.invalid, undefined);
  assert.equal(api.clearReview(storage), true);
  assert.equal(storage.getItem(api.REVIEW_STORAGE_KEY), null);
});

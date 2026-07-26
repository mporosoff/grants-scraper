(() => {
  "use strict";

  const REVIEW_SCHEMA_VERSION = 1;
  const REVIEW_STORAGE_KEY = "funding-finder.deployment-review.v1";
  const REVIEW_STATUSES = new Set([
    "accurate",
    "incorrect",
    "could_not_verify",
  ]);
  const REVIEW_FIELDS = new Set([
    "overall",
    "deadline",
    "funding",
    "eligibility",
    "status",
    "application_requirements",
    "source_link",
  ]);
  const CHECK_VALUES = new Set(["not_tested", "yes", "no"]);
  const USAGE_EVENTS = new Set([
    "searches",
    "profile_searches",
    "ai_matches",
    "chats",
    "official_source_opens",
    "citation_opens",
    "csv_exports",
    "evaluation_exports",
    "review_exports",
  ]);

  function cleanString(value, maximum = 2_000) {
    return String(value || "")
      .replace(/\u0000/g, "")
      .replace(/\r\n?/g, "\n")
      .trim()
      .slice(0, maximum);
  }

  function storageOrNull(storage) {
    try {
      return storage || globalThis.localStorage || null;
    } catch {
      return null;
    }
  }

  function randomId() {
    try {
      if (globalThis.crypto?.randomUUID) {
        return `review-${globalThis.crypto.randomUUID()}`;
      }
    } catch {
      // Fall through to a non-identifying local identifier.
    }
    return `review-${Date.now().toString(36)}-${Math.random()
      .toString(36)
      .slice(2, 10)}`;
  }

  function emptyUsage() {
    return Object.fromEntries([...USAGE_EVENTS].map(name => [name, 0]));
  }

  function emptyChecks() {
    return {
      search_worked: "not_tested",
      official_notice_opened: "not_tested",
      citation_landed_correctly: "not_tested",
      mobile_layout_usable: "not_tested",
      export_or_share_worked: "not_tested",
    };
  }

  function emptyReview(now = new Date().toISOString()) {
    return {
      schema_version: REVIEW_SCHEMA_VERSION,
      review_id: randomId(),
      participant_code: "",
      created_at: now,
      updated_at: now,
      source_reviews: {},
      deployment_checks: emptyChecks(),
      overall_note: "",
      usage: emptyUsage(),
      environment: {},
    };
  }

  function sanitizeSourceReview(value) {
    const source = value && typeof value === "object" ? value : {};
    if (!REVIEW_STATUSES.has(source.status)) return null;
    return {
      opportunity_id: cleanString(source.opportunity_id, 120),
      opportunity_number: cleanString(source.opportunity_number, 180),
      title: cleanString(source.title, 500),
      agency: cleanString(source.agency, 300),
      status: source.status,
      field: REVIEW_FIELDS.has(source.field) ? source.field : "overall",
      note: cleanString(source.note, 800),
      document_url: cleanString(source.document_url, 2_000),
      document_sha256: cleanString(source.document_sha256, 80),
      document_version: Number.isInteger(source.document_version)
        && source.document_version > 0
        ? source.document_version
        : null,
      evidence_ids: Array.isArray(source.evidence_ids)
        ? [...new Set(
            source.evidence_ids
              .map(id => cleanString(id, 180))
              .filter(Boolean),
          )].slice(0, 36)
        : [],
      catalog_generated_at: cleanString(source.catalog_generated_at, 40),
      updated_at: cleanString(source.updated_at, 40)
        || new Date().toISOString(),
    };
  }

  function sanitizeEnvironment(value) {
    const source = value && typeof value === "object" ? value : {};
    return {
      viewport: ["mobile", "tablet", "desktop"].includes(source.viewport)
        ? source.viewport
        : "",
      locale: cleanString(source.locale, 40),
      timezone: cleanString(source.timezone, 80),
      mobile_hint: source.mobile_hint === true,
      file_share_supported: source.file_share_supported === true,
    };
  }

  function sanitizeReview(value) {
    const source = value && typeof value === "object" ? value : {};
    const sourceReviews = source.source_reviews
      && typeof source.source_reviews === "object"
      ? source.source_reviews
      : {};
    const checks = source.deployment_checks
      && typeof source.deployment_checks === "object"
      ? source.deployment_checks
      : {};
    const usage = source.usage && typeof source.usage === "object"
      ? source.usage
      : {};
    return {
      schema_version: REVIEW_SCHEMA_VERSION,
      review_id: cleanString(source.review_id, 100) || randomId(),
      participant_code: cleanString(source.participant_code, 80),
      created_at: cleanString(source.created_at, 40)
        || new Date().toISOString(),
      updated_at: cleanString(source.updated_at, 40)
        || new Date().toISOString(),
      source_reviews: Object.fromEntries(
        Object.entries(sourceReviews)
          .map(([id, entry]) => [
            cleanString(id, 120),
            sanitizeSourceReview(entry),
          ])
          .filter(([id, entry]) => id && entry),
      ),
      deployment_checks: Object.fromEntries(
        Object.keys(emptyChecks()).map(name => [
          name,
          CHECK_VALUES.has(checks[name]) ? checks[name] : "not_tested",
        ]),
      ),
      overall_note: cleanString(source.overall_note, 2_000),
      usage: Object.fromEntries(
        [...USAGE_EVENTS].map(name => {
          const count = Number(usage[name] || 0);
          return [
            name,
            Number.isFinite(count) && count > 0
              ? Math.min(100_000, Math.round(count))
              : 0,
          ];
        }),
      ),
      environment: sanitizeEnvironment(source.environment),
    };
  }

  function loadReview(storage) {
    const target = storageOrNull(storage);
    if (!target) return emptyReview();
    try {
      const parsed = JSON.parse(
        target.getItem(REVIEW_STORAGE_KEY) || "{}",
      );
      if (parsed?.schema_version !== REVIEW_SCHEMA_VERSION) {
        return emptyReview();
      }
      return sanitizeReview(parsed);
    } catch {
      return emptyReview();
    }
  }

  function saveReview(value, storage) {
    const target = storageOrNull(storage);
    const review = sanitizeReview(value);
    review.updated_at = new Date().toISOString();
    if (!target) return { saved: false, review };
    try {
      target.setItem(REVIEW_STORAGE_KEY, JSON.stringify(review));
      return { saved: true, review };
    } catch {
      return { saved: false, review };
    }
  }

  function clearReview(storage) {
    const target = storageOrNull(storage);
    if (!target) return false;
    try {
      target.removeItem(REVIEW_STORAGE_KEY);
      return true;
    } catch {
      return false;
    }
  }

  function recordUsage(value, eventName, increment = 1) {
    const review = sanitizeReview(value);
    if (!USAGE_EVENTS.has(eventName)) return review;
    const amount = Number(increment || 0);
    review.usage[eventName] = Math.min(
      100_000,
      Math.max(0, review.usage[eventName] + (
        Number.isFinite(amount) ? Math.round(amount) : 0
      )),
    );
    review.updated_at = new Date().toISOString();
    return review;
  }

  function sourceReviewCount(value) {
    return Object.keys(sanitizeReview(value).source_reviews).length;
  }

  function buildPackage(value, context = {}) {
    const review = sanitizeReview(value);
    const matchFeedback = Array.isArray(context.match_feedback)
      ? context.match_feedback
      : [];
    const publicMatchFeedback = matchFeedback.map(entry => ({
      opportunity_id: cleanString(entry.opportunity_id, 120),
      opportunity_number: cleanString(entry.opportunity_number, 180),
      title: cleanString(entry.title, 500),
      agency: cleanString(entry.agency, 300),
      label: cleanString(entry.label, 40),
      reason: cleanString(entry.reason, 120),
      retrieval_rank: Number.isInteger(entry.retrieval_rank)
        ? entry.retrieval_rank
        : null,
      displayed_rank: Number.isInteger(entry.displayed_rank)
        ? entry.displayed_rank
        : null,
      ai_rank: Number.isInteger(entry.ai_rank) ? entry.ai_rank : null,
      ai_score: Number.isFinite(Number(entry.ai_score))
        ? Number(entry.ai_score)
        : null,
      provider: cleanString(entry.provider, 40),
      model: cleanString(entry.model, 120),
      updated_at: cleanString(entry.updated_at, 40),
    }));
    return {
      schema_version: REVIEW_SCHEMA_VERSION,
      kind: "funding_finder_phase3_deployment_review",
      exported_at: new Date().toISOString(),
      privacy: (
        "Contains explicit source reviews, optional reviewer notes, coarse "
        + "device capability data, aggregate usage counts, and public "
        + "opportunity metadata. It excludes API keys, CV/profile text, "
        + "search text, Funding Finder search URL/parameters, and chat."
      ),
      review: {
        review_id: review.review_id,
        participant_code: review.participant_code || null,
        created_at: review.created_at,
        updated_at: review.updated_at,
        overall_note: review.overall_note,
        deployment_checks: review.deployment_checks,
        environment: review.environment,
        usage: review.usage,
        source_reviews: Object.values(review.source_reviews).sort(
          (left, right) => left.updated_at.localeCompare(right.updated_at),
        ),
      },
      match_feedback: publicMatchFeedback,
      catalog: {
        schema_version: Number(context.catalog?.schema_version || 0) || null,
        generated_at: cleanString(context.catalog?.generated_at, 40),
        document_evidence_generated_at: cleanString(
          context.catalog?.document_evidence_generated_at,
          40,
        ),
        record_count: Number(context.catalog?.record_count || 0) || null,
      },
      deployment: {
        app_version: cleanString(context.app_version, 80),
        canonical_url: cleanString(context.canonical_url, 500),
      },
    };
  }

  function handoffSummary(payload, filename) {
    const sourceReviews = payload.review.source_reviews || [];
    const matchFeedback = payload.match_feedback || [];
    const checks = payload.review.deployment_checks || {};
    const failedChecks = Object.entries(checks)
      .filter(([, value]) => value === "no")
      .map(([name]) => name.replaceAll("_", " "));
    return [
      "Funding Finder Phase 3 deployment review",
      `Review ID: ${payload.review.review_id}`,
      `Source facts reviewed: ${sourceReviews.length}`,
      `Match ratings included: ${matchFeedback.length}`,
      `Checks needing attention: ${failedChecks.join(", ") || "none marked"}`,
      `File: ${filename}`,
      "",
      "The attached JSON excludes API keys, CV/profile text, search text, Funding Finder search URLs, and chat.",
    ].join("\n");
  }

  globalThis.FUNDING_REVIEW = Object.freeze({
    REVIEW_SCHEMA_VERSION,
    REVIEW_STORAGE_KEY,
    buildPackage,
    clearReview,
    emptyReview,
    handoffSummary,
    loadReview,
    recordUsage,
    sanitizeReview,
    sanitizeSourceReview,
    saveReview,
    sourceReviewCount,
  });
})();

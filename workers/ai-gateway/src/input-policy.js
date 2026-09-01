export const MAX_USER_CHARS = 180_000;

const PROFILE_KEYS = [
  "research_description",
  "expertise_keywords",
  "orcid_id",
  "applicant_context",
  "career_stage",
  "cv_excerpt",
  "cv_excerpt_note",
  "orcid_publications_excerpt",
  "orcid_publications_note",
];
const FILTER_KEYS = [
  "status",
  "source",
  "source_type",
  "discipline",
  "topic",
  "agency",
  "eligibility",
  "funding_instrument",
  "deadline_from",
  "deadline_through",
  "minimum_award",
  "cited_foa_evidence",
  "preliminary_stage",
  "limited_submission_signal",
  "early_career_signal",
  "no_listed_cost_share",
];
const RECORD_KEYS = [
  "id",
  "number",
  "title",
  "agency",
  "source",
  "source_type",
  "status",
  "deadline",
  "deadline_note",
  "deadlines",
  "deadline_source",
  "deadline_conflict",
  "actionability_status",
  "award_floor",
  "award_ceiling",
  "total_program_funding",
  "award_source",
  "award_conflicts",
  "eligibility",
  "eligibility_note",
  "disciplines",
  "topics",
  "funding_instruments",
  "limited_submission_signal",
  "preliminary_stage_signal",
  "cost_share_required",
  "status_verification_required",
  "primary_foa_identified",
  "official_source_url",
  "document_evidence",
  "description",
  "workflow_tier",
  "ai_identified",
  "ai_discovery_phrases",
  "potential_evidence",
  "deterministic_strong_score",
  "strong_match_evidence",
];

function plainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasOnlyKeys(value, allowed, required = []) {
  if (!plainObject(value)) return false;
  const allowedSet = new Set(allowed);
  return Object.keys(value).every(key => allowedSet.has(key))
    && required.every(key => Object.prototype.hasOwnProperty.call(value, key));
}

function boundedText(value, maximum, { empty = true, nullable = false } = {}) {
  if (nullable && value === null) return true;
  return typeof value === "string"
    && (empty || Boolean(value.trim()))
    && value.length <= maximum;
}

function boundedStringList(value, maximumItems, maximumCharacters) {
  return Array.isArray(value)
    && value.length <= maximumItems
    && value.every(item => boundedText(item, maximumCharacters));
}

function safeJsonValue(value, depth = 0) {
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return value.length <= 120_000;
  if (depth >= 5) return false;
  if (Array.isArray(value)) {
    return value.length <= 24 && value.every(item => safeJsonValue(item, depth + 1));
  }
  if (!plainObject(value) || Object.keys(value).length > 32) return false;
  return Object.entries(value).every(([key, item]) => (
    /^[a-z][a-z0-9_]{0,63}$/i.test(key)
    && !["__proto__", "constructor", "prototype"].includes(key)
    && safeJsonValue(item, depth + 1)
  ));
}

function boundedObject(value, allowed, maximumCharacters, required = []) {
  if (!hasOnlyKeys(value, allowed, required) || !safeJsonValue(value)) return false;
  return JSON.stringify(value).length <= maximumCharacters;
}

function validProfile(value) {
  if (value === null) return true;
  return boundedObject(value, PROFILE_KEYS, 48_000)
    && (!Object.hasOwn(value, "research_description")
      || boundedText(value.research_description, 20_000, { nullable: true }))
    && (!Object.hasOwn(value, "expertise_keywords")
      || boundedText(value.expertise_keywords, 4_000, { nullable: true }))
    && (!Object.hasOwn(value, "cv_excerpt") || boundedText(value.cv_excerpt, 12_000))
    && (!Object.hasOwn(value, "orcid_publications_excerpt")
      || boundedText(value.orcid_publications_excerpt, 8_000));
}

function validFilters(value) {
  return boundedObject(value, FILTER_KEYS, 12_000);
}

function validRecord(value) {
  return boundedObject(value, RECORD_KEYS, 9_000, ["id", "title"])
    && boundedText(value.id, 180, { empty: false })
    && boundedText(value.title, 600, { empty: false });
}

function validConversation(value) {
  return Array.isArray(value)
    && value.length >= 1
    && value.length <= 7
    && value.reduce((sum, item) => sum + String(item?.text || "").length, 0) <= 12_000
    && value.every(item => (
      hasOnlyKeys(item, ["role", "text"], ["role", "text"])
      && ["user", "assistant"].includes(item.role)
      && boundedText(item.text, 3_000, { empty: false })
    ));
}

function validSearchPlan(value) {
  return hasOnlyKeys(value, [
    "task", "researcher_profile", "current_keyword_search", "active_filters", "prompt_version",
  ], ["task", "researcher_profile", "current_keyword_search", "active_filters", "prompt_version"])
    && boundedText(value.task, 300, { empty: false })
    && validProfile(value.researcher_profile)
    && boundedText(value.current_keyword_search, 500, { nullable: true })
    && validFilters(value.active_filters)
    && boundedText(value.prompt_version, 100, { empty: false });
}

function validRefinement(value) {
  return hasOnlyKeys(value, [
    "task", "researcher_profile", "search_interpretation", "avoid_concepts",
    "candidate_opportunities", "prompt_version",
  ], [
    "task", "researcher_profile", "search_interpretation", "avoid_concepts",
    "candidate_opportunities", "prompt_version",
  ])
    && boundedText(value.task, 300, { empty: false })
    && validProfile(value.researcher_profile)
    && boundedText(value.search_interpretation, 500)
    && boundedStringList(value.avoid_concepts, 8, 120)
    && Array.isArray(value.candidate_opportunities)
    && value.candidate_opportunities.length >= 1
    && value.candidate_opportunities.length <= 32
    && value.candidate_opportunities.every(validRecord)
    && boundedText(value.prompt_version, 100, { empty: false });
}

function validResultChat(value) {
  return hasOnlyKeys(value, [
    "researcher_profile", "result_context", "current_results", "conversation",
    "latest_question", "prompt_version",
  ], [
    "researcher_profile", "result_context", "current_results", "conversation",
    "latest_question", "prompt_version",
  ])
    && validProfile(value.researcher_profile)
    && boundedText(value.result_context, 240, { empty: false })
    && Array.isArray(value.current_results)
    && value.current_results.length >= 1
    && value.current_results.length <= 10
    && value.current_results.every(validRecord)
    && validConversation(value.conversation)
    && boundedText(value.latest_question, 3_000, { empty: false })
    && boundedText(value.prompt_version, 100, { empty: false });
}

function validNoticeChat(value) {
  const notice = value?.uploaded_notice;
  return hasOnlyKeys(value, [
    "task", "uploaded_notice", "matched_catalog_record", "conversation",
    "latest_question", "prompt_version",
  ], [
    "task", "uploaded_notice", "matched_catalog_record", "conversation",
    "latest_question", "prompt_version",
  ])
    && boundedText(value.task, 300, { empty: false })
    && hasOnlyKeys(notice, [
      "file_name", "page_count", "pages_read", "text_truncated", "document_text",
    ], ["file_name", "page_count", "pages_read", "text_truncated", "document_text"])
    && boundedText(notice.file_name, 300, { empty: false })
    && Number.isInteger(notice.page_count) && notice.page_count >= 1 && notice.page_count <= 20_000
    && Number.isInteger(notice.pages_read) && notice.pages_read >= 1 && notice.pages_read <= notice.page_count
    && typeof notice.text_truncated === "boolean"
    && boundedText(notice.document_text, 120_000, { empty: false })
    && (value.matched_catalog_record === null || validRecord(value.matched_catalog_record))
    && validConversation(value.conversation)
    && boundedText(value.latest_question, 3_000, { empty: false })
    && boundedText(value.prompt_version, 100, { empty: false });
}

function validInstitutionTranslation(value) {
  const filters = value?.current_filters;
  return hasOnlyKeys(value, ["institution", "current_filters", "question"], [
    "institution", "current_filters", "question",
  ])
    && boundedText(value.institution, 500, { empty: false })
    && hasOnlyKeys(filters, [
      "agency", "program", "topic", "pi", "program_officer", "year_start", "year_end",
    ], ["agency", "program", "topic", "pi", "program_officer", "year_start", "year_end"])
    && boundedObject(filters, [
      "agency", "program", "topic", "pi", "program_officer", "year_start", "year_end",
    ], 2_000)
    && boundedText(value.question, 1_000, { empty: false });
}

function validAwardEvidence(value) {
  return hasOnlyKeys(value, [
    "evidence_id", "source", "award_id", "title", "program", "year",
    "investigators", "abstract_excerpt",
  ], [
    "evidence_id", "source", "award_id", "title", "program", "year",
    "investigators", "abstract_excerpt",
  ])
    && boundedText(value.evidence_id, 120, { empty: false })
    && boundedText(value.source, 10, { empty: false })
    && boundedText(value.award_id, 100, { empty: false })
    && boundedText(value.title, 500)
    && boundedText(value.program, 200)
    && (value.year === "" || boundedText(value.year, 4))
    && boundedStringList(value.investigators, 8, 160)
    && boundedText(value.abstract_excerpt, 1_600);
}

function validInstitutionNarrative(value) {
  const institution = value?.institution;
  const filters = value?.visible_filters;
  return hasOnlyKeys(value, [
    "question", "institution", "visible_filters", "answer_intent",
    "public_award_evidence", "evidence_truncated",
  ], [
    "question", "institution", "visible_filters", "answer_intent",
    "public_award_evidence", "evidence_truncated",
  ])
    && boundedText(value.question, 1_000, { empty: false })
    && hasOnlyKeys(institution, ["id", "canonical_name"], ["id", "canonical_name"])
    && boundedText(institution.id, 100)
    && boundedText(institution.canonical_name, 300, { empty: false })
    && hasOnlyKeys(filters, [
      "agency", "program", "topic", "pi", "program_officer", "year_start", "year_end",
    ], ["agency", "program", "topic", "pi", "program_officer", "year_start", "year_end"])
    && boundedObject(filters, [
      "agency", "program", "topic", "pi", "program_officer", "year_start", "year_end",
    ], 2_000)
    && ["count", "investigators", "programs", "years", "awards", "narrative"].includes(value.answer_intent)
    && Array.isArray(value.public_award_evidence)
    && value.public_award_evidence.length >= 1
    && value.public_award_evidence.length <= 30
    && value.public_award_evidence.every(validAwardEvidence)
    && typeof value.evidence_truncated === "boolean";
}

const VALIDATORS = Object.freeze({
  search_plan: validSearchPlan,
  refinement_shortlist: validRefinement,
  result_chat: validResultChat,
  notice_chat: validNoticeChat,
  institution_question_translation: validInstitutionTranslation,
  institution_narrative: validInstitutionNarrative,
});

export function validateOperationUser(operation, user) {
  if (typeof user !== "string" || !user.trim() || user.length > MAX_USER_CHARS) return null;
  let value;
  try {
    value = JSON.parse(user);
  } catch {
    return null;
  }
  return VALIDATORS[operation]?.(value) ? value : null;
}

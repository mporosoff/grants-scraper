const TYPES = new Set(["profile_correction", "new_researcher_nomination"]);
const SURFACES = new Set(["faculty_interests", "team_match"]);
const RELATIONSHIPS = new Set([
  "hajim_core_faculty", "internal_affiliated_researcher", "external_collaborator", "reference_only_researcher",
]);
const VISIBILITIES = new Set(["department", "institution", "approved_collaborator", "reference_only", "hidden"]);
const STATUSES = new Set(["active", "inactive", "departed"]);
const CLAIM_STATUSES = new Set(["active", "retired"]);
const EVIDENCE_LEVELS = new Set(["direct", "corroborated", "administrator_reviewed"]);
const ALLOWED_SUBMISSION_FIELDS = new Set([
  "schema_version", "idempotency_key", "submission_type", "source_surface", "researcher_id",
  "base_registry_generation", "proposed_profile", "submitter", "consent",
]);
const ALLOWED_PROFILE_FIELDS = new Set([
  "display_name", "orcid_id", "home_unit", "relationship_note", "research_summary", "claims", "source_urls",
]);

function fail(code, message, status = 400) {
  throw Object.assign(new Error(message), { code, status });
}
function exactFields(value, allowed, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("invalid_request", `${label} must be an object.`);
  const unexpected = Object.keys(value).filter(key => !allowed.has(key));
  if (unexpected.length) fail("unexpected_field", `${label} contains unsupported fields.`);
}
function text(value, maximum, label, required = false) {
  const normalized = String(value == null ? "" : value).normalize("NFKC").replace(/\s+/g, " ").trim();
  if ((required && !normalized) || normalized.length > maximum) fail("invalid_field", `${label} is invalid.`);
  return normalized;
}
function list(value, maximum, itemMaximum, label, required = false) {
  if (!Array.isArray(value) || value.length > maximum || (required && !value.length)) fail("invalid_field", `${label} is invalid.`);
  const seen = new Set();
  return value.map(item => text(item, itemMaximum, label, true)).filter(item => {
    const key = item.toLocaleLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function urls(value, required = false) {
  return list(value, 8, 500, "Source links", required).map(item => {
    let parsed;
    try { parsed = new URL(item); } catch { fail("invalid_source_url", "Source links must be complete HTTPS URLs."); }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) fail("invalid_source_url", "Source links must be complete HTTPS URLs.");
    parsed.hash = "";
    return parsed.toString();
  });
}
function calendarDate(value, label) {
  const normalized = text(value, 10, label, true);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(normalized);
  if (!match) fail("invalid_date", `${label} must be a valid YYYY-MM-DD calendar date.`);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(0);
  parsed.setUTCHours(0, 0, 0, 0);
  parsed.setUTCFullYear(year, month - 1, day);
  if (year < 1 || parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) {
    fail("invalid_date", `${label} must be a valid YYYY-MM-DD calendar date.`);
  }
  return normalized;
}
function normalizeOrcid(value) {
  const compact = String(value || "").toUpperCase().replace(/[^0-9X]/g, "");
  if (!compact) return "";
  if (!/^[0-9]{15}[0-9X]$/.test(compact)) fail("invalid_orcid", "The ORCID iD is invalid.");
  let total = 0;
  for (let index = 0; index < 15; index += 1) total = (total + Number(compact[index])) * 2;
  const result = (12 - (total % 11)) % 11;
  const check = result === 10 ? "X" : String(result);
  if (check !== compact[15]) fail("invalid_orcid", "The ORCID iD is invalid.");
  return `${compact.slice(0, 4)}-${compact.slice(4, 8)}-${compact.slice(8, 12)}-${compact.slice(12)}`;
}

export function validateSubmission(value) {
  exactFields(value, ALLOWED_SUBMISSION_FIELDS, "Submission");
  if (value.schema_version !== 1 || !TYPES.has(value.submission_type) || !SURFACES.has(value.source_surface)) {
    fail("invalid_contract", "The submission contract is incompatible.");
  }
  const idempotencyKey = text(value.idempotency_key, 80, "Submission identifier", true);
  if (!/^[a-zA-Z0-9-]{16,80}$/.test(idempotencyKey)) fail("invalid_idempotency_key", "The submission identifier is invalid.");
  const researcherId = value.researcher_id == null ? null : text(value.researcher_id, 40, "Researcher identifier", true);
  if (researcherId && !/^urh-[0-9]{6}$/.test(researcherId)) fail("invalid_researcher_id", "The researcher identifier is invalid.");
  if (value.submission_type === "profile_correction" && !researcherId) fail("missing_researcher_id", "A correction must identify the published researcher.");
  if (value.submission_type === "new_researcher_nomination" && researcherId) fail("unexpected_researcher_id", "A nomination cannot claim an existing identity.");
  const generation = text(value.base_registry_generation, 64, "Registry generation", true);
  if (!/^[a-f0-9]{64}$/.test(generation)) fail("invalid_registry_generation", "The registry generation is invalid.");
  exactFields(value.proposed_profile, ALLOWED_PROFILE_FIELDS, "Proposed profile");
  const proposed = {
    display_name: text(value.proposed_profile.display_name, 120, "Researcher name", true),
    orcid_id: normalizeOrcid(value.proposed_profile.orcid_id),
    home_unit: text(value.proposed_profile.home_unit, 180, "Unit"),
    relationship_note: text(value.proposed_profile.relationship_note, 240, "Relationship"),
    research_summary: text(value.proposed_profile.research_summary, 1200, "Research summary"),
    claims: list(value.proposed_profile.claims, 12, 180, "Research interests", true),
    source_urls: urls(value.proposed_profile.source_urls, value.submission_type === "new_researcher_nomination"),
  };
  exactFields(value.submitter, new Set(["contact_email", "note"]), "Submitter");
  const email = text(value.submitter.contact_email, 254, "Contact email").toLocaleLowerCase();
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) fail("invalid_email", "The contact email is invalid.");
  exactFields(value.consent, new Set(["submitted_for_admin_review", "privacy_notice_version"]), "Consent");
  if (value.consent.submitted_for_admin_review !== true || text(value.consent.privacy_notice_version, 40, "Privacy notice", true) !== "2026-09-03") {
    fail("consent_required", "Explicit consent under the current privacy notice is required.");
  }
  return {
    schema_version: 1, idempotency_key: idempotencyKey,
    submission_type: value.submission_type, source_surface: value.source_surface,
    researcher_id: researcherId, base_registry_generation: generation,
    proposed_profile: proposed,
    submitter: { contact_email: email, note: text(value.submitter.note, 1000, "Note") },
    consent: { submitted_for_admin_review: true, privacy_notice_version: "2026-09-03" },
  };
}

export function validateAdminProfile(value, researcherId, reservedLegacyClaimIds = [], reservedOrcidIds = []) {
  const allowed = new Set([
    "display_name", "sort_name", "aliases", "orcid_id", "home_unit", "relationship", "pool_visibility",
    "auto_proposable", "status", "research_summary", "source_urls", "source_checked_date", "claims",
  ]);
  exactFields(value, allowed, "Approved profile");
  if (!RELATIONSHIPS.has(value.relationship) || !VISIBILITIES.has(value.pool_visibility) || !STATUSES.has(value.status) || typeof value.auto_proposable !== "boolean") {
    fail("invalid_admin_policy", "Administrator-controlled profile policy is invalid.");
  }
  if (value.auto_proposable && (value.status !== "active" || ["reference_only", "hidden"].includes(value.pool_visibility))) {
    fail("invalid_admin_policy", "This researcher cannot be automatically proposed under the selected policy.");
  }
  const sources = urls(value.source_urls, true);
  const sourceCheckedDate = calendarDate(value.source_checked_date, "Source checked date");
  const orcidId = normalizeOrcid(value.orcid_id);
  const occupiedOrcids = new Set([...reservedOrcidIds].map(value => String(value).toUpperCase()));
  if (orcidId && occupiedOrcids.has(orcidId)) fail("duplicate_orcid", "That ORCID iD already belongs to another researcher.", 409);
  if (!Array.isArray(value.claims) || value.claims.length > 20) fail("invalid_claims", "Approved claims are invalid.");
  const claimIds = new Set();
  const legacyClaimIds = new Set([...reservedLegacyClaimIds].map(value => String(value).toLocaleLowerCase()));
  const claims = value.claims.map(claim => {
    const claimAllowed = new Set(["claim_id", "revision", "status", "label", "category", "categories", "type", "evidence", "source_urls", "verified_on", "evidence_level", "legacy_claim_ids", "material_hash"]);
    exactFields(claim, claimAllowed, "Claim");
    if (!Number.isInteger(claim.revision) || claim.revision < 1) {
      fail("invalid_claim", "A claim revision must be a positive integer.");
    }
    const claimId = text(claim.claim_id, 40, "Claim identifier");
    if (claimId && !/^urh-[0-9]{6}-c[0-9]{3}$/.test(claimId)) fail("invalid_claim_id", "A claim identifier is invalid.");
    if (claimId && !researcherId) fail("invalid_claim_id", "Nomination claims cannot preassign claim identifiers.");
    if (claimId && researcherId && !claimId.startsWith(`${researcherId}-c`)) fail("invalid_claim_id", "A claim identifier belongs to another researcher.");
    if (claimId && claimIds.has(claimId)) fail("invalid_claim_id", "Claim identifiers must be unique.");
    if (claimId) claimIds.add(claimId);
    if (!CLAIM_STATUSES.has(claim.status) || !EVIDENCE_LEVELS.has(claim.evidence_level)) fail("invalid_claim", "A claim state is invalid.");
    const category = text(claim.category, 140, "Claim category", true);
    const categories = list(claim.categories || [category], 12, 140, "Claim categories", true);
    if (!categories.includes(category)) fail("invalid_claim", "Claim categories must include the primary category.");
    if (!Array.isArray(claim.legacy_claim_ids) || claim.legacy_claim_ids.some(value => typeof value !== "string")) {
      fail("invalid_claim_id", "Legacy claim identifiers must be a bounded list of globally unique strings.");
    }
    const legacyIds = list(claim.legacy_claim_ids, 10, 80, "Legacy claim identifier");
    if (legacyIds.length !== claim.legacy_claim_ids.length || legacyIds.some(value => legacyClaimIds.has(value.toLocaleLowerCase()))) {
      fail("invalid_claim_id", "Legacy claim identifiers must be a bounded list of globally unique strings.");
    }
    legacyIds.forEach(value => legacyClaimIds.add(value.toLocaleLowerCase()));
    return {
      claim_id: claimId, revision: claim.revision, status: claim.status,
      label: text(claim.label, 180, "Claim label", true), category, categories,
      type: text(claim.type, 80, "Claim type", true), evidence: text(claim.evidence, 500, "Claim evidence", true),
      source_urls: urls(claim.source_urls, true), verified_on: calendarDate(claim.verified_on, "Claim verification date"),
      evidence_level: claim.evidence_level, legacy_claim_ids: legacyIds,
      ...(claim.material_hash ? { material_hash: text(claim.material_hash, 64, "Material hash", true) } : {}),
    };
  });
  if (value.auto_proposable && !claims.some(claim => claim.status === "active")) {
    fail("invalid_admin_policy", "An automatically proposed researcher requires an active reviewed claim.");
  }
  return {
    display_name: text(value.display_name, 120, "Display name", true), sort_name: text(value.sort_name, 140, "Sort name", true),
    aliases: list(value.aliases || [], 20, 120, "Alias"), orcid_id: orcidId,
    home_unit: text(value.home_unit, 180, "Unit", true), relationship: value.relationship,
    pool_visibility: value.pool_visibility, auto_proposable: value.auto_proposable, status: value.status,
    research_summary: text(value.research_summary, 1200, "Research summary"), source_urls: sources,
    source_checked_date: sourceCheckedDate, claims,
  };
}

export function enforceSubmittedRelationship(approvedProfile, proposedProfile) {
  const note = text(proposedProfile?.relationship_note, 240, "Relationship").toLocaleLowerCase();
  if (["external collaborator", "collaborator at another institution"].includes(note)
      && ["hajim_core_faculty", "internal_affiliated_researcher"].includes(approvedProfile.relationship)) {
    fail("invalid_admin_policy", "A submitted external collaborator cannot be published as core or internal faculty.");
  }
  return approvedProfile;
}

export function enforceClaimContinuity(approvedProfile, currentProfile) {
  if (!currentProfile) {
    if (approvedProfile.claims.some(claim => claim.legacy_claim_ids.length)) {
      fail("invalid_claim_set", "New claims cannot assign legacy claim identifiers.");
    }
    return approvedProfile;
  }
  const previousClaims = new Map((currentProfile.claims || []).map(claim => [claim.claim_id, claim]));
  const previousIds = new Set((currentProfile.claims || []).map(claim => claim.claim_id));
  const submittedIds = new Set(approvedProfile.claims.map(claim => claim.claim_id).filter(Boolean));
  if ([...previousIds].some(claimId => !submittedIds.has(claimId))) {
    fail("invalid_claim_set", "Existing claims must remain present and be marked retired instead of being removed.");
  }
  if ([...submittedIds].some(claimId => !previousIds.has(claimId))) {
    fail("invalid_claim_set", "New claims must leave the claim identifier empty.");
  }
  for (const claim of approvedProfile.claims) {
    const previous = previousClaims.get(claim.claim_id);
    if (!previous) {
      if (claim.legacy_claim_ids.length) fail("invalid_claim_set", "New claims cannot assign legacy claim identifiers.");
      continue;
    }
    const previousLegacyIds = previous.legacy_claim_ids || [];
    if (claim.legacy_claim_ids.length !== previousLegacyIds.length
        || claim.legacy_claim_ids.some((value, index) => value !== previousLegacyIds[index])) {
      fail("invalid_claim_set", "Existing legacy claim identifiers must remain attached to their original claim.");
    }
  }
  return approvedProfile;
}

export { fail };

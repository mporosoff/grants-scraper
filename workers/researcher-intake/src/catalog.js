import { fail } from "./contract.js";

const REMOVAL_ACTIONS = new Set(["remove_researcher"]);

export function validateCatalogRemoval(value) {
  const fields = new Set(["researcher_id", "base_registry_generation", "action", "reason", "idempotency_key"]);
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !fields.has(key))) {
    fail("invalid_catalog_removal", "The catalog removal request is invalid.");
  }
  if (!/^urh-[0-9]{6}$/.test(value.researcher_id || "")
      || !/^[a-f0-9]{64}$/.test(value.base_registry_generation || "")
      || !REMOVAL_ACTIONS.has(value.action)
      || !/^[a-zA-Z0-9-]{16,80}$/.test(value.idempotency_key || "")) {
    fail("invalid_catalog_removal", "Choose a current researcher to remove.");
  }
  const reason = typeof value.reason === "string" ? value.reason.trim() : "";
  if (reason.length > 500) fail("invalid_note", "An optional administrator note must be no more than 500 characters.");
  return { ...value, reason };
}

export function catalogRemovalProfile(current, action) {
  if (!current || !REMOVAL_ACTIONS.has(action)) fail("invalid_catalog_removal", "The removal cannot be prepared.");
  // Publish only eligibility fields. Public projections intentionally omit some
  // claim metadata, which must remain untouched in the canonical registry.
  return {
    status: "inactive",
    pool_visibility: "hidden",
    auto_proposable: false,
  };
}

export function validateCatalogRemovalApproval(current, action, supplied) {
  const expected = catalogRemovalProfile(current, action);
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied)
      || Object.keys(supplied).length !== Object.keys(expected).length
      || Object.keys(expected).some(key => supplied[key] !== expected[key])) {
    fail("invalid_catalog_removal", "A catalog removal can change only eligibility. Reload the request to restore its removal settings.", 409);
  }
  return expected;
}

export function catalogRemovalProposal(current) {
  return {
    display_name: current.name, orcid_id: current.orcid_id, home_unit: current.home_unit,
    ...(current.institution === undefined ? {} : { institution: structuredClone(current.institution) }),
    relationship_note: "", research_summary: current.research_summary,
    source_urls: current.source_urls,
    claims: (current.claims || []).filter(claim => claim.status === "active").map(claim => claim.label),
  };
}

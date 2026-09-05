import { enforceClaimContinuity, enforceSubmittedRelationship, fail, validateAdminProfile, validateSubmission } from "./contract.js";
import { ResearcherSubmissionStore } from "./store.js";
import { catalogRemovalProfile, catalogRemovalProposal, validateCatalogRemoval, validateCatalogRemovalApproval } from "./catalog.js";

const MAX_REQUEST_BYTES = 32_768;
const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
const TERMINAL_PUBLIC_FIELDS = new Set([
  "submission_id", "submission_type", "source_surface", "state", "revision", "created_at", "updated_at",
  "published_at", "published_commit_sha", "published_registry_generation", "deployment_result", "public_verified_at", "failure_code",
]);

function isPublicOrigin(origin, env) {
  return Boolean(origin) && (origin === env.PUBLIC_APP_ORIGIN || /^http:\/\/(?:localhost|127\.0\.0\.1)(?::[0-9]+)?$/.test(origin));
}
function corsHeaders(origin, env) {
  return isPublicOrigin(origin, env) ? {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600",
    Vary: "Origin",
  } : {};
}
function json(status, value, origin = "", env = {}) {
  return new Response(JSON.stringify(value), { status, headers: { ...JSON_HEADERS, ...corsHeaders(origin, env) } });
}
function html(status, value) {
  return new Response(value, { status, headers: {
    "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
  } });
}
function text(status, value, contentType = "text/plain; charset=utf-8") {
  return new Response(value, { status, headers: { "Content-Type": contentType, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
}
function randomToken(bytes = 24) {
  const values = new Uint8Array(bytes);
  crypto.getRandomValues(values);
  return Array.from(values, value => value.toString(16).padStart(2, "0")).join("");
}
async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value)));
  return Array.from(new Uint8Array(digest), item => item.toString(16).padStart(2, "0")).join("");
}
async function receiptToken(env, idempotencyKey) {
  if (!env.RECEIPT_TOKEN_SECRET) fail("service_not_configured", "Submission receipts are not configured.", 503);
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(env.RECEIPT_TOKEN_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(idempotencyKey));
  return Array.from(new Uint8Array(signature), item => item.toString(16).padStart(2, "0")).join("");
}
function safeEqual(left, right) {
  const a = new TextEncoder().encode(String(left || ""));
  const b = new TextEncoder().encode(String(right || ""));
  if (a.length !== b.length) return false;
  let different = 0;
  for (let index = 0; index < a.length; index += 1) different |= a[index] ^ b[index];
  return different === 0;
}
async function readJson(request) {
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_REQUEST_BYTES) fail("request_too_large", "The request is too large.", 413);
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES) fail("request_too_large", "The request is too large.", 413);
  try { return JSON.parse(body); } catch { fail("invalid_json", "The request must be valid JSON."); }
}
function requirePublicOrigin(request, env) {
  const origin = request.headers.get("origin") || "";
  if (!isPublicOrigin(origin, env)) {
    fail("origin_not_allowed", "This site origin is not allowed.", 403);
  }
  return origin;
}
function decodeBase64Url(value) {
  const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}
async function adminActor(request, env, fetchImpl) {
  const assertion = request.headers.get("cf-access-jwt-assertion") || "";
  const teamDomain = String(env.ACCESS_TEAM_DOMAIN || "").replace(/\/$/, "");
  const audience = String(env.ACCESS_AUD || "");
  const allowed = String(env.ADMIN_EMAILS || "").toLocaleLowerCase().split(",").map(value => value.trim()).filter(Boolean);
  if (!assertion || !audience || !/^https:\/\/[a-z0-9.-]+\.cloudflareaccess\.com$/i.test(teamDomain) || !allowed.length) {
    fail("admin_access_required", "Administrator access is required.", 403);
  }
  try {
    const parts = assertion.split(".");
    if (parts.length !== 3) throw new Error("invalid JWT");
    const header = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[0])));
    const payload = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[1])));
    if (header.alg !== "RS256" || !header.kid || payload.iss !== teamDomain) throw new Error("invalid claims");
    const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
    const timestamp = Math.floor(Date.now() / 1000);
    if (!audiences.includes(audience) || !Number.isFinite(payload.exp) || payload.exp <= timestamp || (payload.nbf && payload.nbf > timestamp)) {
      throw new Error("expired or mismatched claims");
    }
    const certificates = await fetchImpl(`${teamDomain}/cdn-cgi/access/certs`, { cf: { cacheEverything: true, cacheTtl: 300 } });
    if (!certificates.ok) throw new Error("signing keys unavailable");
    const jwks = await certificates.json();
    const jwk = (jwks.keys || []).find(key => key.kid === header.kid);
    if (!jwk) throw new Error("signing key not found");
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const verified = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5", key, decodeBase64Url(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
    );
    const email = String(payload.email || "").toLocaleLowerCase();
    if (!verified || !email || !allowed.includes(email)) throw new Error("unauthorized identity");
    return email;
  } catch {
    fail("admin_access_required", "Administrator access is required.", 403);
  }
}
function requireInternal(request, env) {
  const token = String(request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.REGISTRY_WORKFLOW_TOKEN || !safeEqual(token, env.REGISTRY_WORKFLOW_TOKEN)) fail("workflow_access_required", "Workflow access is required.", 403);
}
function publicStatus(row) {
  return Object.fromEntries(Object.entries(row || {}).filter(([key]) => TERMINAL_PUBLIC_FIELDS.has(key)));
}
async function currentManifest(env, fetchImpl) {
  const response = await fetchImpl(env.REGISTRY_MANIFEST_URL, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) fail("registry_unavailable", "The current researcher registry could not be verified.", 503);
  const value = await response.json();
  if (!/^[a-f0-9]{64}$/.test(value.registry_generation || "")) fail("registry_unavailable", "The current researcher registry is invalid.", 503);
  return value;
}
async function currentDirectory(env, fetchImpl) {
  const url = `${env.PUBLIC_SITE_ROOT}/data/researcher_directory.js?admin=${Date.now()}`;
  const response = await fetchImpl(url, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) return null;
  const source = await response.text();
  const start = source.indexOf("{");
  if (start < 0) return null;
  try { return JSON.parse(source.slice(start).trim().replace(/;$/, "")); } catch { return null; }
}
async function currentTeamData(env, fetchImpl) {
  const url = `${env.PUBLIC_SITE_ROOT}/data/opportunity_teams.js?admin=${Date.now()}`;
  const response = await fetchImpl(url, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) return null;
  const source = await response.text();
  const start = source.indexOf("{");
  if (start < 0) return null;
  try { return JSON.parse(source.slice(start).trim().replace(/;$/, "")); } catch { return null; }
}
async function currentFacultyMatches(env, fetchImpl) {
  const url = `${env.PUBLIC_SITE_ROOT}/data/faculty_matches.js?admin=${Date.now()}`;
  const response = await fetchImpl(url, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) return null;
  const source = await response.text();
  const start = source.indexOf("{");
  if (start < 0) return null;
  try { return JSON.parse(source.slice(start).trim().replace(/;$/, "")); } catch { return null; }
}
function normalized(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
function identityNameKey(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\p{M}]+/gu, " ")
    .trim();
}
function sourceIdentityKey(value) {
  try {
    const parsed = new URL(String(value || ""));
    parsed.hash = "";
    return `${parsed.host.toLocaleLowerCase()}${parsed.pathname.replace(/\/+$/, "") || "/"}${parsed.search}`;
  } catch {
    return "";
  }
}
export function duplicateCandidates(directory, detail) {
  if (!directory) return [];
  const profile = detail.proposed_profile || {};
  const names = new Set([profile.display_name, ...(profile.aliases || [])].map(identityNameKey).filter(Boolean));
  const researchers = directory.researchers || [];
  const sourceOwners = new Map();
  for (const researcher of researchers) {
    for (const source of new Set((researcher.source_urls || []).map(sourceIdentityKey).filter(Boolean))) {
      sourceOwners.set(source, (sourceOwners.get(source) || 0) + 1);
    }
  }
  const uniqueSources = new Set((profile.source_urls || [])
    .map(sourceIdentityKey)
    .filter(source => source && sourceOwners.get(source) === 1));
  return researchers.map(researcher => {
    if (detail.researcher_id && researcher.id === detail.researcher_id) return null;
    const reasons = [];
    if ([researcher.name, ...(researcher.aliases || [])].map(identityNameKey).some(name => names.has(name))) reasons.push("same_name");
    if (profile.orcid_id && profile.orcid_id === researcher.orcid_id) reasons.push("same_orcid");
    if ((researcher.source_urls || []).map(sourceIdentityKey).some(source => uniqueSources.has(source))) reasons.push("same_unique_source");
    return reasons.length ? { researcher_id: researcher.id, display_name: researcher.name, reasons } : null;
  }).filter(Boolean);
}
function trustSignals(directory, detail, duplicates) {
  const profile = detail.proposed_profile || {};
  const stableIdVerified = Boolean(detail.researcher_id
    && directory && (directory.researchers || []).some(researcher => researcher.id === detail.researcher_id));
  return {
    identity_status: duplicates.length ? "conflict"
      : detail.researcher_id ? stableIdVerified ? "matched_existing_profile" : "stable_id_unverified"
      : "no_conflicts_found",
    stable_id_verified: stableIdVerified,
    orcid_present: Boolean(profile.orcid_id),
    source_count: (profile.source_urls || []).length,
    identity_conflict_count: duplicates.length,
  };
}
function validatorWarnings(directory, detail, duplicates) {
  const warnings = [];
  if (!directory) warnings.push("The current public directory could not be loaded.");
  else if (directory.registry_generation !== detail.base_registry_generation) warnings.push("The submission is based on an older registry generation and must be rebased and re-reviewed.");
  if (detail.submission_type === "profile_correction" && directory && !(directory.researchers || []).some(row => row.id === detail.researcher_id)) {
    warnings.push("The correction's stable researcher ID is not in the current directory.");
  }
  if (detail.submission_type === "new_researcher_nomination" && !(detail.proposed_profile.source_urls || []).length) warnings.push("A new researcher requires at least one credible source.");
  if (duplicates.length) warnings.push(`${duplicates.length} potential identity conflict${duplicates.length === 1 ? "" : "s"} must be resolved before publication.`);
  return warnings;
}
function materialEffect(directory, teamData, facultyMatches, detail) {
  const current = directory && (directory.researchers || []).find(row => row.id === detail.researcher_id);
  const generatedOutputs = [
    "researcher directory", "team directory", "faculty opportunity matches", "registry manifest",
  ];
  if (!current) return {
    classification: "new_researcher", changed_claims: detail.proposed_profile.claims.length,
    claim_changes: { additions: detail.proposed_profile.claims || [], retirements: [], unchanged: [] },
    generated_outputs: generatedOutputs, affected_matches: [], affected_team_scopes: [],
  };
  const oldClaims = (current.claims || []).filter(claim => claim.status === "active");
  const nextClaims = detail.catalog_action ? oldClaims.map(claim => claim.label) : detail.proposed_profile.claims || [];
  const oldByLabel = new Map(oldClaims.map(claim => [normalized(claim.label), claim.label]));
  const nextByLabel = new Map(nextClaims.map(label => [normalized(label), label]));
  const additions = [...nextByLabel].filter(([key]) => !oldByLabel.has(key)).map(([, label]) => label);
  const retirements = [...oldByLabel].filter(([key]) => !nextByLabel.has(key)).map(([, label]) => label);
  const unchanged = [...oldByLabel].filter(([key]) => nextByLabel.has(key)).map(([, label]) => label);
  const scientific = additions.length > 0 || retirements.length > 0;
  const institutionChanged = detail.proposed_profile.institution !== undefined &&
    ["name", "ror_id"].some(key => (current.institution?.[key] || "") !== (detail.proposed_profile.institution[key] || ""));
  const administrative = institutionChanged || current.home_unit !== detail.proposed_profile.home_unit || current.orcid_id !== detail.proposed_profile.orcid_id;
  const eligibilityChanged = Boolean(detail.catalog_action) || Boolean(detail.approved_profile
    && ["status", "pool_visibility", "auto_proposable"].some(key => detail.approved_profile[key] !== current[key]));
  const affected = (scientific || eligibilityChanged) && teamData ? (teamData.opportunities || []).filter(scope => {
    if ((scope.members || []).some(member => member.faculty_id === current.id)) return true;
    return (scope.roles || []).some(role => [...(role.candidate_ids || []), ...(role.alternative_ids || [])].includes(current.id));
  }).map(scope => scope.id) : [];
  const matchingEntry = facultyMatches && Object.entries(facultyMatches.faculty || {}).find(([, profile]) => profile.researcher_id === current.id);
  const affectedMatches = (scientific || eligibilityChanged) && matchingEntry
    ? ((facultyMatches.pi_matches || {})[matchingEntry[0]] || []).map(match => match.id)
    : [];
  return {
    classification: detail.catalog_action ? "catalog_removal" : scientific ? "scientific" : administrative || eligibilityChanged ? "administrative" : "cosmetic",
    changed_claims: additions.length + retirements.length,
    claim_changes: { additions, retirements, unchanged },
    generated_outputs: generatedOutputs,
    affected_matches: affectedMatches,
    affected_team_scopes: affected,
  };
}
async function notifyOwner(env, submission, fetchImpl, event = "pending") {
  if (!env.RESEND_API_KEY || !env.ADMIN_NOTIFICATION_EMAIL || !env.NOTIFICATION_FROM) return;
  const failed = event === "publication_failed";
  await fetchImpl("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: env.NOTIFICATION_FROM, to: [env.ADMIN_NOTIFICATION_EMAIL],
      subject: failed ? "Funding Finder researcher publication failed" : "Funding Finder researcher request waiting",
      text: failed
        ? `Submission ${submission.submission_id} entered publication_failed. Open the protected queue to inspect and retry it.`
        : `Submission ${submission.submission_id} (${submission.submission_type}) is waiting in the protected researcher review queue.`,
    }),
  });
}
async function dispatchPublication(env, row, fetchImpl) {
  if (!env.GITHUB_DISPATCH_TOKEN) fail("publication_not_configured", "Registry publication is not configured.", 503);
  const response = await fetchImpl(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json",
      "Content-Type": "application/json", "User-Agent": "funding-finder-researcher-intake",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ event_type: "researcher-registry-publish", client_payload: {
      submission_id: row.submission_id, approved_revision: row.revision,
      expected_registry_generation: row.base_registry_generation,
    } }),
  });
  if (!response.ok) fail("publication_dispatch_failed", "The publication workflow could not be started.", 503);
}

function publicationPullRequestTarget(env, value) {
  const repository = String(env.GITHUB_REPOSITORY || "");
  if (!/^[a-z0-9_.-]+\/[a-z0-9_.-]+$/i.test(repository)) {
    fail("publication_not_configured", "Registry publication is not configured.", 503);
  }
  let parsed;
  try { parsed = new URL(String(value || "")); }
  catch { fail("invalid_publication_target", "The publication pull request is invalid."); }
  const prefix = `/${repository}/pull/`;
  const number = parsed.pathname.startsWith(prefix) ? parsed.pathname.slice(prefix.length) : "";
  if (parsed.origin !== "https://github.com" || parsed.search || parsed.hash || !/^[1-9][0-9]*$/.test(number)) {
    fail("invalid_publication_target", "The publication pull request is invalid.");
  }
  return {
    url: `https://github.com/${repository}/pull/${number}`,
    apiUrl: `https://api.github.com/repos/${repository}/pulls/${number}`,
  };
}

async function publicationPullRequest(env, value, fetchImpl) {
  if (!env.GITHUB_DISPATCH_TOKEN) fail("publication_not_configured", "Registry publication is not configured.", 503);
  const target = publicationPullRequestTarget(env, value);
  const response = await fetchImpl(target.apiUrl, { headers: {
    Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json",
    "User-Agent": "funding-finder-researcher-intake", "X-GitHub-Api-Version": "2022-11-28",
  } });
  if (!response.ok) fail("publication_status_unavailable", "The publication pull request could not be verified.", 503);
  const pullRequest = await response.json();
  if (!["open", "closed"].includes(pullRequest.state)
      || (pullRequest.merged && !/^[a-f0-9]{40}$/.test(pullRequest.merge_commit_sha || ""))) {
    fail("publication_status_unavailable", "The publication pull request returned an invalid state.", 503);
  }
  return pullRequest;
}

export async function reconcilePublication({ store, current, expectedRevision, actor, env, fetchImpl, timestamp }) {
  if (current.state !== "publishing" || current.revision !== expectedRevision) {
    fail("state_conflict", "Only the current publishing revision can be reconciled.", 409);
  }
  if (!/^[a-f0-9]{64}$/.test(current.publication_target_registry_generation || "")
      || !current.publication_target_pr_url) {
    fail("publication_target_unavailable", "This publication does not have a recoverable target.", 409);
  }
  const pullRequest = await publicationPullRequest(env, current.publication_target_pr_url, fetchImpl);
  if (pullRequest.state === "open") {
    fail("publication_in_progress", "The publication pull request is still open.", 409);
  }
  if (!pullRequest.merged) {
    const failed = await store.markPublicationFailed(current.submission_id, {
      expectedRevision, failureCode: "publication_pull_request_closed",
      deploymentResult: "pull_request_closed_without_merge", actor,
    }, timestamp);
    if (!failed) fail("state_conflict", "The publication state changed.", 409);
    return failed;
  }
  const manifest = await currentManifest(env, fetchImpl);
  if (manifest.registry_generation !== current.publication_target_registry_generation) {
    fail("publication_not_live", "The merged registry generation is not served yet. Try reconciliation again later.", 409);
  }
  const published = await store.markPublished(current.submission_id, {
    expectedRevision, commitSha: pullRequest.merge_commit_sha,
    registryGeneration: current.publication_target_registry_generation,
    deploymentResult: "github_pages_succeeded_after_admin_reconciliation",
    verifiedAt: timestamp, actor,
  }, timestamp);
  if (!published) fail("state_conflict", "The publication state changed.", 409);
  return published;
}

export function canonicalSortName(value) {
  const name = String(value || "").trim();
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length < 2) return name;
  const finalToken = parts.at(-1);
  const romanSuffix = finalToken !== "I"
    && /^(?=[MDCLXVI]+$)M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$/.test(finalToken);
  const suffix = parts.length > 2 && (/^(?:jr\.?|sr\.?)$/i.test(finalToken) || romanSuffix) ? parts.pop() : "";
  const family = parts.pop();
  return `${family}, ${parts.join(" ")}${suffix ? ` ${suffix}` : ""}`;
}

export function seedApprovedProfile(value, today = new Date().toISOString().slice(0, 10)) {
  const proposed = value.proposed_profile || {};
  const current = value.current_profile;
  const institution = proposed.institution ?? current?.institution;
  const institutionFields = institution === undefined ? {} : { institution: { ...institution } };
  const name = proposed.display_name || current?.name || "";
  const sortName = current?.sort_name && name === current.name ? current.sort_name : canonicalSortName(name);
  const sources = proposed.source_urls?.length ? proposed.source_urls : (current?.source_urls || []);
  const claimKey = label => String(label || "")
    .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const newClaim = label => ({
    claim_id: "", revision: 1, status: "active", label,
    category: "Interdisciplinary research", categories: ["Interdisciplinary research"],
    type: "Capability", evidence: label, source_urls: sources, verified_on: today,
    evidence_level: "administrator_reviewed", legacy_claim_ids: [],
  });

  if (current) {
    const proposedClaims = new Map((proposed.claims || []).map(label => [claimKey(label), label]));
    const currentClaims = current.claims || [];
    const currentKeys = new Set(currentClaims.map(claim => claimKey(claim.label)));
    const claims = currentClaims.map(claim => ({
      ...claim,
      status: proposedClaims.has(claimKey(claim.label)) ? "active" : "retired",
      verified_on: today,
    }));
    for (const [key, label] of proposedClaims) {
      if (!currentKeys.has(key)) claims.push(newClaim(label));
    }
    return {
      display_name: name, sort_name: sortName, aliases: current.aliases || [],
      ...institutionFields,
      orcid_id: Object.prototype.hasOwnProperty.call(proposed, "orcid_id") ? proposed.orcid_id : (current.orcid_id || ""),
      home_unit: proposed.home_unit || current.home_unit,
      relationship: current.relationship, pool_visibility: current.pool_visibility,
      auto_proposable: current.auto_proposable, status: current.status,
      research_summary: Object.prototype.hasOwnProperty.call(proposed, "research_summary") ? proposed.research_summary : current.research_summary,
      source_urls: sources, source_checked_date: today, claims,
    };
  }
  return {
    display_name: name, sort_name: sortName, aliases: [], orcid_id: proposed.orcid_id,
    ...institutionFields,
    home_unit: proposed.home_unit || "Pending administrator classification",
    relationship: "reference_only_researcher", pool_visibility: "hidden",
    auto_proposable: false, status: "active", research_summary: proposed.research_summary,
    source_urls: sources, source_checked_date: today,
    claims: (proposed.claims || []).map(newClaim),
  };
}

export async function validateApprovalAgainstCurrentRegistry(current, submittedProfile, env, fetchImpl) {
  const [manifest, directory] = await Promise.all([
    currentManifest(env, fetchImpl),
    currentDirectory(env, fetchImpl),
  ]);
  if (manifest.registry_generation !== current.base_registry_generation) {
    fail("stale_registry_generation", "The registry changed. Rebase and review this request again.", 409);
  }
  if (!directory || directory.registry_generation !== manifest.registry_generation || !Array.isArray(directory.researchers)) {
    fail("registry_unavailable", "The current researcher directory could not be verified.", 503);
  }
  const currentProfile = directory.researchers.find(row => row.id === current.researcher_id) || null;
  if (current.researcher_id && !currentProfile) fail("registry_unavailable", "The current researcher profile could not be verified.", 503);
  if (current.catalog_action) return validateCatalogRemovalApproval(currentProfile, current.catalog_action, submittedProfile);
  const otherProfiles = directory.researchers.filter(row => row.id !== current.researcher_id);
  const reservedLegacyClaimIds = otherProfiles
    .flatMap(row => (row.claims || []).flatMap(claim => Array.isArray(claim.legacy_claim_ids) ? claim.legacy_claim_ids : []));
  const reservedOrcidIds = otherProfiles.map(row => row.orcid_id).filter(Boolean);
  const validated = enforceSubmittedRelationship(
    validateAdminProfile(submittedProfile, current.researcher_id, reservedLegacyClaimIds, reservedOrcidIds),
    JSON.parse(current.proposed_profile_json),
  );
  const identityConflicts = duplicateCandidates(directory, {
    submission_type: current.submission_type,
    researcher_id: current.researcher_id,
    proposed_profile: validated,
  });
  if (identityConflicts.length) {
    fail("identity_conflict", "This approval still conflicts with an existing researcher identity. Resolve the name, ORCID, or person-specific source before publishing.", 409);
  }
  return enforceClaimContinuity(validated, currentProfile);
}

const ADMIN_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Researcher review | Funding Finder</title>
  <link rel="stylesheet" href="/admin/styles.css">
</head>
<body>
<main>
  <header id="main-hero" class="hero">
    <p class="eyebrow">Funding Finder administration</p>
    <h1>Researcher administration</h1>
    <p>Review profile updates and keep the active researcher catalog current.</p>
  </header>

  <section id="queue-view" aria-labelledby="queue-title">
    <section class="panel" aria-labelledby="catalog-title">
      <h2 id="catalog-title">Manage researcher catalog</h2>
      <p>Remove a retired, departed, or inactive researcher from active matching and proposed teams. Their stable identity and research history remain available.</p>
      <form id="catalog-removal">
        <label for="catalog-search">Find a researcher</label>
        <input id="catalog-search" type="search" placeholder="Search by name or department" autocomplete="off">
        <label for="catalog-researcher">Researcher</label>
        <select id="catalog-researcher" required size="6" aria-describedby="catalog-selection"><option value="">Loading catalog…</option></select>
        <p id="catalog-selection" class="muted" aria-live="polite">Choose a researcher to prepare a removal.</p>
        <label for="catalog-action">Reason for removal</label>
        <select id="catalog-action"><option value="retired">Retired</option><option value="departed">Left institution</option><option value="inactive">Inactive</option></select>
        <label for="catalog-reason">Administrator note</label>
        <input id="catalog-reason" required maxlength="440" autocomplete="off" placeholder="For example, retired at the end of the academic year">
        <p>The next screen shows the change for review. Removal takes effect after the approved publication completes.</p>
        <button id="catalog-submit" type="submit" disabled>Review removal</button>
        <p id="catalog-status" role="alert"></p>
      </form>
    </section>
    <div class="section-heading">
      <div><p class="eyebrow dark">Review queue</p><h2 id="queue-title">Requests needing attention</h2></div>
      <p id="queue-count" class="count"></p>
    </div>
    <div id="queue" aria-live="polite">Loading queue…</div>
  </section>

  <section id="detail" hidden aria-labelledby="detail-title">
    <button id="back" class="text-button" type="button">← Back to queue</button>
    <div class="detail-heading">
      <div><p id="detail-kicker" class="eyebrow dark"></p><h2 id="detail-title"></h2><p id="detail-meta" class="muted"></p></div>
      <span id="detail-state" class="badge"></span>
    </div>

    <div id="warnings" class="notice warning" hidden></div>

    <section class="panel" aria-labelledby="comparison-title">
      <div class="panel-heading"><div><h3 id="comparison-title">What would change</h3><p>Current and proposed public values are aligned field by field.</p></div></div>
      <div class="comparison-head" aria-hidden="true"><span>Field</span><span>Current</span><span>Proposed</span></div>
      <div id="comparison"></div>
      <div id="claim-changes" class="claim-changes"></div>
    </section>

    <div class="summary-grid">
      <section class="panel" aria-labelledby="identity-title"><h3 id="identity-title">Identity review</h3><div id="identity"></div></section>
      <section class="panel" aria-labelledby="effect-title"><h3 id="effect-title">Publication effect</h3><div id="effect"></div></section>
    </div>

    <section class="panel" aria-labelledby="submission-title">
      <h3 id="submission-title">Submission details</h3><div id="submission-details"></div>
    </section>

    <section class="panel decision" aria-labelledby="decision-title">
      <h3 id="decision-title">Administrator decision</h3>
      <p>The approved record below preserves administrator-controlled policy, evidence, and identifiers. The proposal above contains only fields a submitter is allowed to suggest.</p>
      <div id="approved-summary" class="approved-summary"></div>
      <details class="technical"><summary>Advanced: inspect or edit the complete registry record</summary>
        <p>Use this only when the generated approved record needs a policy or evidence correction.</p>
        <label for="approved">Complete approved registry record (JSON)</label>
        <textarea id="approved" rows="22" spellcheck="false"></textarea>
      </details>
      <details class="technical"><summary>Technical submission data</summary>
        <div class="technical-grid"><div><h4>Current registry data</h4><pre id="technical-current"></pre></div><div><h4>Submitted proposal</h4><pre id="technical-proposed"></pre></div></div>
      </details>
      <label for="reason">Administrator reason <span class="muted">(required when requesting changes or rejecting)</span></label>
      <input id="reason" maxlength="500" autocomplete="off">
      <div class="actions">
        <button data-action="start_review" type="button">Start review</button>
        <button data-action="rebase" type="button">Rebase onto current registry</button>
        <button data-action="approve" class="primary" type="button">Approve and start publication</button>
        <button data-action="request_changes" type="button">Request changes</button>
        <button data-action="reject" class="danger" type="button">Reject</button>
        <button data-action="retry_publish" class="primary" type="button">Retry publication</button>
        <button data-action="reconcile_publish" type="button">Check publication result</button>
      </div>
      <p id="action-note" class="muted"></p>
      <div id="admin-status" class="notice error" role="alert" hidden></div>
    </section>
  </section>

  <section id="outcome" class="outcome" hidden tabindex="-1" aria-labelledby="outcome-title">
    <p class="eyebrow dark">Administrator action complete</p>
    <div id="outcome-icon" class="outcome-icon" aria-hidden="true">✓</div>
    <h2 id="outcome-title"></h2>
    <p id="outcome-message" class="outcome-message"></p>
    <dl id="outcome-details" class="outcome-details"></dl>
    <div id="outcome-confirmation" class="notice"></div>
    <div class="actions centered"><button id="outcome-review" type="button" hidden>Continue reviewing</button><button id="outcome-back" class="primary" type="button">Back to queue</button></div>
  </section>
</main>
<script src="/admin/app.js"></script>
</body>
</html>`;
const ADMIN_CSS = `:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17293f;background:#f4f7fb;line-height:1.5}*{box-sizing:border-box}body{margin:0}button,input,textarea,select{font:inherit}button{cursor:pointer;border:1px solid #9fb0c2;border-radius:8px;background:#fff;color:#17293f;padding:9px 13px;font-weight:750}button:hover:not(:disabled){background:#edf3fa}button:focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #8ab4ff;outline-offset:2px}button:disabled{cursor:not-allowed;opacity:.5}button.primary{color:#fff;background:#0057b8;border-color:#0057b8}button.primary:hover:not(:disabled){background:#00468f}button.danger{color:#9d2027;border-color:#d9a0a4}main{width:min(1120px,calc(100% - 32px));margin:auto;padding:28px 0 56px}.hero{padding:28px 34px;color:#fff;background:#14245f;border-radius:18px;box-shadow:0 10px 30px rgba(24,42,77,.08)}.hero h1{font-size:clamp(2rem,5vw,3rem);line-height:1.1;margin:8px 0}.hero p:last-child{margin:0;max-width:780px;font-size:1.08rem}.eyebrow{margin:0;font-size:.82rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.eyebrow.dark{color:#51657b}.section-heading,.detail-heading,.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.section-heading{margin:32px 0 14px}.section-heading h2,.detail-heading h2{margin:2px 0 0}.count{margin:8px 0;color:#51657b}.queue-list{display:grid;gap:12px}.queue-card{display:grid;grid-template-columns:minmax(200px,1.4fr) minmax(0,3fr) auto;gap:22px;align-items:center;background:#fff;border:1px solid #d8e1eb;border-radius:12px;padding:18px 20px;box-shadow:0 3px 10px rgba(23,41,63,.03)}.queue-card h3{margin:0 0 8px;font-size:1.15rem}.queue-card dl,.compact-dl,.outcome-details{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;margin:0}.queue-card dt,.compact-dl dt,.outcome-details dt{font-weight:750;color:#51657b}.queue-card dd,.compact-dl dd,.outcome-details dd{margin:0;min-width:0;overflow-wrap:anywhere}.tags{display:flex;flex-wrap:wrap;gap:6px}.badge,.tag{display:inline-flex;align-items:center;width:max-content;border-radius:999px;padding:3px 9px;background:#e8eef7;color:#273b54;font-size:.8rem;font-weight:800}.badge.conflict,.tag.conflict{background:#fff0d5;color:#744600}.badge.good,.tag.good{background:#def5e8;color:#155c35}.badge.pending{background:#e8eef7}.badge.review{background:#e1edff;color:#134f91}.badge.failed{background:#fee5e7;color:#8d1f28}.empty{padding:40px 24px;text-align:center;background:#fff;border:1px dashed #bdcad8;border-radius:12px}.text-button{border:0;background:transparent;padding:8px 0;color:#0057b8}.detail-heading{margin:16px 0 20px;align-items:center}.muted{color:#607388;font-weight:400}.panel{min-width:0;margin-top:14px;padding:20px;background:#fff;border:1px solid #d8e1eb;border-radius:12px}.panel h3{margin:0 0 10px}.panel h4{margin:8px 0}.panel p{margin:4px 0}.comparison-head,.comparison-row{display:grid;grid-template-columns:150px minmax(0,1fr) minmax(0,1fr);gap:18px}.comparison-head{padding:10px 12px;color:#51657b;font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;border-bottom:2px solid #d8e1eb}.comparison-row{padding:13px 12px;border-bottom:1px solid #e5ebf2}.comparison-row:last-child{border-bottom:0}.field-label{font-weight:800}.value{min-width:0;overflow-wrap:anywhere}.value.empty{padding:0;text-align:left;background:transparent;border:0;color:#738397;font-style:italic}.link-list,.clean-list{margin:4px 0;padding-left:20px}.link-list a{overflow-wrap:anywhere;color:#0057b8}.claim-changes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:16px}.claim-group{padding:14px;border-radius:10px;background:#f4f7fb}.claim-group h4{margin:0 0 6px}.claim-group.added{background:#eaf7ef}.claim-group.retired{background:#fff1f1}.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.notice{padding:13px 15px;border-radius:9px;background:#edf4ff;border:1px solid #c6daf6}.notice.warning{margin:12px 0;background:#fff7e6;border-color:#edd19b}.notice.error{margin-top:12px;background:#fff0f1;border-color:#e9b9bd;color:#812129}.notice ul{margin:3px 0;padding-left:20px}.decision>p{max-width:850px}.approved-summary{margin:14px 0;padding:14px;background:#f6f8fb;border-radius:9px}.technical{margin-top:12px;border-top:1px solid #e1e7ee;padding-top:12px}.technical summary{cursor:pointer;color:#31485f;font-weight:750}.technical p{color:#607388}.technical-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.technical-grid>div{min-width:0}pre{max-height:420px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;border:1px solid #e0e6ed;border-radius:8px;padding:10px;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}label{display:block;margin-top:14px;font-weight:750}textarea,input,select{width:100%;margin-top:6px;padding:10px;border:1px solid #9db0c5;border-radius:8px;background:#fff;color:#17293f}textarea{resize:vertical;font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.actions.centered{justify-content:center}.outcome{max-width:720px;margin:34px auto 0;padding:36px;background:#fff;border:1px solid #d8e1eb;border-radius:16px;text-align:center;box-shadow:0 10px 30px rgba(24,42,77,.07)}.outcome-icon{display:grid;place-items:center;width:58px;height:58px;margin:16px auto;border-radius:50%;background:#def5e8;color:#155c35;font-size:1.8rem;font-weight:900}.outcome h2{margin:8px 0;font-size:2rem}.outcome-message{font-size:1.08rem;color:#51657b}.outcome-details{max-width:560px;margin:24px auto;text-align:left}.outcome .notice{text-align:left}@media(max-width:820px){.queue-card{grid-template-columns:1fr}.queue-card button{width:100%}.summary-grid,.claim-changes,.technical-grid{grid-template-columns:1fr}.comparison-head{display:none}.comparison-row{grid-template-columns:1fr;gap:6px}.comparison-row .value:before{display:block;color:#607388;font-size:.75rem;font-weight:800;text-transform:uppercase}.comparison-row .value.current:before{content:"Current"}.comparison-row .value.proposed:before{content:"Proposed"}}@media(max-width:520px){main{width:min(100% - 20px,1120px);padding-top:10px}.hero{padding:22px 20px;border-radius:12px}.section-heading,.detail-heading{align-items:flex-start;flex-direction:column}.panel{padding:16px}}`;
const ADMIN_JS = `(() => {
  "use strict";
  let active = null;
  const hero = document.getElementById("main-hero");
  const queueView = document.getElementById("queue-view");
  const queue = document.getElementById("queue");
  const detail = document.getElementById("detail");
  const outcome = document.getElementById("outcome");
  const status = document.getElementById("admin-status");
  const approvedEditor = document.getElementById("approved");
  let catalog = null;
  let catalogRequestKey = null;
  const catalogSearch = document.getElementById("catalog-search");
  const catalogResearcher = document.getElementById("catalog-researcher");
  const catalogStatus = document.getElementById("catalog-status");
  const catalogSubmit = document.getElementById("catalog-submit");
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\\"": "&quot;", "'": "&#39;",
  })[character]);
  const labels = {
    profile_correction: "Profile correction", new_researcher_nomination: "New researcher nomination",
    faculty_interests: "Faculty interests", team_match: "Team Match",
    pending: "Pending", under_review: "Under review", changes_requested: "Changes requested",
    approved: "Approved", publishing: "Publishing", publication_failed: "Publication failed",
    published: "Published", rejected: "Rejected", superseded: "Superseded",
    cosmetic: "Cosmetic", administrative: "Administrative", scientific: "Scientific", new_researcher: "New researcher",
    hajim_core_faculty: "Hajim core faculty", internal_affiliated_researcher: "Internal affiliated researcher",
    external_collaborator: "External collaborator", reference_only_researcher: "Reference-only researcher",
    department: "Department", institution: "Institution", approved_collaborator: "Approved collaborator",
    reference_only: "Reference only", hidden: "Hidden", active: "Active", inactive: "Inactive", departed: "Departed",
    catalog_removal: "Catalog removal", retired: "Retired",
  };
  function label(value) { return labels[value] || String(value || "").replace(/_/g, " "); }
  function formatTime(value) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value || "Not available") : new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium", timeStyle: "short",
    }).format(parsed);
  }
  function stateClass(value) {
    if (value === "under_review" || value === "changes_requested") return "review";
    if (value === "publication_failed" || value === "rejected") return "failed";
    if (value === "published") return "good";
    return "pending";
  }
  function valueHtml(value) {
    if (value == null || value === "") return '<span class="value empty">Not provided</span>';
    return '<span class="value">' + esc(value) + "</span>";
  }
  function listHtml(values, emptyText) {
    const items = Array.isArray(values) ? values.filter(Boolean) : [];
    if (!items.length) return '<span class="value empty">' + esc(emptyText || "None") + "</span>";
    return '<ul class="clean-list">' + items.map(value => "<li>" + esc(value) + "</li>").join("") + "</ul>";
  }
  function linksHtml(values) {
    const items = Array.isArray(values) ? values.filter(value => String(value).startsWith("https://")) : [];
    if (!items.length) return '<span class="value empty">No source links</span>';
    return '<ul class="link-list">' + items.map(value => '<li><a href="' + esc(value) + '" target="_blank" rel="noreferrer">' + esc(value) + "</a></li>").join("") + "</ul>";
  }
  async function api(path, options) {
    const response = await fetch(path, options);
    const value = await response.json();
    if (!response.ok) {
      const error = new Error(value.error && value.error.message || "Request failed");
      error.code = value.error && value.error.code || "request_failed";
      error.status = response.status;
      throw error;
    }
    return value;
  }
  function identityText(signals) {
    if (signals.identity_conflict_count) return signals.identity_conflict_count + " identity conflict" + (signals.identity_conflict_count === 1 ? "" : "s");
    if (signals.stable_id_verified) return "Existing profile verified";
    if (signals.identity_status === "stable_id_unverified") return "Researcher ID could not be verified";
    return "No existing identity conflict found";
  }
  function effectText(effect) {
    const claims = effect.changed_claims === 1 ? "1 research-interest change" : effect.changed_claims + " research-interest changes";
    const teams = effect.affected_team_scopes.length === 1 ? "1 team scope" : effect.affected_team_scopes.length + " team scopes";
    return label(effect.classification) + " · " + claims + " · " + teams;
  }
  async function load() {
    active = null;
    detail.hidden = true;
    outcome.hidden = true;
    queueView.hidden = false;
    hero.hidden = false;
    queue.textContent = "Loading queue…";
    loadCatalog().catch(error => { catalogStatus.textContent = error.message; });
    const value = await api("/admin/api/submissions");
    document.getElementById("queue-count").textContent = value.submissions.length + (value.submissions.length === 1 ? " request" : " requests");
    if (!value.submissions.length) {
      queue.innerHTML = '<div class="empty"><h3>The queue is clear</h3><p>There are no active researcher requests.</p></div>';
      return;
    }
    queue.innerHTML = '<div class="queue-list">' + value.submissions.map(item => {
      const conflict = item.trust_signals.identity_conflict_count > 0;
      return '<article class="queue-card">' +
        '<div><h3>' + esc(item.proposed_profile.display_name) + '</h3><div class="tags"><span class="badge ' + stateClass(item.state) + '">' + esc(label(item.state)) + '</span><span class="tag ' + (conflict ? "conflict" : "good") + '">' + esc(identityText(item.trust_signals)) + "</span></div></div>" +
        '<dl><dt>Request</dt><dd>' + esc(item.catalog_action ? "Catalog removal · " + label(item.catalog_action) : label(item.submission_type)) + '</dd><dt>Submitted from</dt><dd>' + esc(item.catalog_action ? "Admin catalog" : label(item.source_surface)) + '</dd><dt>Effect</dt><dd>' + esc(effectText(item.material_effect)) + '</dd><dt>Submitted</dt><dd>' + esc(formatTime(item.created_at)) + "</dd></dl>" +
        '<button type="button" data-id="' + esc(item.submission_id) + '">Open review</button></article>';
    }).join("") + "</div>";
    queue.querySelectorAll("[data-id]").forEach(button => { button.onclick = () => open(button.dataset.id).catch(showFatal); });
  }
  function comparisonRow(field, current, proposed, renderer) {
    const render = renderer || valueHtml;
    return '<div class="comparison-row"><div class="field-label">' + esc(field) + '</div><div class="value current">' + render(current) + '</div><div class="value proposed">' + render(proposed) + "</div></div>";
  }
  function renderCatalog() {
    const selectedId = catalogResearcher.value;
    const query = catalogSearch.value.trim().toLocaleLowerCase();
    const people = (catalog?.researchers || []).filter(row => !query || (row.name + " " + row.home_unit).toLocaleLowerCase().includes(query));
    catalogResearcher.innerHTML = '<option value="">Choose a researcher</option>' + people.map(row =>
      '<option value="' + esc(row.id) + '"' + (row.status !== "active" && row.pool_visibility === "hidden" ? " disabled" : "") + '>' +
      esc(row.name + " · " + row.home_unit + " · " + label(row.status)) + "</option>").join("");
    catalogResearcher.value = people.some(row => row.id === selectedId) ? selectedId : "";
    updateCatalogSelection();
  }
  function updateCatalogSelection() {
    const person = catalog?.researchers.find(row => row.id === catalogResearcher.value);
    catalogSubmit.disabled = !person || (person.status !== "active" && person.pool_visibility === "hidden");
    document.getElementById("catalog-selection").textContent = person
      ? "Removal selected for " + person.name + " (" + person.home_unit + "). Their research claims and history will be preserved."
      : "Choose a researcher to prepare a removal.";
  }
  async function loadCatalog() {
    catalog = null;
    catalogSubmit.disabled = true;
    catalogStatus.textContent = "";
    catalog = await api("/admin/api/catalog");
    renderCatalog();
  }
  catalogSearch.addEventListener("input", renderCatalog);
  catalogResearcher.addEventListener("change", updateCatalogSelection);
  document.getElementById("catalog-removal").addEventListener("input", () => { catalogRequestKey = null; });
  document.getElementById("catalog-removal").addEventListener("submit", async event => {
    event.preventDefault();
    if (!catalog || catalogSubmit.disabled || !catalogResearcher.value) return;
    catalogSubmit.disabled = true;
    catalogStatus.textContent = "";
    catalogRequestKey ||= crypto.randomUUID();
    try {
      const response = await api("/admin/api/catalog", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          researcher_id: catalogResearcher.value, base_registry_generation: catalog.registry_generation,
          action: document.getElementById("catalog-action").value, reason: document.getElementById("catalog-reason").value.trim(),
          idempotency_key: catalogRequestKey,
        }),
      });
      await open(response.submission_id);
      catalogRequestKey = null;
    } catch (error) {
      catalogStatus.textContent = error.message;
      updateCatalogSelection();
    }
  });
  function renderComparison() {
    const current = active.current_profile || {};
    const proposed = active.proposed_profile || {};
    document.getElementById("comparison").innerHTML =
      comparisonRow("Name", current.name, proposed.display_name) +
      comparisonRow("Home unit", current.home_unit, proposed.home_unit) +
      comparisonRow("Institution", current.institution?.name, proposed.institution?.name ?? current.institution?.name) +
      comparisonRow("ROR identity", current.institution?.ror_id, proposed.institution?.ror_id ?? current.institution?.ror_id) +
      comparisonRow("ORCID", current.orcid_id, proposed.orcid_id) +
      comparisonRow("Research summary", current.research_summary, proposed.research_summary) +
      comparisonRow("Source links", current.source_urls, proposed.source_urls, linksHtml) +
      (active.catalog_action ? comparisonRow("Catalog status", label(current.status), label(active.approved_profile.status)) +
        comparisonRow("Visibility", label(current.pool_visibility), "Hidden") +
        comparisonRow("Automatically proposed", current.auto_proposable ? "Yes" : "No", "No") : "");
    const changes = active.material_effect.claim_changes;
    document.getElementById("claim-changes").innerHTML =
      '<div class="claim-group added"><h4>Added interests</h4>' + listHtml(changes.additions, "No additions") + "</div>" +
      '<div class="claim-group retired"><h4>Retired interests</h4>' + listHtml(changes.retirements, "No retirements") + "</div>" +
      '<div class="claim-group"><h4>Unchanged interests</h4>' + listHtml(changes.unchanged, "None") + "</div>";
  }
  function renderIdentity() {
    const signals = active.trust_signals;
    const conflicts = active.duplicate_candidates || [];
    let html = '<dl class="compact-dl"><dt>Status</dt><dd>' + esc(identityText(signals)) + '</dd><dt>Stable ID</dt><dd>' + (signals.stable_id_verified ? "Verified" : "Not applicable") + '</dd><dt>ORCID</dt><dd>' + (signals.orcid_present ? "Provided" : "Not provided") + '</dd><dt>Sources</dt><dd>' + esc(signals.source_count) + "</dd></dl>";
    if (conflicts.length) {
      html += '<h4>Profiles requiring resolution</h4><ul class="clean-list">' + conflicts.map(candidate => "<li>" + esc(candidate.display_name) + " (" + esc(candidate.researcher_id) + ") — " + esc(candidate.reasons.map(label).join(", ")) + "</li>").join("") + "</ul>";
    } else {
      html += '<p class="muted">Shared directory pages are ignored as identity evidence.</p>';
    }
    document.getElementById("identity").innerHTML = html;
  }
  function renderEffect() {
    const effect = active.material_effect;
    document.getElementById("effect").innerHTML = '<dl class="compact-dl"><dt>Classification</dt><dd>' + esc(label(effect.classification)) + '</dd><dt>Research interests</dt><dd>' + esc(effect.changed_claims) + ' changed</dd><dt>Opportunity matches</dt><dd>' + esc(effect.affected_matches.length) + '</dd><dt>Team scopes</dt><dd>' + esc(effect.affected_team_scopes.length) + '</dd></dl><h4>Generated files</h4>' + listHtml(effect.generated_outputs, "None");
  }
  function renderApprovedSummary(profile = {}) {
    if (active?.catalog_action) profile = { ...active.current_profile, display_name: active.current_profile?.name, ...profile };
    const activeClaims = (profile.claims || []).filter(claim => claim.status === "active").map(claim => claim.label);
    const retiredClaims = (profile.claims || []).filter(claim => claim.status === "retired").map(claim => claim.label);
    document.getElementById("approved-summary").innerHTML = '<dl class="compact-dl"><dt>Name</dt><dd>' + esc(profile.display_name) + '</dd><dt>Catalog status</dt><dd>' + esc(label(profile.status)) + '</dd><dt>Relationship</dt><dd>' + esc(label(profile.relationship)) + '</dd><dt>Visibility</dt><dd>' + esc(label(profile.pool_visibility)) + '</dd><dt>Active interests</dt><dd>' + esc(activeClaims.length) + '</dd><dt>Retired interests</dt><dd>' + esc(retiredClaims.length) + '</dd><dt>Automatically proposed</dt><dd>' + (profile.auto_proposable ? "Yes" : "No") + "</dd></dl>";
  }
  function previewApprovedEditor() {
    try {
      const profile = JSON.parse(approvedEditor.value);
      if (!profile || typeof profile !== "object" || Array.isArray(profile)) throw new Error("invalid profile");
      approvedEditor.removeAttribute("aria-invalid");
      renderApprovedSummary(profile);
      return { ok: true, profile };
    } catch {
      approvedEditor.setAttribute("aria-invalid", "true");
      document.getElementById("approved-summary").innerHTML = '<div class="notice warning">The approval preview is unavailable until the complete registry record contains valid JSON.</div>';
      return { ok: false, profile: null };
    }
  }
  function renderWarnings() {
    const warnings = active.validator_warnings || [];
    const box = document.getElementById("warnings");
    box.hidden = !warnings.length;
    box.innerHTML = warnings.length ? "<strong>Resolve before publication</strong><ul>" + warnings.map(warning => "<li>" + esc(warning) + "</li>").join("") + "</ul>" : "";
  }
  function renderActions() {
    const visible = {
      pending: ["start_review", "request_changes", "reject"],
      under_review: ["approve", "request_changes", "reject"],
      changes_requested: ["start_review", "reject"],
      approved: ["retry_publish"],
      publication_failed: ["retry_publish"],
      publishing: [],
    }[active.state] || [];
    const stale = (active.validator_warnings || []).some(warning => warning.includes("older registry generation"));
    if (stale && ["pending", "under_review", "changes_requested", "approved", "publication_failed"].includes(active.state)) visible.unshift("rebase");
    if (active.publication_target_pr_url && active.state === "publishing") visible.push("reconcile_publish");
    document.querySelectorAll("[data-action]").forEach(button => {
      button.hidden = !visible.includes(button.dataset.action);
      button.disabled = false;
    });
    const conflict = active.trust_signals.identity_conflict_count > 0;
    const publicationButton = Array.from(document.querySelectorAll('[data-action="approve"], [data-action="retry_publish"]')).find(button => !button.hidden);
    if (publicationButton && !publicationButton.hidden && stale) publicationButton.disabled = true;
    document.getElementById("action-note").textContent = conflict ? "Resolve the identity conflict in the advanced approved record. The server will verify it again before publication." : stale ? "Rebase this request before publication." : active.state === "pending" ? "Start review before approval becomes available." : "";
  }
  async function open(id) {
    active = await api("/admin/api/submissions/" + encodeURIComponent(id));
    queueView.hidden = true;
    outcome.hidden = true;
    detail.hidden = false;
    hero.hidden = true;
    document.getElementById("detail-kicker").textContent = active.catalog_action ? "Catalog removal · " + label(active.catalog_action) : label(active.submission_type);
    document.getElementById("detail-title").textContent = active.proposed_profile.display_name;
    document.getElementById("detail-meta").textContent = "Submitted " + formatTime(active.created_at) + " · " + active.submission_id;
    const state = document.getElementById("detail-state");
    state.textContent = label(active.state);
    state.className = "badge " + stateClass(active.state);
    renderWarnings();
    renderComparison();
    renderIdentity();
    renderEffect();
    document.getElementById("submission-details").innerHTML = '<dl class="compact-dl"><dt>Source</dt><dd>' + esc(label(active.source_surface)) + '</dd><dt>Contact</dt><dd>' + esc(active.contact_email || "Not provided") + '</dd><dt>Submitter note</dt><dd>' + esc(active.submitter_note || "None") + '</dd><dt>Registry generation</dt><dd>' + esc(active.base_registry_generation) + "</dd></dl>";
    approvedEditor.value = JSON.stringify(active.approved_profile, null, 2);
    approvedEditor.removeAttribute("aria-invalid");
    renderApprovedSummary(active.approved_profile);
    document.getElementById("technical-current").textContent = JSON.stringify(active.current_profile, null, 2);
    document.getElementById("technical-proposed").textContent = JSON.stringify(active.proposed_profile, null, 2);
    document.getElementById("reason").value = active.catalog_action ? active.administrator_reason || "" : "";
    status.hidden = true;
    status.textContent = "";
    renderActions();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function outcomeCopy(action, state) {
    if (action === "reject") return ["Request rejected", "This researcher request has been removed from the active review queue.", "No registry change was published."];
    if (action === "request_changes") return ["Changes requested", "The decision and reason were recorded for this researcher request.", "No registry change was published."];
    if (action === "start_review") return ["Review started", "The request is now marked as under review.", "No registry change was published."];
    if (action === "rebase") return ["Request rebased", "The request now uses the current researcher registry and requires review again.", "No registry change was published."];
    if (action === "approve" || action === "retry_publish") return ["Publication started", "A checks-gated registry publication has been dispatched.", "The public registry will not change unless its pull request passes the required checks and merges."];
    if (action === "reconcile_publish" && state === "published") return ["Publication verified", "The researcher registry change is live.", "The queue record is now complete."];
    if (action === "reconcile_publish" && state === "publication_failed") return ["Publication did not complete", "The publication result was recorded for follow-up.", "Review the failure before retrying."];
    return ["Action recorded", "The researcher request was updated.", "Review the queue for its current status."];
  }
  function showOutcome(action, response, reason, approvedProfile) {
    const copy = outcomeCopy(action, response.state);
    detail.hidden = true;
    queueView.hidden = true;
    outcome.hidden = false;
    hero.hidden = true;
    document.getElementById("outcome-title").textContent = copy[0];
    document.getElementById("outcome-message").textContent = copy[1];
    document.getElementById("outcome-confirmation").textContent = copy[2];
    const researcherName = approvedProfile && approvedProfile.display_name || active.proposed_profile.display_name;
    document.getElementById("outcome-details").innerHTML = '<dt>Researcher</dt><dd>' + esc(researcherName) + '</dd><dt>Submission</dt><dd>' + esc(response.submission_id) + '</dd><dt>State</dt><dd>' + esc(label(response.state)) + '</dd><dt>Recorded</dt><dd>' + esc(formatTime(response.updated_at)) + '</dd>' + (reason ? '<dt>Reason</dt><dd>' + esc(reason) + "</dd>" : "");
    const continueButton = document.getElementById("outcome-review");
    continueButton.hidden = !["under_review", "changes_requested"].includes(response.state);
    continueButton.onclick = () => open(response.submission_id).catch(showFatal);
    outcome.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function showFatal(error) {
    queue.textContent = error.message || "The administrator page could not be loaded.";
  }
  document.getElementById("back").onclick = () => load().catch(showFatal);
  document.getElementById("outcome-back").onclick = () => load().catch(showFatal);
  document.querySelectorAll("[data-action]").forEach(button => {
    button.onclick = async () => {
      if (!active) return;
      const action = button.dataset.action;
      const reason = document.getElementById("reason").value.trim();
      if (["request_changes", "reject"].includes(action) && !reason) {
        status.textContent = "Enter an administrator reason before completing this action.";
        status.hidden = false;
        document.getElementById("reason").focus();
        return;
      }
      let profile = null;
      if (["approve", "retry_publish"].includes(action)) {
        const preview = previewApprovedEditor();
        if (!preview.ok) {
          status.textContent = "The complete approved registry record contains invalid JSON.";
          status.hidden = false;
          return;
        }
        profile = preview.profile;
      }
      document.querySelectorAll("[data-action]").forEach(actionButton => { actionButton.disabled = true; });
      status.hidden = true;
      try {
        const actionReason = action === "reconcile_publish" ? "" : reason;
        const response = await api("/admin/api/submissions/" + encodeURIComponent(active.submission_id) + "/action", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, expected_revision: active.revision, approved_profile: profile, reason: actionReason }),
        });
        const outcomeReason = action === "reconcile_publish" ? "" : (actionReason || response.administrator_reason || "");
        showOutcome(action, response, outcomeReason, profile);
      } catch (error) {
        const submissionId = active.submission_id;
        if (["approve", "retry_publish"].includes(action) && error.status >= 500) {
          try { await open(submissionId); } catch { /* Keep the original publication error visible. */ }
        }
        status.textContent = error.message;
        status.hidden = false;
        renderActions();
      }
    };
  });
  approvedEditor.addEventListener("input", previewApprovedEditor);
  load().catch(showFatal);
})();`;

export { ADMIN_CSS, ADMIN_HTML, ADMIN_JS };

export function createHandler({ storeFactory = env => new ResearcherSubmissionStore(env.SUBMISSIONS_DB), fetchImpl = (...args) => fetch(...args), now = () => new Date() } = {}) {
  return async function handle(request, env, context = { waitUntil() {} }) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/$/, "") || "/";
    const origin = request.headers.get("origin") || "";
    try {
      if (request.method === "OPTIONS") {
        requirePublicOrigin(request, env);
        return new Response(null, { status: 204, headers: corsHeaders(origin, env) });
      }
      if (path === "/health" && request.method === "GET") return json(200, { ok: true, schema_version: 1 }, origin, env);
      const store = storeFactory(env);
      if (path === "/submissions" && request.method === "POST") {
        const allowedOrigin = requirePublicOrigin(request, env);
        const ip = request.headers.get("cf-connecting-ip") || "unknown";
        if (env.SUBMISSION_RATE_LIMITER && !(await env.SUBMISSION_RATE_LIMITER.limit({ key: await sha256(ip) })).success) {
          fail("rate_limited", "Too many submissions were attempted. Please wait and try again.", 429);
        }
        const submission = validateSubmission(await readJson(request));
        const payloadHash = await sha256(JSON.stringify(submission));
        const duplicateResponse = async row => {
          if (!safeEqual(row.payload_hash, payloadHash)) fail("idempotency_conflict", "That submission identifier was already used for different content.", 409);
          const token = await receiptToken(env, submission.idempotency_key);
          return json(200, { submission_id: row.submission_id, state: row.state, duplicate: true, status_url: `${url.origin}/status/${row.submission_id}?token=${token}` }, allowedOrigin, env);
        };
        const existing = await store.byIdempotencyKey(submission.idempotency_key);
        if (existing) return await duplicateResponse(existing);
        const submissionId = `rs_${randomToken(12)}`;
        const submissionReceiptToken = await receiptToken(env, submission.idempotency_key);
        const createdAt = now().toISOString();
        let row;
        try {
          row = await store.create({
            submissionId, idempotencyKey: submission.idempotency_key, payloadHash,
            receiptTokenHash: await sha256(submissionReceiptToken), submissionType: submission.submission_type,
            sourceSurface: submission.source_surface, researcherId: submission.researcher_id,
            baseRegistryGeneration: submission.base_registry_generation,
            proposedProfile: submission.proposed_profile, contactEmail: submission.submitter.contact_email,
            submitterNote: submission.submitter.note, privacyNoticeVersion: submission.consent.privacy_notice_version,
            createdAt,
          });
        } catch (error) {
          const winner = await store.byIdempotencyKey(submission.idempotency_key);
          if (!winner) throw error;
          return await duplicateResponse(winner);
        }
        context.waitUntil(notifyOwner(env, row, fetchImpl).catch(() => undefined));
        return json(201, { submission_id: submissionId, state: "pending", duplicate: false, status_url: `${url.origin}/status/${submissionId}?token=${submissionReceiptToken}` }, allowedOrigin, env);
      }
      const statusMatch = path.match(/^\/status\/(rs_[a-f0-9]{24})$/);
      if (statusMatch && request.method === "GET") {
        const token = url.searchParams.get("token") || "";
        const row = token ? await store.publicStatus(statusMatch[1], await sha256(token)) : null;
        if (!row) return html(404, "<h1>Status not found</h1><p>Use the complete private receipt link from the original submission.</p>");
        return html(200, `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Researcher request status</title></head><body><main><h1>Researcher request status</h1><p>Submission <code>${row.submission_id}</code></p><p>Current state: <strong>${row.state}</strong></p><p>Last updated: ${row.updated_at}</p>${row.published_registry_generation ? `<p>Published registry generation: <code>${row.published_registry_generation}</code></p>` : ""}<p>No contact information or private note is shown here.</p></main></body></html>`);
      }
      if (path === "/admin/styles.css" && request.method === "GET") { await adminActor(request, env, fetchImpl); return text(200, ADMIN_CSS, "text/css; charset=utf-8"); }
      if (path === "/admin/app.js" && request.method === "GET") { await adminActor(request, env, fetchImpl); return text(200, ADMIN_JS, "text/javascript; charset=utf-8"); }
      if (path === "/admin" && request.method === "GET") { await adminActor(request, env, fetchImpl); return html(200, ADMIN_HTML); }
      if (path === "/admin/api/catalog" && ["GET", "POST"].includes(request.method)) {
        const actor = await adminActor(request, env, fetchImpl);
        if (request.method === "POST" && origin && origin !== url.origin) fail("admin_origin_not_allowed", "Administrator origin is not allowed.", 403);
        const removal = request.method === "POST" ? validateCatalogRemoval(await readJson(request)) : null;
        // Replay accepted requests even if the public generation has since changed.
        const key = removal ? "catalog-" + removal.idempotency_key : "";
        const payloadHash = removal ? await sha256(JSON.stringify(removal)) : "";
        const replay = row => {
          if (!safeEqual(row.payload_hash, payloadHash) || !row.catalog_action) fail("idempotency_conflict", "That request identifier was already used for different content.", 409);
          return json(200, { submission_id: row.submission_id, state: row.state, duplicate: true });
        };
        const existing = removal ? await store.byIdempotencyKey(key) : null;
        if (existing) return replay(existing);
        const [manifest, directory] = await Promise.all([currentManifest(env, fetchImpl), currentDirectory(env, fetchImpl)]);
        if (!directory || directory.registry_generation !== manifest.registry_generation || !Array.isArray(directory.researchers)) {
          fail("registry_unavailable", "The current researcher catalog could not be verified.", 503);
        }
        if (!removal) return json(200, {
          registry_generation: manifest.registry_generation,
          researchers: directory.researchers.map(row => ({
            id: row.id, name: row.name, home_unit: row.home_unit, status: row.status, pool_visibility: row.pool_visibility,
          })),
        });
        if (removal.base_registry_generation !== manifest.registry_generation) fail("stale_registry_generation", "The catalog changed. Reload it before preparing a removal.", 409);
        const person = directory.researchers.find(row => row.id === removal.researcher_id);
        if (!person) fail("not_found", "Researcher not found in the current catalog.", 404);
        if (person.status !== "active" && person.pool_visibility === "hidden" && !person.auto_proposable) fail("already_removed", "This researcher is already removed from the active catalog.", 409);
        const reason = "Catalog removal (" + removal.action + "): " + removal.reason;
        const checkPending = async () => {
          if (await store.activeCatalogRemoval(person.id)) fail("catalog_removal_pending", "This researcher already has a removal request. Open it in the review queue.", 409);
        };
        await checkPending();
        let row;
        try {
          row = await store.create({
            submissionId: "rs_" + randomToken(12), idempotencyKey: key, payloadHash,
            receiptTokenHash: await sha256(randomToken()), submissionType: "profile_correction",
            sourceSurface: "faculty_interests", researcherId: person.id,
            baseRegistryGeneration: manifest.registry_generation, proposedProfile: catalogRemovalProposal(person),
            privacyNoticeVersion: "admin-catalog-v1", createdAt: now().toISOString(),
            catalogAction: removal.action, actor, reason,
          });
        } catch (error) {
          const winner = await store.byIdempotencyKey(key);
          if (winner) return replay(winner);
          await checkPending();
          throw error;
        }
        return json(201, { submission_id: row.submission_id, state: row.state, duplicate: false });
      }
      if (path === "/admin/api/submissions" && request.method === "GET") {
        await adminActor(request, env, fetchImpl);
        const [submissions, directory, teamData, facultyMatches] = await Promise.all([
          store.listQueue(), currentDirectory(env, fetchImpl), currentTeamData(env, fetchImpl), currentFacultyMatches(env, fetchImpl),
        ]);
        return json(200, { submissions: submissions.map(detail => {
          const duplicates = duplicateCandidates(directory, detail);
          return {
            ...detail, trust_signals: trustSignals(directory, detail, duplicates),
            material_effect: materialEffect(directory, teamData, facultyMatches, detail),
            validator_warnings: validatorWarnings(directory, detail, duplicates),
          };
        }) });
      }
      const adminDetailMatch = path.match(/^\/admin\/api\/submissions\/(rs_[a-f0-9]{24})$/);
      if (adminDetailMatch && request.method === "GET") {
        await adminActor(request, env, fetchImpl);
        const detail = await store.adminDetail(adminDetailMatch[1]);
        if (!detail) fail("not_found", "Submission not found.", 404);
        const [directory, teamData, facultyMatches] = await Promise.all([
          currentDirectory(env, fetchImpl), currentTeamData(env, fetchImpl), currentFacultyMatches(env, fetchImpl),
        ]);
        const duplicates = duplicateCandidates(directory, detail);
        const currentProfile = directory && directory.researchers.find(row => row.id === detail.researcher_id) || null;
        return json(200, {
          ...detail, contact_email: detail.contact_email || "", submitter_note: detail.submitter_note || "",
          proposed_profile: detail.catalog_action && currentProfile ? catalogRemovalProposal(currentProfile) : detail.proposed_profile,
          approved_profile: detail.approved_profile || (detail.catalog_action
            ? catalogRemovalProfile(currentProfile, detail.catalog_action) : seedApprovedProfile({
            proposed_profile: detail.proposed_profile, current_profile: currentProfile,
          }, now().toISOString().slice(0, 10))),
          current_profile: currentProfile, duplicate_candidates: duplicates,
          trust_signals: trustSignals(directory, detail, duplicates),
          material_effect: materialEffect(directory, teamData, facultyMatches, detail),
          validator_warnings: validatorWarnings(directory, detail, duplicates),
        });
      }
      const adminActionMatch = path.match(/^\/admin\/api\/submissions\/(rs_[a-f0-9]{24})\/action$/);
      if (adminActionMatch && request.method === "POST") {
        const actor = await adminActor(request, env, fetchImpl);
        if (origin && origin !== url.origin) fail("admin_origin_not_allowed", "Administrator origin is not allowed.", 403);
        const body = await readJson(request);
        const expectedRevision = Number(body.expected_revision);
        if (!Number.isInteger(expectedRevision) || expectedRevision < 1) fail("invalid_revision", "The expected revision is invalid.");
        const current = await store.byId(adminActionMatch[1]);
        if (!current) fail("not_found", "Submission not found.", 404);
        const reason = String(body.reason || "").trim().slice(0, 500);
        if (body.action === "rebase") {
          const manifest = await currentManifest(env, fetchImpl);
          if (manifest.registry_generation === current.base_registry_generation) fail("rebase_not_required", "This submission already uses the current registry generation.", 409);
          const rebased = await store.rebase({
            id: current.submission_id, expectedRevision, nextGeneration: manifest.registry_generation,
            actor, reason, now: now().toISOString(),
          });
          if (!rebased) fail("state_conflict", "The submission changed before it could be rebased.", 409);
          return json(200, {
            submission_id: rebased.submission_id, state: rebased.state, revision: rebased.revision,
            base_registry_generation: rebased.base_registry_generation, updated_at: rebased.updated_at,
            administrator_reason: rebased.administrator_reason || "",
          });
        }
        if (body.action === "approve") {
          if (current.state !== "under_review") {
            fail("state_conflict", "Start review before approving this request.", 409);
          }
          const approvedProfile = await validateApprovalAgainstCurrentRegistry(current, body.approved_profile, env, fetchImpl);
          const approved = await store.transition({ id: current.submission_id, fromStates: ["under_review"], toState: "approved", expectedRevision, actor, reason, approvedProfile, now: now().toISOString() });
          if (!approved) fail("state_conflict", "The submission changed while you were reviewing it.", 409);
          const publishing = await store.markPublishing(approved.submission_id, approved.revision, actor, now().toISOString());
          if (!publishing) fail("state_conflict", "The submission changed before publication started.", 409);
          try { await dispatchPublication(env, publishing, fetchImpl); }
          catch (error) {
            const failed = await store.markPublicationFailed(publishing.submission_id, { expectedRevision: publishing.revision, failureCode: error.code || "publication_dispatch_failed", deploymentResult: "dispatch_failed" }, now().toISOString());
            if (failed) context.waitUntil(notifyOwner(env, failed, fetchImpl, "publication_failed").catch(() => undefined));
            throw error;
          }
          return json(200, {
            submission_id: publishing.submission_id, state: "publishing", revision: publishing.revision,
            updated_at: publishing.updated_at, administrator_reason: reason,
          });
        }
        if (body.action === "retry_publish") {
          if (!["approved", "publication_failed"].includes(current.state)) {
            fail("state_conflict", "Only an approved or failed publication can be retried.", 409);
          }
          const approvedProfile = await validateApprovalAgainstCurrentRegistry(current, body.approved_profile, env, fetchImpl);
          const publishing = await store.markPublishing(current.submission_id, expectedRevision, actor, now().toISOString(), approvedProfile, reason);
          if (!publishing) fail("state_conflict", "The submission changed while you were reviewing it.", 409);
          try { await dispatchPublication(env, publishing, fetchImpl); }
          catch (error) {
            const failed = await store.markPublicationFailed(publishing.submission_id, { expectedRevision: publishing.revision, failureCode: error.code || "publication_dispatch_failed", deploymentResult: "dispatch_failed" }, now().toISOString());
            if (failed) context.waitUntil(notifyOwner(env, failed, fetchImpl, "publication_failed").catch(() => undefined));
            throw error;
          }
          return json(200, {
            submission_id: publishing.submission_id, state: "publishing", revision: publishing.revision,
            updated_at: publishing.updated_at, administrator_reason: publishing.administrator_reason || "",
          });
        }
        if (body.action === "reconcile_publish") {
          const reconciled = await reconcilePublication({
            store, current, expectedRevision, actor, env, fetchImpl, timestamp: now().toISOString(),
          });
          if (reconciled.state === "publication_failed") {
            context.waitUntil(notifyOwner(env, reconciled, fetchImpl, "publication_failed").catch(() => undefined));
          }
          return json(200, {
            submission_id: reconciled.submission_id, state: reconciled.state, revision: reconciled.revision,
            updated_at: reconciled.updated_at, administrator_reason: reconciled.administrator_reason || "",
          });
        }
        const state = body.action === "request_changes" ? "changes_requested" : body.action === "reject" ? "rejected" : body.action === "start_review" ? "under_review" : "";
        if (!state) fail("invalid_action", "The administrator action is invalid.");
        if (["changes_requested", "rejected"].includes(state) && !reason) fail("reason_required", "A reason is required for this action.");
        const fromStates = body.action === "start_review" ? ["pending", "changes_requested"] : ["pending", "under_review", "changes_requested"];
        const updated = await store.transition({ id: current.submission_id, fromStates, toState: state, expectedRevision, actor, reason, now: now().toISOString() });
        if (!updated) fail("state_conflict", "The submission changed while you were reviewing it.", 409);
        return json(200, {
          submission_id: updated.submission_id, state: updated.state, revision: updated.revision,
          updated_at: updated.updated_at, administrator_reason: updated.administrator_reason || "",
        });
      }
      const publicationMatch = path.match(/^\/internal\/publications\/(rs_[a-f0-9]{24})$/);
      if (publicationMatch && request.method === "GET") {
        requireInternal(request, env);
        const row = await store.byId(publicationMatch[1]);
        if (!row || row.state !== "publishing") fail("publication_not_ready", "The approved publication is not ready.", 409);
        return json(200, {
          schema_version: 1, submission_id: row.submission_id, state: "approved", revision: row.revision,
          researcher_id: row.researcher_id, base_registry_generation: row.base_registry_generation,
          approved_at: row.approved_at, approved_profile: JSON.parse(row.approved_profile_json),
        });
      }
      const publicationTargetMatch = path.match(/^\/internal\/publications\/(rs_[a-f0-9]{24})\/target$/);
      if (publicationTargetMatch && request.method === "POST") {
        requireInternal(request, env);
        const body = await readJson(request);
        const expectedRevision = Number(body.expected_revision);
        const registryGeneration = String(body.registry_generation || "");
        if (!Number.isInteger(expectedRevision) || expectedRevision < 1 || !/^[a-f0-9]{64}$/.test(registryGeneration)) {
          fail("invalid_publication_target", "The publication target is invalid.");
        }
        const target = publicationPullRequestTarget(env, body.publication_pr_url);
        const result = await store.recordPublicationTarget(publicationTargetMatch[1], {
          expectedRevision, prUrl: target.url, registryGeneration,
        }, now().toISOString());
        if (!result) fail("state_conflict", "The publication state changed.", 409);
        return json(200, { submission_id: result.submission_id, state: result.state, revision: result.revision });
      }
      const completionMatch = path.match(/^\/internal\/publications\/(rs_[a-f0-9]{24})\/(complete|fail)$/);
      if (completionMatch && request.method === "POST") {
        requireInternal(request, env);
        const body = await readJson(request);
        const expectedRevision = Number(body.expected_revision);
        const result = completionMatch[2] === "complete"
          ? await store.markPublished(completionMatch[1], {
              expectedRevision, commitSha: String(body.commit_sha || ""), registryGeneration: String(body.registry_generation || ""),
              deploymentResult: String(body.deployment_result || ""), verifiedAt: String(body.public_verified_at || ""),
            }, now().toISOString())
          : await store.markPublicationFailed(completionMatch[1], {
              expectedRevision, failureCode: String(body.failure_code || "publication_failed").slice(0, 80),
              deploymentResult: String(body.deployment_result || "").slice(0, 120),
            }, now().toISOString());
        if (!result) fail("state_conflict", "The publication state changed.", 409);
        if (result.state === "publication_failed") context.waitUntil(notifyOwner(env, result, fetchImpl, "publication_failed").catch(() => undefined));
        return json(200, { submission_id: result.submission_id, state: result.state, revision: result.revision });
      }
      return json(404, { error: { code: "not_found", message: "Not found." } }, origin, env);
    } catch (error) {
      return json(error.status || 503, { error: { code: error.code || "service_unavailable", message: error.message || "The service is unavailable." } }, origin, env);
    }
  };
}

export function createScheduledHandler({ storeFactory = env => new ResearcherSubmissionStore(env.SUBMISSIONS_DB), now = () => new Date() } = {}) {
  return async function scheduled(_controller, env) {
    const store = storeFactory(env);
    return store.cleanup(now().toISOString(), Math.max(1, Number(env.REJECTED_RETENTION_DAYS) || 90), Math.max(1, Number(env.CONTACT_RETENTION_DAYS) || 90));
  };
}

const handle = createHandler();
const scheduled = createScheduledHandler();
export default {
  fetch(request, env, context) { return handle(request, env, context); },
  scheduled(controller, env, context) { context.waitUntil(scheduled(controller, env)); },
};

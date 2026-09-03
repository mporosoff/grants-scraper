(function (global) {
  "use strict";

  var SCHEMA_VERSION = 1;
  var PRIVACY_NOTICE_VERSION = "2026-09-03";
  var DEFAULT_ENDPOINT = "https://funding-finder-researchers.urochestercheme.workers.dev";
  var MAX = Object.freeze({
    displayName: 120,
    homeUnit: 180,
    relationshipNote: 240,
    researchSummary: 1200,
    claim: 180,
    claims: 12,
    sources: 8,
    contactEmail: 254,
    note: 1000,
  });

  function normalizeText(value) {
    return String(value == null ? "" : value).normalize("NFKC").replace(/\s+/g, " ").trim();
  }

  function normalizeIdentity(value) {
    return normalizeText(value).normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  function normalizeOrcid(value) {
    var compact = String(value || "").toUpperCase().replace(/[^0-9X]/g, "");
    if (!/^[0-9]{15}[0-9X]$/.test(compact)) return "";
    var total = 0;
    for (var index = 0; index < 15; index += 1) total = (total + Number(compact[index])) * 2;
    var result = (12 - (total % 11)) % 11;
    var check = result === 10 ? "X" : String(result);
    if (check !== compact[15]) return "";
    return compact.slice(0, 4) + "-" + compact.slice(4, 8) + "-" + compact.slice(8, 12) + "-" + compact.slice(12);
  }

  function parseLines(value, maximum, normalizer) {
    var seen = new Set();
    var output = [];
    String(value || "").split(/[\n,]+/).forEach(function (item) {
      var normalized = (normalizer || normalizeText)(item);
      var key = normalized.toLowerCase();
      if (normalized && !seen.has(key) && output.length < maximum) {
        seen.add(key);
        output.push(normalized);
      }
    });
    return output;
  }

  function normalizeUrls(value) {
    return parseLines(value, MAX.sources).map(function (item) {
      var url;
      try { url = new URL(item); } catch (_error) { throw new Error("Use complete HTTPS source links."); }
      if (url.protocol !== "https:" || url.username || url.password || item.length > 500) {
        throw new Error("Use complete HTTPS source links.");
      }
      url.hash = "";
      return url.toString();
    });
  }

  function bounded(value, maximum, label, required) {
    var text = normalizeText(value);
    if ((required && !text) || text.length > maximum) {
      throw new Error(label + (required ? " is required" : " is too long") + ".");
    }
    return text;
  }

  function createIdempotencyKey() {
    if (global.crypto && typeof global.crypto.randomUUID === "function") return global.crypto.randomUUID();
    var bytes = new Uint8Array(16);
    if (!global.crypto || typeof global.crypto.getRandomValues !== "function") {
      throw new Error("This browser cannot create a secure submission identifier.");
    }
    global.crypto.getRandomValues(bytes);
    return Array.from(bytes, function (value) { return value.toString(16).padStart(2, "0"); }).join("");
  }

  function buildSubmission(input) {
    input = input || {};
    var type = input.submissionType;
    var surface = input.sourceSurface;
    if (!["profile_correction", "new_researcher_nomination"].includes(type)) throw new Error("Choose a request type.");
    if (!["faculty_interests", "team_match"].includes(surface)) throw new Error("The request source is invalid.");
    var researcherId = bounded(input.researcherId, 40, "Researcher identifier", false);
    if (type === "profile_correction" && !/^urh-[0-9]{6}$/.test(researcherId)) {
      throw new Error("Choose the existing researcher whose profile should change.");
    }
    var displayName = bounded(input.displayName, MAX.displayName, "Researcher name", true);
    var claims = parseLines(input.claims, MAX.claims);
    if (!claims.length) throw new Error("Add at least one specific research interest.");
    claims.forEach(function (claim) {
      if (claim.length > MAX.claim) throw new Error("Each research interest must be 180 characters or fewer.");
    });
    var sources = normalizeUrls(input.sourceUrls);
    if (type === "new_researcher_nomination" && !sources.length) {
      throw new Error("Add at least one supporting source link for a new researcher.");
    }
    var rawOrcid = normalizeText(input.orcidId);
    var orcid = rawOrcid ? normalizeOrcid(rawOrcid) : "";
    if (rawOrcid && !orcid) throw new Error("Enter a valid ORCID iD.");
    var email = bounded(input.contactEmail, MAX.contactEmail, "Contact email", false).toLowerCase();
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error("Enter a valid contact email.");
    if (input.submittedForAdminReview !== true) throw new Error("Confirm that you want administrator review.");
    var generation = bounded(input.baseRegistryGeneration, 64, "Registry generation", true);
    if (!/^[a-f0-9]{64}$/.test(generation)) throw new Error("The published researcher directory is unavailable. Refresh and try again.");
    var key = bounded(input.idempotencyKey, 80, "Submission identifier", true);
    if (!/^[a-zA-Z0-9-]{16,80}$/.test(key)) throw new Error("The submission identifier is invalid.");
    return {
      schema_version: SCHEMA_VERSION,
      idempotency_key: key,
      submission_type: type,
      source_surface: surface,
      researcher_id: researcherId || null,
      base_registry_generation: generation,
      proposed_profile: {
        display_name: displayName,
        orcid_id: orcid,
        home_unit: bounded(input.homeUnit, MAX.homeUnit, "Unit", false),
        relationship_note: bounded(input.relationshipNote, MAX.relationshipNote, "Relationship", false),
        research_summary: bounded(input.researchSummary, MAX.researchSummary, "Research summary", false),
        claims: claims,
        source_urls: sources,
      },
      submitter: {
        contact_email: email,
        note: bounded(input.note, MAX.note, "Note", false),
      },
      consent: {
        submitted_for_admin_review: true,
        privacy_notice_version: PRIVACY_NOTICE_VERSION,
      },
    };
  }

  function directoryResearchers(directory) {
    return directory && Array.isArray(directory.researchers) ? directory.researchers : [];
  }

  function findPossibleDuplicates(directory, proposed) {
    var name = normalizeIdentity(proposed.display_name || proposed.displayName);
    var orcid = normalizeOrcid(proposed.orcid_id || proposed.orcidId);
    var sources = new Set((proposed.source_urls || proposed.sourceUrls || []).map(function (url) {
      try { return new URL(url).origin + new URL(url).pathname.replace(/\/$/, "").toLowerCase(); }
      catch (_error) { return ""; }
    }).filter(Boolean));
    return directoryResearchers(directory).map(function (researcher) {
      var reasons = [];
      var names = [researcher.name].concat(researcher.aliases || []).map(normalizeIdentity);
      if (name && names.includes(name)) reasons.push("same normalized name");
      if (orcid && researcher.orcid_id === orcid) reasons.push("same ORCID iD");
      if ((researcher.source_urls || []).some(function (url) {
        try { return sources.has(new URL(url).origin + new URL(url).pathname.replace(/\/$/, "").toLowerCase()); }
        catch (_error) { return false; }
      })) reasons.push("same source");
      return reasons.length ? { researcher: researcher, reasons: reasons } : null;
    }).filter(Boolean);
  }

  async function submit(submission, options) {
    options = options || {};
    var endpoint = String(options.endpoint || DEFAULT_ENDPOINT).replace(/\/$/, "");
    var response;
    try {
      response = await (options.fetchImpl || global.fetch)(endpoint + "/submissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(submission),
      });
    } catch (_error) {
      throw Object.assign(new Error("The administrator queue could not be reached."), { code: "queue_unavailable" });
    }
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      throw Object.assign(new Error(payload.error && payload.error.message || "The administrator queue did not accept the request."), {
        code: payload.error && payload.error.code || "submission_failed",
      });
    }
    return payload;
  }

  function downloadFallback(submission, documentRef) {
    var doc = documentRef || global.document;
    var blob = new Blob([JSON.stringify(submission, null, 2) + "\n"], { type: "application/json" });
    var link = doc.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "funding-finder-researcher-request.json";
    link.click();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 0);
  }

  global.FUNDING_RESEARCHER_INTAKE = Object.freeze({
    SCHEMA_VERSION: SCHEMA_VERSION,
    PRIVACY_NOTICE_VERSION: PRIVACY_NOTICE_VERSION,
    DEFAULT_ENDPOINT: DEFAULT_ENDPOINT,
    normalizeText: normalizeText,
    normalizeIdentity: normalizeIdentity,
    normalizeOrcid: normalizeOrcid,
    parseLines: parseLines,
    normalizeUrls: normalizeUrls,
    createIdempotencyKey: createIdempotencyKey,
    buildSubmission: buildSubmission,
    findPossibleDuplicates: findPossibleDuplicates,
    submit: submit,
    downloadFallback: downloadFallback,
  });
})(globalThis);

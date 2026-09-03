import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [source, page, pageScript, team] = await Promise.all([
  readFile(new URL("assets/researcher-intake.js", root), "utf8"),
  readFile(new URL("faculty_interests.html", root), "utf8"),
  readFile(new URL("assets/faculty-interests.js", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
]);

function api() {
  const sandbox = { URL, Uint8Array, Blob, setTimeout() {}, globalThis: null };
  sandbox.globalThis = sandbox;
  sandbox.crypto = { randomUUID: () => "12345678-1234-4234-8234-123456789abc" };
  vm.runInNewContext(source, sandbox);
  return sandbox.FUNDING_RESEARCHER_INTAKE;
}

test("both public entry points disclose and use one bounded intake contract", () => {
  assert.match(page, /Configure Faculty Interests/);
  assert.match(page, /shared pool\. <strong>Submitting does not publish a change\.<\/strong> The current profile/);
  assert.doesNotMatch(page, /class="notice"/);
  assert.match(page, /Add a missing researcher/);
  assert.doesNotMatch(page, /ORCID iD/);
  assert.match(page, /id="existing-researcher"/);
  assert.match(page, /id="researcher-search"[^>]*type="search"[^>]*role="combobox"[^>]*aria-controls="researcher-options"/);
  assert.match(page, /id="researcher-options"[^>]*role="listbox"/);
  assert.match(page, /class="span-2" for="submitter-note"/);
  assert.match(page, /&copy; 2026 Marc D\. Porosoff/);
  assert.match(pageScript, /researcherSortName\(left\)\.localeCompare\(researcherSortName\(right\)/);
  assert.match(pageScript, /profile\.sort_name/);
  assert.match(pageScript, /event\.key === "ArrowDown"/);
  assert.match(pageScript, /data-researcher-index/);
  assert.match(page, /id="review-consent"/);
  assert.match(page, /assets\/researcher-intake\.js/);
  assert.match(team, /connect-src[^;"]*https:\/\/funding-finder-researchers\.urochestercheme\.workers\.dev/);
  assert.match(team, /id="submit-researcher-review" type="checkbox"/);
  assert.match(team, /Save locally and submit for review/);
  assert.match(team, /Local save completed\. The review request was not sent/);
  assert.match(team, /assets\/researcher-intake\.js/);
  assert.ok(team.indexOf("persistExternal(next)") < team.indexOf("INTAKE_API.submit(lastResearcherSubmission)"));
});

test("unchecked Team Match submission remains browser-local by default", () => {
  assert.doesNotMatch(team, /id="submit-researcher-review"[^>]*checked/);
  assert.match(team, /if \(!submitForReview\)/);
  assert.match(team, /closeExternalEditor\(\);[\s\S]*?return;[\s\S]*?INTAKE_API\.buildSubmission/);
});

test("the shared browser builder emits only consented allowlisted fields", () => {
  const intake = api();
  const input = {
    submissionType: "new_researcher_nomination", sourceSurface: "team_match",
    researcherId: "", baseRegistryGeneration: "a".repeat(64), displayName: "Ada Lovelace",
    homeUnit: "External", relationshipNote: "External collaborator",
    researchSummary: "Computational research.", claims: ["Analytical engines", "Computational methods"],
    sourceUrls: "https://example.edu/ada", orcidId: "0000-0002-1825-0097",
    contactEmail: "ADA@example.edu", note: "Please review", submittedForAdminReview: true,
    idempotencyKey: "12345678-1234-4234-8234-123456789abc",
  };
  const submission = intake.buildSubmission(input);
  assert.deepEqual(Object.keys(submission), [
    "schema_version", "idempotency_key", "submission_type", "source_surface", "researcher_id",
    "base_registry_generation", "proposed_profile", "submitter", "consent",
  ]);
  assert.equal(submission.submitter.contact_email, "ada@example.edu");
  assert.equal(submission.consent.submitted_for_admin_review, true);
  assert.equal(JSON.stringify(submission).includes("publication_text"), false);
  assert.equal(JSON.stringify(submission).includes("team_members"), false);
  assert.throws(
    () => intake.buildSubmission({ ...input, claims: Array.from({ length: 13 }, (_, index) => `Interest ${index}`) }),
    /no more than 12 research interests/,
  );
  assert.throws(
    () => intake.buildSubmission({ ...input, sourceUrls: Array.from({ length: 9 }, (_, index) => `https:\/\/example.edu\/${index}`).join("\n") }),
    /no more than 8 source links/,
  );
});

test("identity signals warn but never merge ambiguous candidates", () => {
  const intake = api();
  const matches = intake.findPossibleDuplicates({ researchers: [
    { id: "urh-000001", name: "Ada Lovelace", aliases: [], orcid_id: "", source_urls: ["https://example.edu/ada"] },
    { id: "urh-000002", name: "Ada M. Lovelace", aliases: ["Ada Lovelace"], orcid_id: "", source_urls: [] },
  ] }, { display_name: "Ada Lovelace", source_urls: ["https://example.edu/ada"] });
  assert.equal(matches.length, 2);
  assert.equal(matches.every(item => item.researcher.id), true);
  assert.equal("merged" in matches[0], false);
  assert.equal(intake.uniqueRegistryMatchId(matches), "");
  assert.equal(intake.uniqueRegistryMatchId([matches[0]]), "urh-000001");
  assert.match(team, /INTAKE_API\.uniqueRegistryMatchId\(registryMatches\)/);
  assert.doesNotMatch(team, /existingProfile\s*&&\s*existingProfile\.registry_id/);
  assert.match(team, /Nothing is merged automatically when identity is ambiguous/);
});

test("Team Match revalidates a persisted association from the edited identity", () => {
  const intake = api();
  const directory = { researchers: [
    { id: "urh-000001", name: "Ada Lovelace", aliases: [], orcid_id: "0000-0002-1825-0097", source_urls: ["https://example.edu/ada"] },
    { id: "urh-000002", name: "Grace Hopper", aliases: [], orcid_id: "0000-0002-1694-233X", source_urls: ["https://example.edu/grace"] },
  ] };
  const editedMatches = intake.findPossibleDuplicates(directory, {
    display_name: "Grace Hopper", orcid_id: "0000-0002-1694-233X", source_urls: ["https://example.edu/grace"],
  });
  assert.equal(intake.uniqueRegistryMatchId(editedMatches), "urh-000002");
  const unrelated = intake.findPossibleDuplicates(directory, {
    display_name: "Katherine Johnson", orcid_id: "", source_urls: ["https://example.edu/katherine"],
  });
  assert.equal(intake.uniqueRegistryMatchId(unrelated), "");
});

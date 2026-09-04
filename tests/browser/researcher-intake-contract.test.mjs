import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [source, page, pageScript, team, contractSource] = await Promise.all([
  readFile(new URL("assets/researcher-intake.js", root), "utf8"),
  readFile(new URL("faculty_interests.html", root), "utf8"),
  readFile(new URL("assets/faculty-interests.js", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
  readFile(new URL("workers/researcher-intake/src/contract.js", root), "utf8"),
]);

function api() {
  const sandbox = { URL, Uint8Array, Blob, setTimeout() {}, globalThis: null };
  sandbox.globalThis = sandbox;
  sandbox.crypto = { randomUUID: () => "12345678-1234-4234-8234-123456789abc" };
  vm.runInNewContext(source, sandbox);
  return sandbox.FUNDING_RESEARCHER_INTAKE;
}

test("Configure Faculty Interests discloses separate reviewed and browser-only paths", () => {
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
  assert.match(pageScript, /function renderResearcherOptions\(query\) \{\s*activeResearcherOption = -1;\s*element\("researcher-search"\)\.removeAttribute\("aria-activedescendant"\)/);
  assert.match(pageScript, /event\.key === "ArrowDown"/);
  assert.match(pageScript, /data-researcher-index/);
  assert.match(page, /id="review-consent"/);
  assert.doesNotMatch(page, /privacy notice version/);
  assert.doesNotMatch(contractSource, /under the current privacy notice/i);
  assert.match(page, /id="add-locally"[^>]*>Add locally</);
  assert.match(page, /Stored only in this browser for Team Match/);
  assert.match(page, /not submitted for administrator review or considered for the full catalog/);
  assert.match(page, /connect-src[^;"]*https:\/\/funding-finder-researchers\.urochestercheme\.workers\.dev/);
  assert.match(page, /data-orcid-input/);
  assert.match(page, /assets\/orcid\.js/);
  assert.match(page, /assets\/team-researchers\.js/);
  assert.match(page, /assets\/researcher-intake\.js/);
  assert.match(team, /faculty_interests\.html\?mode=add&amp;return=team_match/);
  assert.match(team, /id="remove-saved-researcher"/);
  assert.doesNotMatch(team, /external-researcher-form|assets\/researcher-intake\.js/);
  assert.doesNotMatch(team, /funding-finder-researchers\.urochestercheme\.workers\.dev/);
});

test("mode-specific drafts persist until a successful action", () => {
  assert.match(pageScript, /var modeDrafts = \{/);
  assert.match(pageScript, /modeDrafts\[activeRequestType\] = captureDraft\(\)/);
  assert.match(pageScript, /restoreDraft\(modeDrafts\[nextType\] \|\| blankDraft\(\)\)/);
  assert.match(pageScript, /if \(query\.get\("mode"\) === "add"\) form\.elements\.request_type\.value = "new_researcher_nomination"/);
  const submitStart = pageScript.indexOf("  async function submitRequest(event) {");
  const submitEnd = pageScript.indexOf("\n\n  if (!intake", submitStart);
  const submitSource = pageScript.slice(submitStart, submitEnd);
  assert.match(submitSource, /await intake\.submit\(currentSubmission\)[\s\S]*?resetActiveDraft\(\)/);
  assert.match(submitSource, /catch \(error\) \{[\s\S]*?Your form is still here/);
  const failedSubmit = submitSource.slice(submitSource.lastIndexOf("    } catch (error) {"), submitSource.indexOf("    } finally"));
  assert.doesNotMatch(failedSubmit, /resetActiveDraft/);
  assert.match(pageScript, /TEAM_API|teamApi\.save/);
  assert.match(pageScript, /teamApi\.completeHandoff\(safeHandoffStorage\(\), savedId\)/);
  assert.match(pageScript, /location\.assign\("\.\/team_match\.html\?handoff=1"\)/);
  assert.doesNotMatch(pageScript, /new URLSearchParams\(\{ local: savedId \}\)|returnParams\.set|[?&]locals?=/);
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
  assert.match(pageScript, /intake\.findPossibleDuplicates\(directory/);
  assert.match(pageScript, /nothing is merged automatically/i);
  assert.doesNotMatch(team, /INTAKE_API|uniqueRegistryMatchId/);
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

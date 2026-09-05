import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { load } from "cheerio";
import { validateSubmission, validateAdminProfile } from "../../workers/researcher-intake/src/contract.js";
import { seedApprovedProfile } from "../../workers/researcher-intake/src/index.js";

const read = path => readFile(new URL(`../../${path}`, import.meta.url), "utf8");
const sandbox = { URL, Uint8Array, Blob, setTimeout, clearTimeout };
vm.createContext(sandbox);
vm.runInContext(await read("assets/researcher-intake.js"), sandbox);
vm.runInContext(await read("assets/team-researchers.js"), sandbox);
const input = {
  submissionType: "new_researcher_nomination", sourceSurface: "faculty_interests",
  baseRegistryGeneration: "a".repeat(64), displayName: "Example Researcher", claims: ["Catalysis"],
  sourceUrls: ["https://example.edu/researcher"], submittedForAdminReview: true,
  idempotencyKey: "12345678-1234-4234-8234-123456789abc",
};
const institution = { name: "California Institute of Technology", ror_id: "https://ror.org/05dxps055" };
const plain = value => JSON.parse(JSON.stringify(value));

test("Optional institution survives bounded intake, administrator approval, and browser-only storage", () => {
  const original = plain(sandbox.FUNDING_RESEARCHER_INTAKE.buildSubmission(input));
  assert.equal("institution" in validateSubmission(original).proposed_profile, false, "Older submissions retain their exact shape");
  const submission = plain(sandbox.FUNDING_RESEARCHER_INTAKE.buildSubmission({ ...input, institution }));
  assert.deepEqual(validateSubmission(submission).proposed_profile.institution, institution);
  const seeded = seedApprovedProfile({ proposed_profile: submission.proposed_profile });
  assert.deepEqual(validateAdminProfile(seeded, null).institution, institution);
  assert.equal(seeded.auto_proposable, false);
  assert.equal(seeded.pool_visibility, "hidden", "An institution selection confers no team eligibility");
  const local = sandbox.FUNDING_TEAM_RESEARCHERS.normalizeProfiles([{ id: "ext-example", name: input.displayName, keywords: ["catalysis", "hydrogen", "kinetics"], institution }]);
  assert.deepEqual(plain(local[0].institution), institution);
  assert.equal(local[0].id, "ext-example");
  const current = { ...seeded, name: seeded.display_name, id: "urh-000001" };
  assert.deepEqual(seedApprovedProfile({ current_profile: current, proposed_profile: original.proposed_profile }).institution, institution, "An older correction cannot erase metadata it never supplied");
  assert.deepEqual(seedApprovedProfile({ current_profile: current, proposed_profile: { ...original.proposed_profile, institution: { name: "", ror_id: "" } } }).institution, { name: "", ror_id: "" }, "Explicit clearing remains reviewable");
});

test("Institution metadata rejects unbounded, malformed and non-allowlisted inputs on both client and server", () => {
  const original = plain(sandbox.FUNDING_RESEARCHER_INTAKE.buildSubmission(input));
  for (const institution of [null, [], { name: "x".repeat(301) }, { name: "Example", ror_id: "https://evil.example/05dxps055" }, { name: "", ror_id: "https://ror.org/05dxps055" }, { name: "Example", auto_proposable: true }]) {
    assert.throws(() => sandbox.FUNDING_RESEARCHER_INTAKE.buildSubmission({ ...input, institution }));
    assert.throws(() => validateSubmission({ ...original, proposed_profile: { ...original.proposed_profile, institution } }));
  }
});

test("The optional institution integration uses the award ROR endpoint and exact served scripts", async () => {
  const $ = load(await read("faculty_interests.html"));
  assert.equal($("#institution-name[role='combobox']:not([required])").length, 1);
  assert.equal($("#institution-options[role='listbox']").length, 1);
  assert.equal($("#institution-ror-id[type='hidden']").length, 1);
  for (const name of ["institution-picker.js", "faculty-interests.js", "researcher-intake.js"]) {
    assert.equal($(`script[src^='./assets/${name}?v=']`).length, 1);
    assert.equal($(`script[src^='./assets/${name}?v=']`).attr("src"), `./assets/${name}?v=${createHash("sha256").update(await read(name.startsWith("assets/") ? name : `assets/${name}`)).digest("hex")}`);
  }
  assert.equal($("script[src^='./assets/award-api-config.js']").length, 1);
  const picker = await read("assets/institution-picker.js");
  assert.match(picker, /FUNDING_AWARD_API_CONFIG\.institutionSearchUrl/);
  assert.match(picker, /credentials: "omit"/);
  assert.doesNotMatch(picker, /localStorage|sessionStorage|researcherId|contactEmail|researchSummary|API.key/i);
});

test("All existing business functions outside authorized hero and institution changes remain identical", async () => {
  const baseline = JSON.parse(await read("tests/fixtures/user-fixes-preserved-functions.json"));
  const allowed = {
    "assets/app.js": ["renderSearchShell"],
    "assets/team-researchers.js": ["normalizeProfiles"],
    "assets/researcher-intake.js": ["buildSubmission"],
    "assets/faculty-interests.js": ["fillProfile", "restoreDraft", "makeSubmission", "addLocally"],
  };
  for (const [path, functions] of Object.entries(baseline)) {
    const source = await read(path);
    const matches = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
    for (const [name, expected] of Object.entries(functions)) {
      if (allowed[path].includes(name)) continue;
      const i = matches.findIndex(match => match[1] === name);
      assert.ok(i >= 0, name);
      const end = name === "submitRequest" ? source.indexOf("\n  if (!intake", matches[i].index) : matches[i + 1]?.index ?? source.length;
      assert.equal(createHash("sha256").update(source.slice(matches[i].index, end).trim()).digest("hex"), expected, `${path}: ${name}`);
    }
  }
});

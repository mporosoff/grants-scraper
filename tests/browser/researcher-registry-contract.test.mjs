import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { assertResearcherIdentities } from "../helpers/assert-researcher-identities.mjs";

const root = new URL("../../", import.meta.url);
const [registry, manifest, directorySource, matchesSource, teamModel, teamDataSource, runtime, teamPage] = await Promise.all([
  readFile(new URL("config/researcher_registry.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/researcher_registry_manifest.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/researcher_directory.js", root), "utf8"),
  readFile(new URL("data/faculty_matches.js", root), "utf8"),
  readFile(new URL("config/opportunity_team_model.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/opportunity_teams.js", root), "utf8"),
  readFile(new URL("assets/opportunity-team.js", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
]);

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{")).trim().replace(/;$/, ""));
}

const identityBaseline = JSON.parse(await readFile(new URL("tests/fixtures/researcher-identity-baseline.json", root), "utf8"));
// PR/push CI explicitly supplies the protected pre-change SHA. Refresh and
// publication validate an uncommitted registry against their checked-out main.
const protectedRef = process.env.RESEARCHER_IDENTITY_BASE_SHA || "HEAD";
if (protectedRef !== "HEAD") assert.match(protectedRef, /^[a-f0-9]{40}$/);
const publishedSource = spawnSync("git", ["show", `${protectedRef}:config/researcher_registry.json`], {
  cwd: fileURLToPath(root), encoding: "utf8",
});
assert.equal(publishedSource.status, 0, `Cannot load protected registry identity baseline: ${publishedSource.stderr}`);
const publishedRegistry = JSON.parse(publishedSource.stdout);

test("existing researcher, legacy and claim mappings survive mutable registry publication", () => {
  assertResearcherIdentities(registry, identityBaseline);
  assertResearcherIdentities(registry, publishedRegistry);
  const updated = { researchers: structuredClone(identityBaseline.researchers) };
  const person = updated.researchers[0];
  person.display_name = "Reviewed display-name correction";
  person.home_unit = "Reviewed unit correction";
  person.institution = { name: "Reviewed institution", ror_id: "" };
  person.status = "inactive";
  person.claims[0].revision += 1;
  person.claims[0].material_hash = "a".repeat(64);
  person.claims[0].status = "retired";
  person.claims.push({ claim_id: `${person.researcher_id}-c999`, legacy_claim_ids: [], revision: 1, material_hash: "b".repeat(64) });
  updated.researchers.push({ researcher_id: "urh-999999", legacy_ids: ["new-researcher"], claims: [] });
  assertResearcherIdentities(updated, identityBaseline);
  // Once this valid addition is the published baseline, the next generation
  // must retain both newly accepted identities without updating the old fixture.
  const next = structuredClone(updated);
  next.researchers.pop();
  assert.throws(() => assertResearcherIdentities(next, updated), /Missing stable researcher urh-999999/);
  const missingClaim = structuredClone(updated);
  missingClaim.researchers[0].claims.pop();
  assert.throws(() => assertResearcherIdentities(missingClaim, updated), /Missing stable claim .*c999/);
});

test("protected PR and push gates fetch the pre-change registry while refresh and publication use their current checkout", async () => {
  const workflow = await readFile(new URL(".github/workflows/tests.yml", root), "utf8");
  assert.match(workflow, /RESEARCHER_IDENTITY_BASE_SHA: \$\{\{ github\.event\.pull_request\.base\.sha \|\| github\.event\.before \}\}/);
  assert.match(workflow, /git fetch --no-tags --depth=1 origin "\$RESEARCHER_IDENTITY_BASE_SHA"/);
  assert.ok(workflow.indexOf("Fetch the protected researcher identity baseline") < workflow.indexOf("node --test tests/browser/*.test.mjs"));
});

test("consistent regeneration cannot hide reassigned or removed historical identities", () => {
  const corruptions = [
    rows => rows.shift(),
    rows => { rows[0].researcher_id = "urh-999999"; },
    rows => { [rows[0].legacy_ids, rows[1].legacy_ids] = [rows[1].legacy_ids, rows[0].legacy_ids]; },
    rows => { rows[0].legacy_ids = []; },
    rows => rows[0].claims.shift(),
    rows => { rows[0].claims[0].claim_id = `${rows[0].researcher_id}-c999`; },
    rows => { rows[0].claims[0].legacy_claim_ids = []; },
    rows => { rows[0].claims[0].revision = 0; },
    rows => { rows[0].claims[0].material_hash = "c".repeat(64); },
  ];
  for (const corrupt of corruptions) {
    const changed = { researchers: structuredClone(identityBaseline.researchers) };
    corrupt(changed.researchers);
    assert.throws(() => assertResearcherIdentities(changed, identityBaseline));
  }
});

test("one generated registry generation owns every public researcher projection", () => {
  const directory = assignmentJson(directorySource);
  const matches = assignmentJson(matchesSource);
  const teamData = assignmentJson(teamDataSource);
  const matchesVersion = createHash("sha256").update(matchesSource).digest("hex");
  assert.equal(registry.schema_version, 3);
  assert.match(registry.registry_generation, /^[a-f0-9]{64}$/);
  assert.equal(directory.registry_generation, registry.registry_generation);
  assert.equal(manifest.registry_generation, registry.registry_generation);
  assert.equal(matches.registry_generation, registry.registry_generation);
  assert.equal(teamModel.researcher_registry_generation, registry.registry_generation);
  assert.equal(teamData.researcher_registry_generation, registry.registry_generation);
  assert.match(teamPage, new RegExp(`data/faculty_matches\\.js\\?v=${matchesVersion}`));
  assert.match(teamPage, /M\.registry_generation !== globalThis\.RESEARCHER_DIRECTORY\.registry_generation/);
  assert.equal(directory.researchers.length, manifest.counts.total);
  assert.equal(new Set(directory.researchers.map(row => row.id)).size, directory.researchers.length);
});

test("stable researcher and claim identities preserve every legacy browser ID", () => {
  const directory = assignmentJson(directorySource);
  const legacy = new Set();
  directory.researchers.forEach(researcher => {
    assert.match(researcher.id, /^urh-[0-9]{6}$/);
    assert.equal(typeof researcher.sort_name, "string");
    assert.ok(researcher.sort_name.includes(","));
    assert.ok(researcher.legacy_ids.length >= 1);
    researcher.legacy_ids.forEach(id => {
      assert.equal(legacy.has(id), false);
      legacy.add(id);
    });
    researcher.claims.forEach(claim => {
      assert.match(claim.claim_id, new RegExp(`^${researcher.id}-c[0-9]{3}$`));
      assert.ok(Number.isInteger(claim.revision) && claim.revision >= 1);
    });
  });
  teamModel.opportunities.flatMap(row => row.members).forEach(member => {
    assert.match(member.faculty_id, /^urh-[0-9]{6}$/);
  });
});

test("runtime validates generated manifest counts instead of a frozen roster", () => {
  assert.match(runtime, /directory\.counts/);
  assert.match(runtime, /directory\.registry_generation !== data\.researcher_registry_generation/);
  assert.doesNotMatch(runtime, /data\.faculty\.length !== 156|pools\.main !== 118|source\.rankable !== 145/);
  assert.match(runtime, /profile\.legacy_ids/);
});

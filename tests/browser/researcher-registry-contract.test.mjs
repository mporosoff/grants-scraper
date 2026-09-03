import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [registry, manifest, directorySource, matchesSource, teamModel, teamDataSource, runtime] = await Promise.all([
  readFile(new URL("config/researcher_registry.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/researcher_registry_manifest.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/researcher_directory.js", root), "utf8"),
  readFile(new URL("data/faculty_matches.js", root), "utf8"),
  readFile(new URL("config/opportunity_team_model.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/opportunity_teams.js", root), "utf8"),
  readFile(new URL("assets/opportunity-team.js", root), "utf8"),
]);

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{")).trim().replace(/;$/, ""));
}

test("one generated registry generation owns every public researcher projection", () => {
  const directory = assignmentJson(directorySource);
  const matches = assignmentJson(matchesSource);
  const teamData = assignmentJson(teamDataSource);
  assert.equal(registry.schema_version, 3);
  assert.match(registry.registry_generation, /^[a-f0-9]{64}$/);
  assert.equal(directory.registry_generation, registry.registry_generation);
  assert.equal(manifest.registry_generation, registry.registry_generation);
  assert.equal(matches.registry_generation, registry.registry_generation);
  assert.equal(teamModel.researcher_registry_generation, registry.registry_generation);
  assert.equal(teamData.researcher_registry_generation, registry.registry_generation);
  assert.equal(directory.researchers.length, manifest.counts.total);
  assert.equal(new Set(directory.researchers.map(row => row.id)).size, directory.researchers.length);
});

test("stable researcher and claim identities preserve every legacy browser ID", () => {
  const directory = assignmentJson(directorySource);
  const legacy = new Set();
  directory.researchers.forEach(researcher => {
    assert.match(researcher.id, /^urh-[0-9]{6}$/);
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

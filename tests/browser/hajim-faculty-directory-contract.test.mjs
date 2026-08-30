import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [helperSource, matcherSource, assetSource, teamPage, facultySource, release, deployWorkflow, refreshWorkflow] = await Promise.all([
  readFile(new URL("assets/hajim-faculty-directory.js", root), "utf8"),
  readFile(new URL("assets/team-matcher.js", root), "utf8"),
  readFile(new URL("data/hajim-faculty-directory.js", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
  readFile(new URL("data/faculty_matches.js", root), "utf8"),
  readFile(new URL("data/search-v2-release.json", root), "utf8").then(JSON.parse),
  readFile(new URL(".github/workflows/deploy-search-package.yml", root), "utf8"),
  readFile(new URL(".github/workflows/refresh-opportunities.yml", root), "utf8"),
]);

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{"), source.lastIndexOf(";")).trim());
}

function apiHarness() {
  const globalObject = { setTimeout, clearTimeout };
  const context = { globalThis: globalObject };
  vm.runInNewContext(helperSource, context, { filename: "assets/hajim-faculty-directory.js" });
  return { api: globalObject.FUNDING_HAJIM_FACULTY, globalObject };
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

const payload = assignmentJson(assetSource);
const curated = assignmentJson(facultySource).faculty;
const { api } = apiHarness();
const directory = api.buildIndex(api.validate(payload, payload.generation_identity));

test("reviewed workbook and content-derived generation are coherent across HTML, asset, and release", () => {
  const core = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== "generation_identity"));
  assert.equal(createHash("sha256").update(canonical(core)).digest("hex"), payload.generation_identity);
  assert.match(teamPage, new RegExp(`name="hajim-faculty-directory-generation" content="${payload.generation_identity}"`));
  assert.equal(release.source_hashes["data/hajim-faculty-directory.js"], createHash("sha256").update(assetSource).digest("hex"));
  assert.equal(payload.source_sha256, api.SOURCE_SHA256);
  assert.deepEqual({ ...payload.counts }, { ...api.EXPECTED_COUNTS });
});

test("every changed Team Match runtime has a content-derived HTML and release cache key", () => {
  const runtimes = {
    "data/faculty_matches.js": { source: facultySource, prefix: "faculty-matches" },
    "assets/hajim-faculty-directory.js": { source: helperSource, prefix: "hajim-faculty-directory" },
    "assets/team-matcher.js": { source: matcherSource, prefix: "team-matcher" },
  };
  for (const [path, { source, prefix }] of Object.entries(runtimes)) {
    const digest = createHash("sha256").update(source).digest("hex");
    const cacheKey = `${prefix}-${digest.slice(0, 16)}`;
    assert.equal(release.runtime_cache_keys[path], cacheKey);
    assert.equal(release.source_hashes[path], digest);
    assert.match(teamPage, new RegExp(`${path.replaceAll(".", "\\.")}\\?v=${cacheKey}`));
  }
});

test("both Pages publication paths verify the exact Team Match page and every manifest runtime", () => {
  for (const workflow of [deployWorkflow, refreshWorkflow]) {
    assert.match(workflow, /expected_team_sha=.*source_hashes\["team_match\.html"\]/);
    assert.match(workflow, /live_team_sha=.*sha256sum "\$live_team_path"/);
    assert.match(workflow, /"\$live_team_sha" != "\$expected_team_sha"/);
    assert.match(workflow, /mapfile -t team_runtime_entries/);
    assert.match(workflow, /\.runtime_cache_keys \| to_entries\[\]/);
    assert.match(workflow, /grep -Fq "\$\{runtime_path\}\?v=\$\{runtime_key\}" "\$live_team_path"/);
    assert.match(workflow, /source_hashes\[\$path\] \/\/ empty/);
    assert.match(workflow, /"\$\{pages_base\}\/\$\{runtime_path\}\?v=\$\{runtime_key\}"/);
    assert.match(workflow, /"\$live_runtime_sha" != "\$expected_runtime_sha"/);
    assert.match(workflow, /data\/hajim-faculty-directory\.js\?v=\$\{directory_generation\}/);
  }
});

test("the complete directory is absent from initial HTML and loads only through its exact identity", async () => {
  assert.doesNotMatch(teamPage, /<script[^>]+data\/hajim-faculty-directory\.js/i);
  assert.match(teamPage, /assets\/hajim-faculty-directory\.js/);
  const harness = apiHarness();
  let appended = null;
  const documentRef = {
    querySelector() { return { content: payload.generation_identity }; },
    createElement() {
      return {
        dataset: {},
        remove() {},
      };
    },
    head: {
      appendChild(script) {
        appended = script;
        harness.globalObject.HAJIM_FACULTY_DIRECTORY = payload;
        queueMicrotask(() => script.onload());
      },
    },
  };
  assert.equal(appended, null);
  const loaded = await harness.api.load({ documentRef, timeoutMs: 100 });
  assert.equal(loaded.profiles.length, 157);
  assert.equal(appended.src, `data/hajim-faculty-directory.js?v=${payload.generation_identity}`);
  assert.equal(appended.dataset.hajimFacultyDirectory, payload.generation_identity);
});

test("search requires meaningful input, covers name, unit, and reviewed evidence, and caps at twelve", () => {
  assert.equal(api.search(directory, "a").length, 0);
  assert.ok(api.search(directory, "Marc Porosoff").some(profile => profile.name === "Marc D. Porosoff"));
  assert.ok(api.search(directory, "Computer Science").every(profile => profile.search_text.includes("computer science")));
  assert.ok(api.search(directory, "terahertz").some(profile => /terahertz/i.test(profile.search_text)));
  assert.equal(api.search(directory, "engineering").length, 12);
  assert.ok(api.search(directory, "engineering").length <= api.MAX_RESULTS);
});

test("curated ChemE identities use only their frozen profiles while all other matching uses primary anchors", () => {
  const marc = directory.profiles.find(profile => profile.name === "Marc D. Porosoff");
  const marcMatcher = api.matchingProfile(directory, marc, curated);
  assert.deepEqual(Array.from(marcMatcher.key_terms), curated["Marc D. Porosoff"].key_terms);
  assert.deepEqual(Array.from(marcMatcher.domains), curated["Marc D. Porosoff"].domains);
  assert.equal(marcMatcher.research_summary, curated["Marc D. Porosoff"].research_summary);
  assert.equal(marcMatcher.faculty_evidence.authority, "curated_cheme");

  const additional = directory.profiles.find(profile => !profile.curated_profile_key && profile.primary.length < 5 && profile.context.length);
  assert.ok(additional);
  const additionalMatcher = api.matchingProfile(directory, additional, curated);
  const primaryLabels = additional.primary.map(mapping => directory.terms.get(mapping.term_id).label);
  const contextLabels = additional.context.map(mapping => directory.terms.get(mapping.term_id).label);
  assert.deepEqual(Array.from(additionalMatcher.key_terms), primaryLabels);
  assert.equal(additionalMatcher.domains.length, 0);
  assert.ok(contextLabels.every(label => !additionalMatcher.key_terms.includes(label)));
  assert.equal(additionalMatcher.faculty_evidence.authority, "reviewed_primary_anchors");
  assert.ok(additionalMatcher.faculty_evidence.primary.every(mapping => mapping.source_phrase && mapping.evidence));
});

test("a future zero-anchor profile remains searchable but cannot enter matching", () => {
  const source = directory.profiles[0];
  const unavailable = { ...source, primary: [], matching_available: false };
  assert.equal(api.matchingProfile(directory, unavailable, curated), null);
  const fixture = api.buildIndex({
    ...payload,
    profiles: [{ ...unavailable, name: "Future Searchable Researcher", summary: "Reviewed contextual evidence" }],
  });
  assert.equal(api.search(fixture, "Future Searchable")[0].matching_available, false);
});

test("identity joins are nonduplicative and the removed identity and opportunity graph are absent", () => {
  assert.equal(new Set(directory.profiles.map(profile => profile.id)).size, 157);
  assert.equal(directory.profiles.filter(profile => profile.curated_profile_key).length, 13);
  assert.equal(directory.profiles.filter(profile => profile.name === "Astrid M. Müller").length, 1);
  assert.equal(directory.profiles.find(profile => profile.name === "Astrid M. Müller").curated_profile_key, "Astrid M. Muller");
  assert.doesNotMatch(assetSource, /Melodie|Lawton/i);
  assert.doesNotMatch(assetSource, /pi_matches|faculty_opportunit|"edges"/i);
});

test("mismatched generations fail closed without accepting stale faculty bytes", () => {
  assert.throws(() => api.validate(payload, "0".repeat(64)), /does not match this page generation/);
  assert.throws(() => api.assetUrl("hajim-pr1"), /generation is invalid/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [source, page, appConfig, hybridSource] = await Promise.all([
  readFile(new URL("../../assets/team-hybrid.js", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
  readFile(new URL("../../assets/app-config.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-hybrid.js", import.meta.url), "utf8"),
]);

function loadApi() {
  const context = {
    globalThis: { FUNDING_HYBRID_SEARCH: { MAX_QUERY_CHARS: 500 } },
    Map,
    Set,
  };
  vm.runInNewContext(source, context);
  return context.globalThis.FUNDING_TEAM_HYBRID;
}

const profiles = [
  { name: "Researcher A", key_terms: ["catalyst design", "reaction kinetics"] },
  { name: "Researcher B", keywords: ["machine learning", "molecular simulation"] },
];
const themes = [{ label: "Data-driven catalyst discovery" }];

test("builds one balanced team query from every selected researcher", () => {
  const api = loadApi();
  const query = api.buildTeamQuery(profiles, themes);
  assert.match(query, /Data-driven catalyst discovery/);
  assert.match(query, /catalyst design/);
  assert.match(query, /machine learning/);
  assert.match(query, /reaction kinetics/);
  assert.match(query, /molecular simulation/);
  assert.doesNotMatch(query, /Researcher A|Researcher B/);
  assert.match(page, /Researcher names and publication text are not sent/);
});

test("team query derives a phrase-boundary limit from the shared client contract", () => {
  const api = loadApi();
  const longProfiles = ["alpha", "beta", "gamma", "delta"].map(marker => ({
    name: `${marker} researcher name must remain private`,
    key_terms: [
      `${marker} ${"x".repeat(72)}`,
      `${marker} ${"y".repeat(72)}`,
      `${marker} ${"z".repeat(72)}`,
    ],
  }));
  const allPhrases = new Set(longProfiles.flatMap(profile => profile.key_terms));
  const query = api.buildTeamQuery(longProfiles, [{ label: `theme ${"t".repeat(72)}` }]);
  assert.equal(api.SHARED_MAX_QUERY_CHARS, 500);
  assert.equal(api.MAX_QUERY_CHARS, 500 - api.CANONICALIZATION_SAFETY_CHARS);
  assert.ok(query.length <= api.MAX_QUERY_CHARS);
  assert.ok(query.split("; ").every(phrase => allPhrases.has(phrase) || phrase.startsWith("theme ")));
  for (const marker of ["alpha", "beta", "gamma", "delta"]) assert.match(query, new RegExp(marker));
  assert.doesNotMatch(query, /researcher name must remain private/);
});

test("query budgeting never silently omits a selected researcher's interests", () => {
  const api = loadApi();
  const oversized = Array.from({ length: 4 }, (_, i) => ({ key_terms: [`member ${i} ${"long ".repeat(34)}`] }));
  assert.equal(api.buildTeamQuery(oversized), "", "unrepresentable teams use the local fallback");
  oversized[0].capability_phrases = ["specific catalyst synthesis"];
  for (let i = 1; i < oversized.length; i++) oversized[i].capability_phrases = [`specific method ${i}`];
  const query = api.buildTeamQuery(oversized);
  assert.match(query, /specific catalyst synthesis/);
  for (let i = 1; i < oversized.length; i++) assert.ok(query.includes(`specific method ${i}`));
});

test("uses at most one shared hybrid request per team recomputation", async () => {
  const api = loadApi();
  let requests = 0;
  const client = {
    configured: true,
    async search() {
      requests += 1;
      return { parents: [{ parent_id: "fit-b", hybrid_rank: 1 }] };
    },
  };
  const coordinator = api.createCoordinator({ client });
  const outcomes = await Promise.all([
    coordinator.run({ profiles, themes }),
    coordinator.run({ profiles, themes }),
  ]);
  assert.equal(requests, 1);
  assert.equal(coordinator.requestCount(), 1);
  assert.equal(outcomes[0].cached, false);
  assert.equal(outcomes[1].cached, true);
  assert.equal(coordinator.state().request_count, 1);
  await coordinator.run({ profiles, themes: [{ label: "A different active theme" }] });
  assert.equal(requests, 2);
});

test("semantic ranking cannot add an opportunity without full-team local evidence", async () => {
  const api = loadApi();
  const client = {
    configured: true,
    async search() {
      return { parents: [
        { parent_id: "semantic-only", hybrid_rank: 1 },
        { parent_id: "fit-b", hybrid_rank: 2 },
        { parent_id: "fit-a", hybrid_rank: 3 },
      ] };
    },
  };
  const outcome = await api.createCoordinator({ client }).run({ profiles, themes });
  const localFullTeamMatches = [{ d: { id: "fit-a" } }, { d: { id: "fit-b" } }];
  const ranked = api.applyHybridRanking(localFullTeamMatches, outcome.rankById);
  assert.deepEqual(Array.from(ranked, item => item.d.id), ["fit-b", "fit-a"]);
  assert.equal(ranked.some(item => item.d.id === "semantic-only"), false);
});

test("provider failure preserves the original local Team Match order", async () => {
  const api = loadApi();
  const client = {
    configured: true,
    async search() { throw Object.assign(new Error("timeout"), { code: "proxy_timeout" }); },
  };
  const local = [{ d: { id: "fit-a" } }, { d: { id: "fit-b" } }];
  const outcome = await api.createCoordinator({ client }).run({ profiles, themes });
  assert.equal(outcome.fallback, true);
  assert.equal(outcome.enhanced, false);
  assert.equal(outcome.reason, "proxy_timeout");
  assert.equal(outcome.reason_category, "unavailable");
  assert.equal(outcome.request_count, 1);
  assert.equal(outcome.cached, false);
  assert.deepEqual(Array.from(api.applyHybridRanking(local, outcome.rankById), item => item.d.id), ["fit-a", "fit-b"]);
});

test("an unconfigured provider makes no request and preserves local behavior", async () => {
  const api = loadApi();
  let requests = 0;
  const client = {
    configured: false,
    async search() { requests += 1; return { parents: [] }; },
  };
  const coordinator = api.createCoordinator({ client });
  const outcome = await coordinator.run({ profiles, themes });
  assert.equal(requests, 0);
  assert.equal(coordinator.requestCount(), 0);
  assert.equal(outcome.fallback, true);
  assert.equal(outcome.reason, "proxy_unconfigured");
  assert.equal(outcome.request_count, 0);
});

test("rate and budget failures are exposed as a nontechnical limited category", async () => {
  const api = loadApi();
  for (const code of ["rate_limited", "budget_limited"]) {
    const client = {
      configured: true,
      async search() { throw Object.assign(new Error(code), { code }); },
    };
    const outcome = await api.createCoordinator({ client }).run({ profiles, themes });
    assert.equal(outcome.fallback, true);
    assert.equal(outcome.reason, code);
    assert.equal(outcome.reason_category, "limited");
  }
  assert.match(page, /Showing the local team-fit order\. Enhanced ordering is temporarily unavailable\./);
  assert.match(page, /Showing the local team-fit order\. Enhanced ordering is temporarily limited\./);
  assert.match(page, /Retry enhanced ordering/);
});

test("Team Match reuses the frozen hybrid client, vector assets, and proxy handshake", () => {
  assert.match(page, /assets\/search-v2-config\.js/);
  assert.match(page, /assets\/search-hybrid\.js/);
  assert.match(page, /HYBRID_SEARCH_API\.createClient/);
  assert.match(page, /RETRIEVAL_API\.create\(catalogData, SEARCH_API, \{[\s\S]*?searchV2: true/);
  assert.match(page, /RETRIEVAL_API\.create\(CHILD_CATALOG, SEARCH_API, \{[\s\S]*?catalogRole: "child"/);
  assert.match(page, /APP_CONFIG\.hybridSearch\.proxyUrl/);
  assert.match(page, /APP_CONFIG\.hybridSearch\.manifestUrl/);
  assert.match(page, /APP_CONFIG\.hybridSearch\.vectorUrl/);
  assert.match(page, /connect-src[^>]*http:\/\/localhost:\* http:\/\/127\.0\.0\.1:\*/);
  assert.match(appConfig, /search-v2-voyage-manifest\.json/);
  assert.match(appConfig, /search-v2-voyage-vectors\.f16/);
  assert.match(hybridSource, /manifest\.corpus_sha256 !== localCorpusHash/);
  assert.match(hybridSource, /vector_hash_mismatch/);
  assert.match(hybridSource, /strongestParents\(passages\)/);
});

test("team reranking restricts candidates to the full-team intersection and refreshes when eligibility changes", async () => {
  const api = loadApi();
  const calls = [];
  const coordinator = api.createCoordinator({ client: {
    configured: true,
    async search(query, options) { calls.push({ query, options }); return { parents: [] }; },
  } });
  await coordinator.run({ profiles, eligibleParentIds: new Set(["fit-a"]) });
  await coordinator.run({ profiles, eligibleParentIds: new Set(["fit-b"]) });
  assert.equal(calls.length, 2);
  assert.deepEqual([...calls[0].options.eligibleParentIds], ["fit-a"]);
  assert.deepEqual([...calls[1].options.eligibleParentIds], ["fit-b"]);
  await coordinator.run({ profiles, eligibleParentIds: new Set() });
  assert.equal(calls.length, 2, "empty intersections do not spend an API request");
  assert.match(page, /eligibleParentIds: lastHybridEligibleIds/);
});

test("profile corrections invalidate cached acronym context without sending it as the query", async () => {
  const api = loadApi();
  const calls = [];
  const coordinator = api.createCoordinator({ client: {
    configured: true,
    async search(query, options) { calls.push({ query, options }); return { parents: [] }; },
  } });
  const before = [{ name: "Private Name", keywords: ["CARS"], research_summary: "Coherent anti-Stokes Raman spectroscopy (CARS)" }];
  const after = [{ ...before[0], research_summary: "Computer aided routing systems (CARS)" }];
  await coordinator.run({ profiles: before });
  await coordinator.run({ profiles: after });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].query, "CARS");
  assert.match(calls[0].options.context, /Coherent anti-Stokes/);
  assert.doesNotMatch(calls[0].options.context, /Private Name/);
  assert.notEqual(api.teamSignature(before), api.teamSignature([{ ...before[0], keywords: ["cars"] }]));
});

test("synchronous provider errors preserve local team matching", async () => {
  const api = loadApi();
  const outcome = await api.createCoordinator({ client: {
    configured: true, search() { throw new Error("unavailable"); },
  } }).run({ profiles });
  assert.equal(outcome.fallback, true);
});

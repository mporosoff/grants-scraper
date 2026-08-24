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
  const context = { globalThis: {}, Map, Set };
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
  assert.match(page, /not researcher names or publication text/);
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

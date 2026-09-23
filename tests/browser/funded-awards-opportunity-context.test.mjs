import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import vm from "node:vm";
import test from "node:test";
import { buildAwardSnapshot, publicSnapshot, snapshotPage } from "../../workers/award-api/src/snapshot.js";
import { validateSnapshotCreate } from "../../workers/award-api/src/index.js";

const root = new URL("../../", import.meta.url);
const paths = ["assets/award-links.js", "assets/funded-awards-core.js", "assets/institutional-intelligence-core.js", "assets/funded-awards.js", "assets/institutional-intelligence-snapshots.js"];
const sources = await Promise.all(paths.map(path => readFile(new URL(path, root), "utf8")));
const records = [
  { opportunity_id: "362061", opportunity_number: "PD-26-367Y", agency_code: "NSF", agency: "National Science Foundation", title: "Chemical Process Systems", detail_page: "https://www.nsf.gov/funding/opportunities/chemical-process-systems" },
  { opportunity_id: "nih-test", opportunity_number: "PAR-26-123", agency_code: "HHS-NIH", agency: "National Institutes of Health", title: "Synthetic NIH opportunity" },
  { opportunity_id: "doe-test", opportunity_number: "DE-FOA-0003000", agency_code: "PAMS-SC", agency: "Office of Science", title: "Synthetic DOE opportunity" },
  { opportunity_id: "unmapped", opportunity_number: "NSF-26-999", agency_code: "NSF", title: "Unmapped synthetic opportunity" },
];
const plain = value => JSON.parse(JSON.stringify(value));

function loadCore() {
  const context = vm.createContext({ URL, URLSearchParams, GRANT_CATALOG: { opportunities: records } });
  sources.slice(0, 3).forEach(source => vm.runInContext(source, context));
  return context.FUNDING_INSTITUTIONAL_INTELLIGENCE;
}

test("selected award requests retain complete reviewed mappings and source-specific identities", () => {
  const core = loadCore();
  for (const [id, source, mapping] of [
    ["362061", "NSF", { program_codes: ["367Y00", "140100", "764400", "141700", "140300"] }],
    ["nih-test", "NIH", { opportunity_number: "PAR-26-123" }],
    ["doe-test", "DOE", { opportunity_number: "DE-FOA-0003000" }],
  ]) {
    const state = { opportunity: id, agency: "DOD", program: "12.800", institution: "Test University", ror_id: "https://ror.org/012345678", year_start: "2020", topic: "catalysis" };
    const request = plain(core.buildAwardRequest(state));
    assert.deepEqual(request.sources, [source]);
    assert.deepEqual(request.criteria, { ...mapping, institution: "Test University", institution_id: "https://ror.org/012345678", year_start: 2020, topic: "catalysis" });
    const restored = core.stateFromSearch(core.urlForState("https://example.test/funded_awards.html", state).search);
    assert.equal(restored.opportunity, id);
    assert.deepEqual(plain(core.buildAwardRequest(restored)), request);
    const translated = core.sanitizeQuestionPlan({ agency: "DOD", program: "12.800" }, state);
    assert.equal(translated.opportunity, id);
    assert.equal(translated.agency, source);
    const normalized = validateSnapshotCreate({ sources: request.sources, criteria: request.criteria }, { maxResults: 50 });
    assert.ok(normalized);
    core.validateSelectedSnapshot(restored, { request: { sources: normalized.sources, criteria: normalized.publicCriteria } });
    const ended = { ...state, year_end: "2025", institution: "  Test   University  ", topic: "  catalysis   research " };
    const endedRequest = plain(core.buildAwardRequest(ended));
    const endedNormalized = validateSnapshotCreate({ sources: endedRequest.sources, criteria: endedRequest.criteria }, { maxResults: 50 });
    assert.ok(endedNormalized);
    core.validateSelectedSnapshot(ended, { request: { sources: endedNormalized.sources, criteria: endedNormalized.publicCriteria } });
  }
  assert.throws(() => core.buildAwardRequest({ opportunity: "missing", institution: "Test University" }), /unavailable in this catalog/);
  assert.throws(() => core.buildAwardRequest({ opportunity: "unmapped", institution: "Test University" }), /no exact historical-award mapping/);
});

test("the only HTML consumer references all three exact changed browser module bytes", async () => {
  const html = await readFile(new URL("funded_awards.html", root), "utf8");
  for (const index of [2, 3, 4]) {
    const hash = createHash("sha256").update(sources[index]).digest("hex");
    assert.ok(html.includes(`${paths[index]}?v=${hash}`), paths[index]);
  }
});

test("scoped cached pages expose only the existing public request and reject changed scope or filters", () => {
  const core = loadCore();
  const state = { opportunity: "362061", institution: "Test University" };
  const request = plain(core.buildAwardRequest(state));
  const snapshot = buildAwardSnapshot({ snapshotId: "a".repeat(64), queryId: "b".repeat(64), asOf: "2026-09-23T12:00:00Z", request, sourcePayloads: { NSF: { source: "NSF", results: [], total_count: 0, has_more: false } } });
  snapshot.runtime_request = { private_runtime_marker: "must never be exported" };
  const page = snapshotPage(snapshot);
  assert.deepEqual(page.request, publicSnapshot(snapshot).request);
  assert.equal(JSON.stringify(page).includes("private_runtime_marker"), false);
  core.validateSelectedSnapshot(state, page);
  for (const bad of [
    { ...page, request: undefined },
    { ...page, request: { ...request, sources: ["NIH"] } },
    { ...page, request: { ...request, criteria: { ...request.criteria, program_codes: ["367Y00"] } } },
    { ...page, request: { ...request, criteria: { ...request.criteria, institution: "Other University" } } },
  ]) assert.throws(() => core.validateSelectedSnapshot(state, bad), /do not match/);
});

class Element {
  constructor(id) {
    this.id = id; this.value = ""; this.textContent = ""; this.innerHTML = ""; this.dataset = {}; this.events = new Map(); this.attributes = new Map();
    const classes = new Set(["hidden"]);
    this.classList = { add: (...v) => v.forEach(x => classes.add(x)), remove: (...v) => v.forEach(x => classes.delete(x)), contains: x => classes.has(x), toggle: (x, yes = !classes.has(x)) => yes ? classes.add(x) : classes.delete(x) };
  }
  addEventListener(name, fn) { this.events.set(name, [...(this.events.get(name) || []), fn]); }
  async fire(name, extra = {}) { for (const fn of this.events.get(name) || []) await fn({ currentTarget: this, target: this, preventDefault() {}, ...extra }); }
  setAttribute(k, v) { this.attributes.set(k, String(v)); }
  removeAttribute(k) { this.attributes.delete(k); }
  getAttribute(k) { return this.attributes.get(k); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  closest() { return null; }
  focus() {}
  blur() {}
  scrollIntoView() {}
  contains() { return false; }
}

async function browser(search = "?opportunity=362061", { wrongCachedRequest = false, legacyPages = false, wrongPageId = false, savedSnapshots = [] } = {}) {
  const elements = new Map();
  const node = id => { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); };
  const events = new Map();
  const location = { href: `https://example.test/funded_awards.html${search}`, search, protocol: "https:" };
  const historyEntries = [];
  function update(url) { const next = new URL(url); location.href = next.href; location.search = next.search; }
  const history = {
    state: null,
    replaceState(value, _title, url) { this.state = value; update(url); },
    pushState(value, _title, url) { historyEntries.push(location.href); this.state = value; update(url); },
  };
  const calls = []; const snapshots = new Map(savedSnapshots);
  const context = vm.createContext({
    URL, URLSearchParams, AbortController, console, setTimeout, clearTimeout, structuredClone,
    location, history, GRANT_CATALOG: { opportunities: records },
    document: { baseURI: location.href, getElementById: node, querySelector: () => null, addEventListener() {}, activeElement: node("ii-institution"), documentElement: { scrollHeight: 1000 }, body: { scrollHeight: 1000 } },
    FUNDING_CREDENTIALS: { loadKey: () => "", resolveProvider: () => "hosted" },
    FUNDING_AWARD_API_CONFIG: { searchUrl: "https://awards.test/legacy", snapshotUrl: "https://awards.test/snapshots", snapshotPageUrl: "https://awards.test/page", institutionsUrl: "https://awards.test/institutions", institutionSearchUrl: "https://awards.test/institutions", timeoutMs: 1000, maxResultsPerSource: 10 },
    FUNDING_AI: {},
    PublicTools: { syncAwardForm() {}, resetAwardViews() {}, showAwardProjects() {}, restoreAwardFocus() {}, awardAiOpen: () => false },
    requestAnimationFrame: fn => { fn(); return 1; },
    scrollTo() {}, scrollX: 0, scrollY: 0, innerHeight: 800,
    addEventListener(name, fn) { events.set(name, [...(events.get(name) || []), fn]); },
    fetch: async (url, options) => {
      const request = options?.body ? JSON.parse(options.body) : null;
      calls.push({ url: String(url), request });
      if (String(url).includes("institutions")) return { ok: true, json: async () => ({ institutions: [{ id: "https://ror.org/012345678", canonical_name: "Test University", aliases: [], acronyms: [], location: {}, match: { exact: true, type: "canonical" } }], registry: { status: "ok" } }) };
      let payload;
      if (String(url).endsWith("/snapshots")) {
        const id = createHash("sha256").update(JSON.stringify(request)).digest("hex");
        const value = buildAwardSnapshot({ snapshotId: id, queryId: "b".repeat(64), asOf: "2026-09-23T12:00:00Z", request, sourcePayloads: Object.fromEntries(request.sources.map(source => [source, { source, results: [], total_count: 0, has_more: false }])) });
        snapshots.set(id, value); payload = publicSnapshot(value);
      } else if (String(url).endsWith("/page")) {
        const value = snapshots.get(request.snapshot_id);
        if (!value) throw new Error("Unknown synthetic snapshot");
        payload = snapshotPage(value, { page: request.page, pageSize: request.page_size, facet: request.facet, sort: request.sort });
        if (legacyPages) delete payload.request;
        if (wrongCachedRequest) payload.request = { sources: ["NIH"], criteria: { topic: "unrelated" } };
        if (wrongPageId) payload.snapshot_id = "f".repeat(64);
      } else throw new Error(`Unexpected route ${url}`);
      return { ok: true, json: async () => payload };
    },
  });
  context.window = context;
  sources.forEach(source => vm.runInContext(source, context));
  const settle = async () => { for (let i = 0; i < 30; i += 1) await new Promise(resolve => setImmediate(resolve)); };
  await settle();
  return { node, calls, context, historyEntries, snapshots, settle, async navigate(url) { update(url); for (const fn of events.get("popstate") || []) await fn({ state: history.state }); await settle(); } };
}

test("actual loaded controllers keep selected context through institution submit, history and explicit clearing", async () => {
  const app = await browser();
  assert.equal(app.node("selected-opportunity-heading").textContent, "Chemical Process Systems");
  assert.equal(app.node("ii-agency").value, "NSF");
  assert.equal(app.node("ii-agency").disabled, true);
  assert.equal(app.calls.filter(c => c.url.endsWith("/snapshots")).length, 1);
  assert.equal(app.calls.filter(c => c.url.endsWith("/legacy")).length, 0);
  assert.equal(app.node("ii-status").classList.contains("error-text"), false, app.node("ii-status").textContent);
  const initial = app.context.location.href;
  app.node("ii-institution").value = "Test University";
  await app.node("ii-form").fire("submit"); await app.settle();
  assert.equal(app.node("ii-status").classList.contains("error-text"), false, app.node("ii-status").textContent);
  const scoped = app.context.location.href;
  const request = app.calls.filter(c => c.url.endsWith("/snapshots")).at(-1).request;
  assert.deepEqual(request.sources, ["NSF"]);
  assert.deepEqual(request.criteria.program_codes, ["367Y00", "140100", "764400", "141700", "140300"]);
  assert.equal(request.criteria.institution, "Test University");
  assert.equal(new URL(scoped).searchParams.get("opportunity"), "362061");
  assert.equal(app.node("ii-status").classList.contains("error-text"), false, app.node("ii-status").textContent);
  const creations = app.calls.filter(c => c.url.endsWith("/snapshots")).length;
  await app.navigate(initial); await app.navigate(scoped);
  assert.equal(app.node("ii-institution").value, "Test University");
  assert.equal(app.node("selected-opportunity").classList.contains("hidden"), false);
  assert.equal(app.calls.filter(c => c.url.endsWith("/snapshots")).length, creations, "history reuses exact snapshot pages");
  await app.node("clear-opportunity").fire("click"); await app.settle();
  assert.equal(new URL(app.context.location.href).searchParams.has("opportunity"), false);
  assert.equal(app.node("ii-institution").value, "Test University");
  assert.equal(app.node("ii-agency").disabled, false);
  assert.equal(app.node("selected-opportunity").classList.contains("hidden"), true);
  assert.match(app.node("ii-search-help").textContent, /institution’s awards/);
});

test("unmapped or missing selection never silently submits a generic award search", async () => {
  for (const id of ["missing", "unmapped"]) {
    const app = await browser(`?opportunity=${id}&institution=Test+University`);
    assert.equal(app.calls.length, 0);
    assert.equal(app.node("ii-status").classList.contains("error-text"), true);
    assert.match(app.node("ii-status").textContent, /clear selection/i);
    assert.equal(new URL(app.context.location.href).searchParams.get("opportunity"), id);
  }
});

test("actual snapshot response with another scope is not rendered under the selected title", async () => {
  const app = await browser("?opportunity=362061", { wrongCachedRequest: true });
  assert.match(app.node("ii-status").textContent, /do not match/);
  assert.equal(app.node("ii-output").classList.contains("hidden"), true);
  assert.equal(app.calls.filter(c => c.url.endsWith("/snapshots")).length, 1);
});

test("Pages-first and Worker rollback pages reuse only exact validated session metadata", async () => {
  const app = await browser("?opportunity=362061", { legacyPages: true });
  assert.equal(app.node("ii-status").classList.contains("error-text"), false, app.node("ii-status").textContent);
  const initial = app.context.location.href;
  app.node("ii-institution").value = "Test University";
  await app.node("ii-form").fire("submit"); await app.settle();
  const scoped = app.context.location.href;
  await app.navigate(initial); await app.navigate(scoped);
  assert.equal(app.node("ii-status").classList.contains("error-text"), false, app.node("ii-status").textContent);
  assert.equal(app.calls.filter(c => c.url.endsWith("/snapshots")).length, 2, "history introduces no new searches");
  const unproved = await browser(new URL(scoped).search, { legacyPages: true, savedSnapshots: app.snapshots });
  assert.match(unproved.node("ii-status").textContent, /Run Search again/);
  assert.equal(unproved.node("ii-output").classList.contains("hidden"), true);
  assert.equal(unproved.calls.filter(c => c.url.endsWith("/snapshots")).length, 0, "a bookmarked legacy page is not silently regenerated");
  for (const options of [{ wrongPageId: true }, { wrongPageId: true, legacyPages: true }, { wrongCachedRequest: true, legacyPages: true }]) {
    const bad = await browser("?opportunity=362061", options);
    assert.match(bad.node("ii-status").textContent, /do not match/);
    assert.equal(bad.node("ii-output").classList.contains("hidden"), true);
  }
});

test("old scope-proof eviction stays bounded and cannot broaden later history results", async () => {
  const app = await browser("?opportunity=362061", { legacyPages: true });
  const original = app.context.location.href;
  for (let index = 0; index < 20; index += 1) {
    app.node("ii-topic").value = `Synthetic topic ${index}`;
    await app.node("ii-form").fire("submit"); await app.settle();
  }
  const creations = app.calls.filter(c => c.url.endsWith("/snapshots")).length;
  await app.navigate(original);
  assert.match(app.node("ii-status").textContent, /Run Search again/);
  assert.equal(app.node("ii-output").classList.contains("hidden"), true, "previous results cannot remain under the restored scope");
  assert.equal(app.calls.filter(c => c.url.endsWith("/snapshots")).length, creations);
});

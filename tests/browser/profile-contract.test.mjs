import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../../assets/profile.js", import.meta.url),
  "utf8",
);

function loadProfileApi() {
  const context = {
    Blob,
    Date,
    JSON,
    Math,
    Object,
    Set,
    String,
    Uint8Array,
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.FUNDING_PROFILE;
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
    dump() {
      return Object.fromEntries(values);
    },
  };
}

function mockFile(name, type, text) {
  const bytes = new TextEncoder().encode(text);
  return {
    name,
    type,
    size: bytes.byteLength,
    text: async () => text,
    arrayBuffer: async () =>
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
  };
}

test("persists a sanitized profile and preferences without credential fields", () => {
  const api = loadProfileApi();
  const storage = memoryStorage();
  const result = api.saveProfile({
    research_description: "Electrochemical carbon dioxide conversion",
    expertise_keywords: "catalysis, reactors",
    applicant_context: "higher_education",
    career_stage: "early_career",
    orcid_id: "0000-0002-1825-0097",
    orcid_name: "Josiah Carberry",
    orcid_text: "Ionic liquid extraction and rare earth element recovery",
    orcid_work_count: 12,
    cv_name: "researcher-cv.txt",
    cv_text: "Catalysis and electrochemistry ".repeat(20),
    include_cv_in_ai: true,
    remember: true,
    api_key: "must-not-persist",
    preferences: {
      status_posted: true,
      status_forecasted: false,
      status_archived: true,
      profile_search_active: true,
      ai_provider: "anthropic",
      sort: "relevance",
      evidence: true,
      facets: {
        agency: ["Department of Energy"],
        source: ["National Science Foundation"],
        source_type: ["Federal"],
      },
    },
  }, storage);

  assert.equal(result.saved, true);
  const raw = storage.dump()[api.PROFILE_STORAGE_KEY];
  assert.doesNotMatch(raw, /must-not-persist|api_key/);
  const loaded = api.loadProfile(storage);
  assert.equal(loaded.research_description, "Electrochemical carbon dioxide conversion");
  assert.equal(loaded.preferences.profile_search_active, true);
  assert.equal(loaded.preferences.status_archived, false, "archive opt-in must remain session-only");
  assert.equal(loaded.preferences.ai_provider, "anthropic");
  assert.equal(loaded.preferences.evidence, true);
  assert.equal(loaded.orcid_id, "0000-0002-1825-0097");
  assert.match(loaded.orcid_text, /rare earth element/);
  assert.deepEqual([...loaded.preferences.facets.agency], ["Department of Energy"]);
  assert.deepEqual(
    [...loaded.preferences.facets.source],
    ["National Science Foundation"],
  );
  assert.deepEqual([...loaded.preferences.facets.source_type], ["Federal"]);
  assert.ok(loaded.cv_word_count > 10);
});

test("an empty profile is not treated as saved before explicit opt-in", () => {
  const storage = memoryStorage();
  const profile = loadProfileApi();

  assert.equal(profile.emptyProfile().remember, false);
  assert.equal(profile.loadProfile(storage).remember, false);
});

test("disabling remember removes the saved profile", () => {
  const api = loadProfileApi();
  const storage = memoryStorage();
  api.saveProfile({ research_description: "first profile", remember: true }, storage);
  const result = api.saveProfile({
    research_description: "tab-only profile",
    remember: false,
  }, storage);
  assert.equal(result.saved, false);
  assert.equal(result.reason, "remember_disabled");
  assert.equal(storage.getItem(api.PROFILE_STORAGE_KEY), null);
});

test("bounds persisted CV text", () => {
  const api = loadProfileApi();
  const profile = api.sanitizeProfile({
    cv_text: "research ".repeat(20_000),
  });
  assert.equal(profile.cv_text.length, api.MAX_CV_TEXT_CHARS);
  assert.equal(profile.cv_truncated, true);
});

test("extracts TXT CV content locally", async () => {
  const api = loadProfileApi();
  const text = [
    "Marc Researcher",
    "Research: catalytic carbon dioxide conversion and electrochemical reactors.",
    "Publications: sustainable chemicals, process systems, and materials synthesis.",
  ].join("\n");
  const extracted = await api.extractCv(mockFile("cv.txt", "text/plain", text));
  assert.equal(extracted.type, "text");
  assert.match(extracted.text, /electrochemical reactors/);
  assert.ok(extracted.wordCount > 10);
});

test("supports injected PDF and DOCX parsers without network access", async () => {
  const api = loadProfileApi();
  const pdf = await api.extractCv(
    mockFile("cv.pdf", "application/pdf", "mock pdf bytes"),
    {
      pdfLoader: async () => ({
        getDocument: () => ({
          promise: Promise.resolve({
            numPages: 2,
            getPage: async pageNumber => ({
              getTextContent: async () => ({
                items: [{
                  str: `Page ${pageNumber} catalytic materials and reactor systems research`,
                  hasEOL: true,
                }],
              }),
              cleanup() {},
            }),
            cleanup() {},
            destroy() {},
          }),
        }),
      }),
    },
  );
  assert.equal(pdf.pageCount, 2);
  assert.match(pdf.text, /Page 2 catalytic/);

  const docx = await api.extractCv(
    mockFile(
      "cv.docx",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "mock docx bytes",
    ),
    {
      mammothLoader: async () => ({
        extractRawText: async () => ({
          value: "Research experience in catalysis, electrochemistry, carbon utilization, materials, and reactor design. ".repeat(2),
          messages: [],
        }),
      }),
    },
  );
  assert.equal(docx.type, "DOCX");
  assert.match(docx.text, /carbon utilization/);
});

test("stores evaluation labels separately and fingerprints profiles deterministically", () => {
  const api = loadProfileApi();
  const storage = memoryStorage();
  const profile = {
    research_description: "Catalytic carbon conversion",
    expertise_keywords: "electrochemistry",
  };
  assert.equal(api.profileFingerprint(profile), api.profileFingerprint(profile));

  const saved = api.saveFeedback({
    "ABC-123": {
      opportunity_id: "ABC-123",
      title: "Example opportunity",
      label: "useful",
      reason: "topic_fit",
      retrieval_rank: 4,
      ai_rank: 2,
    },
    invalid: {
      opportunity_id: "invalid",
      label: "unsupported",
    },
  }, storage);
  assert.equal(saved, true);
  const loaded = api.loadFeedback(storage);
  assert.equal(loaded["ABC-123"].label, "useful");
  assert.equal(loaded["ABC-123"].ai_rank, 2);
  assert.equal(loaded.invalid, undefined);
});

test("builds a bounded opt-in CV context for AI calls", () => {
  const api = loadProfileApi();
  const profile = {
    research_description: "Electrochemical carbon conversion",
    expertise_keywords: "catalysis",
    applicant_context: "higher_education",
    career_stage: "early_career",
    cv_text: "0123456789".repeat(100),
    include_cv_in_ai: true,
    orcid_id: "0000-0002-1825-0097",
    orcid_text: "Ionic liquids and rare earth extraction. ".repeat(500),
  };
  const enabled = api.aiProfileContext(profile, 120);
  assert.equal(enabled.cv_excerpt.length, 120);
  assert.match(enabled.cv_excerpt_note, /First 120 characters/);
  assert.equal(enabled.orcid_id, "0000-0002-1825-0097");
  assert.equal(enabled.orcid_publications_excerpt.length, 120);

  const disabled = api.aiProfileContext({
    ...profile,
    include_cv_in_ai: false,
  }, 120);
  assert.equal(disabled.cv_excerpt, undefined);
  assert.equal(disabled.research_description, profile.research_description);
});

test("extracts a text CV and collapses blank lines", async () => {
  const api = loadProfileApi();
  const text =
    "Research Summary\n\n\n\nI study heterogeneous catalysis for clean " +
    "hydrogen production and carbon capture across several funded projects.\n\n\n";
  const extracted = await api.extractCv(mockFile("cv.txt", "text/plain", text));
  assert.match(extracted.text, /Research Summary/);
  assert.match(extracted.text, /heterogeneous catalysis/);
  assert.ok(!extracted.text.includes("\n\n\n"));   // multiple blanks collapsed
  assert.ok(extracted.text.length >= 80);           // passes the min-text gate
});

test("profile.js avoids Array.prototype.at (older Safari lacks it)", () => {
  // Regression guard for the CV-upload bug: .at() throws on Safari < 15.4,
  // which made every CV upload fail silently.
  assert.ok(!source.includes(".at("), "use index access instead of .at() in profile.js");
});

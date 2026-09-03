import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../../assets/orcid.js", import.meta.url), "utf8");

function loadApi() {
  const context = { Date, Error, Math, Number, Object, Set, String, encodeURIComponent };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.FUNDING_ORCID;
}

function payload() {
  const author = { given: "Josiah", family: "Carberry", ORCID: "https://orcid.org/0000-0002-1825-0097" };
  return {
    message: {
      "total-results": 2,
      items: [
        {
          DOI: "10.1234/ree-1",
          title: ["Ionic liquid extraction and recovery of rare earth elements"],
          author: [author],
          subject: ["Separation Science"],
          published: { "date-parts": [[2026, 1, 1]] },
        },
        {
          DOI: "10.1234/ree-2",
          title: ["Selective ionic liquid separation of critical minerals"],
          author: [author],
          subject: ["Separation Science"],
          published: { "date-parts": [[2025]] },
        },
      ],
    },
  };
}

test("formats ORCID entry, accepts compact IDs, and rejects invalid checksums", () => {
  const api = loadApi();
  assert.equal(api.formatInput("0000000218250097"), "0000-0002-1825-0097");
  assert.equal(api.formatInput("0000000218"), "0000-0002-18");
  assert.equal(api.formatInput("00000002182500971234"), "0000-0002-1825-0097");
  assert.equal(api.normalizeId("https://orcid.org/0000-0002-1825-0097/"), "0000-0002-1825-0097");
  assert.equal(api.normalizeId("0000000218250097"), "0000-0002-1825-0097");
  assert.equal(api.normalizeId("0000-0002-1825-0098"), "");
  assert.equal(api.normalizeId("not-an-orcid"), "");
});

test("binds a 19-character auto-formatting input contract", () => {
  const api = loadApi();
  const listeners = {};
  const input = {
    autocomplete: "",
    dataset: {},
    inputMode: "",
    maxLength: 0,
    pattern: "",
    value: "",
    addEventListener(type, listener) { listeners[type] = listener; },
  };
  api.bindInput(input);
  assert.equal(input.maxLength, 19);
  assert.equal(input.inputMode, "text");
  assert.match(input.pattern, /\[0-9\]\{4\}/);
  input.value = "00000002182500971234";
  listeners.input();
  assert.equal(input.value, "0000-0002-1825-0097");
  let prevented = false;
  listeners.paste({
    clipboardData: { getData: () => "https://orcid.org/0000-0002-1825-0097" },
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(input.value, "0000-0002-1825-0097");
});

test("parses ORCID-linked publications into bounded matching context", () => {
  const api = loadApi();
  const parsed = api.parseWorks(payload(), "0000-0002-1825-0097");
  assert.equal(parsed.name, "Josiah Carberry");
  assert.equal(parsed.importedWorkCount, 2);
  assert.match(parsed.publicationText, /rare earth elements/i);
  assert.ok(parsed.keywords.some(keyword => /ionic liquid/.test(keyword)));
  assert.ok(parsed.keywords.some(keyword => /separation science/.test(keyword)));
});

test("fetches Crossref works using an ORCID filter", async () => {
  const api = loadApi();
  let requested = "";
  const parsed = await api.fetchProfile("0000-0002-1825-0097", {
    fetchImpl: async url => {
      requested = url;
      return { ok: true, status: 200, json: async () => payload() };
    },
  });
  assert.match(requested, /filter=orcid%3A0000-0002-1825-0097/);
  assert.equal(parsed.works.length, 2);
});

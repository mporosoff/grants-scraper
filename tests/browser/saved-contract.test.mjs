import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../../assets/saved.js", import.meta.url),
  "utf8",
);

function loadSaved() {
  const context = { Array, Set, JSON, String, Object, Date };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.FUNDING_SAVED;
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
}

const S = loadSaved();
const rec = (over = {}) => ({
  opportunity_id: "x1", opportunity_number: "DE-FOA-1",
  title: "Carbon capture catalysis", agency: "Office of Science",
  source: "Grants.gov", source_type: "Federal", close_date: "2026-12-01",
  detail_page: "https://x.org/a", ...over,
});

test("toggle saves then unsaves, persisting to storage", () => {
  const store = memoryStorage();
  let result = S.toggle(rec(), store);
  assert.equal(result.saved, true);
  assert.equal(result.items.length, 1);
  assert.equal(S.isSaved(S.load(store), "x1"), true);
  result = S.toggle(rec(), store);
  assert.equal(result.saved, false);
  assert.equal(S.load(store).length, 0);
});

test("keeps a compact snapshot with an official url", () => {
  const store = memoryStorage();
  S.toggle(rec(), store);
  const item = S.load(store)[0];
  assert.equal(item.title, "Carbon capture catalysis");
  assert.equal(item.url, "https://x.org/a");
  assert.equal(item.source, "Grants.gov");
  assert.ok(item.saved_at);
});

test("dedupes by id and supports remove/clear", () => {
  const store = memoryStorage();
  S.toggle(rec(), store);
  S.toggle(rec({ opportunity_id: "x2", opportunity_number: "NSF-2", title: "Second" }), store);
  assert.equal(S.load(store).length, 2);
  const items = S.remove("x1", store);
  assert.equal(items.length, 1);
  assert.equal(S.idOf(items[0]), "x2");
  S.clear(store);
  assert.equal(S.load(store).length, 0);
});

test("rejects items without a title or id", () => {
  assert.equal(S.sanitizeItem({ title: "no id" }), null);
  assert.equal(S.sanitizeItem({ opportunity_id: "x" }), null);
});

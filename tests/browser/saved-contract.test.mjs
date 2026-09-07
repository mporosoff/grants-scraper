import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import "../../assets/submission-schedule.js";

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

function rejectingStorage(items = []) {
  const values = new Map([[S.STORAGE_KEY, JSON.stringify(items)]]);
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem() { throw new Error("deterministic setItem rejection"); },
    removeItem() { throw new Error("deterministic removeItem rejection"); },
  };
}

const S = loadSaved();
const schedule = globalThis.FUNDING_SUBMISSION_SCHEDULE;
const rec = (over = {}) => ({
  opportunity_id: "x1", opportunity_number: "DE-FOA-1",
  title: "Carbon capture catalysis", agency: "Office of Science",
  source: "Grants.gov", source_type: "Federal", close_date: "2026-12-01",
  detail_page: "https://x.org/a", ...over,
});

test("a saved source alias has canonical membership without rewriting pursuit data", async () => {
  const store = memoryStorage();
  const oldId = "exchange:one";
  const canonical = rec({opportunity_id: "123", source_aliases: [{opportunity_id: oldId}]});
  const records = [canonical];
  const resolveId = id => schedule.recordById(records, id)?.opportunity_id || id;
  S.toggle(rec({opportunity_id: oldId}), store);
  S.updatePursuit(oldId, {pursuit_status: "pursuing", note: "Keep my draft note"}, store);
  const durable = store.getItem(S.STORAGE_KEY);
  const items = S.load(store);
  assert.equal(S.isSaved(items, "123", resolveId), true);
  assert.equal(store.getItem(S.STORAGE_KEY), durable);

  // Exercise the actual app membership functions through the catalog-load
  // transition, without a browser or user storage.
  const app = await readFile(new URL("../../assets/app.js", import.meta.url), "utf8");
  function fn(name) {
    const tail = app.slice(app.indexOf(`  function ${name}(`));
    return tail.slice(0, tail.slice(3).search(/\n  (?:async )?function /) + 3);
  }
  const state = {ready: false, savedItems: []};
  const context = {state, SAVED_API: S, Set, recordById: id => schedule.recordById(records, id), recordId: S.idOf};
  vm.runInNewContext(`${fn("canonicalSavedId")}\n${fn("refreshSavedState")}`, context);
  context.refreshSavedState(items);
  assert.equal(state.savedIds.has(oldId), true);
  state.ready = true;
  context.refreshSavedState(state.savedItems);
  assert.equal(state.savedIds.has("123"), true);
  assert.equal(state.savedIds.has(oldId), false);
  assert.equal(state.savedItems[0].note, "Keep my draft note");
  assert.match(app, /state\.ready = true;\s+refreshSavedState\(state\.savedItems\)/);
  assert.match(fn("toggleSave"), /SAVED_API\.toggle\(snapshot, undefined, canonicalSavedId\)/);

  const rejected = S.toggle(canonical, rejectingStorage(items), resolveId);
  assert.equal(rejected.ok, false);
  assert.equal(rejected.saved, true);
  assert.equal(rejected.items[0].note, "Keep my draft note");
  assert.equal(rejected.items[0].pursuit_status, "pursuing");
  const removed = S.toggle(canonical, store, resolveId);
  assert.equal(removed.saved, false);
  assert.equal(S.load(store).length, 0);
  assert.equal(S.toggle(canonical, store, resolveId).saved, true);
  assert.equal(S.load(store)[0].opportunity_id, "123");
});

test("canonical toggles do not leave duplicate alias snapshots or guess ambiguous aliases", () => {
  const store = memoryStorage();
  const first = rec({opportunity_id: "123", source_aliases: [{opportunity_id: "source:old"}]});
  const resolveId = id => schedule.recordById([first], id)?.opportunity_id || id;
  S.toggle(rec({opportunity_id: "source:old", note: "Original note"}), store);
  S.toggle(first, store); // Reproduce a duplicate created by the prior behavior.
  assert.equal(S.load(store).length, 2);
  assert.equal(S.toggle(first, store, resolveId).items.length, 0);
  const other = rec({opportunity_id: "456", source_aliases: first.source_aliases});
  const ambiguous = id => schedule.recordById([first, other], id)?.opportunity_id || id;
  S.toggle(rec({opportunity_id: "source:old"}), store);
  assert.equal(S.isSaved(S.load(store), "123", ambiguous), false);
  assert.equal(S.isSaved(S.load(store), "456", ambiguous), false);
  assert.equal(S.load(store)[0].opportunity_id, "source:old");
});

test("toggle saves then unsaves, persisting to storage", () => {
  const store = memoryStorage();
  let result = S.toggle(rec(), store);
  assert.equal(result.ok, true);
  assert.equal(result.persisted, true);
  assert.equal(result.saved, true);
  assert.equal(result.items.length, 1);
  assert.equal(S.isSaved(S.load(store), "x1"), true);
  result = S.toggle(rec(), store);
  assert.equal(result.ok, true);
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
  assert.equal(item.pursuit_status, "saved");
  assert.equal(item.note, "");
});

test("pursuit statuses and notes remain in the device-local Saved record", () => {
  const store = memoryStorage();
  S.toggle(rec(), store);
  assert.equal(S.updatePursuit("x1", { pursuit_status: "pursuing", note: "Draft due Friday" }, store).ok, true);
  const item = S.load(store)[0];
  assert.equal(item.pursuit_status, "pursuing");
  assert.equal(item.note, "Draft due Friday");
  S.updatePursuit("x1", { pursuit_status: "invalid", note: "x".repeat(3_000) }, store);
  assert.equal(S.load(store)[0].pursuit_status, "pursuing");
  assert.equal(S.load(store)[0].note.length, S.MAX_NOTE_LENGTH);
});

test("dedupes by id and supports remove/clear", () => {
  const store = memoryStorage();
  S.toggle(rec(), store);
  S.toggle(rec({ opportunity_id: "x2", opportunity_number: "NSF-2", title: "Second" }), store);
  assert.equal(S.load(store).length, 2);
  const removed = S.remove("x1", store);
  assert.equal(removed.ok, true);
  assert.equal(removed.items.length, 1);
  assert.equal(S.idOf(removed.items[0]), "x2");
  assert.equal(S.clear(store).ok, true);
  assert.equal(S.load(store).length, 0);
});

test("write rejection reports failure and preserves the last durable state for every mutation", () => {
  const first = S.sanitizeItem(rec({ pursuit_status: "considering", note: "Persisted note" }));
  const store = rejectingStorage([first]);

  const unsave = S.toggle(rec(), store);
  assert.equal(unsave.ok, false);
  assert.equal(unsave.persisted, false);
  assert.equal(unsave.saved, true);
  assert.equal(unsave.error, "storage_rejected");
  assert.equal(unsave.items.length, 1);

  const save = S.toggle(rec({ opportunity_id: "x2", opportunity_number: "NSF-2", title: "Second" }), store);
  assert.equal(save.ok, false);
  assert.equal(save.saved, false);
  assert.deepEqual(Array.from(save.items, S.idOf), ["x1"]);

  const removed = S.remove("x1", store);
  assert.equal(removed.ok, false);
  assert.deepEqual(Array.from(removed.items, S.idOf), ["x1"]);

  const updated = S.updatePursuit("x1", { pursuit_status: "submitted", note: "Uncommitted note" }, store);
  assert.equal(updated.ok, false);
  assert.equal(updated.items[0].pursuit_status, "considering");
  assert.equal(updated.items[0].note, "Persisted note");

  const cleared = S.clear(store);
  assert.equal(cleared.ok, false);
  assert.deepEqual(Array.from(cleared.items, S.idOf), ["x1"]);
  assert.equal(S.load(store)[0].note, "Persisted note");
});

test("rejects items without a title or id", () => {
  assert.equal(S.sanitizeItem({ title: "no id" }), null);
  assert.equal(S.sanitizeItem({ opportunity_id: "x" }), null);
});

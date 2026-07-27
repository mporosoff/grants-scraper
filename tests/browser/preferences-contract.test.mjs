import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../../assets/preferences.js", import.meta.url),
  "utf8",
);

function loadPreferences() {
  const context = { Array, Map, Math, Object, String, JSON };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.FUNDING_PREFERENCES;
}

const P = loadPreferences();

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
}

function rec(id, fields) {
  return { opportunity_id: id, ...fields };
}

test("does not personalize below the minimum label count", () => {
  const model = P.buildModel([
    { label: "strong", record: rec("A", { topic_areas: ["Carbon management"] }) },
    { label: "useful", record: rec("B", { topic_areas: ["Carbon management"] }) },
  ]);
  assert.equal(model.ready, false); // only 2 labels
  assert.equal(P.factor(rec("Z", { topic_areas: ["Carbon management"] }), model), 0);
});

test("persists the opt-in independently from a saved research profile", () => {
  const store = memoryStorage();
  assert.equal(P.loadEnabled(store), null);
  assert.equal(P.saveEnabled(true, store), true);
  assert.equal(P.loadEnabled(store), true);
  assert.equal(P.saveEnabled(false, store), true);
  assert.equal(P.loadEnabled(store), false);
  store.setItem(P.STORAGE_KEY, "{not-json");
  assert.equal(P.loadEnabled(store), null);
});

test("boosts records that share positively-rated signals", () => {
  const labeled = [
    { label: "strong", record: rec("A", { topic_areas: ["Carbon management"], agency: "DOE" }) },
    { label: "useful", record: rec("B", { topic_areas: ["Carbon management"], agency: "DOE" }) },
    { label: "strong", record: rec("C", { topic_areas: ["Catalysis and reaction engineering"] }) },
  ];
  const model = P.buildModel(labeled);
  assert.equal(model.ready, true);
  const liked = rec("X", { topic_areas: ["Carbon management"], agency: "DOE" });
  const neutral = rec("Y", { topic_areas: ["Arts and culture"] });
  assert.ok(P.factor(liked, model) > 0);
  assert.equal(P.factor(neutral, model), 0);
  assert.ok(P.factor(liked, model) <= 1.0); // bounded
});

test("penalizes records matching rejected signals, bounded", () => {
  const labeled = [
    { label: "not_relevant", record: rec("A", { topic_areas: ["Arts and culture"] }) },
    { label: "not_relevant", record: rec("B", { topic_areas: ["Arts and culture"] }) },
    { label: "strong", record: rec("C", { topic_areas: ["Carbon management"] }) },
  ];
  const model = P.buildModel(labeled);
  const disliked = rec("X", { topic_areas: ["Arts and culture"] });
  assert.ok(P.factor(disliked, model) < 0);
  assert.ok(P.factor(disliked, model) >= -0.5); // bounded floor
});

test("explains a boost with the strongest positive signal", () => {
  const labeled = [
    { label: "strong", record: rec("A", { topic_areas: ["Carbon management"] }) },
    { label: "strong", record: rec("B", { topic_areas: ["Carbon management"] }) },
    { label: "useful", record: rec("C", { agency: "NSF" }) },
  ];
  const model = P.buildModel(labeled);
  const why = P.explain(rec("X", { topic_areas: ["Carbon management"], agency: "NSF" }), model);
  assert.equal(why.field, "topic_areas");
  assert.equal(why.value, "Carbon management");
});

test("exploration surfaces unseen positive-signal matches, best first", () => {
  const labeled = [
    { label: "strong", record: rec("A", { topic_areas: ["Carbon management"] }) },
    { label: "strong", record: rec("B", { topic_areas: ["Carbon management"] }) },
    { label: "useful", record: rec("C", { disciplines: ["Engineering and Physical Sciences"] }) },
  ];
  const model = P.buildModel(labeled);
  const candidates = [
    rec("hit1", { topic_areas: ["Carbon management"], disciplines: ["Engineering and Physical Sciences"] }),
    rec("miss", { topic_areas: ["Arts and culture"] }),
    rec("hit2", { topic_areas: ["Carbon management"] }),
  ];
  const picks = P.selectExploration(model, candidates, 3);
  const ids = picks.map(r => r.opportunity_id);
  assert.ok(ids.includes("hit1"));
  assert.ok(ids.includes("hit2"));
  assert.ok(!ids.includes("miss"));
  assert.equal(ids[0], "hit1"); // strongest match first
});

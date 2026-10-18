import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import test from "node:test";

import "../../assets/saved.js";
import {evaluateSubscriptions} from "../../workers/alerts/src/evaluator.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
const fixture = JSON.parse(readFileSync(new URL("../fixtures/sam_imr_identity_continuity.json", import.meta.url), "utf8"));
const merged = JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c", `
import json,sys
from datetime import date
from scripts.sources.merge import reconcile_source_aliases
from scripts.build_changes import diff_catalogs
f=json.load(sys.stdin)
records,stats=reconcile_source_aliases([f['current']],[f['previous']])
previous={'generated_at':'2026-10-16T16:54:22Z','opportunities':[f['previous']]}
current={'generated_at':'2026-10-18T23:00:00Z','opportunities':records}
print(json.dumps({'record':records[0],'events':diff_catalogs(previous,current,as_of=date(2026,10,18)),'stats':stats}))
`], {cwd: root, input: JSON.stringify(fixture), encoding: "utf8"}));
const saved = globalThis.FUNDING_SAVED;
const schedule = globalThis.FUNDING_SUBMISSION_SCHEDULE;

async function evaluate(record, ids, events = merged.events, instant = "2026-10-18T23:15:00Z") {
  const now = new Date(instant);
  const subscription = {id: "retained-imr-watch", type: "opportunity", cadence: "immediate",
    baseline_at: new Date(now.getTime() - 2 * 86_400_000).toISOString(),
    definition_json: JSON.stringify({opportunity_ids: ids,
      triggers: ["amended", "deadline_changed", "status_changed", "closing_reminders"]})};
  const queued = [];
  const store = {activeSubscriptions: async () => [subscription],
    enqueueEvent: async event => {queued.push(event); return true;}, markEvaluated: async () => {}};
  const result = await evaluateSubscriptions({store,
    assets: {catalog: {opportunities: [record]}, changes: {generated_at: now.toISOString(), events}},
    env: {PUBLIC_APP_ORIGIN: "https://mporosoff.github.io/grants-scraper/"}, now});
  return {result, queued};
}

test("real IMR alias preserves saved membership, pursuit notes and source-owned calendar selection", () => {
  const values = new Map();
  const storage = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
  saved.toggle(fixture.previous, storage);
  saved.updatePursuit(fixture.previous.opportunity_id, {pursuit_status: "pursuing", note: "Existing pursuit note"}, storage);
  assert.equal(schedule.recordById([fixture.current], fixture.previous.opportunity_id), null);
  const resolve = id => schedule.recordById([merged.record], id)?.opportunity_id || id;
  const items = saved.load(storage);
  assert.equal(saved.isSaved(items, fixture.current.opportunity_id, resolve), true);
  assert.equal(items[0].opportunity_id, fixture.previous.opportunity_id);
  assert.equal(items[0].pursuit_status, "pursuing");
  assert.equal(items[0].note, "Existing pursuit note");
  const current = schedule.recordById([merged.record], fixture.previous.opportunity_id);
  assert.equal(current, merged.record);
  assert.equal(schedule.nextSubmission(current, "2026-10-18").date, "2026-10-22");
});

test("real merge and change feed deliver successor amendments to an existing old-ID watch once", async () => {
  assert.ok(merged.events.some(event => event.type === "amended"));
  assert.equal(merged.events.some(event => ["new", "closed_or_removed"].includes(event.type)), false);
  const missing = await evaluate(fixture.current, [fixture.previous.opportunity_id]);
  assert.equal(missing.result.matchedEventCount, 0);
  const matched = await evaluate(merged.record, [fixture.previous.opportunity_id, fixture.current.opportunity_id]);
  assert.equal(matched.result.matchedEventCount, 1);
  assert.equal(matched.queued[0].opportunityId, fixture.current.opportunity_id);
  assert.equal(matched.queued[0].eventKind, "amended");
});

test("resolved old-ID watches reach the exact reviewed seven-day reminder without changing the deadline", async () => {
  const missing = await evaluate(fixture.current, [fixture.previous.opportunity_id], [], "2026-10-15T12:00:00Z");
  assert.equal(missing.result.matchedEventCount, 0);
  const matched = await evaluate(merged.record, [fixture.previous.opportunity_id], [], "2026-10-15T12:00:00Z");
  assert.equal(matched.result.matchedEventCount, 1);
  assert.equal(matched.queued[0].eventKind, "closing_reminder");
  assert.equal(matched.queued[0].opportunityId, fixture.current.opportunity_id);
  assert.match(matched.queued[0].eventKey, /:2026-10-22:7$/);
});

test("a conflicting second alias owner remains unresolved", () => {
  const other = {...merged.record, opportunity_id: "sam-gov:" + "f".repeat(32)};
  assert.equal(schedule.recordById([merged.record, other], fixture.previous.opportunity_id), null);
});

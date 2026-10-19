import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
import {recordIsCurrent as alertIsCurrent} from "../../workers/alerts/src/contract.js";

const root = new URL("../../", import.meta.url);
const fixture = JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c",
  "import json; from tests.test_administrative_close_contract import browser_cases; print(json.dumps(browser_cases()))"],
{encoding: "utf8"})).corrected;
const source = name => readFileSync(new URL(name, root), "utf8");

function apis({schedule = true, asOf = "2026-10-19"} = {}) {
  const context = {Date, console, globalThis: {}};
  vm.createContext(context);
  for (const name of [...(schedule ? ["assets/submission-schedule.js"] : []),
    "assets/search-query.js", "assets/search-retrieval.js", "assets/team-matcher.js"]) vm.runInContext(source(name), context);
  const api = context.globalThis;
  context.RETRIEVAL_API = api.FUNDING_RETRIEVAL;
  context.runtimeDateIso = () => asOf;
  const app = source("assets/app.js");
  for (const name of ["recordIsArchived", "recordIsCurrent", "recordIsTestOpportunity", "recordIsAvailable"]) {
    const match = app.match(new RegExp(`^  function ${name}\\([^]*?^  }`, "m"));
    assert.ok(match, name);
    vm.runInContext(match[0], context);
  }
  return {...api, context};
}

test("actual administrative close agrees across live schedule, search, Team Match and Alerts", () => {
  const before = structuredClone(fixture);
  for (const [asOf, expected] of [["2026-10-13", true], ["2026-10-14", true],
    ["2026-10-15", false], ["2026-10-19", false]]) {
    const api = apis({asOf});
    assert.equal(api.FUNDING_SUBMISSION_SCHEDULE.administrativeSubmissionClosed(fixture, asOf), !expected);
    assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(fixture, asOf), expected);
    api.context.record = fixture;
    assert.equal(vm.runInContext("recordIsAvailable(record)", api.context), expected);
    const team = api.FUNDING_TEAM_MATCHER.create({opportunities: [fixture]}, {}, null, {now: `${asOf}T12:00:00Z`});
    assert.equal(team.records.some(row => row.id === "362893"), expected);
    assert.equal(alertIsCurrent(fixture, asOf), expected);
  }
  assert.deepEqual(fixture, before);
});

test("future cycles, tracks, resubmissions and rolling applications preserve currentness", () => {
  const api = apis();
  for (const alternative of [
    {kind: "application", date: "2026-11-03", cycle: "Second cycle"},
    {kind: "application", date: "2026-11-03", track: "Other track"},
    {kind: "application", date: "2026-11-03", application_class: "resubmission"},
    {kind: "application", date: null, rolling: true},
    {kind: "application", date: null, rolling: true, application_class: "resubmission"},
  ]) {
    const record = structuredClone(fixture);
    record.deadlines.push(alternative);
    assert.equal(api.FUNDING_SUBMISSION_SCHEDULE.administrativeSubmissionClosed(record, "2026-10-19"), false);
    assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(record, "2026-10-19"), true);
    assert.equal(alertIsCurrent(record, "2026-10-19"), true);
  }
  const rolling = {...structuredClone(fixture), rolling: true};
  assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(rolling, "2026-10-19"), true);
  assert.equal(alertIsCurrent(rolling, "2026-10-19"), true);
});

test("ordinary portal windows retain existing admission and administrative runtime needs its shared helper", () => {
  const ordinary = {status: "posted", close_date: "2026-12-16",
    deadlines: [{kind: "submission", date: "2026-12-16"}]};
  const without = apis({schedule: false});
  assert.equal(without.FUNDING_RETRIEVAL.recordIsCurrent(ordinary, "2026-10-19"), true);
  assert.throws(() => without.FUNDING_RETRIEVAL.recordIsCurrent(fixture, "2026-10-19"), /shared administrative submission schedule/);
  const api = apis();
  assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(ordinary, "2026-10-19"), true);
  assert.equal(alertIsCurrent(ordinary, "2026-10-19"), true);
  const otherClose = {...structuredClone(fixture), close_date: "2026-12-17"};
  assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(otherClose, "2026-10-19"), true);
});

test("runtime currentness does not change immutable corpus admission", () => {
  const api = apis();
  const catalog = {generated_at: "2026-10-19T17:04:10.369932Z", opportunities: [fixture],
    search_index: {document_count: 1, average_document_length: 1, document_lengths: [1], postings: {}}};
  const engine = api.FUNDING_RETRIEVAL.create(catalog, api.FUNDING_SEARCH_QUERY);
  assert.deepEqual(Array.from(engine.corpusCurrentness().currentnessRejectedIndexes), []);
  assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(fixture, "2026-10-19"), false);
});

test("the production offline harness loads the qualified-record currentness dependency", async () => {
  const {loadHarness} = await import("../../tools/run_search_diagnosis.mjs");
  const harness = await loadHarness();
  assert.equal(harness.retrievalApi.recordIsCurrent(fixture, "2026-10-19"), false);
  assert.equal(harness.retrievalApi.recordIsCurrent(fixture, "2026-10-14"), true);
});

import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {execFileSync} from "node:child_process";
import test from "node:test";
import "../../assets/submission-schedule.js";
import "../../assets/saved.js";

const api = globalThis.FUNDING_SUBMISSION_SCHEDULE;
const cases = JSON.parse(readFileSync(new URL("../fixtures/submission-schedule.json", import.meta.url), "utf8"));

test("saved windows retain opening dates and full source track identity", () => {
  const track = "Division of Chemistry - Chemistry of Life Processes, Chemical Structure and Dynamics, Chemical Theory, Models and Computational Methods";
  const saved = globalThis.FUNDING_SAVED.sanitizeItem({opportunity_id: "window", title: "Window",
    deadlines: [{kind: "application", date: "2026-09-15", window_start: "2026-09-01", track}]});
  const event = api.nextSubmission(saved, "2026-09-07").event;
  assert.equal(event.date, "2026-09-15");
  assert.equal(event.window_start, "2026-09-01");
  assert.equal(event.track, track);
});

test("saved anticipated schedules retain uncertainty before and after the forecast date", () => {
  const saved = globalThis.FUNDING_SAVED.sanitizeItem({opportunity_id: "forecast", title: "Forecast",
    deadlines: [{kind: "application", date: "2026-07-31", date_qualifier: "anticipated", estimated: true}]});
  assert.equal(saved.deadlines[0].estimated, true);
  assert.equal(api.nextSubmission(saved, "2026-07-01").access, "verify_stage");
  assert.equal(api.nextSubmission(saved, "2026-09-07").access, "verify_stage");
});

test("browser and Python consumers select the same dates and access from typed schedules", () => {
  const python = JSON.parse(execFileSync("python", ["-c", "import json; from pathlib import Path; from scripts.submission_schedule import next_submission; print(json.dumps([next_submission(c['record'],c['as_of']) for c in json.loads(Path('tests/fixtures/submission-schedule.json').read_text())]))"], {encoding:"utf8"}));
  cases.forEach((item, index) => {
    const before = structuredClone(item.record);
    const actual = api.nextSubmission(item.record, item.as_of);
    assert.deepEqual({date: actual.date, access: actual.access, kind: actual.event?.kind ?? null}, item.expected, item.name);
    assert.deepEqual(actual, python[index], `${item.name}: cross-runtime parity`);
    assert.deepEqual(item.record, before, "Source fields were modified");
  });
});

test("saved aliases resolve only to one canonical opportunity", () => {
  const record = {opportunity_id:"123", source_aliases:[{opportunity_id:"exchange:RFP-1"}]};
  assert.equal(api.recordById([record], "exchange:RFP-1"), record);
  assert.equal(api.recordById([record], "123"), record);
  assert.equal(api.recordById([record, {...record, opportunity_id:"456"}], "exchange:RFP-1"), null);
});

test("invalid or undated native fields cannot become calendar dates", () => {
  for (const date of ["2027-02-30", "2027-13-01", "02/01/2027", null])
    assert.equal(api.nextSubmission({deadlines:[{kind:"application", date}]}, "2026-09-07").date, null);
});

test("saved snapshots retain undated required steps when the catalog is unavailable", () => {
  const record = {opportunity_id: "source-contract", title: "Source contract", close_date: "2027-05-01",
    submission_requirements: [{kind: "concept_paper", date: null, required: true}]};
  const saved = globalThis.FUNDING_SAVED.sanitizeItem(record);
  const result = api.nextSubmission(saved, "2026-09-07");
  assert.equal(result.date, "2027-05-01");
  assert.equal(result.access, "verify_prerequisite");
  assert.equal(result.prerequisites[0].required, true);
  assert.equal(result.prerequisites[0].date, null);
});

test("saved snapshots retain recommended dates and explicitly rolling prerequisites", () => {
  const record = {opportunity_id: "source-contract", title: "Source contract", close_date: "2026-11-16",
    deadlines: [{kind: "application", date: "2026-11-16", date_qualifier: "recommended"}],
    submission_requirements: [{kind: "white_paper", date: null, required: true, rolling: true}]};
  const saved = globalThis.FUNDING_SAVED.sanitizeItem(record);
  assert.equal(api.nextSubmission(saved, "2026-09-07").access, "open");
  assert.equal(api.nextSubmission(saved, "2026-11-17").access, "verify_stage");
});

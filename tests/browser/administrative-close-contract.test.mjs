import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {execFileSync} from "node:child_process";
import vm from "node:vm";
import test from "node:test";
import "../../assets/submission-schedule.js";
import "../../assets/saved.js";
import {installSubmissionSchedule} from "../helpers/submission-schedule.mjs";

const fixture = JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c",
  "import json; from tests.test_administrative_close_contract import browser_cases; print(json.dumps(browser_cases()))"],
{encoding: "utf8"}));
const api = globalThis.FUNDING_SUBMISSION_SCHEDULE;
const app = readFileSync(new URL("../../assets/app.js", import.meta.url), "utf8");

function display(asOf) {
  const scope = {URL, formatDate: value => value};
  installSubmissionSchedule(scope, app, asOf);
  for (const name of ["deadlineLabel", "calendarEvents"]) {
    const start = app.indexOf(`  function ${name}(`);
    assert.ok(start >= 0, name);
    vm.runInContext(app.slice(start, app.indexOf("\n  }", start) + 4), scope);
  }
  scope.recordId = record => record.opportunity_id;
  scope.officialActions = () => ({url: "https://www.grants.gov/search-results-detail/362893"});
  scope.deadlineKindLabel = kind => kind;
  return scope;
}

test("retained administrative cutoff never becomes next submission or calendar event after correction", () => {
  const record = fixture.corrected;
  const before = structuredClone(record);
  assert.equal(api.nextSubmission(record, fixture.as_of).access, "closed");
  assert.equal(api.nextSubmission(record, fixture.as_of).date, null);
  assert.deepEqual(api.events(record).map(row => row.date), ["2026-10-14"]);
  const ui = display(fixture.as_of);
  assert.equal(ui.deadlineLabel(record), "No upcoming submission date");
  assert.equal(ui.calendarEvents(record).length, 0);
  assert.deepEqual(record, before);
});

test("actual application date stays actionable before it closes; administrative end is never exported", () => {
  const ui = display("2026-10-01");
  assert.equal(api.nextSubmission(fixture.corrected, "2026-10-01").date, "2026-10-14");
  assert.deepEqual(Array.from(ui.calendarEvents(fixture.corrected), row => row.date), ["2026-10-14"]);
});

test("saved offline snapshots preserve administrative qualifier and source dates", () => {
  const saved = globalThis.FUNDING_SAVED.sanitizeItem(fixture.corrected);
  assert.equal(saved.deadlines[0].date_qualifier, "administrative");
  assert.equal(saved.deadlines[0].kind, "submission");
  assert.equal(saved.deadlines[0].date, "2026-12-16");
  assert.equal(saved.close_date, "2026-12-16");
  assert.equal(api.nextSubmission(saved, fixture.as_of).date, null);
  assert.equal(api.nextSubmission(saved, fixture.as_of).access, "closed");
  assert.equal(display(fixture.as_of).calendarEvents(saved).length, 0);
});

test("administrative-only snapshots suppress the scalar close-date fallback", () => {
  const saved = globalThis.FUNDING_SAVED.sanitizeItem(fixture.administrative_only);
  assert.deepEqual(api.events(saved), []);
  assert.equal(api.nextSubmission(saved, fixture.as_of).date, null);
  assert.equal(display(fixture.as_of).calendarEvents(saved).length, 0);
});

test("ordinary application dates and real portal windows remain available", () => {
  for (const kind of ["application", "submission"]) {
    const record = {opportunity_id: "portal", title: "Open portal", close_date: "2026-12-16",
      deadlines: [{kind, date: "2026-12-16", note: "Applications accepted through December 16."}]};
    assert.equal(api.nextSubmission(record, fixture.as_of).date, "2026-12-16");
    assert.deepEqual(Array.from(display(fixture.as_of).calendarEvents(record), row => row.date), ["2026-12-16"]);
  }
});

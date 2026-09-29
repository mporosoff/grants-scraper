import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { installSubmissionSchedule } from "../helpers/submission-schedule.mjs";

const app = readFileSync(new URL("../../assets/app.js", import.meta.url), "utf8");

function context(asOf = "2026-09-28") {
  const scope = { URL, formatDate: value => value };
  installSubmissionSchedule(scope, app, asOf);
  for (const name of ["escapeHtml", "escapeAttribute", "safeUrl", "isoDateOrdinal", "deadlineKindLabel",
    "evidenceCitation", "deadlineCitation", "deadlineRows", "calendarEvents"]) {
    const start = app.indexOf(`  function ${name}(`);
    assert.ok(start >= 0, name);
    vm.runInContext(app.slice(start, app.indexOf("\n  }", start) + 4), scope);
  }
  scope.recordId = record => record.opportunity_id;
  scope.officialActions = () => ({ url: "https://example.gov/notice" });
  return scope;
}

function termRows(html) {
  return [...html.matchAll(/<dt>(.*?)<\/dt>\s*<dd>(.*?)<\/dd>/gs)].map(match => ({ label: match[1], value: match[2] }));
}

test("NIH recurring schedules retain historical rows without presenting them as current deadlines", () => {
  const scope = context();
  for (const [id, closeDate, pastDates, futureDates, expectedNext] of [
    ["357941", "2027-08-11", ["2025-03-10", "2025-08-12", "2026-03-10", "2026-08-05"],
      ["2027-03-10", "2027-08-11"], "2027-03-10"],
    ["359655", "2027-05-26", ["2026-05-27"], ["2027-05-26"], "2027-05-26"],
  ]) {
    const events = [...pastDates, ...futureDates].flatMap(date => ["new", "resubmission"].map(application_class => ({
      kind: "application", date, application_class, time: "5:00 PM", timezone: "applicant_local",
    })));
    // Actual catalog ordering starts with the structured final closing date.
    const primary = events.findIndex(event => event.date === closeDate && event.application_class === "new");
    const record = { opportunity_id: id, status: "posted", close_date: closeDate,
      deadlines: [events[primary], ...events.filter((_, index) => index !== primary)] };
    const before = structuredClone(record);
    const rows = termRows(scope.deadlineRows(record));
    assert.equal(rows.length, events.length, id);
    rows.forEach((row, index) => {
      const deadline = record.deadlines[index];
      assert.equal(row.label, `${pastDates.includes(deadline.date) ? "Past date · " : ""}Application deadline`, id);
      assert.ok(row.value.startsWith(`${deadline.date} · 5:00 PM · applicant_local`), id);
    });
    assert.equal(rows.filter(row => row.label.startsWith("Past date")).length, pastDates.length * 2, id);
    assert.equal(scope.nextSubmission(record).date, expectedNext, id);
    assert.deepEqual(Array.from(scope.calendarEvents(record), event => event.date),
      record.deadlines.filter(event => event.date >= "2026-09-28").map(event => event.date), id);
    assert.deepEqual(record, before, "Display must preserve source events and their order");
  }
});

test("past labels use valid calendar dates and preserve same-day, open-ended, and submission-window meanings", () => {
  const scope = context();
  const rows = termRows(scope.deadlineRows({ deadlines: [
    { kind: "application", date: "2026-09-27" },
    { kind: "application", date: "2026-09-28", time: "5:00 PM", timezone: "Pacific" },
    { kind: "application", date: "2026-10-01", window_start: "2026-09-01" },
    { kind: "application", date: null, rolling: true },
    { kind: "letter_of_intent", date: null, required: true },
    { kind: "application", date: "2026-02-30" },
    { kind: "application", date: "02/01/2026" },
  ] }));
  assert.equal(rows[0].label, "Past date · Application deadline");
  assert.ok(rows.slice(1).every(row => !row.label.includes("Past date")));
  assert.match(rows[1].value, /2026-09-28 · 5:00 PM · Pacific/);
  assert.match(rows[2].value, /Window opens 2026-09-01 · 2026-10-01/);
  assert.match(rows[3].value, /Date not listed/);
  assert.match(rows[4].value, /Date not listed/);
});

test("historical prerequisite rows remain visible and continue blocking new full applications", () => {
  const scope = context();
  const record = { deadlines: [
    { kind: "letter_of_intent", date: "2026-09-27", required: true, cycle: "2026" },
    { kind: "application", date: "2026-11-01", cycle: "2026" },
  ] };
  const rows = termRows(scope.deadlineRows(record));
  assert.equal(rows[0].label, "Past date · Letter of intent");
  assert.equal(rows[1].label, "Application deadline");
  assert.equal(scope.nextSubmission(record).access, "prerequisite_closed");
  assert.equal(scope.nextSubmission(record).prerequisites[0].date, "2026-09-27");
});

test("past recommendations and forecasts retain uncertainty, citations, and escaped source text", () => {
  const scope = context();
  const record = { status: "forecasted", deadlines: [
    { kind: "application", date: "2026-09-27", date_qualifier: "recommended", track: "Partner <group>",
      note: "Verify <requirements>", confidence: "machine_extracted_needs_verification", evidence_id: "past" },
    { kind: "estimated_application", date: "2026-09-27", date_qualifier: "anticipated" },
  ], document_evidence: { facts: [{ id: "past", citation: {
    citation_url: "https://example.gov/notice#dates", location: "section <dates>", quote: "Recommended date",
  } }] } };
  const rows = termRows(scope.deadlineRows(record));
  assert.equal(rows[0].label, "Past date · Recommended application submission · Partner &lt;group&gt;");
  assert.match(rows[0].value, /Verify &lt;requirements&gt;/);
  assert.match(rows[0].value, /verify in the official notice/);
  assert.match(rows[0].value, /href="https:\/\/example.gov\/notice#dates"/);
  assert.match(rows[0].value, /section &lt;dates&gt;/);
  assert.equal(rows[1].label, "Past date · Anticipated estimated application deadline");
  assert.ok(rows.every(row => !/closed|expired/i.test(row.label)));
  assert.equal(scope.nextSubmission(record).access, "verify_stage");
});

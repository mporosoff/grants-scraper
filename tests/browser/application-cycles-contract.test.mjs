import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
import {recordIsCurrent as alertIsCurrent} from "../../workers/alerts/src/contract.js";

const fixture = JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c",
  "import json; from tests.test_application_cycles import corrected_record; print(json.dumps(corrected_record()))"],
{encoding: "utf8"}));
const source = name => readFileSync(new URL(`../../${name}`, import.meta.url), "utf8");

function apis() {
  const context = {Date, console, globalThis: {}};
  vm.createContext(context);
  for (const name of ["assets/submission-schedule.js", "assets/search-query.js", "assets/search-retrieval.js", "assets/team-matcher.js"]) {
    vm.runInContext(source(name), context);
  }
  return context.globalThis;
}

test("documented FY2028 application stays available after the portal FY2027 close and archive dates", () => {
  const api = apis();
  const original = structuredClone(fixture);
  assert.equal(api.FUNDING_SUBMISSION_SCHEDULE.applicationCycleEnd(fixture), "2028-03-15");
  for (const [asOf, expected] of [["2027-03-15", true], ["2027-03-16", true],
    ["2027-04-15", true], ["2028-03-15", true], ["2028-03-16", false]]) {
    assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(fixture, asOf), expected, asOf);
    assert.equal(alertIsCurrent(fixture, asOf), expected, asOf);
    const team = api.FUNDING_TEAM_MATCHER.create({opportunities: [fixture]}, {}, null, {now: `${asOf}T12:00:00Z`});
    assert.equal(team.records.some(row => row.id === "364271"), expected, asOf);
  }
  assert.equal(api.FUNDING_RETRIEVAL.recordIsArchived(fixture, "2027-04-15"), false);
  assert.equal(api.FUNDING_RETRIEVAL.recordIsArchived(fixture, "2028-03-16"), true);
  assert.equal(api.FUNDING_SUBMISSION_SCHEDULE.nextSubmission(fixture, "2027-03-16").date, "2028-03-15");
  assert.equal(api.FUNDING_SUBMISSION_SCHEDULE.nextSubmission(fixture, "2028-03-16").access, "closed");
  assert.deepEqual(fixture, original);
});

test("unowned, anticipated, preliminary and unbound future facts cannot extend a lifetime", () => {
  const api = apis();
  const cases = [];
  for (const [field, value] of [["date_qualifier", "anticipated"], ["estimated", true],
    ["deadline_kind", "concept_paper"], ["application_class", "resubmission"], ["track", "B"]]) {
    const record = structuredClone(fixture);
    record.document_evidence.facts[1][field] = value;
    cases.push(record);
  }
  const borrowed = structuredClone(fixture);
  borrowed.document_evidence.facts[1].cycle_citation.sha256 = "0".repeat(64);
  cases.push(borrowed);
  const noBinding = structuredClone(fixture);
  noBinding.deadlines[1].evidence_id = "different-fact";
  cases.push(noBinding);
  const otherDocument = structuredClone(fixture);
  otherDocument.primary_document_url = "https://example.org/other.pdf";
  cases.push(otherDocument);
  for (const record of cases) {
    assert.equal(api.FUNDING_SUBMISSION_SCHEDULE.applicationCycleEnd(record), null);
    assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(record, "2027-03-16"), false);
    assert.equal(alertIsCurrent(record, "2027-03-16"), false);
  }
});

test("explicit terminal source status and verification expiry override documented future cycles", () => {
  const api = apis();
  for (const status of ["closed", "archived", "cancelled", "withdrawn"]) {
    const record = {...structuredClone(fixture), status};
    assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(record, "2027-04-15"), false);
    assert.equal(alertIsCurrent(record, "2027-04-15"), false);
    assert.equal(api.FUNDING_RETRIEVAL.recordIsArchived(record, "2027-04-15"), true);
  }
  for (const source_review_after of ["2027-04-14", "2027-02-30", "invalid"]) {
    const record = {...structuredClone(fixture), source_review_after};
    assert.equal(api.FUNDING_RETRIEVAL.recordIsCurrent(record, "2027-04-15"), false);
    assert.equal(alertIsCurrent(record, "2027-04-15"), false);
  }
});

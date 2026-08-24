import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const ROOT = new URL("../../", import.meta.url);
const [
  explainSource,
  appSource,
  cssSource,
  frame,
  phase2,
  phase3,
] = await Promise.all([
  readFile(new URL("assets/match-explain.js", ROOT), "utf8"),
  readFile(new URL("assets/app.js", ROOT), "utf8"),
  readFile(new URL("assets/app.css", ROOT), "utf8"),
  readFile(new URL("evaluation/match_explain_v2_frame.json", ROOT), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/search_v2_results.json", ROOT), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/match_explain_v2_results.json", ROOT), "utf8").then(JSON.parse),
]);

const context = { globalThis: {} };
vm.runInNewContext(explainSource, context, { filename: "assets/match-explain.js" });
const explain = context.globalThis.FUNDING_MATCH_EXPLAIN;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

test("explanation v2 exposes a structured causal contract", () => {
  assert.equal(explain.contractVersion, 2);
  const result = explain.buildV2(clone(frame.fixtures.explicit_description));
  assert.equal(result.tier, "contextual");
  assert.ok(result.reasons.length > 0 && result.reasons.length <= 3);
  assert.ok(result.reasons.every(item => item.code && item.evidence));
  assert.ok(result.reasons.some(item => item.evidence.field === "parent_description"));
  assert.ok(result.trace.admittedBy.length > 0);
  assert.ok(result.trace.rankedBy.length > 0);
});

test("non-expandable Why this matched evidence never ends in a clipped fragment", () => {
  const input = clone(frame.fixtures.explicit_description);
  const completeSentence = `The program supports lanthanide recovery and purification from ${"complex feedstocks using selective experimental separations and validated analytical methods ".repeat(4).trim()}.`;
  input.parent.record.description = `${completeSentence} A second sentence supplies unrelated administrative context.`;
  const result = explain.buildV2(input);
  const fieldContext = result.reasons.find(item => item.code === "field_context");
  assert.ok(fieldContext);
  assert.doesNotMatch(fieldContext.text, /…|\.{3}/);
  assert.match(fieldContext.text, /validated analytical methods”\.$/);
});

test("authoritative scope is explained as a primary admission path, never a broad suggestion", () => {
  const ree = phase2.results.find(item => item.query === "REE separations");
  for (const row of ree.top_results) {
    const result = explain.buildV2({
      query: "REE separations",
      parent: {
        record: { opportunity_id: row.id, title: row.title },
        parentAdmitted: true,
        directEvidence: {
          schemaVersion: 2,
          authoritativeScope: row.authoritative_scope,
          admission: {
            admitted: true,
            reason: row.admission_reason,
            admittedBy: row.admitted_by,
            rankedBy: [],
            fieldContributions: row.field_contributions,
          },
        },
      },
      parentAdmitted: true,
    });
    assert.equal(result.tier, "authoritative_scope", row.id);
    assert.equal(result.label, "Primary program-scope match", row.id);
    assert.deepEqual(
      Array.from(result.reasons, item => item.code),
      ["authoritative_scope", "controlled_relationship", "query_interpretation"],
      row.id,
    );
    assert.doesNotMatch(JSON.stringify(result), /Broader program fit/, row.id);
  }
});

test("removing causal field evidence removes the contextual explanation", () => {
  const input = clone(frame.fixtures.explicit_description);
  const before = explain.buildV2(input);
  assert.ok(before.reasons.some(item => item.code === "field_context"));
  input.parent.directEvidence.admission.admittedBy = [];
  input.parent.directEvidence.admission.fieldContributions = [];
  const after = explain.buildV2(input);
  assert.equal(after.tier, "weak_lexical");
  assert.deepEqual([...after.reasons], []);
});

test("child explanations name only publication-eligible causal children", () => {
  const published = explain.buildV2(clone(frame.fixtures.child_title));
  assert.equal(published.tier, "direct");
  assert.match(published.reasons[0].text, /publication-eligible subprogram “Catalysis Science”/);

  const review = explain.buildV2(clone(frame.fixtures.review_only_child));
  assert.equal(review.tier, "weak_lexical");
  assert.deepEqual([...review.reasons], []);
  assert.doesNotMatch(JSON.stringify(review), /Internal Review Separation Science|fixture-review-child:rss/);
});

test("profile explanations disclose the source type but never private text", () => {
  const input = clone(frame.fixtures.profile_assisted);
  input.profileSources.cv = { score: 0 };
  input.profileSources.orcid = { score: 0 };
  input.eligibility = 0;
  const result = explain.buildV2(input);
  assert.ok(result.reasons.some(item => item.code === "profile_contribution"));
  assert.match(result.reasons.map(item => item.text).join(" "), /research profile increased/);
  assert.doesNotMatch(JSON.stringify(result), /secret zeolite project/);
  assert.equal(result.trace.exactTitlePhrase, true);
  assert.deepEqual([...result.trace.profileSources], ["manual"]);
});

test("weak metadata receives no prose and rejected acronym collisions receive no explanation", () => {
  const metadata = explain.buildV2(clone(frame.fixtures.weak_metadata));
  assert.equal(metadata.tier, "weak_lexical");
  assert.deepEqual([...metadata.reasons], []);
  const cfd = phase3.results.find(item => item.id === "weak_cfd_collision");
  assert.equal(cfd.admitted, false);
  assert.equal(cfd.explanation, null);
});

test("the frozen 42-pair explanation truth gate passes without holdout use", () => {
  assert.equal(
    phase3.explanation_asset_sha256,
    createHash("sha256").update(explainSource).digest("hex"),
  );
  assert.equal(phase3.status, "explanation_gates_passed");
  assert.equal(phase3.case_count, 42);
  assert.equal(phase3.holdout_status, "sealed_not_executed_or_adjudicated");
  assert.deepEqual(phase3.gates.unsupported_explanations, []);
  assert.deepEqual(phase3.gates.causal_evidence_violations, []);
  assert.deepEqual(phase3.gates.review_only_child_leakage, []);
  assert.deepEqual(phase3.gates.private_profile_excerpt_leakage, []);
  assert.deepEqual(phase3.gates.tautological_explanations, []);
  assert.ok(phase3.gates.correct_and_useful_rate >= .9);
  assert.ok(phase3.gates.maximum_reason_count <= 3);
});

test("the v2 card remains compact and collapsed by default", () => {
  assert.match(appSource, /MATCH_EXPLAIN_API\.buildV2/);
  assert.match(appSource, /data-match-tier=/);
  assert.match(appSource, /match-explanation-tier/);
  assert.match(appSource, /Number\(MATCH_EXPLAIN_API\?\.contractVersion \|\| 0\) !== 2/);
  assert.doesNotMatch(appSource, /<details class="match-explanation match-explanation-v2"[^>]* open/);
  assert.match(cssSource, /\.match-explanation-v2 > summary/);
  assert.match(cssSource, /\.match-explanation-tier/);
});

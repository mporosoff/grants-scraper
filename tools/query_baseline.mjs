#!/usr/bin/env node
// The retrieval regression gate: a frozen query set compared on result IDs
// and ranks.
//
// Usage:
//   node tools/query_baseline.mjs --write    write evaluation/query_baseline.json
//   node tools/query_baseline.mjs --check    exit 1 on regression
//
// This replaces the labelled baseline v6.2 asked for, which cannot be built --
// evaluate_phase2.py consumes exported human relevance labels and the label
// corpus is deliberately private. This gate needs no judgments: it compares a
// build against its own prior self.
//
// It reports three numbers per query and gates on the third:
//
//   set delta          IDs entering or leaving the top 50   report only
//   rank displacement  sum of |change in rank| for IDs in both  report only
//   top-10 churn       IDs entering or leaving the top 10   FAILS the build
//
// Top-10 churn is the gate because it is what a user sees. Set delta at rank
// 47 is noise; a new record at rank 3 is a product change.
//
// What it cannot do: tell you a change was an IMPROVEMENT. Only that it was a
// change. When a flag-on build moves top-10 results, a human has to look at the
// diff and decide. The gate's job is to guarantee nobody has to *notice* the
// movement first.
//
// Determinism: scoring is pure BM25 over a fixed index with no clock and no
// network, so the same catalog plus the same query set gives byte-identical
// output. Ties are broken on opportunity id compared by code unit, NOT with
// localeCompare -- localeCompare is ICU- and locale-dependent, so it could
// order ties differently on a developer's machine than on the CI runner and
// turn a platform difference into a phantom regression.
//
// See docs/TOPIC_LAYER_PLAN.md §8.5.

import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const QUERY_SET = "evaluation/query_set.json";
const BASELINE = "evaluation/query_baseline.json";
const TOP_N = 50;
const TOP_GATE = 10;

function usage(code) {
  process.stderr.write(
    "usage: node tools/query_baseline.mjs (--write | --check)\n",
  );
  return code;
}

async function loadEngine(catalogPath) {
  const context = { globalThis: {} };
  for (const relative of [
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "assets/profile-ranking.js",
  ]) {
    vm.runInNewContext(await readFile(new URL(relative, ROOT), "utf8"), context);
  }
  vm.runInNewContext(await readFile(new URL(catalogPath, ROOT), "utf8"), context);

  const queryApi = context.globalThis.FUNDING_SEARCH_QUERY;
  const profileApi = context.globalThis.FUNDING_PROFILE_RANKING;
  const catalog = context.globalThis.GRANT_CATALOG;
  if (!catalog?.opportunities) {
    throw new Error(`${catalogPath} did not define GRANT_CATALOG`);
  }
  const engine = context.globalThis.FUNDING_RETRIEVAL.create(catalog, queryApi);
  return { queryApi, profileApi, catalog, engine };
}

// Resolve "@path" in profile text fields against a repository file, so a CV
// fixture can be referenced rather than pasted into the query set.
async function resolveProfile(profile) {
  if (!profile) return null;
  const resolved = { ...profile };
  for (const [key, value] of Object.entries(resolved)) {
    if (typeof value === "string" && value.startsWith("@")) {
      resolved[key] = await readFile(new URL(value.slice(1), ROOT), "utf8");
    }
  }
  return resolved;
}

// Mirrors evaluation/profile_relevance_probe.mjs, which is the shape the
// browser scores with: direct relevance dominates, the profile term query
// contributes, and applicant/career fit are additive bonuses.
function rank({ queryApi, profileApi, catalog, engine }, queryText, profile) {
  const direct = engine.score(queryText, {
    context: profile ? profileApi.context(profile) : "",
  });
  const built = profile
    ? profileApi.buildTermQuery(profile, {
        catalog,
        tokenize: queryApi.tokenize,
        expandGroups: (value, options) => engine.expandGroups(value, options),
      })
    : { query: "", terms: [] };
  const profiled = profile
    ? engine.score(built.query, {
        semantic: false,
        coverage: false,
        minimumCoverage: 0,
      })
    : null;

  const rows = [];
  catalog.opportunities.forEach((record, index) => {
    if (record.status === "archived") return;
    if (!(direct.scores[index] > 0)) return;
    const profileScore = profiled ? profiled.scores[index] || 0 : 0;
    const eligibility = profile
      ? profileApi.applicantFitBonus(record, profile.applicant_context)
        + profileApi.careerFitBonus(record, profile.career_stage)
      : 0;
    rows.push({
      id: String(record.opportunity_id),
      total: direct.scores[index] * 2 + profileScore + eligibility,
    });
  });

  rows.sort(
    (left, right) =>
      right.total - left.total
      || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0),
  );
  return rows.slice(0, TOP_N).map((row, index) => ({
    rank: index + 1,
    id: row.id,
    // Six decimals is far finer than any meaningful ranking difference and
    // avoids float formatting noise in the committed baseline.
    score: Number(row.total.toFixed(6)),
  }));
}

async function collect() {
  const set = JSON.parse(await readFile(new URL(QUERY_SET, ROOT), "utf8"));
  // The engine is Object.freeze'd, so rank() reads tokenize off the query API
  // in the harness rather than being handed an engine with it attached.
  const harness = await loadEngine(set.catalog);

  const results = {};
  for (const query of set.queries) {
    const profile = await resolveProfile(query.profile);
    results[query.id] = {
      kind: query.kind,
      query: query.query ?? "",
      results: rank(harness, query.query ?? "", profile),
    };
  }
  return {
    schema_version: 1,
    catalog: set.catalog,
    query_count: set.queries.length,
    top_n: TOP_N,
    results,
  };
}

function compare(baseline, current) {
  const report = [];
  let churnTotal = 0;

  const ids = new Set([
    ...Object.keys(baseline.results),
    ...Object.keys(current.results),
  ]);
  for (const id of [...ids].sort()) {
    const before = baseline.results[id];
    const after = current.results[id];
    if (!before || !after) {
      churnTotal += 1;
      report.push({
        id,
        note: before ? "query removed from the set" : "query added to the set",
        churn: 1,
      });
      continue;
    }

    const beforeRanks = new Map(before.results.map(row => [row.id, row.rank]));
    const afterRanks = new Map(after.results.map(row => [row.id, row.rank]));

    const setDelta = [
      ...[...afterRanks.keys()].filter(key => !beforeRanks.has(key)),
      ...[...beforeRanks.keys()].filter(key => !afterRanks.has(key)),
    ].length;

    let displacement = 0;
    for (const [key, rankBefore] of beforeRanks) {
      if (afterRanks.has(key)) {
        displacement += Math.abs(afterRanks.get(key) - rankBefore);
      }
    }

    const beforeTop = new Set(
      before.results.filter(row => row.rank <= TOP_GATE).map(row => row.id),
    );
    const afterTop = new Set(
      after.results.filter(row => row.rank <= TOP_GATE).map(row => row.id),
    );
    const entering = [...afterTop].filter(key => !beforeTop.has(key));
    const leaving = [...beforeTop].filter(key => !afterTop.has(key));
    const churn = entering.length + leaving.length;
    churnTotal += churn;

    if (setDelta || displacement || churn) {
      report.push({ id, setDelta, displacement, churn, entering, leaving });
    }
  }
  return { report, churnTotal };
}

async function main(argv) {
  const mode = argv[0];
  if (argv.length !== 1 || !["--write", "--check"].includes(mode)) {
    return usage(2);
  }

  const current = await collect();

  if (mode === "--write") {
    await writeFile(
      new URL(BASELINE, ROOT),
      `${JSON.stringify(current, null, 2)}\n`,
      "utf8",
    );
    const matched = Object.values(current.results).filter(
      entry => entry.results.length,
    ).length;
    process.stdout.write(
      `Wrote ${BASELINE}: ${current.query_count} queries, `
        + `${matched} returning results, `
        + `${current.query_count - matched} returning none.\n`,
    );
    process.stdout.write(
      "Run twice and confirm the file is byte-identical before committing "
        + "it (§8.5).\n",
    );
    return 0;
  }

  let baseline;
  try {
    baseline = JSON.parse(await readFile(new URL(BASELINE, ROOT), "utf8"));
  } catch {
    process.stderr.write(
      `Missing or unreadable ${BASELINE}. Run --write first.\n`,
    );
    return 2;
  }

  const { report, churnTotal } = compare(baseline, current);
  if (!report.length) {
    process.stdout.write(
      `query-baseline: OK (${current.query_count} queries, `
        + `zero top-${TOP_GATE} churn)\n`,
    );
    return 0;
  }

  for (const row of report) {
    process.stdout.write(`${row.id}: ${JSON.stringify(row)}\n`);
  }
  if (!churnTotal) {
    process.stdout.write(
      `query-baseline: movement below the gate (zero top-${TOP_GATE} churn). `
        + "Reported, not failing.\n",
    );
    return 0;
  }
  process.stderr.write(
    `\nQUERY REGRESSION: ${churnTotal} top-${TOP_GATE} change(s).\n\n`
      + "Top-10 churn is what a user sees, so it fails the build. With the\n"
      + "subtopic flag OFF this must be zero -- see docs/TOPIC_LAYER_PLAN.md\n"
      + "§0.5 and §8.5. If the movement was intended, review it case by case\n"
      + "and re-run --write.\n",
  );
  return 1;
}

process.exitCode = await main(process.argv.slice(2));

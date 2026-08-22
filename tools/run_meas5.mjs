#!/usr/bin/env node
// Additive cross-discipline retrieval probe for MEAS-5.
// The input frame is frozen separately in evaluation/meas5_query_set.json.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const FRAME_PATH = "evaluation/meas5_query_set.json";
const OUTPUT_PATH = "evaluation/meas5_results.json";
const TOP_N = 10;

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{"), source.lastIndexOf(";")).trim());
}

export async function loadHarness({ searchV2 = false } = {}) {
  const context = { globalThis: {} };
  for (const relative of [
    "assets/search-v2-config.js",
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "assets/profile-ranking.js",
  ]) {
    vm.runInNewContext(await readFile(new URL(relative, ROOT), "utf8"), context);
  }
  const catalog = assignmentJson(await readFile(new URL("data/opportunities.js", ROOT), "utf8"));
  const sidecarSource = await readFile(new URL("data/subtopics.js", ROOT), "utf8");
  const sidecar = assignmentJson(sidecarSource);
  const queryApi = context.globalThis.FUNDING_SEARCH_QUERY;
  const retrievalApi = context.globalThis.FUNDING_RETRIEVAL;
  const profileApi = context.globalThis.FUNDING_PROFILE_RANKING;
  const searchV2Config = context.globalThis.FUNDING_SEARCH_V2_CONFIG;
  const childCatalog = retrievalApi.createChildCatalog(sidecar);
  const sharedConfiguration = searchV2 ? { searchV2: true, searchV2Config } : {};
  return {
    catalog,
    childCatalog,
    parentEngine: retrievalApi.create(catalog, queryApi, {
      ...sharedConfiguration,
      catalogRole: "parent",
    }),
    childEngine: retrievalApi.create(childCatalog, queryApi, {
      ...sharedConfiguration,
      catalogRole: "child",
    }),
    profileApi,
    searchV2Config,
    queryApi,
    retrievalApi,
    sidecarSha256: createHash("sha256").update(sidecarSource).digest("hex"),
  };
}

function termQuery(harness, profile, catalog, engine, options = {}) {
  return harness.profileApi.buildTermQuery(profile, {
    catalog,
    tokenize: harness.queryApi.tokenize,
    expandGroups: (value, expandOptions) => engine.expandGroups(value, expandOptions),
    ...options,
  });
}

function emptyScores(count) {
  return { scores: new Float64Array(count), evidence: null };
}

function sourceScores(harness, profile, catalog, engine) {
  if (!profile) return {};
  const sources = {
    manual: {
      research_description: profile.research_description || "",
      expertise_keywords: profile.expertise_keywords || "",
    },
    cv: { cv_text: profile.cv_text || "" },
    orcid: { orcid_text: profile.orcid_text || "" },
  };
  return Object.fromEntries(Object.entries(sources).flatMap(([name, values]) => {
    if (!Object.values(values).some(value => String(value).trim())) return [];
    const built = termQuery(harness, values, catalog, engine);
    if (!built.query) return [];
    return [[name, engine.score(built.query, {
      semantic: false,
      coverage: false,
      minimumCoverage: 0,
      evidence: true,
    })]];
  }));
}

export function rank(harness, query, profile, topicsEnabled) {
  const context = profile ? harness.profileApi.context(profile) : "";
  const directOptions = { context, evidence: true };
  let parentDirect = harness.parentEngine.score(query, directOptions);
  let childDirect = harness.childEngine.score(query, directOptions);
  const parentProfileQuery = profile
    ? termQuery(harness, profile, harness.catalog, harness.parentEngine)
    : { query: "", terms: [] };
  const childProfileQuery = profile
    ? termQuery(harness, profile, harness.childCatalog, harness.childEngine)
    : { query: "", terms: [] };
  const parentProfile = profile
    ? harness.parentEngine.score(parentProfileQuery.query, {
        semantic: false, coverage: false, minimumCoverage: 0, evidence: true,
      })
    : emptyScores(harness.catalog.opportunities.length);
  const childProfile = profile
    ? harness.childEngine.score(childProfileQuery.query, {
        semantic: false, coverage: false, minimumCoverage: 0, evidence: true,
      })
    : emptyScores(harness.childCatalog.opportunities.length);

  if (profile && !parentDirect.hasTerms) {
    const manualParent = termQuery(
      harness, profile, harness.catalog, harness.parentEngine, { admissionOnly: true },
    );
    const manualChild = termQuery(
      harness, profile, harness.childCatalog, harness.childEngine, { admissionOnly: true },
    );
    const parentAdmission = manualParent.terms.length ? manualParent : parentProfileQuery;
    const childAdmission = manualChild.terms.length ? manualChild : childProfileQuery;
    parentDirect = harness.parentEngine.score(parentAdmission.query, {
      semantic: false,
      coverage: false,
      minimumCoverage: harness.profileApi.minimumCoverage(parentAdmission.terms.length),
      evidence: true,
    });
    childDirect = harness.childEngine.score(childAdmission.query, {
      semantic: false,
      coverage: false,
      minimumCoverage: harness.profileApi.minimumCoverage(childAdmission.terms.length),
      evidence: true,
    });
  }

  const bonuses = harness.catalog.opportunities.map(record => profile
    ? harness.profileApi.applicantFitBonus(record, profile.applicant_context)
      + harness.profileApi.careerFitBonus(record, profile.career_stage)
    : 0);
  const parentSourceScores = sourceScores(
    harness, profile, harness.catalog, harness.parentEngine,
  );
  const childSourceScores = sourceScores(
    harness, profile, harness.childCatalog, harness.childEngine,
  );

  let rows;
  if (!topicsEnabled) {
    rows = harness.catalog.opportunities.flatMap((record, index) => {
      if (record.status === "archived" || !(parentDirect.scores[index] > 0)) return [];
      return [{
        id: String(record.opportunity_id),
        record,
        score: (2 * parentDirect.scores[index]) + parentProfile.scores[index] + bonuses[index],
        bestChild: null,
        parentDirectEvidence: parentDirect.evidence?.[index] || null,
        profileSources: Object.fromEntries(Object.entries(parentSourceScores).map(([name, scored]) => [
          name,
          { score: scored.scores[index] || 0, evidence: scored.evidence?.[index] || null, record },
        ])),
      }];
    });
  } else {
    const rolled = harness.retrievalApi.rollupScores({
      parentCatalog: harness.catalog,
      childCatalog: harness.childCatalog,
      parentDirect,
      parentProfile,
      childDirect,
      childProfile,
      eligibilityBonuses: bonuses,
    });
    const parents = new Map(harness.catalog.opportunities.map((record, index) => [
      String(record.opportunity_id), { record, index },
    ]));
    rows = rolled.rows.flatMap(row => {
      const parent = parents.get(row.id);
      if (!parent || parent.record.status === "archived") return [];
      const activeBestChild = row.childDroveMatch ? row.bestChild : null;
      const childIndex = activeBestChild
        ? harness.childCatalog.opportunities.indexOf(activeBestChild.record)
        : -1;
      return [{
        ...row,
        record: parent.record,
        profileSources: Object.fromEntries(["manual", "cv", "orcid"].map(name => {
          const parentScored = parentSourceScores[name];
          const childScored = childSourceScores[name];
          const parentScore = Number(parentScored?.scores?.[parent.index] || 0);
          const childScore = childIndex >= 0
            ? Number(childScored?.scores?.[childIndex] || 0)
            : 0;
          return [name, childScore > parentScore
            ? { score: childScore, evidence: childScored?.evidence?.[childIndex] || null, record: activeBestChild.record }
            : { score: parentScore, evidence: parentScored?.evidence?.[parent.index] || null, record: parent.record }];
        })),
        bestChild: activeBestChild,
        matchingChildren: row.childDroveMatch ? row.matchingChildren : [],
        matchingChildCount: row.childDroveMatch ? row.matchingChildCount : 0,
      }];
    });
  }
  rows.sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
  return rows;
}

function compactRow(row, rankValue) {
  const groups = evidence => (evidence?.groups || []).map(group => ({
    source: group.source,
    matched_terms: Array.from(group.matchedTerms || []),
  }));
  return {
    rank: rankValue,
    id: row.id,
    number: row.record.opportunity_number || "",
    title: row.record.title,
    score: Number(row.score.toFixed(6)),
    child: row.childDroveMatch && row.bestChild ? {
      id: row.bestChild.id,
      title: row.bestChild.record.title,
      evidence: groups(row.bestChild.directEvidence),
    } : null,
    parent_evidence: groups(row.parentDirectEvidence),
  };
}

async function main() {
  const frameSource = await readFile(new URL(FRAME_PATH, ROOT), "utf8");
  const frame = JSON.parse(frameSource);
  const harness = await loadHarness();
  const results = [];
  for (const item of frame.queries) {
    const offRows = rank(harness, item.query || "", item.profile || null, false);
    const onRows = rank(harness, item.query || "", item.profile || null, true);
    const offTop = offRows.slice(0, TOP_N);
    const onTop = onRows.slice(0, TOP_N);
    const offIds = new Set(offTop.map(row => row.id));
    const onIds = new Set(onTop.map(row => row.id));
    results.push({
      id: item.id,
      discipline: item.discipline,
      kind: item.kind,
      query: item.query,
      flag_off_candidate_count: offRows.length,
      flag_on_candidate_count: onRows.length,
      entering_top_10: onTop.filter(row => !offIds.has(row.id)).map(row => compactRow(row, onTop.indexOf(row) + 1)),
      leaving_top_10: offTop.filter(row => !onIds.has(row.id)).map(row => compactRow(row, offTop.indexOf(row) + 1)),
      flag_off_top_10: offTop.map((row, index) => compactRow(row, index + 1)),
      flag_on_top_10: onTop.map((row, index) => compactRow(row, index + 1)),
    });
  }

  const disciplines = {};
  for (const row of results) {
    const summary = disciplines[row.discipline] ||= {
      query_count: 0,
      profile_query_count: 0,
      flag_off_queries_with_results: 0,
      flag_on_queries_with_results: 0,
      candidate_expansion: 0,
      top_10_churn: 0,
      child_driven_top_10: 0,
    };
    summary.query_count += 1;
    summary.profile_query_count += row.kind === "profile" ? 1 : 0;
    summary.flag_off_queries_with_results += row.flag_off_candidate_count ? 1 : 0;
    summary.flag_on_queries_with_results += row.flag_on_candidate_count ? 1 : 0;
    summary.candidate_expansion += row.flag_on_candidate_count - row.flag_off_candidate_count;
    summary.top_10_churn += row.entering_top_10.length + row.leaving_top_10.length;
    summary.child_driven_top_10 += row.flag_on_top_10.filter(item => item.child).length;
  }

  const output = {
    schema_version: 1,
    measured_at: new Date().toISOString(),
    frame: FRAME_PATH,
    frame_sha256: createHash("sha256").update(frameSource).digest("hex"),
    sidecar_sha256: harness.sidecarSha256,
    query_count: results.length,
    discipline_count: Object.keys(disciplines).length,
    top_n: TOP_N,
    interpretation: "Regression breadth and flag-on movement only; no human relevance labels were assigned.",
    disciplines,
    results,
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(OUTPUT_PATH, ROOT), `${JSON.stringify(output, null, 2)}\n`, "utf8");
    process.stdout.write(`Wrote ${OUTPUT_PATH}: ${results.length} queries across ${Object.keys(disciplines).length} disciplines.\n`);
  } else {
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
  }
}

if (String(process.argv[1] || "").replace(/\\/g, "/").endsWith("/tools/run_meas5.mjs")) {
  await main();
}

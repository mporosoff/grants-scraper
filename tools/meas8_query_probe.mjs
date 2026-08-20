#!/usr/bin/env node
// MEAS-8 targeted parent-discoverability probe.
//
// Loads the current browser retrieval implementation and committed catalog.
// This is a measurement harness only: it does not mutate the index or add
// query-time vocabulary.

import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const DEFAULT_CATALOG = "data/opportunities.js";
const TOP_N = 50;

const QUERIES = [
  ["doe-office-science", "catalysis", "360678"],
  ["doe-office-science", "plasma physics", "360678"],
  ["doe-office-science", "isotope research", "360678"],
  ["doe-genesis", "autonomous laboratories", "361526"],
  ["doe-genesis", "quantum algorithms", "361526"],
  ["doe-genesis", "subsurface strategic energy", "361526"],
  ["doe-arpa-e", "SCALEUP energy technology", "356623"],
  ["doe-arpa-e", "energy innovators", "362036"],
  ["doe-netl-hgeo", "produced water treatment", "363065"],
  ["doe-netl-hgeo", "fracture propagation", "363065"],
  ["doe-netl-hgeo", "laboratory validation catalysts", "363302"],
  ["doe-netl-hgeo", "subsurface energy development", "363594"],
  ["doe-nuclear-energy", "advanced reactor licensing", "358100"],
  ["dod-muri", "multidisciplinary university research initiative", "344592"],
  ["dod-muri", "quantum sensing", "344592"],
  ["dod-muri", "energetic materials", "344592"],
  ["dod-muri", "online learning theory", "344592"],
  ["dod-army-tdac", "multi-domain operations", "345241"],
  ["dod-army-tdac", "future army systems quantum", "345241"],
  ["dod-onr", "catalyst design", "356605"],
  ["dod-onr", "quantum sensing", "356605"],
  ["dod-onr", "power and energy", "356605"],
  ["dod-darpa", "integrated materials analysis", "362859"],
  ["dod-darpa", "foundations for surface analysis", "362859"],
  ["dod-darpa", "multimodal data fusion", "362859"],
  ["dod-afosr", "energetic solid-state physics", "362681"],
  ["dod-afosr", "quantum information sciences", "362681"],
  ["dod-afosr", "computational cognition machine intelligence", "362681"],
  ["noaa-baas", "weather radar", "355705"],
  ["noaa-baas", "satellite remote sensing", "356127"],
  ["noaa-baas", "STEM education", "356002"],
  ["noaa-baas", "fisheries science", "355706"],
  ["noaa-baas", "ocean acidification", "356669"],
];

async function loadHarness(catalogPath) {
  const context = { globalThis: {} };
  for (const relative of [
    "assets/search-query.js",
    "assets/search-retrieval.js",
  ]) {
    vm.runInNewContext(await readFile(new URL(relative, ROOT), "utf8"), context);
  }
  vm.runInNewContext(await readFile(new URL(catalogPath, ROOT), "utf8"), context);
  const queryApi = context.globalThis.FUNDING_SEARCH_QUERY;
  const catalog = context.globalThis.GRANT_CATALOG;
  const engine = context.globalThis.FUNDING_RETRIEVAL.create(catalog, queryApi);
  return { catalog, engine };
}

function rank(harness, query) {
  const scored = harness.engine.score(query);
  return harness.catalog.opportunities
    .flatMap((record, index) => {
      if (record.status === "archived" || !(scored.scores[index] > 0)) return [];
      return [{ id: String(record.opportunity_id), score: scored.scores[index] * 2 }];
    })
    .sort((left, right) =>
      right.score - left.score
      || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0)
    )
    .slice(0, TOP_N)
    .map((row, index) => ({
      rank: index + 1,
      id: row.id,
      score: Number(row.score.toFixed(6)),
    }));
}

function resultFor(harness, caseId, query, expectedId, source = "frozen_case") {
  const results = rank(harness, query);
  const expected = results.find(row => row.id === expectedId);
  const record = harness.catalog.opportunities.find(
    row => String(row.opportunity_id) === expectedId,
  );
  return {
    case_id: caseId,
    query,
    expected_id: expectedId,
    expected_rank: expected?.rank ?? null,
    retrieved_top_50: Boolean(expected),
    expected_discoverability_rules:
      record?.discoverability_contribution?.rule_ids ?? [],
    top_10_ids: results.slice(0, 10).map(row => row.id),
    source,
  };
}

function parseArgs(argv) {
  const args = { catalog: DEFAULT_CATALOG, out: null, genesis: null };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--catalog") args.catalog = argv[++index];
    else if (value === "--out") args.out = argv[++index];
    else if (value === "--genesis-focus-file") args.genesis = argv[++index];
    else throw new Error(`unknown argument: ${value}`);
  }
  return args;
}

async function main(argv) {
  const args = parseArgs(argv);
  const harness = await loadHarness(args.catalog);
  const queries = QUERIES.map(row => resultFor(harness, ...row));

  let genesisFocus = null;
  if (args.genesis) {
    const text = await readFile(args.genesis, "utf8");
    const rows = text.split(/\r?\n/).flatMap(line => {
      const match = line.match(/^\d{1,2}-[A-Z]\s+.+?\|\s*(.+)$/);
      return match ? [match[1].trim()] : [];
    });
    const results = rows.map(query =>
      resultFor(harness, "doe-genesis", query, "361526", "live_focus_workbook")
    );
    const ranks = results.flatMap(row => row.expected_rank ?? []);
    const sortedRanks = [...ranks].sort((left, right) => left - right);
    genesisFocus = {
      focus_area_count: rows.length,
      retrieved_top_50: results.filter(row => row.retrieved_top_50).length,
      retrieved_top_10: results.filter(row => (row.expected_rank ?? 51) <= 10).length,
      median_retrieved_rank: sortedRanks.length
        ? sortedRanks[Math.floor((sortedRanks.length - 1) / 2)]
        : null,
      results,
    };
  }

  const payload = {
    schema_version: 1,
    catalog: args.catalog,
    catalog_generated_at: harness.catalog.generated_at,
    query_count: queries.length,
    top_n: TOP_N,
    queries,
    genesis_focus_areas: genesisFocus,
  };
  const serialized = `${JSON.stringify(payload, null, 2)}\n`;
  if (args.out) await writeFile(args.out, serialized, "utf8");
  else process.stdout.write(serialized);
}

await main(process.argv.slice(2));

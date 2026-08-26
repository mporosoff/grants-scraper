import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const paths = {
  app: "assets/app.js",
  catalog: "data/opportunities.js",
  loader: "assets/catalog-loader.js",
  metadata: "data/catalog-metadata.js",
  explorer: "match_explorer.html",
  team: "team_match.html",
  release: "data/search-v2-release.json",
  refresh: ".github/workflows/refresh-opportunities.yml",
  deploy: ".github/workflows/deploy-search-package.yml",
};
const sources = Object.fromEntries(await Promise.all(
  Object.entries(paths).map(async ([key, path]) => [
    key,
    await readFile(new URL(path, root), key === "catalog" ? "utf8" : "utf8"),
  ]),
));

function assignedJson(source, globalName) {
  const prefix = `globalThis.${globalName}=`;
  assert.ok(source.includes(prefix), `${globalName} assignment is missing`);
  return JSON.parse(source.split(prefix, 2)[1].trim().replace(/;$/, ""));
}

function sha256(source) {
  return createHash("sha256").update(source).digest("hex");
}

function releaseIdentity(catalog, assetVersion) {
  const status = Object.entries(catalog.status_counts || {})
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${Number(value) || 0}`)
    .join(",");
  return [
    `catalog-v${Number(catalog.schema_version) || 0}`,
    assetVersion,
    `records=${Number(catalog.record_count) || 0}`,
    `documents=${Number(catalog.search_index?.document_count) || 0}`,
    `terms=${Object.keys(catalog.search_index?.postings || {}).length}`,
    `status=${status}`,
  ].join(":");
}

test("Funding Finder critical HTML executes metadata and the loader, never the full catalog", () => {
  assert.doesNotMatch(sources.explorer, /<script src="\.\/data\/opportunities\.js/);
  assert.match(sources.explorer, /<script src="\.\/data\/catalog-metadata\.js\?v=catalog-[^"]+"><\/script>/);
  assert.match(sources.explorer, /<script src="\.\/assets\/catalog-loader\.js\?v=[^"]+"><\/script>/);
  assert.ok(
    sources.explorer.indexOf("data/catalog-metadata.js")
      < sources.explorer.indexOf("assets/catalog-loader.js"),
  );
  assert.ok(
    sources.explorer.indexOf("assets/catalog-loader.js")
      < sources.explorer.indexOf("assets/app.js"),
  );
  assert.match(sources.team, /<script src="\.\/data\/opportunities\.js\?v=catalog-[^"]+"><\/script>/);
});

test("generated startup metadata is small and coherent with the canonical catalog", () => {
  const catalog = assignedJson(sources.catalog, "GRANT_CATALOG");
  const metadata = assignedJson(sources.metadata, "GRANT_CATALOG_METADATA");
  assert.equal(
    sha256(sources.catalog),
    "34de841033fba1e7ffb233cddf051d77b21b6759f143404b06f2919628647c43",
    "the startup refactor must not change the canonical catalog or frozen ranking inputs",
  );
  assert.ok(Buffer.byteLength(sources.metadata) < 2_048);
  assert.equal(metadata.schema_version, 1);
  assert.equal(metadata.catalog_schema_version, catalog.schema_version);
  assert.equal(metadata.generated_at, catalog.generated_at);
  assert.equal(metadata.record_count, catalog.record_count);
  assert.deepEqual(metadata.status_counts, catalog.status_counts);
  assert.equal(metadata.catalog_url, `./data/opportunities.js?v=${metadata.asset_version}`);
  assert.match(metadata.asset_version, /^catalog-\d{8}T\d{12}Z$/);
  assert.equal(metadata.release_identity, releaseIdentity(catalog, metadata.asset_version));
});

test("loader owns one bounded lifecycle without executable prefetch or unsafe code paths", () => {
  for (const state of ["idle", "prefetching", "loading", "initializing", "ready", "failed"]) {
    assert.match(sources.loader, new RegExp(`"${state}"`));
  }
  assert.match(sources.loader, /if \(inFlight\) return inFlight/);
  assert.match(sources.loader, /link\.rel = "prefetch"/);
  assert.match(sources.loader, /link\.as = "script"/);
  assert.match(sources.loader, /connection\?\.saveData === true/);
  assert.match(sources.loader, /type === "slow-2g" \|\| type === "2g"/);
  assert.match(sources.loader, /document\.hidden/);
  assert.match(sources.loader, /document\.createElement\("script"\)/);
  assert.match(sources.loader, /url\.origin !== location\.origin/);
  assert.match(sources.loader, /fundingCatalogMetadataRecovery/);
  assert.match(sources.loader, /if \(retrying\) await refreshMetadata\(\)/);
  assert.match(sources.loader, /pathname\.endsWith\("\/data\/catalog-metadata\.js"\)/);
  assert.match(sources.loader, /Catalog startup metadata refresh timed out/);
  assert.match(sources.loader, /function catalogAssetVersion\(catalog\)/);
  assert.match(sources.loader, /candidatePipelineTimestamp !== startup\.pipeline_generated_at/);
  assert.match(sources.loader, /candidateAssetVersion !== startup\.asset_version/);
  assert.match(sources.loader, /releaseIdentity\(candidate\) !== startup\.release_identity/);
  assert.doesNotMatch(sources.loader, /releaseIdentity\(candidate, startup\.asset_version\)/);
  assert.doesNotMatch(sources.loader, /\beval\s*\(|new Function|createObjectURL|blob:/);
});

test("application explicitly separates shell and catalog initialization and marks first use", () => {
  assert.match(sources.app, /function initializeShell\(\)/);
  assert.match(sources.app, /async function initializeCatalog\(candidate\)/);
  assert.match(sources.app, /CATALOG_LOADER\.configure\(\{/);
  assert.match(sources.app, /initialize: initializeCatalog/);
  assert.match(sources.app, /reset: resetCatalogInitialization/);
  assert.match(sources.app, /markPerformance\("funding-shell-ready"\)/);
  assert.match(sources.loader, /mark\("funding-catalog-requested"\)/);
  assert.match(sources.loader, /mark\("funding-catalog-executed"\)/);
  assert.match(sources.loader, /mark\("funding-catalog-initialized"\)/);
  assert.match(sources.app, /markPerformance\("funding-first-search-completed"\)/);
  assert.match(sources.app, /globalThis\.addEventListener\("popstate", handleHistoryNavigation\)/);
});

test("release and refresh contracts publish and verify metadata with the exact catalog", () => {
  const release = JSON.parse(sources.release);
  for (const path of [
    "data/opportunities.js",
    "data/catalog-metadata.js",
    "assets/catalog-loader.js",
  ]) {
    assert.equal(release.source_hashes[path], sha256(sources[
      path === "data/opportunities.js" ? "catalog"
        : path === "data/catalog-metadata.js" ? "metadata" : "loader"
    ]));
  }
  assert.match(release.atomic_publication_contract, /startup metadata/);
  assert.match(sources.refresh, /git add[^\n]*data\/opportunities\.js data\/catalog-metadata\.js/);
  assert.match(sources.refresh, /live_metadata/);
  assert.match(sources.refresh, /live_catalog_sha/);
  assert.match(sources.deploy, /"assets\/catalog-loader\.js"/);
  assert.match(sources.deploy, /"data\/catalog-metadata\.js"/);
  assert.match(sources.deploy, /live_metadata/);
  assert.match(sources.deploy, /live_catalog_sha/);
});

import assert from "node:assert/strict";
import test from "node:test";
import { copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { requireCompleteDocumentWork } from "../../tools/build_search_v2_voyage_vectors.mjs";

const root = new URL("../../", import.meta.url);
const outputs = ["data/search-v2-voyage-manifest.json", "data/search-v2-voyage-vectors.f16",
  "data/search-v2-voyage-canaries.json", "evaluation/search_v2_hybrid_vector_build.json"];

test("document-work markers require explicit true while legacy catalogs remain supported", () => {
  for (const catalog of [{}, {diagnostics: {}}, {diagnostics: {document_work: {publication_safe: true}}}]) {
    assert.doesNotThrow(() => requireCompleteDocumentWork(catalog));
  }
  for (const work of [null, false, true, 0, "complete", [], {}, {publication_safe: false},
    {publication_safe: "true"}, {publication_safe: 1}, {publication_safe: null}]) {
    assert.throws(() => requireCompleteDocumentWork({diagnostics: {document_work: work}}),
      /Document processing is incomplete/);
  }
});

async function withFixture(catalog, inspect) {
  const directory = await mkdtemp(join(tmpdir(), "funding-document-vector-"));
  try {
    for (const subdir of ["tools", "data", "assets", "evaluation"]) await mkdir(join(directory, subdir));
    for (const name of ["build_search_v2_voyage_vectors.mjs", "coherent_files.mjs", "embedding_contract.mjs"]) {
      await copyFile(new URL(`tools/${name}`, root), join(directory, "tools", name));
    }
    await writeFile(join(directory, "data/opportunities.js"), JSON.stringify(catalog));
    await writeFile(join(directory, "tools/run_search_diagnosis.mjs"), `
      import {readFile} from 'node:fs/promises';
      import {writeFileSync} from 'node:fs';
      export async function loadHarness() {
        return {catalog: JSON.parse(await readFile(new URL('../data/opportunities.js', import.meta.url), 'utf8'))};
      }
      export function makeVariantHarness(base) {
        writeFileSync(new URL('../corpus-started', import.meta.url), 'started');
        return {parentCatalog: base.catalog, childCatalog: {},
          parentEngine: {score: () => ({currentnessRejectedIndexes: []})}};
      }
    `);
    await writeFile(join(directory, "assets/search-hybrid.js"), `
      globalThis.FUNDING_HYBRID_SEARCH = {buildCorpus: () => [{passage_id: 'parent:one',
        parent_id: 'one', record_id: 'one', passage_kind: 'parent', text: 'Public source science'}]};
    `);
    const preload = join(directory, "transport.mjs");
    await writeFile(preload, `
      import {writeFileSync} from 'node:fs';
      globalThis.fetch = async () => {
        writeFileSync(new URL('./provider-attempted', import.meta.url), 'attempted');
        throw new Error('SYNTHETIC_PROVIDER_BOUNDARY');
      };
    `);
    for (const name of outputs) await writeFile(join(directory, name), "prior coherent output: " + name);
    const result = spawnSync(process.execPath, ["--import", pathToFileURL(preload).href,
      join(directory, "tools/build_search_v2_voyage_vectors.mjs"), "--production", "--write"], {
      cwd: directory, encoding: "utf8", timeout: 10_000,
      env: {...process.env, VOYAGE_API_KEY: "synthetic-unused"},
    });
    assert.ifError(result.error);
    assert.equal(result.status, 1, result.stderr);
    for (const name of outputs) {
      assert.equal(await readFile(join(directory, name), "utf8"), "prior coherent output: " + name);
    }
    await inspect(result, directory);
  } finally {
    assert.equal(dirname(directory), resolve(tmpdir()));
    assert.match(basename(directory), /^funding-document-vector-/);
    await rm(directory, {recursive: true, force: true});
  }
}

test("production CLI blocks incomplete notices before corpus work, provider dispatch or output mutation", async () => {
  for (const work of [{publication_safe: false}, null, [], {publication_safe: "true"}]) {
    await withFixture({diagnostics: {document_work: work}}, async (result, directory) => {
      assert.match(result.stderr, /Document processing is incomplete/);
      assert.doesNotMatch(result.stderr, /SYNTHETIC_PROVIDER_BOUNDARY/);
      for (const name of ["provider-attempted", "corpus-started", ".cache"]) {
        await assert.rejects(stat(join(directory, name)), {code: "ENOENT"});
      }
    });
  }
});

test("legacy and explicitly complete catalogs still reach the unchanged vector producer", async () => {
  for (const catalog of [{}, {diagnostics: {document_work: {publication_safe: true}}}]) {
    await withFixture(catalog, async (result, directory) => {
      assert.match(result.stderr, /SYNTHETIC_PROVIDER_BOUNDARY/);
      assert.equal(await readFile(join(directory, "provider-attempted"), "utf8"), "attempted");
      assert.equal(await readFile(join(directory, "corpus-started"), "utf8"), "started");
    });
  }
});

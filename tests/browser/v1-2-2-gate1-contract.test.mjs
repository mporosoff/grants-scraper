import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile, mkdtemp, mkdir, copyFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { createServer } from "node:http";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = new URL("../../", import.meta.url);
const [app, searchPage, teamPage, smoke, worker, refreshWorkflow, deployWorkflow, allowlist] = await Promise.all([
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
  readFile(new URL("tools/smoke_search_worker.mjs", root), "utf8"),
  readFile(new URL("workers/search-voyage-proxy/src/index.js", root), "utf8"),
  readFile(new URL(".github/workflows/refresh-opportunities.yml", root), "utf8"),
  readFile(new URL("tools/publish_release_candidate.py", root), "utf8"),
  readFile(new URL("workers/search-voyage-proxy/generated/corpus-allowlist.json", root), "utf8").then(JSON.parse),
]);

function runSmoke(workerUrl, candidateRoot) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [
      fileURLToPath(new URL("tools/smoke_search_worker.mjs", root)),
      workerUrl,
    ], { cwd: fileURLToPath(root), env: {...process.env,
      ...(candidateRoot ? {FUNDING_RELEASE_INPUT_ROOT: candidateRoot} : {})} });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", chunk => { stdout += chunk; });
    child.stderr.on("data", chunk => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", code => resolve({ code, stdout, stderr }));
  });
}

function assertSafeFundingFinderTopicFallback(fallback) {
  const approvedTimeoutRethrow = /if \(_topicError\?\.code === "topic_sidecar_timeout"\) throw _topicError;/;
  assert.match(fallback, approvedTimeoutRethrow);
  const ordinaryFailurePath = fallback.replace(approvedTimeoutRethrow, "");
  assert.match(ordinaryFailurePath, /topicLayerFailed = true/);
  assert.match(ordinaryFailurePath, /nextTopicLayerAvailable = false/);
  assert.doesNotMatch(
    ordinaryFailurePath,
    /catalog-error|throw|state\.ready\s*=\s*false/,
  );
}

async function withMockWorker({ failEmbed = false, packageAllowlist = allowlist } = {}, callback) {
  const observed = [];
  const server = createServer((request, response) => {
    let source = "";
    request.on("data", chunk => { source += chunk; });
    request.on("end", () => {
      response.setHeader("Content-Type", "application/json");
      if (request.url === "/health") {
        response.end(JSON.stringify({
          service: "available",
          corpus_sha256: packageAllowlist.current.corpus_sha256,
          model_space_fingerprint: packageAllowlist.current.model_space_fingerprint,
          previous_corpus_supported: true,
          budget_state: "available",
        }));
        return;
      }
      const body = source ? JSON.parse(source) : {};
      if (request.url === "/embed-query") {
        if (failEmbed) {
          response.statusCode = 503;
          response.end(JSON.stringify({ error: { code: "provider_unavailable" } }));
          return;
        }
        observed.push({ endpoint: "embed", body });
        response.end(JSON.stringify({
          model: "voyage-4-lite",
          embedding: new Array(1024).fill(0),
          usage: { total_tokens: 1 },
        }));
        return;
      }
      const generation = [packageAllowlist.current, packageAllowlist.previous]
        .find(item => item.corpus_sha256 === body.corpus_sha256);
      if (!generation) {
        response.statusCode = 400;
        response.end(JSON.stringify({ error: { code: "invalid_candidates" } }));
        return;
      }
      observed.push({ endpoint: "rerank", generation, body });
      response.end(JSON.stringify({
        model: "rerank-2.5",
        rankings: [{ index: 0, passage_id: body.candidates[0].passage_id, relevance_score: .9 }],
        usage: { total_tokens: 1 },
      }));
    });
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    return await callback(`http://127.0.0.1:${address.port}/`, observed);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
}

test('release smoke reads the exact candidate package instead of the older release-code checkout', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'funding-smoke-'));
  try {
    for (const name of ['data/opportunities.js', 'data/subtopics.js', 'assets/search-hybrid.js']) {
      await mkdir(dirname(join(directory, name)), {recursive: true});
      await copyFile(new URL(name, root), join(directory, name));
    }
    const candidate = structuredClone(allowlist);
    candidate.current.corpus_sha256 = '1'.repeat(64);
    const name = 'workers/search-voyage-proxy/generated/corpus-allowlist.json';
    await mkdir(dirname(join(directory, name)), {recursive: true});
    await writeFile(join(directory, name), JSON.stringify(candidate));
    await withMockWorker({packageAllowlist: candidate}, async workerUrl => {
      const oldCheckout = await runSmoke(workerUrl);
      assert.notEqual(oldCheckout.code, 0);
      const exactCandidate = await runSmoke(workerUrl, directory);
      assert.equal(exactCandidate.code, 0, exactCandidate.stderr);
      assert.equal(JSON.parse(exactCandidate.stdout).current_corpus_sha256, candidate.current.corpus_sha256);
    });
  } finally {
    await rm(directory, {recursive: true, force: true});
  }
});

test("Funding Finder keeps parent search available when the topic sidecar fails", () => {
  const parentInit = app.indexOf("const nextSearchEngine = RETRIEVAL_API.create(candidate");
  const sidecarLoad = app.indexOf("const sidecar = await SUBTOPIC_API.loadSidecar()");
  assert.ok(parentInit >= 0 && parentInit < sidecarLoad);
  assert.match(searchPage, /id="topic-layer-warning"[^>]*role="status"/);
  const fallback = app.match(/catch \(_topicError\) \{[\s\S]*?\n        \}/)?.[0] || "";
  assertSafeFundingFinderTopicFallback(fallback);
  const catalogInit = app.slice(
    app.indexOf("async function initializeCatalog(candidate)"),
    app.indexOf("function initializeShell()"),
  );
  assert.match(catalogInit, /searchEngine = nextSearchEngine/);
  assert.match(catalogInit, /hybridSearchClient = nextHybridSearchClient/);
  assert.match(catalogInit, /topic-layer-warning/);
  assert.match(catalogInit, /Parent-level Strong search, filters, saved opportunities, and exports still work/);
  assert.match(app, /topicLayerAvailable\s*\?\s*"proxy_unconfigured"\s*:\s*"topic_layer_unavailable"/);
  assert.match(catalogInit, /APP_CONFIG\?\.flags\?\.searchV2[\s\S]*?&& nextChildCatalog[\s\S]*?&& nextChildSearchEngine/);
});

test("Funding Finder topic fallback contract rejects unrelated failure escalation", () => {
  const approved = 'if (_topicError?.code === "topic_sidecar_timeout") throw _topicError;';
  for (const prohibited of [
    "throw new Error('unrelated');",
    'document.querySelector("#catalog-error").hidden = false;',
    "state.ready = false;",
    "if (_topicError) throw _topicError;",
  ]) {
    assert.throws(() => assertSafeFundingFinderTopicFallback(`
      catch (_topicError) {
        ${approved}
        ${prohibited}
        topicLayerFailed = true;
        nextTopicLayerAvailable = false;
      }
    `));
  }
});

test("Team Match keeps parent-only matching and disables hosted enhancement on sidecar failure", () => {
  const sidecarLoad = teamPage.indexOf("var sidecar = await SUBTOPIC_API.loadSidecar()");
  const continueInit = teamPage.indexOf("renderExternalButtons();", sidecarLoad);
  assert.ok(sidecarLoad >= 0 && continueInit > sidecarLoad);
  const fallback = teamPage.slice(sidecarLoad, teamPage.indexOf("if (\n      CHILD_CATALOG", sidecarLoad));
  assert.match(fallback, /CHILD_CATALOG = null/);
  assert.match(fallback, /CHILD_MATCH_ENGINE = null/);
  assert.match(fallback, /TEAM_HYBRID_COORDINATOR = null/);
  assert.match(fallback, /Parent-level team matching still works/);
  assert.doesNotMatch(fallback, /return;/);
  assert.match(teamPage, /if \(!CHILD_MATCH_ENGINE \|\| !RETRIEVAL_API \|\| !CHILD_CATALOG\) \{[\s\S]*?return outcome\.results/);
  assert.match(teamPage, /id="team-topic-layer-status"/);
});

test("Worker smoke supplies every declared generation fingerprint", () => {
  assert.match(smoke, /if \(generation\.model_space_fingerprint\) \{[\s\S]*?payload\.model_space_fingerprint = generation\.model_space_fingerprint/);
  assert.match(smoke, /rerank\(allowlist\.current\)/);
  assert.match(smoke, /rerank\(allowlist\.previous\)/);
  assert.doesNotMatch(smoke, /rerank\(allowlist\.previous, false\)/);
});

test("Worker smoke performs the real bounded sequence and fails on provider rejection", async () => {
  await withMockWorker({}, async (workerUrl, observed) => {
    const result = await runSmoke(workerUrl);
    assert.equal(result.code, 0, result.stderr);
    assert.equal(observed.filter(call => call.endpoint === "embed").length, 1);
    const reranks = observed.filter(call => call.endpoint === "rerank");
    assert.equal(reranks.length, 2);
    for (const call of reranks) {
      assert.equal(call.body.model_space_fingerprint, call.generation.model_space_fingerprint);
    }
    assert.equal(JSON.parse(result.stdout).unknown_corpus_status, 400);
  });
  await withMockWorker({ failEmbed: true }, async workerUrl => {
    const result = await runSmoke(workerUrl);
    assert.equal(result.code, 1);
    assert.match(result.stderr, /Current embed smoke failed with HTTP 503/);
  });
});

test("package-sensitive changes can reuse generated data through the single release owner", async () => {
  const reuse = refreshWorkflow.slice(refreshWorkflow.indexOf('  assemble:'), refreshWorkflow.indexOf('  candidate:'));
  const assembler = await readFile(new URL('tools/assemble_release_candidate.py', root), 'utf8');
  assert.match(assembler, /c.verify_dependencies\(root, manifest, allowed=\('teams',\) if team_update else \(\)\)/);
  assert.match(reuse, /tools.assemble_release_candidate/);
  assert.match(reuse, /build_search_release_package\.mjs --write/);
  assert.doesNotMatch(reuse, /scripts\.build_catalog|build_search_v2_voyage_vectors/);
  for (const step of reuse.split('      - name:').slice(1)) {
    if (/--generate|secrets\.(?:ANTHROPIC|OPENAI|VOYAGE)_API_KEY/.test(step)) {
      assert.match(step, /if: steps.restore.outputs.candidate_id == '' && needs.plan.outputs.stage != 'reuse'/);
    }
  }
  assert.match(refreshWorkflow, /if: steps.worker-inputs.outputs.deploy_required == 'true'/);
});

test("the publication owner captures actual serving provenance and fails closed on main races", () => {
  assert.match(refreshWorkflow, /tools\/search_worker_checkpoint.mjs/);
  assert.match(refreshWorkflow, /steps.worker-inputs.outputs.version_id/);
  assert.match(refreshWorkflow, /wrangler@4.125.0 rollback "\$PRIOR_VERSION"/);
  assert.match(refreshWorkflow, /group: funding-finder-coordinated-release/);
  assert.match(deployWorkflow, /'git', 'ls-remote', 'origin', 'refs\/heads\/main'/);
  assert.match(deployWorkflow, /if remote != base/);
  assert.match(deployWorkflow, /Protected merge changed candidate bytes/);
  assert.equal((refreshWorkflow.match(/node tools\/smoke_search_worker.mjs/g) || []).length, 2);
});

test("reservations use bounded timestamps and health exposes aggregate totals only", () => {
  assert.match(worker, /RESERVATION_TTL_MS\s*=\s*30_000/);
  assert.match(worker, /pruneExpiredReservations\(state, now\)/);
  assert.match(worker, /created_at: now[\s\S]*?expires_at: now \+ RESERVATION_TTL_MS/);
  assert.match(worker, /reserved_tokens: boundedReservedTokens/);
  assert.doesNotMatch(worker, /query.*reservations|reservations.*query/);
});

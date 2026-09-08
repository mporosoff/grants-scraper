#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const WORKER_DEPLOYMENT_MESSAGE_PREFIX = "protected-main:";

export const WORKER_DEPLOYMENT_INPUTS = Object.freeze({
  "award-api": Object.freeze({
    prefixes: Object.freeze(["workers/award-api/"]),
    files: Object.freeze([
      "config/award_institutions.json",
      "package.json",
      "pnpm-lock.yaml",
    ]),
  }),
  alerts: Object.freeze({
    prefixes: Object.freeze(["workers/alerts/"]),
    files: Object.freeze([
      "assets/award-links.js",
      "assets/match-explain.js",
      "assets/search-query.js",
      "assets/search-retrieval.js",
      "assets/submission-schedule.js",
      "assets/search-v2-config.js",
    ]),
  }),
});

function normalizedPath(value) {
  return String(value || "").trim().replaceAll("\\", "/").replace(/^\.\//, "");
}

function activeDeployment(deployments) {
  if (!Array.isArray(deployments)) throw new Error("Worker deployments must be a JSON array.");
  if (!deployments.length) throw new Error("No active Worker deployment checkpoint is available.");
  for (const deployment of deployments) {
    if (!deployment?.id || !Number.isFinite(Date.parse(deployment.created_on))) {
      throw new Error("Worker deployment identity or timestamp is missing.");
    }
  }
  const ordered = [...deployments]
    .sort((left, right) => {
      return Date.parse(left.created_on) - Date.parse(right.created_on);
    });
  const active = ordered.at(-1);
  if (ordered.length > 1 && Date.parse(ordered.at(-2).created_on) === Date.parse(active.created_on)) {
    throw new Error("The active Worker deployment has an ambiguous timestamp.");
  }
  const versions = active.versions;
  if (!Array.isArray(versions) || !versions.length || versions.some(version => (
    !Number.isFinite(version?.percentage) || version.percentage < 0 || version.percentage > 100
  ))) throw new Error("The active Worker deployment has invalid traffic weights.");
  const serving = versions.filter(version => version.percentage > 0);
  // The existing rollback workflow restores one version at 100%. Do not infer
  // one checkpoint or rollback target for a mixed or incomplete rollout.
  if (serving.length !== 1 || serving[0].percentage !== 100) {
    throw new Error("A single fully active Worker version is required for safe deployment and rollback.");
  }
  checkedVersionId(serving[0].version_id);
  return { deployment: active, versionId: serving[0].version_id };
}

function checkedVersionId(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error("Active Worker version must have an exact UUID.");
  }
  return value;
}

function checkpointMessage(annotations) {
  const message = String(annotations?.["workers/message"] || "").trim();
  const escapedPrefix = WORKER_DEPLOYMENT_MESSAGE_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`^${escapedPrefix}([0-9a-f]{40})(?:;|$)`, "i").exec(message);
  const sha = match?.[1]?.toLowerCase();
  return sha && !/^0{40}$/.test(sha) ? sha : null;
}

export function readWorkerVersionMetadata(worker, versionId, { execute = execFileSync } = {}) {
  if (!Object.hasOwn(WORKER_DEPLOYMENT_INPUTS, worker)) throw new Error(`Unknown Worker deployment target: ${worker}`);
  checkedVersionId(versionId);
  try {
    // Pinned Wrangler --json returns ApiVersion, including upload annotations.
    // Do not print its resources/bindings or process-error buffers to Actions.
    const value = JSON.parse(execute("npx", [
      "--yes", "wrangler@4.125.0", "versions", "view", versionId,
      "--config", `workers/${worker}/wrangler.jsonc`, "--json",
    ], { encoding: "utf8", timeout: 60_000, maxBuffer: 1024 * 1024, stdio: ["ignore", "pipe", "pipe"] }));
    return { id: value.id, annotations: { "workers/message": value.annotations?.["workers/message"] } };
  } catch {
    throw new Error("Unable to read active Worker version metadata; publication is blocked.");
  }
}

export function resolveWorkerDeploymentCheckpoint(worker, deployments, version) {
  if (!Object.hasOwn(WORKER_DEPLOYMENT_INPUTS, worker)) throw new Error(`Unknown Worker deployment target: ${worker}`);
  const { deployment, versionId } = activeDeployment(deployments);
  if (!version || version.id !== versionId) {
    throw new Error("Worker version metadata does not belong to the active deployment.");
  }
  const uploadedSha = checkpointMessage(version.annotations);
  const deployedSha = checkpointMessage(deployment.annotations);
  if (uploadedSha && deployedSha && uploadedSha !== deployedSha) {
    throw new Error("Active Worker version and deployment checkpoints conflict.");
  }
  if (!uploadedSha && !deployedSha) {
    throw new Error("Active Worker has no verified Git checkpoint; publication is blocked.");
  }
  return Object.freeze({
    baseSha: uploadedSha || deployedSha,
    source: uploadedSha ? "active-version-message" : "active-deployment-message",
    activeDeploymentId: deployment.id,
    activeVersionId: versionId,
  });
}

export function classifyWorkerDeployment(worker, changedPaths) {
  if (!Object.hasOwn(WORKER_DEPLOYMENT_INPUTS, worker)) throw new Error(`Unknown Worker deployment target: ${worker}`);
  const specification = WORKER_DEPLOYMENT_INPUTS[worker];
  const changed = [...new Set((changedPaths || []).map(normalizedPath).filter(Boolean))].sort();
  const deploymentInputs = changed.filter(file => (
    specification.files.includes(file)
    || specification.prefixes.some(prefix => file.startsWith(prefix))
  ));
  return Object.freeze({
    worker,
    deployRequired: deploymentInputs.length > 0,
    changed: Object.freeze(changed),
    deploymentInputs: Object.freeze(deploymentInputs),
  });
}

function checkedSha(value, label) {
  const sha = String(value || "").trim();
  if (!/^[0-9a-f]{40}$/i.test(sha)) throw new Error(`${label} must be a complete Git commit SHA.`);
  return sha;
}

export function changedPathsBetween(baseValue, headValue, { git = "git", cwd } = {}) {
  const base = checkedSha(baseValue, "Base");
  const head = checkedSha(headValue, "Head");
  const argumentsList = /^0{40}$/.test(base)
    ? ["diff-tree", "--root", "--no-commit-id", "--name-only", "--no-renames", "-r", head]
    : ["diff", "--name-only", "--no-renames", base, head, "--"];
  return execFileSync(git, argumentsList, { cwd, encoding: "utf8" })
    .split(/\r?\n/)
    .map(normalizedPath)
    .filter(Boolean);
}

function run() {
  const [worker, deploymentsPath, head] = process.argv.slice(2);
  if (!worker || !deploymentsPath || !head) {
    throw new Error("Usage: classify_worker_deployment.mjs <award-api|alerts> <deployments-json> <head-sha>");
  }
  const deployments = JSON.parse(readFileSync(deploymentsPath, "utf8"));
  const { versionId } = activeDeployment(deployments);
  const version = readWorkerVersionMetadata(worker, versionId);
  const checkpoint = resolveWorkerDeploymentCheckpoint(worker, deployments, version);
  const result = classifyWorkerDeployment(worker, changedPathsBetween(checkpoint.baseSha, head));
  const output = process.env.GITHUB_OUTPUT;
  if (!output) throw new Error("GITHUB_OUTPUT is required for workflow classification.");
  appendFileSync(output, `deploy_required=${result.deployRequired}\n`, "utf8");
  appendFileSync(output, `deployment_input_count=${result.deploymentInputs.length}\n`, "utf8");
  appendFileSync(output, `deployed_base_sha=${checkpoint.baseSha}\n`, "utf8");
  appendFileSync(output, `checkpoint_source=${checkpoint.source}\n`, "utf8");
  console.log(JSON.stringify({ ...result, checkpoint }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    run();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}

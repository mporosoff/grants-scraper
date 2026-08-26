#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const WORKER_DEPLOYMENT_MESSAGE_PREFIX = "protected-main:";

// PR #63's protected main was verified as the live source for both Workers
// before deployment messages began carrying an exact Git checkpoint.
export const INITIAL_WORKER_DEPLOYMENT_CHECKPOINTS = Object.freeze({
  "award-api": "6165c2778297fb736e908c8432724d23b913adae",
  alerts: "6165c2778297fb736e908c8432724d23b913adae",
});

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
      "assets/search-v2-config.js",
    ]),
  }),
});

function normalizedPath(value) {
  return String(value || "").trim().replaceAll("\\", "/").replace(/^\.\//, "");
}

function activeDeployment(deployments) {
  return deployments
    .filter(deployment => (
      Array.isArray(deployment?.versions)
      && deployment.versions.some(version => Number(version?.percentage || 0) > 0)
    ))
    .sort((left, right) => {
      const leftTime = Date.parse(String(left?.created_on || ""));
      const rightTime = Date.parse(String(right?.created_on || ""));
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
        return leftTime - rightTime;
      }
      if (Number.isFinite(leftTime) !== Number.isFinite(rightTime)) {
        return Number.isFinite(leftTime) ? 1 : -1;
      }
      return String(left?.id || "").localeCompare(String(right?.id || ""));
    })
    .at(-1) || null;
}

export function resolveWorkerDeploymentCheckpoint(worker, deployments) {
  const bootstrap = INITIAL_WORKER_DEPLOYMENT_CHECKPOINTS[worker];
  if (!bootstrap) throw new Error(`Unknown Worker deployment target: ${worker}`);
  if (!Array.isArray(deployments)) throw new Error("Worker deployments must be a JSON array.");
  const active = activeDeployment(deployments);
  const message = String(active?.annotations?.["workers/message"] || "").trim();
  const escapedPrefix = WORKER_DEPLOYMENT_MESSAGE_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`^${escapedPrefix}([0-9a-f]{40})(?:;|$)`, "i").exec(message);
  return Object.freeze({
    baseSha: match?.[1]?.toLowerCase() || bootstrap,
    source: match ? "active-deployment-message" : "verified-pr63-bootstrap",
    activeDeploymentId: String(active?.id || ""),
  });
}

export function classifyWorkerDeployment(worker, changedPaths) {
  const specification = WORKER_DEPLOYMENT_INPUTS[worker];
  if (!specification) throw new Error(`Unknown Worker deployment target: ${worker}`);
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
  const checkpoint = resolveWorkerDeploymentCheckpoint(worker, deployments);
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

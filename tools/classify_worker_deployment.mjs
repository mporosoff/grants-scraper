#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

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

export function changedPathsBetween(baseValue, headValue, { git = "git" } = {}) {
  const base = checkedSha(baseValue, "Base");
  const head = checkedSha(headValue, "Head");
  const argumentsList = /^0{40}$/.test(base)
    ? ["diff-tree", "--root", "--no-commit-id", "--name-only", "--no-renames", "-r", head]
    : ["diff", "--name-only", "--no-renames", base, head, "--"];
  return execFileSync(git, argumentsList, { encoding: "utf8" })
    .split(/\r?\n/)
    .map(normalizedPath)
    .filter(Boolean);
}

function run() {
  const [worker, base, head] = process.argv.slice(2);
  if (!worker || !base || !head) {
    throw new Error("Usage: classify_worker_deployment.mjs <award-api|alerts> <base-sha> <head-sha>");
  }
  const result = classifyWorkerDeployment(worker, changedPathsBetween(base, head));
  const output = process.env.GITHUB_OUTPUT;
  if (!output) throw new Error("GITHUB_OUTPUT is required for workflow classification.");
  appendFileSync(output, `deploy_required=${result.deployRequired}\n`, "utf8");
  appendFileSync(output, `deployment_input_count=${result.deploymentInputs.length}\n`, "utf8");
  console.log(JSON.stringify(result));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    run();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}

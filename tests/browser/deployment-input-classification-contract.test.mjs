import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  WORKER_DEPLOYMENT_INPUTS,
  classifyWorkerDeployment,
} from "../../tools/classify_worker_deployment.mjs";

const root = new URL("../../", import.meta.url);
const [awardWorkflow, alertsWorkflow] = await Promise.all([
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-alerts.yml", root), "utf8"),
]);

test("Award Worker deployment inputs include source, config, and actual package dependencies", () => {
  assert.deepEqual(WORKER_DEPLOYMENT_INPUTS["award-api"].prefixes, ["workers/award-api/"]);
  assert.deepEqual(WORKER_DEPLOYMENT_INPUTS["award-api"].files, [
    "config/award_institutions.json",
    "package.json",
    "pnpm-lock.yaml",
  ]);
  const result = classifyWorkerDeployment("award-api", [
    "workers\\award-api\\src\\index.js",
    "workers/award-api/wrangler.jsonc",
    "config/award_institutions.json",
    "package.json",
    "pnpm-lock.yaml",
  ]);
  assert.equal(result.deployRequired, true);
  assert.equal(result.deploymentInputs.length, 5);
});

test("Alerts Worker deployment inputs include source, migrations, config, and bundled shared runtime modules", () => {
  assert.deepEqual(WORKER_DEPLOYMENT_INPUTS.alerts.prefixes, ["workers/alerts/"]);
  assert.deepEqual(WORKER_DEPLOYMENT_INPUTS.alerts.files, [
    "assets/award-links.js",
    "assets/match-explain.js",
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "assets/search-v2-config.js",
  ]);
  const result = classifyWorkerDeployment("alerts", [
    "workers/alerts/src/index.js",
    "workers/alerts/migrations/0003_phase2_alert_lifecycle.sql",
    "workers/alerts/wrangler.jsonc",
    ...WORKER_DEPLOYMENT_INPUTS.alerts.files,
  ]);
  assert.equal(result.deployRequired, true);
  assert.equal(result.deploymentInputs.length, 8);
});

test("shared UI and release-support changes retain both existing Worker versions", () => {
  const uiOnlyChanges = [
    ".github/workflows/deploy-award-api.yml",
    ".github/workflows/deploy-alerts.yml",
    "assets/alerts.js",
    "assets/app.js",
    "assets/funded-awards.js",
    "funded_awards.html",
    "match_explorer.html",
    "tests/e2e/funding-finder.spec.mjs",
    "tools/classify_worker_deployment.mjs",
  ];
  assert.equal(classifyWorkerDeployment("award-api", uiOnlyChanges).deployRequired, false);
  assert.equal(classifyWorkerDeployment("alerts", uiOnlyChanges).deployRequired, false);
  assert.throws(() => classifyWorkerDeployment("unknown", uiOnlyChanges), /Unknown Worker/);
});

function assertOrdered(source, labels) {
  let previous = -1;
  for (const label of labels) {
    const current = source.indexOf(label);
    assert.ok(current > previous, `${label} must follow the prior guarded release step`);
    previous = current;
  }
}

function workflowStep(source, name) {
  const marker = `- name: ${name}`;
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `${name} must exist`);
  const next = source.indexOf("\n      - name:", start + marker.length);
  return source.slice(start, next === -1 ? source.length : next);
}

function assertDeployGuard(source, name) {
  assert.match(
    workflowStep(source, name),
    /if: \$\{\{ steps\.worker-inputs\.outputs\.deploy_required == 'true' \}\}/,
    `${name} must run only when deployment inputs changed`,
  );
}

test("Award workflow classifies before mutation and retains Pages validation on no-op releases", () => {
  assert.match(awardWorkflow, /tools\/classify_worker_deployment\.mjs/);
  assert.match(awardWorkflow, /Classify Award Worker deployment inputs/);
  assert.match(awardWorkflow, /Record retained Award Worker version/);
  assert.match(awardWorkflow, /Existing deployed Award Worker version retained because deployment inputs were unchanged/);
  assert.match(awardWorkflow, /steps\.worker-inputs\.outputs\.deploy_required == 'true'/);
  for (const name of [
    "Capture the active Award Worker version for rollback",
    "Reconfirm protected main immediately before Award Worker mutation",
    "Deploy the committed Award Worker",
    "Wait for the Award Worker health contract",
    "Run bounded exact-source smokes",
  ]) assertDeployGuard(awardWorkflow, name);
  assertOrdered(awardWorkflow, [
    "Capture and verify the protected main release base",
    "Classify Award Worker deployment inputs",
    "Capture the active Award Worker version for rollback",
    "Reconfirm protected main immediately before Award Worker mutation",
    "Deploy the committed Award Worker",
    "Wait for the Award Worker health contract",
    "Run bounded exact-source smokes",
    "Verify Pages serves the committed Funded Awards page",
  ]);
  assert.doesNotMatch(workflowStep(awardWorkflow, "Verify Pages serves the committed Funded Awards page"), /deploy_required/);
  assert.doesNotMatch(workflowStep(awardWorkflow, "Verify Pages serves the committed Funding Finder integration"), /deploy_required/);
  assert.equal(
    awardWorkflow.indexOf("\n      - name: Deploy the committed Award Worker"),
    awardWorkflow.indexOf("\n      - name:", awardWorkflow.indexOf("Reconfirm protected main immediately before Award Worker mutation")),
  );
});

test("Alerts workflow guards version capture, D1 migration, deployment, and rollback preparation", () => {
  assert.match(alertsWorkflow, /tools\/classify_worker_deployment\.mjs/);
  assert.match(alertsWorkflow, /Classify Alerts Worker deployment inputs/);
  assert.match(alertsWorkflow, /Record retained Alerts Worker version/);
  assert.match(alertsWorkflow, /Existing deployed Alerts Worker version retained because deployment inputs were unchanged/);
  assert.match(alertsWorkflow, /steps\.worker-inputs\.outputs\.deploy_required == 'true'/);
  for (const name of [
    "Capture the active Alerts Worker version for rollback",
    "Reconfirm protected main immediately before Alerts Worker mutation",
    "Apply committed D1 migrations",
    "Deploy the committed Alerts Worker",
    "Wait for the Alerts Worker health contract",
    "Run bounded Alerts Worker smokes",
  ]) assertDeployGuard(alertsWorkflow, name);
  assertOrdered(alertsWorkflow, [
    "Capture and verify the protected main release base",
    "Classify Alerts Worker deployment inputs",
    "Capture the active Alerts Worker version for rollback",
    "Reconfirm protected main immediately before Alerts Worker mutation",
    "Apply committed D1 migrations",
    "Deploy the committed Alerts Worker",
    "Wait for the Alerts Worker health contract",
    "Run bounded Alerts Worker smokes",
    "Verify Pages serves the committed alert surfaces",
  ]);
  assert.doesNotMatch(workflowStep(alertsWorkflow, "Verify Pages serves the committed alert surfaces"), /deploy_required/);
  assert.equal(
    alertsWorkflow.indexOf("\n      - name: Apply committed D1 migrations"),
    alertsWorkflow.indexOf("\n      - name:", alertsWorkflow.indexOf("Reconfirm protected main immediately before Alerts Worker mutation")),
  );
  assert.match(alertsWorkflow, /if: \$\{\{ always\(\) && steps\.worker-deploy\.outcome == 'success'/);
});

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  INITIAL_WORKER_DEPLOYMENT_CHECKPOINTS,
  WORKER_DEPLOYMENT_INPUTS,
  changedPathsBetween,
  classifyWorkerDeployment,
  resolveWorkerDeploymentCheckpoint,
} from "../../tools/classify_worker_deployment.mjs";
import { validateAlertCapabilityRotation } from "../../tools/validate_alert_capability_rotation.mjs";

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

test("active deployment messages provide the exact comparison checkpoint with a verified PR 63 bootstrap", () => {
  assert.deepEqual(INITIAL_WORKER_DEPLOYMENT_CHECKPOINTS, {
    "award-api": "6165c2778297fb736e908c8432724d23b913adae",
    alerts: "6165c2778297fb736e908c8432724d23b913adae",
  });
  assert.deepEqual(resolveWorkerDeploymentCheckpoint("award-api", []), {
    baseSha: INITIAL_WORKER_DEPLOYMENT_CHECKPOINTS["award-api"],
    source: "verified-pr63-bootstrap",
    activeDeploymentId: "",
  });
  assert.deepEqual(resolveWorkerDeploymentCheckpoint("alerts", [
    {
      id: "inactive-newer",
      created_on: "2026-08-26T12:00:01.000Z",
      versions: [{ percentage: 0 }],
      annotations: { "workers/message": `protected-main:${"f".repeat(40)}` },
    },
    {
      id: "active-older",
      created_on: "2026-08-26T12:00:00.125Z",
      versions: [{ percentage: 100 }],
      annotations: { "workers/message": `protected-main:${"a".repeat(40)}` },
    },
    {
      id: "active-rollback",
      created_on: "2026-08-26T12:00:00.250Z",
      versions: [{ percentage: 100 }],
      annotations: { "workers/message": `protected-main:${"B".repeat(40)}; automatic rollback because main advanced` },
    },
  ]), {
    baseSha: "b".repeat(40),
    source: "active-deployment-message",
    activeDeploymentId: "active-rollback",
  });
  assert.equal(
    resolveWorkerDeploymentCheckpoint("alerts", [{
      id: "manual",
      created_on: "2026-08-26T12:00:00Z",
      versions: [{ percentage: 100 }],
      annotations: { "workers/message": "unrecognized manual deployment" },
    }]).source,
    "verified-pr63-bootstrap",
  );
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", {}), /JSON array/);
});

test("a queued UI-only push still deploys a Worker change missed after the prior checkpoint", async () => {
  const repository = await mkdtemp(join(tmpdir(), "worker-deployment-classifier-"));
  const git = (...argumentsList) => execFileSync("git", ["-C", repository, ...argumentsList], { encoding: "utf8" }).trim();
  try {
    git("init", "--quiet");
    git("config", "user.name", "Deployment Contract");
    git("config", "user.email", "deployment-contract@example.test");
    await writeFile(join(repository, "README.md"), "checkpoint\n", "utf8");
    git("add", "README.md");
    git("commit", "--quiet", "-m", "checkpoint");
    const deployedCheckpoint = git("rev-parse", "HEAD");

    await mkdir(join(repository, "workers", "award-api", "src"), { recursive: true });
    await writeFile(join(repository, "workers", "award-api", "src", "index.js"), "export default {};\n", "utf8");
    git("add", "workers/award-api/src/index.js");
    git("commit", "--quiet", "-m", "worker change");
    const workerPush = git("rev-parse", "HEAD");

    await writeFile(join(repository, "match_explorer.html"), "<main>UI only</main>\n", "utf8");
    git("add", "match_explorer.html");
    git("commit", "--quiet", "-m", "queued UI change");
    const uiPush = git("rev-parse", "HEAD");

    assert.equal(
      classifyWorkerDeployment("award-api", changedPathsBetween(workerPush, uiPush, { cwd: repository })).deployRequired,
      false,
      "the adjacent push range reproduces the lost-deployment bug",
    );
    assert.equal(
      classifyWorkerDeployment("award-api", changedPathsBetween(deployedCheckpoint, uiPush, { cwd: repository })).deployRequired,
      true,
      "the deployed checkpoint keeps the missed Worker change in scope",
    );
  } finally {
    await rm(repository, { recursive: true, force: true });
  }
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
    /if: \$\{\{ steps\.worker-inputs\.outputs\.deploy_required == 'true'(?: && [^}]*)? \}\}/,
    `${name} must run only when deployment inputs changed`,
  );
}

test("Award workflow classifies before mutation and retains Pages validation on no-op releases", () => {
  assert.match(awardWorkflow, /tools\/classify_worker_deployment\.mjs/);
  assert.match(awardWorkflow, /assets\/institutional-intelligence-snapshots\.js/);
  assert.match(awardWorkflow, /workers\/award-api\/src\/snapshot\.js/);
  assert.match(awardWorkflow, /unit-b-funded-awards-snapshot-contract\.test\.mjs/);
  assert.match(awardWorkflow, /tools\/smoke_unit_b_award_worker\.mjs/);
  assert.match(awardWorkflow, /complete_result_snapshots\.ordering_version/);
  assert.match(awardWorkflow, /Classify Award Worker inputs since the active deployment/);
  assert.match(awardWorkflow, /deployments list --config workers\/award-api\/wrangler\.jsonc --json/);
  assert.doesNotMatch(awardWorkflow, /github\.event\.before/);
  assert.match(awardWorkflow, /--message "protected-main:\$\{GITHUB_SHA\}; protected main deployment"/);
  assert.match(awardWorkflow, /protected-main:\$\{\{ steps\.worker-inputs\.outputs\.deployed_base_sha \}\}; automatic rollback/);
  assert.match(awardWorkflow, /Record retained Award Worker version/);
  assert.match(awardWorkflow, /Existing deployed Award Worker version retained because deployment inputs were unchanged/);
  assert.match(awardWorkflow, /steps\.worker-inputs\.outputs\.deploy_required == 'true'/);
  for (const name of [
    "Capture the active Award Worker version for rollback",
    "Reconfirm protected main immediately before Award Worker mutation",
    "Configure the Award abuse-control identity secret",
    "Deploy the committed Award Worker",
    "Wait for the Award Worker health contract",
    "Run bounded exact-source smokes",
  ]) assertDeployGuard(awardWorkflow, name);
  assertOrdered(awardWorkflow, [
    "Capture and verify the protected main release base",
    "Classify Award Worker inputs since the active deployment",
    "Capture the active Award Worker version for rollback",
    "Reconfirm protected main immediately before Award Worker mutation",
    "Configure the Award abuse-control identity secret",
    "Deploy the committed Award Worker",
    "Wait for the Award Worker health contract",
    "Run bounded exact-source smokes",
    "Verify Pages serves the committed Funded Awards page",
  ]);
  assert.doesNotMatch(workflowStep(awardWorkflow, "Verify Pages serves the committed Funded Awards page"), /deploy_required/);
  assert.doesNotMatch(workflowStep(awardWorkflow, "Verify Pages serves the committed Funding Finder integration"), /deploy_required/);
  assert.equal(
    awardWorkflow.indexOf("\n      - name: Configure the Award abuse-control identity secret"),
    awardWorkflow.indexOf("\n      - name:", awardWorkflow.indexOf("Reconfirm protected main immediately before Award Worker mutation")),
  );
  assert.equal(
    awardWorkflow.indexOf("\n      - name: Deploy the committed Award Worker"),
    awardWorkflow.indexOf("\n      - name:", awardWorkflow.indexOf("Configure the Award abuse-control identity secret")),
  );
});

test("Alerts workflow guards version capture, D1 migration, deployment, and rollback preparation", () => {
  assert.match(alertsWorkflow, /tools\/classify_worker_deployment\.mjs/);
  assert.match(alertsWorkflow, /Classify Alerts Worker inputs since the active deployment/);
  assert.match(alertsWorkflow, /deployments list --config workers\/alerts\/wrangler\.jsonc --json/);
  assert.doesNotMatch(alertsWorkflow, /github\.event\.before/);
  assert.match(alertsWorkflow, /--message "protected-main:\$\{GITHUB_SHA\}; protected main deployment"/);
  assert.match(alertsWorkflow, /protected-main:\$\{\{ steps\.worker-inputs\.outputs\.deployed_base_sha \}\}; automatic rollback/);
  assert.match(alertsWorkflow, /Record retained Alerts Worker version/);
  assert.match(alertsWorkflow, /Existing deployed Alerts Worker version retained because deployment inputs were unchanged/);
  assert.match(alertsWorkflow, /steps\.worker-inputs\.outputs\.deploy_required == 'true'/);
  assert.match(alertsWorkflow, /recovery_required=true/);
  assert.match(alertsWorkflow, /last_daily_run_status/);
  assert.match(alertsWorkflow, /failed_stale_recovered/);
  assert.match(alertsWorkflow, /2026-08-28T13:37:40\.002Z/);
  assert.match(alertsWorkflow, /worker-health\.outputs\.recovery_required != 'true'/);
  const capabilityStep = workflowStep(alertsWorkflow, "Configure the Alerts capability-signing secrets");
  assert.match(capabilityStep, /secrets\.ALERT_CAPABILITY_PREVIOUS_SECRET/);
  assert.match(capabilityStep, /set -euo pipefail/);
  assert.match(capabilityStep, /curl --silent --show-error --max-time 10/);
  assert.match(capabilityStep, /--output "\$health_file" --write-out '%\{http_code\}'/);
  assert.match(capabilityStep, /"\$health_status" != "200".*"\$health_status" != "503"/s);
  assert.match(capabilityStep, /validate_alert_capability_rotation\.mjs[\s\S]*< "\$health_file"/);
  assert.doesNotMatch(capabilityStep, /curl[^\n]*--fail/);
  assert.match(capabilityStep, /validate_alert_capability_rotation\.mjs/);
  assert.doesNotMatch(capabilityStep, /curl[^\n]*\|\| true/);
  assert.match(capabilityStep, /if \[ "\$rotation_mode" = "verified-same-key" \]/);
  assert.match(capabilityStep, /elif \[ "\$rotation_mode" = "repair-previous-binding" \]/);
  assert.match(capabilityStep, /deployed current and previous signing-key bindings are retained unchanged/);
  assert.ok(
    capabilityStep.indexOf("secret put ALERT_CAPABILITY_PREVIOUS_SECRET")
      < capabilityStep.indexOf("secret put ALERT_CAPABILITY_SECRET"),
    "the previous signing key must be staged before the current key is rotated",
  );
  for (const name of [
    "Capture the active Alerts Worker version for rollback",
    "Reconfirm protected main immediately before Alerts Worker mutation",
    "Apply committed D1 migrations",
    "Configure the Alerts capability-signing secrets",
    "Deploy the committed Alerts Worker",
    "Wait for the Alerts Worker health contract",
    "Run bounded Alerts Worker smokes",
  ]) assertDeployGuard(alertsWorkflow, name);
  assertOrdered(alertsWorkflow, [
    "Capture and verify the protected main release base",
    "Classify Alerts Worker inputs since the active deployment",
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

test("Alerts signing-key rotation fails closed except for the exact verified Phase 2 bootstrap", () => {
  const current = "1".repeat(16);
  const previous = "2".repeat(16);
  const phase2Health = {
    service: "available",
    delivery_ready: true,
    api_enabled: true,
    schema_version: 2,
    database_ready: true,
    email_provider: "resend",
    email_provider_selected: true,
    email_provider_configured: true,
    email_template_version: "phase2-lifecycle-20260825",
    outbound_email_enabled: true,
    scheduler_ready: true,
  };
  assert.equal(validateAlertCapabilityRotation(phase2Health, current, previous).mode, "verified-phase2-bootstrap");
  assert.equal(validateAlertCapabilityRotation({
    ...phase2Health,
    capability_key_id: current,
    capability_previous_signing_ready: true,
  }, current, previous).mode, "verified-same-key");
  assert.equal(validateAlertCapabilityRotation({
    ...phase2Health,
    capability_key_id: current,
    capability_previous_signing_ready: false,
  }, current, previous).mode, "repair-previous-binding");
  assert.equal(validateAlertCapabilityRotation({
    ...phase2Health,
    capability_key_id: current,
  }, current, previous).mode, "repair-previous-binding");
  assert.equal(validateAlertCapabilityRotation({ ...phase2Health, capability_key_id: previous }, current, previous).mode, "verified-rotation");

  assert.throws(() => validateAlertCapabilityRotation({ ...phase2Health, capability_key_id: "3".repeat(16) }, current, previous), /must match/);
  assert.throws(() => validateAlertCapabilityRotation({ ...phase2Health, capability_key_id: "" }, current, previous), /Deployed key ID/);
  assert.throws(() => validateAlertCapabilityRotation({ ...phase2Health, schema_version: 3 }, current, previous), /fingerprint is unavailable/);
  assert.throws(() => validateAlertCapabilityRotation({ ...phase2Health, delivery_ready: false }, current, previous), /fingerprint is unavailable/);
  assert.throws(() => validateAlertCapabilityRotation([], current, previous), /JSON object/);
});

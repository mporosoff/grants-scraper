import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  WORKER_DEPLOYMENT_INPUTS,
  changedPathsBetween,
  classifyWorkerDeployment,
  readWorkerVersionMetadata,
  resolveWorkerDeploymentCheckpoint,
} from "../../tools/classify_worker_deployment.mjs";
import { validateAlertCapabilityRotation } from "../../tools/validate_alert_capability_rotation.mjs";

const root = new URL("../../", import.meta.url);
const [awardWorkflow, alertsWorkflow, awardSmoke] = await Promise.all([
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-alerts.yml", root), "utf8"),
  readFile(new URL("tools/smoke_unit_b_award_worker.mjs", root), "utf8"),
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
    "assets/submission-schedule.js",
    "assets/search-v2-config.js",
  ]);
  const result = classifyWorkerDeployment("alerts", [
    "workers/alerts/src/index.js",
    "workers/alerts/migrations/0003_phase2_alert_lifecycle.sql",
    "workers/alerts/wrangler.jsonc",
    ...WORKER_DEPLOYMENT_INPUTS.alerts.files,
  ]);
  assert.equal(result.deployRequired, true);
  assert.equal(result.deploymentInputs.length, 9);
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

const activeVersion = "e91048c4-f180-42d0-a0b5-681f5893f16e";
const otherVersion = "11111111-1111-4111-8111-111111111111";
const deployedSha = "9be83a9341e956226aa52b849e4d877644135814";
const deployment = (overrides = {}) => ({
  id: "560a2f5c-225d-425d-b9f2-ee84024a6ff4", created_on: "2026-09-06T20:03:10.000Z",
  versions: [{ version_id: activeVersion, percentage: 100 }], ...overrides,
});
const metadata = (sha = deployedSha, id = activeVersion) => ({
  id, annotations: { "workers/message": `protected-main:${sha}; protected main deployment` },
});

test("Wrangler upload metadata supplies the exact active Worker checkpoint without a historical bootstrap", () => {
  for (const worker of ["award-api", "alerts"]) {
    assert.deepEqual(resolveWorkerDeploymentCheckpoint(worker, [deployment()], metadata()), {
      baseSha: deployedSha, source: "active-version-message",
      activeDeploymentId: deployment().id, activeVersionId: activeVersion,
    });
  }
});

test("rollback ownership follows the newest deployment and its serving version, not an older upload", () => {
  const rollback = deployment({
    id: "rollback", created_on: "2026-09-06T20:03:10.250Z",
    versions: [{ version_id: otherVersion, percentage: 0 }, { version_id: activeVersion, percentage: 100 }],
    annotations: { "workers/message": `protected-main:${deployedSha.toUpperCase()}; automatic rollback because main advanced` },
  });
  const stale = deployment({ versions: [{ version_id: otherVersion, percentage: 100 }] });
  for (const rows of [[rollback, stale], [stale, rollback]]) {
    assert.equal(resolveWorkerDeploymentCheckpoint("alerts", rows, metadata()).baseSha, deployedSha);
    // Legacy uploads can use the exact rollback deployment message, after
    // verifying that the metadata really belongs to the active version.
    assert.equal(resolveWorkerDeploymentCheckpoint("alerts", rows, { id: activeVersion }).source, "active-deployment-message");
  }
});

test("missing, mismatched and contradictory checkpoints stop classification rather than asserting PR 63 ownership", () => {
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", {}), /JSON array/);
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", []), /No active/);
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", [deployment()]), /does not belong/);
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", [deployment()], metadata(deployedSha, otherVersion)), /does not belong/);
  for (const message of [undefined, "manual upload", "protected-main:short", `protected-main:${"0".repeat(40)}`, `protected-main:${deployedSha}suffix`]) {
    assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", [deployment()], {
      id: activeVersion, annotations: { "workers/message": message },
    }), /no verified Git checkpoint/);
  }
  assert.throws(() => resolveWorkerDeploymentCheckpoint("award-api", [deployment({
    annotations: { "workers/message": `protected-main:${"a".repeat(40)}` },
  })], metadata()), /checkpoints conflict/);
});

test("mixed traffic, malformed latest deployment and ambiguous ordering cannot select a convenient prior checkpoint", () => {
  for (const versions of [
    [], [{ version_id: activeVersion, percentage: 0 }],
    [{ version_id: activeVersion, percentage: 90 }],
    [{ version_id: activeVersion, percentage: 100 }, { version_id: otherVersion, percentage: 1 }],
    [{ version_id: activeVersion, percentage: 60 }, { version_id: otherVersion, percentage: 40 }],
    [{ version_id: activeVersion, percentage: "100" }],
    [{ version_id: activeVersion, percentage: 100 }, { version_id: otherVersion, percentage: -1 }],
    [{ version_id: "--config=other", percentage: 100 }],
  ]) {
    assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", [deployment({
      id: "newer", created_on: "2026-09-06T20:03:11Z", versions,
    }), deployment()], metadata()), /weights|single fully active|exact UUID/);
  }
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", [deployment(), deployment({ id: "tie" })], metadata()), /ambiguous timestamp/);
  assert.throws(() => resolveWorkerDeploymentCheckpoint("alerts", [deployment({ created_on: null })], metadata()), /timestamp/);
});

test("active version metadata is retrieved through pinned bounded Wrangler and only checkpoint fields leave the reader", () => {
  let calls = 0;
  const value = readWorkerVersionMetadata("award-api", activeVersion, { execute: (command, args, options) => {
    calls += 1;
    assert.equal(command, "npx");
    assert.deepEqual(args, ["--yes", "wrangler@4.125.0", "versions", "view", activeVersion,
      "--config", "workers/award-api/wrangler.jsonc", "--json"]);
    assert.equal(options.timeout, 60_000);
    assert.equal(options.maxBuffer, 1024 * 1024);
    assert.deepEqual(options.stdio, ["ignore", "pipe", "pipe"]);
    return JSON.stringify({ ...metadata(), resources: { bindings: [{ value: "private-binding" }] } });
  } });
  assert.equal(calls, 1);
  assert.deepEqual(value, metadata());
  for (const execute of [() => { throw new Error("private output"); }, () => "invalid json", () => "null"]) {
    assert.throws(() => readWorkerVersionMetadata("alerts", activeVersion, { execute }), error => {
      assert.equal(error.message, "Unable to read active Worker version metadata; publication is blocked.");
      return true;
    });
  }
  assert.throws(() => readWorkerVersionMetadata("other", activeVersion), /Unknown Worker/);
  assert.throws(() => readWorkerVersionMetadata("__proto__", activeVersion), /Unknown Worker/);
  assert.throws(() => readWorkerVersionMetadata("alerts", "--config=other"), /exact UUID/);
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

    const checkpoint = resolveWorkerDeploymentCheckpoint("award-api", [deployment()], metadata(workerPush));
    assert.equal(
      classifyWorkerDeployment("award-api", changedPathsBetween(checkpoint.baseSha, uiPush, { cwd: repository })).deployRequired,
      false,
      "a healthy Worker uploaded at the real checkpoint is retained across an unrelated UI push",
    );

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
  const awardSecretStep = workflowStep(awardWorkflow, "Configure the Award abuse-control identity secret");
  assert.match(awardSecretStep, /id: worker-secret/);
  assert.match(awardSecretStep, /secret_file="\$\(mktemp\)"[\s\S]*chmod 600 "\$secret_file"/);
  assert.match(awardSecretStep, /jq -Rs '\{AWARD_RATE_LIMIT_SECRET: \.\}' > "\$secret_file"/);
  assert.doesNotMatch(awardSecretStep, /wrangler[^\n]*secret put/);
  const awardDeployStep = workflowStep(awardWorkflow, "Deploy the committed Award Worker");
  assert.match(awardDeployStep, /secret_file="\$\{\{ steps\.worker-secret\.outputs\.secrets_file \}\}"/);
  assert.match(awardDeployStep, /trap 'rm -f -- "\$secret_file"' EXIT/);
  assert.match(awardDeployStep, /wrangler@4\.125\.0 deploy[\s\S]*--secrets-file "\$secret_file"/);
});

test("Award Worker live smoke exercises investigator facets from the direct page aggregate", () => {
  assert.match(awardSmoke, /const investigator = firstPage\.aggregate\.investigators\[0\]/);
  assert.match(awardSmoke, /facetPage\.aggregate\.project_count > firstPage\.aggregate\.project_count/);
  assert.match(awardSmoke, /investigator\?\.identity_key && !facetVerified/);
  assert.doesNotMatch(awardSmoke, /snapshot\.base_aggregate/);
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
    "Verify Pages serves the committed alert surfaces and catalog",
    "Reconfirm protected main immediately before Alerts Worker mutation",
    "Apply committed D1 migrations",
    "Deploy the committed Alerts Worker",
    "Wait for the Alerts Worker health contract",
    "Run bounded Alerts Worker smokes",
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

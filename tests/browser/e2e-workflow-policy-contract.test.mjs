import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [automaticWorkflow, manualWorkflow, repositoryPolicy] = await Promise.all([
  readFile(new URL(".github/workflows/tests.yml", root), "utf8"),
  readFile(new URL(".github/workflows/e2e-manual.yml", root), "utf8"),
  readFile(new URL("AGENTS.md", root), "utf8"),
]);

test("Playwright is manual-only while pull requests retain fast Python and browser checks", () => {
  assert.match(automaticWorkflow, /pull_request:/);
  assert.match(automaticWorkflow, /push:[\s\S]*branches:[\s\S]*- main/);
  assert.match(automaticWorkflow, /^  python:/m);
  assert.match(automaticWorkflow, /^  browser:/m);
  assert.doesNotMatch(automaticWorkflow, /^  e2e:/m);
  assert.doesNotMatch(automaticWorkflow, /playwright|test:e2e/i);

  assert.match(manualWorkflow, /on:\s*\n  workflow_dispatch:/);
  assert.doesNotMatch(manualWorkflow, /pull_request:|push:/);
  assert.match(manualWorkflow, /^  e2e:/m);
  assert.match(manualWorkflow, /pnpm exec playwright install --with-deps chromium/);
  assert.match(manualWorkflow, /run: pnpm test:e2e/);

  assert.match(repositoryPolicy, /Full manual E2E\/Playwright may be started only with explicit user authorization/);
  assert.match(repositoryPolicy, /bounded monitoring, reading status\/logs\/results\/artifacts/);
  assert.doesNotMatch(repositoryPolicy, /Do not wait for or poll E2E jobs/);
  assert.match(repositoryPolicy, /required Python and Node\/browser contracts/);
  assert.match(repositoryPolicy, /one integrated review, one consolidated remediation batch if needed, and one exact-head verification review/);
});

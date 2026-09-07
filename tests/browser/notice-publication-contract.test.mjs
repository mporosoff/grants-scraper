import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const workflow = name => readFileSync(new URL(`../../.github/workflows/${name}.yml`, import.meta.url), "utf8");

test("Pages verifies the interpreted package before upload or deployment", () => {
  const text = workflow("pages");
  const gate = text.indexOf("run: python -m tools.verify_notice_publication");
  assert.ok(gate > 0);
  assert.ok(gate < text.indexOf("actions/upload-pages-artifact@"));
  assert.ok(gate < text.indexOf("actions/deploy-pages@"));
});

test("both refresh modes and committed search verify before changing Worker state", () => {
  for (const text of [workflow("deploy-search-package"), ...workflow("refresh-opportunities").split(/^  refresh:/m)]) {
    const mutation = text.indexOf("--config workers/search-voyage-proxy/wrangler.jsonc");
    const gate = text.indexOf("run: python -m tools.verify_notice_publication");
    assert.ok(gate >= 0 && gate < mutation);
  }
});

test("a detected parser migration enters the existing manual checkpoint even on a push", () => {
  const text = workflow("refresh-opportunities");
  const detect = text.indexOf("python -m tools.verify_notice_publication --detect");
  assert.ok(detect > 0 && detect < text.indexOf("- name: Build and validate complete public opportunity catalog"));
  assert.match(text, /MANUAL_RELEASE_VALIDATION:.*inputs\.manual_release_validation.*\|\| steps\.notice-checkpoint\.outputs\.required == 'true'/);
  assert.ok(text.includes('python -m tools.wait_refresh_review "$pr_url" "$head_sha" "$built_from_sha"'));
});

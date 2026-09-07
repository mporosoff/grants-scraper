import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const workflow = name => readFileSync(new URL(`../../.github/workflows/${name}.yml`, import.meta.url), "utf8");

test("Alerts verifies both its interpreted projection and served catalog before any production mutation", () => {
  const text = workflow("deploy-alerts");
  const gate = text.indexOf("run: python -m tools.verify_notice_publication");
  const served = text.indexOf("id: pages-verify");
  assert.ok(gate > text.indexOf("python -m pip install -r requirements.txt"));
  assert.ok(served > gate);
  for (const marker of ["d1 migrations apply", "Configure the Alerts capability-signing secrets", "name: Deploy the committed Alerts Worker"]) {
    assert.ok(text.indexOf(marker) > served, marker);
  }
  const verification = text.slice(served, text.indexOf("Reconfirm protected main immediately before Alerts Worker mutation"));
  assert.match(verification, /cmp -s data\/opportunities\.js/);
  assert.match(verification, /SECONDS \+ 180/);
  assert.match(verification, /--max-time 10 --max-filesize 67108864/);
  assert.ok(text.includes('"data/opportunities.js"'));
});

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

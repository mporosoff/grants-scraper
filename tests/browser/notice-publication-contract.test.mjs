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

test("Pages and Worker publication require a persisted candidate validation receipt", () => {
  const text = workflow("refresh-opportunities");
  const validator = readFileSync(new URL('../../tools/validate_release_candidate.py', import.meta.url), 'utf8');
  assert.match(validator, /'notice-projection': \['python', '-m', 'tools.verify_notice_publication'/);
  assert.ok(text.indexOf('tools.validate_release_candidate') < text.indexOf('Deploy changed Worker inputs'));
  assert.match(text, /needs.validate.result == 'success'/);
  assert.match(text, /tools.release_candidate receipt/);
  assert.match(workflow('pages'), /workflow_call:/);
  assert.doesNotMatch(workflow('pages'), /^  (?:push|workflow_dispatch):/m);
});

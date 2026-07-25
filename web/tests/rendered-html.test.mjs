import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("builds the grant matcher product shell", async () => {
  const [layout, page, client, css] = await Promise.all([
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/GrantMatcherApp.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
  ]);

  assert.match(layout, /title:\s*"UR Grant Matcher"/);
  assert.match(page, /<GrantMatcherApp \/>/);
  assert.match(client, /Funding worth your attention\./);
  assert.match(client, /Research profile/);
  assert.match(client, /Opportunity feed/);
  assert.match(client, /Match explorer/);
  assert.match(client, /Faculty-controlled profiles/);
  assert.match(client, /formatFunding/);
  assert.match(client, /Grant duration/);
  assert.match(client, /Expected awards/);
  assert.doesNotMatch(client, /Import grants\.json|type="file"/);
  assert.match(css, /\.match-card/);
  assert.match(css, /\.grant-facts/);
  assert.match(css, /@media \(max-width: 640px\)/);
  assert.doesNotMatch(client, /OpenAI API key|Anthropic API key|localStorage/i);
  await access(new URL("dist/server/index.js", root));
});

test("uses persistent application storage and removes starter dependencies", async () => {
  const [hosting, client, packageJson, schema, migration, previewFiles] = await Promise.all([
    readFile(new URL(".openai/hosting.json", root), "utf8"),
    readFile(new URL("app/GrantMatcherApp.tsx", root), "utf8"),
    readFile(new URL("package.json", root), "utf8"),
    readFile(new URL("db/schema.ts", root), "utf8"),
    readFile(new URL("drizzle/0001_blue_ezekiel.sql", root), "utf8"),
    readdir(new URL("app/_sites-preview", root)).catch(() => []),
  ]);

  assert.match(hosting, /"d1":\s*"DB"/);
  assert.match(hosting, /"project_id":\s*"appgprj_/);
  assert.match(client, /\/api\/profile/);
  assert.match(client, /\/api\/opportunities\/refresh/);
  assert.match(client, /\/api\/matches/);
  assert.match(schema, /totalProgramFunding/);
  assert.match(schema, /expectedAwards/);
  assert.match(schema, /preliminaryStageType/);
  assert.match(migration, /ADD `duration`/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.deepEqual(previewFiles, []);
});

test("uses one selected AI provider and one key in the standalone explorer", async () => {
  const prototype = await readFile(
    new URL("../match_explorer.html", root),
    "utf8",
  );
  const script = prototype.match(/<script>([\s\S]*?)<\/script>/)?.[1];

  assert.match(prototype, /id="k-provider"/);
  assert.match(prototype, /id="k-key"/);
  assert.match(prototype, /gpt-5\.6-sol/);
  assert.match(prototype, /claude-sonnet-5/);
  assert.match(prototype, /async function deepRank/);
  assert.match(prototype, /async function anthropicShortlist/);
  assert.match(prototype, /id="research-profile"/);
  assert.match(prototype, /id="btn-save-search"/);
  assert.match(prototype, /id="btn-new-search"/);
  assert.match(prototype, /id="saved-searches"/);
  assert.match(prototype, /Export results\.csv/);
  assert.match(prototype, /Due date\(s\)/);
  assert.match(prototype, /Grant duration/);
  assert.match(prototype, /Expected awards/);
  assert.doesNotMatch(
    prototype,
    /id="sel-faculty"|id="load-faculty"|id="load-grants"|type="file"/,
  );
  assert.doesNotMatch(prototype, /id="k-openai"|id="k-anthropic"/);
  assert.ok(script);
  assert.doesNotThrow(() => new Function(script));
});

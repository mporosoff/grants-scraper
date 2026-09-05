import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { PUBLIC_PAGES, SHELL_ASSETS, syncPublicShellAssets } from "../../tools/sync_public_shell_assets.mjs";
import { openAwardAi, closeAwardAi, showAwardView, selectAwardFacet, openAwardAdvanced } from "../e2e/public-tool-workflow.mjs";

test("All public shell references match served bytes before release", async () => {
  assert.deepEqual(await syncPublicShellAssets(), [], "Run the maintained shell asset sync before rebuilding the search release package");
});

test("Shared asset updates cover every public page, preserve unrelated identities, and are idempotent", async () => {
  const dir = await mkdtemp(join(tmpdir(), "public-shell-assets-"));
  const root = pathToFileURL(dir + sep);
  try {
    await mkdir(new URL("assets/", root));
    for (const asset of SHELL_ASSETS) await writeFile(new URL(asset, root), `${asset}\n`);
    const unrelated = '<script src="data/faculty_matches.js?v=exact-binding"></script><script src="assets/app.js?v=existing"></script>';
    const source = '<script src="./assets/site-shell.js?v=old"></script><link href=\'assets/site-nav.css\'>' + unrelated;
    for (const page of PUBLIC_PAGES) await writeFile(new URL(page, root), source);
    assert.equal((await syncPublicShellAssets({ root })).length, PUBLIC_PAGES.length * 2);
    assert.equal(await readFile(new URL(PUBLIC_PAGES[0], root), "utf8"), source, "Check is read-only");
    await syncPublicShellAssets({ root, write: true });
    for (const page of PUBLIC_PAGES) {
      const html = await readFile(new URL(page, root), "utf8");
      assert.ok(html.endsWith(unrelated));
      assert.ok(html.includes(createHash("sha256").update("assets/site-shell.js\n").digest("hex")));
    }
    assert.deepEqual(await syncPublicShellAssets({ root, write: true }), []);
    await writeFile(new URL("assets/site-shell.js", root), "next release\n");
    assert.equal((await syncPublicShellAssets({ root })).length, PUBLIC_PAGES.length);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test("Dormant award workflows use visible shell actions and preserve modal boundaries without browser execution", async () => {
  let open = false, advanced = false;
  const actions = [];
  const page = { locator(selector) {
    return {
      async isVisible() { return selector === "#awards-ai" ? open : advanced; },
      async click() {
        actions.push(selector);
        if (selector === "#open-awards-ai") open = true;
        else if (selector === "Close Ask AI") open = false;
        else { assert.equal(open, false, "Underlying page cannot be operated through a modal"); advanced = true; }
      },
      async waitFor({ state }) { if (selector === "#awards-ai") assert.equal(open, state === "visible"); },
      getByRole(role, { name }) { assert.equal(role, "button"); return page.locator(name); },
      locator(child) { return page.locator(child); },
      async selectOption(option) { assert.equal(open, false); actions.push([selector, option]); },
    };
  } };
  await openAwardAi(page);
  await openAwardAi(page);
  assert.deepEqual(actions, ["#open-awards-ai"], "Repeated setup never toggles an open dialog closed");
  await selectAwardFacet(page, "programs", "program-id");
  assert.deepEqual(actions.slice(1), ["Close Ask AI", '[data-award-view="programs"]', ["#ii-programs", "program-id"]]);
  await openAwardAi(page);
  await showAwardView(page, "projects");
  await openAwardAi(page);
  await openAwardAdvanced(page);
  await closeAwardAi(page);
  assert.equal(open, false);
  assert.equal(advanced, true);
  const e2e = new URL("../e2e/", import.meta.url);
  for (const name of await readdir(e2e)) if (name.endsWith(".mjs")) {
    const source = await readFile(new URL(name, e2e), "utf8");
    assert.doesNotMatch(source, /locator\(["']#ii-ask["']\)\.evaluate/, name);
  }
});

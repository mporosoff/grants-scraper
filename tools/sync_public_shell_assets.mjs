#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

export const PUBLIC_PAGES = Object.freeze([
  "match_explorer.html", "team_match.html", "funded_awards.html", "faculty_interests.html",
]);
// Only presentation assets owned by the public shell. Catalog, team, registry,
// and search-generation identities retain their existing generators.
export const SHELL_ASSETS = Object.freeze([
  "site-shell.js", "site-shell.css", "site-nav.js", "site-nav.css",
  "public-tools.js", "public-tools.css", "team-match.css",
  "institutional-intelligence-snapshots.js",
].map(name => `assets/${name}`));

export async function syncPublicShellAssets({ root = new URL("../", import.meta.url), write = false } = {}) {
  const hashes = new Map(await Promise.all(SHELL_ASSETS.map(async asset => [
    asset, createHash("sha256").update(await readFile(new URL(asset, root))).digest("hex"),
  ])));
  const changes = [];
  const updates = [];
  for (const page of PUBLIC_PAGES) {
    const source = await readFile(new URL(page, root), "utf8");
    let references = 0;
    const updated = source.replace(/\b(src|href)=(['"])([^'"]+)\2/g, (original, attr, quote, reference) => {
      const path = reference.split(/[?#]/, 1)[0];
      const asset = path.replace(/^\.\//, "");
      if (!hashes.has(asset)) return original;
      references += 1;
      const expected = `${path}?v=${hashes.get(asset)}`;
      if (reference === expected) return original;
      changes.push({ page, asset, reference, expected });
      return `${attr}=${quote}${expected}${quote}`;
    });
    if (!references) throw new Error(`${page}: no public shell assets found; check the shared page integration.`);
    if (updated !== source) updates.push([page, updated]);
  }
  // Read and validate the complete family before writing any page.
  if (write) for (const [page, source] of updates) await writeFile(new URL(page, root), source);
  return changes;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  if (args.some(arg => !["--check", "--write"].includes(arg)) || args.length > 1) {
    throw new Error("Usage: node tools/sync_public_shell_assets.mjs [--check|--write]");
  }
  const write = args.includes("--write");
  const changes = await syncPublicShellAssets({ write });
  if (changes.length && !write) {
    console.error(changes.map(({ page, asset }) => `${page}: stale ${asset}`).join("\n"));
    console.error("Run node tools/sync_public_shell_assets.mjs --write, then regenerate the search release package.");
    process.exitCode = 1;
  } else console.log(`${write ? "Updated" : "Verified"} public shell asset versions (${changes.length} changes).`);
}

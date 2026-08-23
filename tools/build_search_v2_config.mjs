#!/usr/bin/env node
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";

const ROOT = new URL("../", import.meta.url);
const SOURCE = new URL("config/search_v2.json", ROOT);
const TARGET = new URL("assets/search-v2-config.js", ROOT);

function render(value) {
  const body = JSON.stringify(value, null, 2)
    .split("\n")
    .map(line => `  ${line}`)
    .join("\n");
  return `(() => {\n  "use strict";\n  globalThis.FUNDING_SEARCH_V2_CONFIG = Object.freeze(${body.trimStart()});\n})();\n`;
}

const configuration = JSON.parse(await readFile(SOURCE, "utf8"));
const expected = render(configuration);
if (process.argv.includes("--check")) {
  assert.equal(await readFile(TARGET, "utf8"), expected, "search-v2 config asset is stale");
  process.stdout.write("search-v2 config asset is current\n");
} else {
  await writeFile(TARGET, expected, "utf8");
  process.stdout.write("wrote assets/search-v2-config.js\n");
}

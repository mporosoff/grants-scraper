import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../../assets/credentials.js", import.meta.url),
  "utf8",
);

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

function loadModule(localStorage = memoryStorage()) {
  const context = vm.createContext({ localStorage });
  vm.runInContext(source, context);
  return context.FUNDING_CREDENTIALS;
}

test("saves provider keys only after an explicit save call", () => {
  const storage = memoryStorage();
  const credentials = loadModule(storage);

  assert.equal(credentials.loadKey("openai", storage), "");
  assert.deepEqual(
    { ...credentials.saveKey("openai", "  sk-openai-test  ", storage) },
    { saved: true, provider: "openai" },
  );
  assert.equal(credentials.loadKey("openai", storage), "sk-openai-test");
  assert.equal(credentials.loadKey("anthropic", storage), "");
});

test("keeps OpenAI and Anthropic keys separate and clears one at a time", () => {
  const storage = memoryStorage();
  const credentials = loadModule(storage);

  credentials.saveKey("openai", "sk-openai-test", storage);
  credentials.saveKey("anthropic", "sk-ant-test", storage);
  assert.equal(credentials.loadKey("openai", storage), "sk-openai-test");
  assert.equal(credentials.loadKey("anthropic", storage), "sk-ant-test");

  assert.equal(credentials.clearKey("openai", storage), true);
  assert.equal(credentials.loadKey("openai", storage), "");
  assert.equal(credentials.loadKey("anthropic", storage), "sk-ant-test");
});

test("fails closed for malformed storage and bounds saved values", () => {
  const storage = memoryStorage({
    "funding-finder.credentials.v1": "{not-json",
  });
  const credentials = loadModule(storage);

  assert.equal(credentials.loadKey("openai", storage), "");
  credentials.saveKey("openai", `sk-${"x".repeat(700)}`, storage);
  assert.equal(credentials.loadKey("openai", storage).length, 500);
});

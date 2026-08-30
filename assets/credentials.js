(function attachFundingCredentials(global) {
  "use strict";

  const CREDENTIAL_STORAGE_KEY = "funding-finder.credentials.v1";
  const PROVIDERS = new Set(["openai", "anthropic"]);
  const MAX_KEY_LENGTH = 500;

  function storageOrDefault(storage) {
    if (storage) return storage;
    try {
      return global.localStorage;
    } catch {
      return null;
    }
  }

  function normalizeProvider(provider) {
    const value = String(provider || "").toLowerCase();
    return PROVIDERS.has(value) ? value : "openai";
  }

  function normalizeKey(key) {
    return String(key || "").trim().slice(0, MAX_KEY_LENGTH);
  }

  function readRecord(storage) {
    const target = storageOrDefault(storage);
    if (!target) return { keys: {} };
    try {
      const parsed = JSON.parse(target.getItem(CREDENTIAL_STORAGE_KEY) || "{}");
      const keys = {};
      for (const provider of PROVIDERS) {
        const key = normalizeKey(parsed?.keys?.[provider]);
        if (key) keys[provider] = key;
      }
      const preferredProvider = normalizeProvider(parsed?.preferred_provider);
      return {
        keys,
        preferred_provider: keys[preferredProvider] ? preferredProvider : "",
      };
    } catch {
      return { keys: {}, preferred_provider: "" };
    }
  }

  function loadKey(provider, storage) {
    return readRecord(storage).keys[normalizeProvider(provider)] || "";
  }

  function saveKey(provider, key, storage) {
    const target = storageOrDefault(storage);
    const normalizedProvider = normalizeProvider(provider);
    const normalizedKey = normalizeKey(key);
    if (!target || !normalizedKey) {
      return { saved: false, provider: normalizedProvider };
    }
    const record = readRecord(target);
    record.keys[normalizedProvider] = normalizedKey;
    record.preferred_provider = normalizedProvider;
    try {
      target.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify(record));
      return { saved: true, provider: normalizedProvider };
    } catch {
      return { saved: false, provider: normalizedProvider };
    }
  }

  function clearKey(provider, storage) {
    const target = storageOrDefault(storage);
    const normalizedProvider = normalizeProvider(provider);
    if (!target) return false;
    const record = readRecord(target);
    delete record.keys[normalizedProvider];
    if (record.preferred_provider === normalizedProvider) {
      record.preferred_provider = Object.keys(record.keys)[0] || "";
    }
    try {
      if (Object.keys(record.keys).length) {
        target.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify(record));
      } else {
        target.removeItem(CREDENTIAL_STORAGE_KEY);
      }
      return true;
    } catch {
      return false;
    }
  }

  function resolveProvider(preferred, storage) {
    const requestedProvider = String(preferred || "").toLowerCase();
    const normalizedPreferred = normalizeProvider(requestedProvider);
    const record = readRecord(storage);
    if (PROVIDERS.has(requestedProvider) && record.keys[normalizedPreferred]) {
      return normalizedPreferred;
    }
    if (record.preferred_provider && record.keys[record.preferred_provider]) {
      return record.preferred_provider;
    }
    return [...PROVIDERS].find(provider => Boolean(record.keys[provider]))
      || normalizedPreferred;
  }

  global.FUNDING_CREDENTIALS = Object.freeze({
    CREDENTIAL_STORAGE_KEY,
    loadKey,
    saveKey,
    clearKey,
    resolveProvider,
  });
})(globalThis);

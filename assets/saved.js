/*
 * Device-local "Saved / Favorites" store for funding opportunities.
 *
 * Lets a user star an opportunity and return to it later without re-running a
 * search. Stored only in this browser (localStorage key
 * "funding-finder.saved.v1"); nothing is sent anywhere, matching the app's
 * device-local privacy model. A compact snapshot (id, title, agency, source,
 * deadline, official URL, pursuit status, and note) is kept so saved items
 * render without the catalog. Pursuit state and notes never leave this device.
 */
(() => {
  "use strict";

  const STORAGE_KEY = "funding-finder.saved.v1";
  const MAX_SAVED = 500;
  const MAX_NOTE_LENGTH = 2_000;
  const PURSUIT_STATUSES = Object.freeze([
    "saved", "considering", "pursuing", "submitted", "passed",
  ]);

  function storageOrNull(storage) {
    try {
      return storage || globalThis.localStorage || null;
    } catch {
      return null;
    }
  }

  function cleanString(value, maximum = 500) {
    return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function idOf(item) {
    // Must match the app's recordId(): opportunity_id first, then number.
    return cleanString(item.opportunity_id, 200) || cleanString(item.opportunity_number, 200);
  }

  function sanitizeItem(record) {
    if (!record || typeof record !== "object") return null;
    const title = cleanString(record.title, 500);
    const number = cleanString(record.opportunity_number, 200);
    const id = cleanString(record.opportunity_id, 200);
    if (!title || (!number && !id)) return null;
    const pursuitStatus = cleanString(record.pursuit_status, 24).toLowerCase();
    return {
      opportunity_id: id,
      opportunity_number: number,
      title,
      agency: cleanString(record.agency, 300),
      source: cleanString(record.source, 120),
      source_type: cleanString(record.source_type, 60),
      close_date: cleanString(record.close_date, 10),
      url: cleanString(
        record.url || record.detail_page || record.funding_opportunity_url
          || record.primary_document_url,
        1000,
      ),
      saved_at: cleanString(record.saved_at, 40) || new Date().toISOString(),
      pursuit_status: PURSUIT_STATUSES.includes(pursuitStatus)
        ? pursuitStatus
        : "saved",
      note: String(record.note ?? "").replace(/\r\n?/g, "\n").trim().slice(0, MAX_NOTE_LENGTH),
    };
  }

  function load(storage) {
    const target = storageOrNull(storage);
    if (!target) return [];
    let raw;
    try {
      raw = target.getItem(STORAGE_KEY);
    } catch {
      return [];
    }
    if (!raw) return [];
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return [];
    }
    if (!Array.isArray(parsed)) return [];
    const items = [];
    const seen = new Set();
    for (const entry of parsed) {
      const item = sanitizeItem(entry);
      if (!item) continue;
      const key = idOf(item);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      items.push(item);
      if (items.length >= MAX_SAVED) break;
    }
    return items;
  }

  function persist(items, storage) {
    const target = storageOrNull(storage);
    if (!target) return false;
    try {
      target.setItem(STORAGE_KEY, JSON.stringify(items));
      return true;
    } catch {
      return false;
    }
  }

  function isSaved(items, id) {
    return (items || []).some(item => idOf(item) === id);
  }

  function toggle(record, storage) {
    const items = load(storage);
    const item = sanitizeItem(record);
    if (!item) return { saved: false, items };
    const key = idOf(item);
    const index = items.findIndex(existing => idOf(existing) === key);
    let saved;
    if (index >= 0) {
      items.splice(index, 1);
      saved = false;
    } else {
      items.unshift(item);
      saved = true;
    }
    persist(items, storage);
    return { saved, items };
  }

  function remove(id, storage) {
    const items = load(storage).filter(item => idOf(item) !== id);
    persist(items, storage);
    return items;
  }

  function updatePursuit(id, changes, storage) {
    const items = load(storage);
    const item = items.find(existing => idOf(existing) === cleanString(id, 200));
    if (!item) return items;
    if (Object.prototype.hasOwnProperty.call(changes || {}, "pursuit_status")) {
      const status = cleanString(changes.pursuit_status, 24).toLowerCase();
      if (PURSUIT_STATUSES.includes(status)) item.pursuit_status = status;
    }
    if (Object.prototype.hasOwnProperty.call(changes || {}, "note")) {
      item.note = String(changes.note ?? "")
        .replace(/\r\n?/g, "\n")
        .trim()
        .slice(0, MAX_NOTE_LENGTH);
    }
    persist(items, storage);
    return items;
  }

  function clear(storage) {
    const target = storageOrNull(storage);
    if (target) {
      try {
        target.removeItem(STORAGE_KEY);
      } catch {
        /* ignore */
      }
    }
    return [];
  }

  globalThis.FUNDING_SAVED = Object.freeze({
    STORAGE_KEY, MAX_SAVED, MAX_NOTE_LENGTH, PURSUIT_STATUSES,
    idOf, sanitizeItem, load, isSaved, toggle, remove, updatePursuit, clear,
  });
})();

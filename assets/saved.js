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
      has_preliminary_stage: record.has_preliminary_stage === true,
      preliminary_required: typeof record.preliminary_required === "boolean" ? record.preliminary_required : null,
      ...Object.fromEntries(["deadlines", "submission_requirements"].filter(key => Array.isArray(record[key])).map(key => [key,
        record[key].slice(0, 50).filter(event => event && typeof event === "object").map(event => ({
        kind: cleanString(event.kind, 40), date: cleanString(event.date, 10) || null,
        window_start: cleanString(event.window_start, 10) || null,
        time: cleanString(event.time, 40) || null, timezone: cleanString(event.timezone, 80) || null,
        application_class: cleanString(event.application_class, 40) || null,
        cycle: cleanString(event.cycle, 60) || null, track: cleanString(event.track, 500) || null,
        required: typeof event.required === "boolean" ? event.required : null,
        invitation_required: event.invitation_required === true,
        prerequisite: cleanString(event.prerequisite, 60) || null,
        rolling: event.rolling === true,
        date_qualifier: ["recommended", "anticipated"].includes(event.date_qualifier) ? event.date_qualifier : null,
        estimated: event.estimated === true,
      }))])),
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

  function isSaved(items, id, resolveId = value => value) {
    return (items || []).some(item => resolveId(idOf(item)) === resolveId(id));
  }

  function mutationResult(ok, items, details = {}) {
    return {
      ok,
      persisted: ok,
      items,
      changed: Boolean(details.changed),
      ...details,
    };
  }

  function toggle(record, storage, resolveId = value => value) {
    const persistedItems = load(storage);
    const item = sanitizeItem(record);
    if (!item) return mutationResult(false, persistedItems, { saved: false, error: "invalid_item" });
    const key = resolveId(idOf(item));
    let items = persistedItems.map(existing => ({ ...existing }));
    const existingSaved = isSaved(items, key, resolveId);
    let saved;
    if (existingSaved) {
      // Resolve membership without rewriting durable pursuit notes/status.
      // An explicit unsave removes every snapshot of this one canonical call.
      items = items.filter(existing => resolveId(idOf(existing)) !== key);
      saved = false;
    } else {
      items.unshift(item);
      saved = true;
    }
    if (!persist(items, storage)) {
      return mutationResult(false, persistedItems, {
        saved: isSaved(persistedItems, key, resolveId), error: "storage_rejected",
      });
    }
    return mutationResult(true, items, { saved, changed: true });
  }

  function remove(id, storage) {
    const persistedItems = load(storage);
    const items = persistedItems.filter(item => idOf(item) !== cleanString(id, 200));
    if (items.length === persistedItems.length) return mutationResult(true, persistedItems);
    if (!persist(items, storage)) {
      return mutationResult(false, persistedItems, { error: "storage_rejected" });
    }
    return mutationResult(true, items, { changed: true });
  }

  function updatePursuit(id, changes, storage) {
    const persistedItems = load(storage);
    const items = persistedItems.map(existing => ({ ...existing }));
    const item = items.find(existing => idOf(existing) === cleanString(id, 200));
    if (!item) return mutationResult(true, persistedItems);
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
    if (!persist(items, storage)) {
      return mutationResult(false, persistedItems, { error: "storage_rejected" });
    }
    return mutationResult(true, items, { changed: true });
  }

  function clear(storage) {
    const target = storageOrNull(storage);
    const persistedItems = load(storage);
    if (!target) return mutationResult(false, persistedItems, { error: "storage_rejected" });
    try {
      target.removeItem(STORAGE_KEY);
      return mutationResult(true, [], { changed: persistedItems.length > 0 });
    } catch {
      return mutationResult(false, persistedItems, { error: "storage_rejected" });
    }
  }

  globalThis.FUNDING_SAVED = Object.freeze({
    STORAGE_KEY, MAX_SAVED, MAX_NOTE_LENGTH, PURSUIT_STATUSES,
    idOf, sanitizeItem, load, isSaved, toggle, remove, updatePursuit, clear,
  });
})();

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import {
  mockHybrid,
  openFundingFinderShell,
  waitForHybridSettled,
  watchRuntimeErrors,
} from "./helpers.mjs";

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function installConnection(page, value) {
  await page.addInitScript(connection => {
    Object.defineProperty(Navigator.prototype, "connection", {
      configurable: true,
      get: () => connection,
    });
  }, value);
}

async function installScriptClock(page) {
  await page.addInitScript(() => {
    let nextTimer = 0;
    let now = 0;
    const timers = new Map();
    globalThis.FUNDING_FINDER_CATALOG_TIMEOUT_MS = 120_000;
    globalThis.FUNDING_FINDER_SIDECAR_TIMEOUT_MS = 15_000;
    globalThis.FUNDING_FINDER_SCRIPT_CLOCK = {
      setTimeout(callback, delay) {
        const timer = ++nextTimer;
        timers.set(timer, { callback, delay, due: now + delay });
        return timer;
      },
      clearTimeout(timer) {
        timers.delete(timer);
      },
    };
    globalThis.__FUNDING_FINDER_SCRIPT_CLOCK = Object.freeze({
      pending: () => timers.size,
      delays: () => [...timers.values()].map(item => item.delay).sort((a, b) => a - b),
      advance: milliseconds => {
        now += milliseconds;
        const due = [...timers.entries()]
          .filter(([, item]) => item.due <= now)
          .sort((left, right) => left[1].due - right[1].due);
        due.forEach(([timer]) => timers.delete(timer));
        due.forEach(([, item]) => item.callback());
        return due.length;
      },
      runAll: () => {
        const callbacks = [...timers.values()].map(item => item.callback);
        timers.clear();
        callbacks.forEach(callback => callback());
        return callbacks.length;
      },
    });
  });
}

async function executeStaleCatalogAttempt(page, label) {
  await page.evaluate(currentLabel => new Promise((resolve, reject) => {
    const staleAttempt = globalThis.__TIMED_OUT_CATALOG_SCRIPT
      ?.dataset?.fundingCatalogAttempt;
    if (!staleAttempt) {
      reject(new Error("The timed-out catalog attempt ID is unavailable."));
      return;
    }
    const script = document.createElement("script");
    script.async = true;
    script.src = `./__stale-catalog-execution.js?case=${encodeURIComponent(currentLabel)}`;
    script.dataset.fundingCatalogAttempt = staleAttempt;
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", () => reject(new Error("Stale fixture failed.")), {
      once: true,
    });
    document.head.append(script);
  }), label);
}

async function seriousAxeViolations(page) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  return result.violations.filter(item => ["serious", "critical"].includes(item.impact));
}

test("delayed catalog cannot block the interactive shell, Help, navigation, or mobile accessibility", async ({ page }) => {
  const gate = deferred();
  let catalogRequests = 0;
  let prefetchFulfilled = false;
  await page.route("**/data/opportunities.js*", async route => {
    catalogRequests += 1;
    await gate.promise;
    await route.fulfill({
      status: 200,
      contentType: "text/javascript",
      body: "globalThis.__PREFETCH_ONLY_FIXTURE=true;",
    });
    prefetchFulfilled = true;
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await openFundingFinderShell(page);
  await expect.poll(() => catalogRequests).toBe(1);
  await page.locator("#query").fill("carbon capture while the catalog is delayed");
  await page.getByRole("button", { name: "Help" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Help" })).toBeFocused();
  await page.locator("[data-nav-toggle]").click();
  await expect(page.getByRole("link", { name: "Team Match" })).toHaveAttribute("href", "./team_match.html");
  expect(await page.evaluate(() => ({
    catalog: globalThis.GRANT_CATALOG,
    prefetchedCodeExecuted: globalThis.__PREFETCH_ONLY_FIXTURE,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
  }))).toMatchObject({
    catalog: undefined,
    prefetchedCodeExecuted: undefined,
    snapshot: { state: "prefetching", executions: 0, initializations: 0, prefetches: 1 },
  });
  expect(await seriousAxeViolations(page)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await seriousAxeViolations(page)).toEqual([]);
  gate.resolve();
  await expect.poll(() => prefetchFulfilled).toBe(true);
  expect(await page.evaluate(() => ({
    catalog: globalThis.GRANT_CATALOG,
    prefetchedCodeExecuted: globalThis.__PREFETCH_ONLY_FIXTURE,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
  }))).toMatchObject({
    catalog: undefined,
    prefetchedCodeExecuted: undefined,
    snapshot: { executions: 0, initializations: 0, prefetches: 1 },
  });
  await page.getByRole("link", { name: "Team Match" }).click();
  await expect(page).toHaveURL(/team_match\.html/);
});

test("Save-Data and slow connections deterministically skip background catalog prefetch", async ({ browser }) => {
  for (const connection of [
    { saveData: true, effectiveType: "4g" },
    { saveData: false, effectiveType: "slow-2g" },
    { saveData: false, effectiveType: "2g" },
  ]) {
    const page = await browser.newPage();
    let requests = 0;
    await installConnection(page, connection);
    await page.route("**/data/opportunities.js*", route => {
      requests += 1;
      return route.abort();
    });
    await openFundingFinderShell(page);
    await page.evaluate(() => {
      globalThis.FUNDING_CATALOG_LOADER.schedulePrefetch();
      return new Promise(resolve => setTimeout(resolve, 800));
    });
    expect(requests).toBe(0);
    await expect(page.locator('link[data-funding-catalog-prefetch="true"]')).toHaveCount(0);
    expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot().prefetches)).toBe(0);
    await page.close();
  }
});

test("a hidden document postpones prefetch and resumes it when visible without execution", async ({ page }) => {
  await page.addInitScript(() => {
    globalThis.__TEST_DOCUMENT_HIDDEN = true;
    Object.defineProperty(Document.prototype, "hidden", {
      configurable: true,
      get: () => globalThis.__TEST_DOCUMENT_HIDDEN,
    });
  });
  let requests = 0;
  await page.route("**/data/opportunities.js*", async route => {
    requests += 1;
    await route.fulfill({
      status: 200,
      contentType: "text/javascript",
      body: "globalThis.__VISIBILITY_PREFETCH_FIXTURE=true;",
    });
  });
  await openFundingFinderShell(page);
  await page.waitForTimeout(800);
  expect(requests).toBe(0);
  await page.evaluate(() => {
    globalThis.__TEST_DOCUMENT_HIDDEN = false;
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => requests).toBe(1);
  expect(await page.evaluate(() => ({
    executed: globalThis.__VISIBILITY_PREFETCH_FIXTURE,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
  }))).toMatchObject({
    executed: undefined,
    snapshot: { prefetches: 1, executions: 0, initializations: 0 },
  });
});

test("two rapid searches share one catalog execution and initialization, then preserve normal ordered results", async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  const calls = mockHybrid(page);
  await page.route("https://funding-usage.urochestercheme.workers.dev/**", route => (
    route.fulfill({ status: 204 })
  ));
  await page.route("https://static.cloudflareinsights.com/**", route => (
    route.fulfill({ status: 200, contentType: "text/javascript", body: "" })
  ));
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  const gate = deferred();
  let scriptRequests = 0;
  await page.route("**/data/opportunities.js*", async route => {
    scriptRequests += 1;
    await gate.promise;
    await route.continue();
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("carbon capture");
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill("Catalysis and carbon dioxide conversion");
  await page.locator("#filter-panel > summary").click();
  await page.locator("#status-forecasted").uncheck();
  await page.evaluate(() => {
    const form = document.querySelector("#search-form");
    form.requestSubmit();
    form.requestSubmit();
  });
  await expect.poll(() => scriptRequests).toBe(1);
  await expect(page.locator("#search-status")).toHaveText("Preparing funding catalog…");
  await expect(page.locator("#query")).toHaveValue("carbon capture");
  await expect(page.locator("#research-profile")).toHaveValue("Catalysis and carbon dioxide conversion");
  await expect(page.locator("#status-forecasted")).not.toBeChecked();
  await page.getByRole("button", { name: "Help" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  gate.resolve();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  await waitForHybridSettled(page);
  const result = await page.evaluate(() => ({
    ids: [...document.querySelectorAll("#results .result-card")]
      .map(card => card.dataset.opportunityId),
    tiers: [...document.querySelectorAll("#results .result-card")]
      .map(card => card.querySelector(".badge.potential") ? "potential" : "strong"),
    explanations: [...document.querySelectorAll("#results .result-card")]
      .map(card => [...card.querySelectorAll(".match-explanation li")].map(item => item.textContent.trim())),
    postedFacetCount: document.querySelector("#count-posted")?.textContent,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
    marks: performance.getEntriesByType("mark").map(entry => entry.name),
  }));
  expect(result.ids.length).toBeGreaterThan(0);
  expect(result.tiers.every(tier => ["strong", "potential"].includes(tier))).toBe(true);
  expect(result.explanations.some(items => items.length)).toBe(true);
  expect(Number(result.postedFacetCount.replaceAll(",", ""))).toBeGreaterThan(0);
  expect(result.snapshot).toMatchObject({ requests: 1, executions: 1, initializations: 1, state: "ready" });
  for (const mark of [
    "funding-shell-ready",
    "funding-catalog-requested",
    "funding-catalog-executed",
    "funding-catalog-initialized",
    "funding-first-search-completed",
  ]) expect(result.marks).toContain(mark);
  expect(calls.embed).toHaveLength(1);
  expect(calls.rerank).toHaveLength(1);
  expect(errors).toEqual([]);
  await page.locator("#query").fill("membrane separation");
  await page.locator("#find-funding").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await expect.poll(() => calls.embed.length).toBe(2);
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    requests: 1,
    executions: 1,
    initializations: 1,
    state: "ready",
  });
});

test("catalog failure preserves entered and saved state and retry completes the original search", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  await page.addInitScript(() => {
    localStorage.setItem("funding-finder.saved.v1", JSON.stringify([{
      opportunity_id: "saved-fixture",
      title: "Saved before catalog load",
      agency: "Fixture agency",
      source: "Fixture source",
      pursuit_status: "considering",
      note: "Keep this note",
    }]));
  });
  let attempts = 0;
  await page.route("**/data/opportunities.js*", async route => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({ status: 503, contentType: "text/plain", body: "bounded failure" });
      return;
    }
    await route.continue();
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("hydrogen catalysis");
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill("Electrochemical reaction engineering");
  await page.locator("#filter-panel > summary").click();
  await page.getByText("Deadline and award", { exact: true }).click();
  await page.locator("#deadline-from").fill("2026-09-01");
  await page.locator("#find-funding").click();
  await expect(page.locator("#catalog-error")).toBeVisible();
  await expect(page.locator("#catalog-error")).toContainText(/could not be downloaded|could not be prepared/i);
  await expect(page.locator("#query")).toHaveValue("hydrogen catalysis");
  await expect(page.locator("#research-profile")).toHaveValue("Electrochemical reaction engineering");
  await expect(page.locator("#deadline-from")).toHaveValue("2026-09-01");
  await expect(page.locator("#saved-count")).toHaveText("(1)");
  await page.locator("#saved-panel > summary").click();
  await expect(page.locator("[data-pursuit-note]")).toHaveValue("Keep this note");
  await page.locator("#catalog-retry").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(attempts).toBe(2);
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "ready",
    requests: 2,
    executions: 1,
    initializations: 1,
    metadataRefreshes: 1,
  });
});

test("timed-out catalog ownership quarantines stale execution across failed and successful retries", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  await installScriptClock(page);
  await page.addInitScript(() => {
    localStorage.setItem("funding-finder.saved.v1", JSON.stringify([{
      opportunity_id: "timeout-saved-fixture",
      title: "Saved before timeout",
      agency: "Fixture agency",
      source: "Fixture source",
      pursuit_status: "considering",
      note: "Timeout must preserve this note",
    }]));
  });
  const requestGates = [deferred(), deferred(), deferred()];
  let catalogRequests = 0;
  let staleExecutions = 0;
  const catalogUrls = [];
  await page.route("**/__stale-catalog-execution.js*", async route => {
    staleExecutions += 1;
    const label = new URL(route.request().url()).searchParams.get("case") || "unknown";
    await route.fulfill({
      status: 200,
      contentType: "text/javascript",
      body: `globalThis.GRANT_CATALOG=Object.freeze({
        schema_version: 3,
        generated_at: globalThis.GRANT_CATALOG_METADATA.generated_at,
        record_count: globalThis.GRANT_CATALOG_METADATA.record_count,
        status_counts: globalThis.GRANT_CATALOG_METADATA.status_counts,
        opportunities: [],
        search_index: { document_count: 0, postings: {} },
        stale_execution: ${JSON.stringify(label)}
      });`,
    });
  });
  await page.route("**/data/opportunities.js*", async route => {
    catalogRequests += 1;
    catalogUrls.push(new URL(route.request().url()));
    await requestGates[catalogRequests - 1].promise;
    if (catalogRequests === 1) {
      await route.abort().catch(() => {});
      return;
    }
    if (catalogRequests === 2) {
      await route.fulfill({ status: 503, contentType: "text/plain", body: "retry failed" });
      return;
    }
    await route.continue();
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("hydrogen catalysis timeout");
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill("Electrochemical reaction engineering");
  await page.locator("#filter-panel > summary").click();
  await page.getByText("Deadline and award", { exact: true }).click();
  await page.locator("#deadline-from").fill("2026-09-01");
  await page.locator("#find-funding").click();
  await expect.poll(() => catalogRequests).toBe(1);
  await expect(page.locator("#search-status")).toHaveText("Preparing funding catalog…");
  await page.evaluate(() => {
    globalThis.__TIMED_OUT_CATALOG_SCRIPT = document.querySelector(
      'script[data-funding-catalog="true"]',
    );
    globalThis.__CONCURRENT_CATALOG_SETTLEMENTS = Promise.allSettled([
      globalThis.FUNDING_CATALOG_LOADER.ensureCatalogReady(),
      globalThis.FUNDING_CATALOG_LOADER.ensureCatalogReady(),
    ]).then(items => items.map(item => ({
      status: item.status,
      message: item.reason?.message || "",
    })));
  });
  expect(await page.evaluate(() => globalThis.FUNDING_FINDER_APP.boundedScripts.catalog.timeoutMs))
    .toBe(120_000);
  expect(await page.evaluate(() => globalThis.FUNDING_FINDER_APP.boundedScripts.sidecar.timeoutMs))
    .toBe(15_000);
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.delays()))
    .toEqual([120_000]);
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.runAll())).toBe(1);
  requestGates[0].resolve();
  await expect(page.locator("#catalog-error")).toContainText(/catalog request timed out/i);
  const settlements = await page.evaluate(() => globalThis.__CONCURRENT_CATALOG_SETTLEMENTS);
  expect(settlements.map(item => item.status)).toEqual(["rejected", "rejected"]);
  expect(settlements[0].message).toBe(settlements[1].message);
  await expect(page.locator("#query")).toHaveValue("hydrogen catalysis timeout");
  await expect(page.locator("#research-profile")).toHaveValue("Electrochemical reaction engineering");
  await expect(page.locator("#deadline-from")).toHaveValue("2026-09-01");
  await expect(page.locator("#saved-count")).toHaveText("(1)");
  expect(await page.evaluate(() => ({
    catalog: globalThis.GRANT_CATALOG,
    scriptConnected: globalThis.__TIMED_OUT_CATALOG_SCRIPT?.isConnected,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
  }))).toMatchObject({
    catalog: undefined,
    scriptConnected: false,
    snapshot: {
      state: "failed",
      requests: 1,
      executions: 0,
      initializations: 0,
      catalogScriptCleanups: 1,
    },
  });

  await executeStaleCatalogAttempt(page, "before-retry");
  expect(await page.evaluate(() => ({
    catalog: globalThis.GRANT_CATALOG,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
  }))).toMatchObject({
    catalog: undefined,
    snapshot: { quarantinedCatalogAssignments: 1 },
  });

  await page.locator("#catalog-retry").click();
  await expect.poll(() => catalogRequests).toBe(2);
  await executeStaleCatalogAttempt(page, "during-failed-retry");
  expect(await page.evaluate(() => globalThis.GRANT_CATALOG)).toBeUndefined();
  requestGates[1].resolve();
  await expect(page.locator("#catalog-error")).toContainText(/could not be downloaded/i);
  await expect(page.locator("#query")).toHaveValue("hydrogen catalysis timeout");
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot()))
    .toMatchObject({
      state: "failed",
      requests: 2,
      executions: 0,
      initializations: 0,
      metadataRefreshes: 1,
      catalogScriptCleanups: 2,
      quarantinedCatalogAssignments: 2,
    });

  await page.locator("#catalog-retry").click();
  await expect.poll(() => catalogRequests).toBe(3);
  await page.evaluate(() => {
    globalThis.__CONCURRENT_RETRY_SETTLEMENTS = Promise.allSettled([
      globalThis.FUNDING_CATALOG_LOADER.ensureCatalogReady(),
      globalThis.FUNDING_CATALOG_LOADER.ensureCatalogReady(),
    ]).then(items => items.map(item => item.status));
  });
  await executeStaleCatalogAttempt(page, "immediately-before-active-load");
  expect(await page.evaluate(() => globalThis.GRANT_CATALOG)).toBeUndefined();
  requestGates[2].resolve();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(await page.evaluate(() => globalThis.__CONCURRENT_RETRY_SETTLEMENTS))
    .toEqual(["fulfilled", "fulfilled"]);
  const acceptedCatalog = await page.evaluate(() => ({
    generatedAt: globalThis.GRANT_CATALOG?.generated_at,
    recordCount: globalThis.GRANT_CATALOG?.record_count,
  }));
  expect(acceptedCatalog.recordCount).toBeGreaterThan(1000);
  await executeStaleCatalogAttempt(page, "after-successful-retry");
  expect(await page.evaluate(() => ({
    generatedAt: globalThis.GRANT_CATALOG?.generated_at,
    recordCount: globalThis.GRANT_CATALOG?.record_count,
    staleExecution: globalThis.GRANT_CATALOG?.stale_execution,
  }))).toEqual({ ...acceptedCatalog, staleExecution: undefined });
  const beforeLateEvents = await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot());
  await page.evaluate(() => {
    globalThis.__TIMED_OUT_CATALOG_SCRIPT.dispatchEvent(new Event("load"));
    globalThis.__TIMED_OUT_CATALOG_SCRIPT.dispatchEvent(new Event("error"));
  });
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot()))
    .toEqual(beforeLateEvents);
  expect(await page.evaluate(() => globalThis.GRANT_CATALOG?.record_count)).toBeGreaterThan(1000);
  expect(catalogRequests).toBe(3);
  expect(staleExecutions).toBe(4);
  expect(catalogUrls[0].searchParams.has("recovery")).toBe(false);
  expect(catalogUrls[1].searchParams.has("recovery")).toBe(true);
  expect(catalogUrls[2].searchParams.has("recovery")).toBe(true);
  expect(catalogUrls[1].href).not.toBe(catalogUrls[2].href);
  expect(beforeLateEvents).toMatchObject({
    state: "ready",
    requests: 3,
    executions: 1,
    initializations: 1,
    metadataRefreshes: 2,
    catalogScriptCleanups: 3,
    quarantinedCatalogAssignments: 4,
  });
});

test("a stalled topic sidecar fails initialization cleanly and a fresh bounded retry succeeds", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  await installScriptClock(page);
  const releaseStalledRequest = deferred();
  const sidecarUrls = [];
  await page.route("**/data/subtopics.js*", async route => {
    const requestUrl = new URL(route.request().url());
    sidecarUrls.push(requestUrl);
    if (sidecarUrls.length === 1) {
      await releaseStalledRequest.promise;
      await route.abort().catch(() => {});
      return;
    }
    await route.continue();
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("carbon capture sidecar timeout");
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill("Catalysis and carbon dioxide conversion");
  await page.locator("#find-funding").click();
  await expect.poll(() => sidecarUrls.length).toBe(1);
  await expect.poll(() => (
    page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot().state)
  )).toBe("initializing");
  await page.evaluate(() => {
    globalThis.__TIMED_OUT_SIDECAR_SCRIPT = document.querySelector(
      'script[data-funding-subtopic-catalog="true"]',
    );
    globalThis.__CONCURRENT_SIDECAR_SETTLEMENTS = Promise.allSettled([
      globalThis.FUNDING_SUBTOPICS.loadSidecar(),
      globalThis.FUNDING_SUBTOPICS.loadSidecar(),
    ]).then(items => items.map(item => ({
      status: item.status,
      code: item.reason?.code || "",
    })));
  });
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.delays()))
    .toEqual([15_000]);
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.runAll())).toBe(1);
  releaseStalledRequest.resolve();
  await expect(page.locator("#catalog-error")).toContainText(/topic catalog request timed out/i);
  const settlements = await page.evaluate(() => globalThis.__CONCURRENT_SIDECAR_SETTLEMENTS);
  expect(settlements.map(item => item.status)).toEqual(["rejected", "rejected"]);
  expect(settlements.map(item => item.code)).toEqual([
    "topic_sidecar_timeout",
    "topic_sidecar_timeout",
  ]);
  await expect(page.locator("#query")).toHaveValue("carbon capture sidecar timeout");
  await expect(page.locator("#research-profile")).toHaveValue("Catalysis and carbon dioxide conversion");
  await expect(page.locator("#results .result-card")).toHaveCount(0);
  expect(await page.evaluate(() => ({
    catalog: globalThis.GRANT_CATALOG,
    sidecar: globalThis.SUBTOPIC_CATALOG,
    scriptConnected: globalThis.__TIMED_OUT_SIDECAR_SCRIPT?.isConnected,
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
  }))).toMatchObject({
    catalog: undefined,
    sidecar: undefined,
    scriptConnected: false,
    snapshot: { state: "failed", requests: 1, executions: 1, initializations: 1 },
  });
  await page.locator("#catalog-retry").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(sidecarUrls).toHaveLength(2);
  expect(sidecarUrls[0].searchParams.has("recovery")).toBe(false);
  expect(sidecarUrls[1].searchParams.get("recovery")).toBe("1");
  const beforeLateEvents = await page.evaluate(() => ({
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
    sidecar: globalThis.SUBTOPIC_CATALOG,
  }));
  await page.evaluate(() => {
    globalThis.__TIMED_OUT_SIDECAR_SCRIPT.dispatchEvent(new Event("load"));
    globalThis.__TIMED_OUT_SIDECAR_SCRIPT.dispatchEvent(new Event("error"));
  });
  const afterLateEvents = await page.evaluate(() => ({
    snapshot: globalThis.FUNDING_CATALOG_LOADER.getSnapshot(),
    sidecar: globalThis.SUBTOPIC_CATALOG,
  }));
  expect(afterLateEvents).toEqual(beforeLateEvents);
  expect(beforeLateEvents.snapshot).toMatchObject({
    state: "ready",
    requests: 2,
    executions: 2,
    initializations: 2,
    metadataRefreshes: 1,
  });
});

test("a healthy catalog may complete after 15 seconds and both asset timers still clean up", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  await installScriptClock(page);
  const gate = deferred();
  await page.route("**/data/opportunities.js*", async route => {
    await gate.promise;
    await route.continue();
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("membrane separation");
  await page.locator("#find-funding").click();
  await expect.poll(() => page.evaluate(() => (
    globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.pending()
  ))).toBe(1);
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.delays()))
    .toEqual([120_000]);
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.advance(15_001)))
    .toBe(0);
  await expect(page.locator("#search-status")).toHaveText("Preparing funding catalog…");
  gate.resolve();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.pending())).toBe(0);
  expect(await page.evaluate(() => globalThis.__FUNDING_FINDER_SCRIPT_CLOCK.runAll())).toBe(0);
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "ready",
    requests: 1,
    executions: 1,
    initializations: 1,
  });
});

test("shell dependency failures do not offer a catalog retry that cannot run", async ({ page }) => {
  await page.route("**/assets/search-query.js*", route => route.fulfill({
    status: 200,
    contentType: "text/javascript",
    body: "",
  }));
  await page.goto("/match_explorer.html");
  await expect(page.locator("#query")).toBeVisible();
  await expect(page.locator("#query")).toBeEnabled();
  await expect(page.locator("#catalog-error")).toBeVisible();
  await expect(page.locator("#catalog-error-message")).toContainText(
    /search-term helper did not load.*refresh the page/i,
  );
  await expect(page.locator("#catalog-retry")).toBeHidden();
  await page.locator("#query").fill("state remains editable");
  await expect(page.locator("#query")).toHaveValue("state remains editable");
});

test("retry refreshes stale startup metadata after a catalog generation changes", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  let metadataRequests = 0;
  await page.route("**/data/catalog-metadata.js*", async route => {
    metadataRequests += 1;
    const response = await route.fetch();
    let body = await response.text();
    if (metadataRequests === 1) {
      const marker = "globalThis.GRANT_CATALOG_METADATA=";
      const payload = JSON.parse(body.split(marker, 2)[1].trim().replace(/;$/, ""));
      const staleCount = Number(payload.record_count) - 1;
      payload.release_identity = payload.release_identity.replace(
        `records=${payload.record_count}`,
        `records=${staleCount}`,
      );
      payload.record_count = staleCount;
      body = `/* Deterministic stale-generation fixture. */\n${marker}${JSON.stringify(payload)};\n`;
    }
    await route.fulfill({ response, body, contentType: "text/javascript" });
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("carbon capture");
  await page.locator("#find-funding").click();
  await expect(page.locator("#catalog-error")).toBeVisible();
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "failed",
    requests: 1,
    executions: 1,
    initializations: 0,
    metadataRefreshes: 0,
  });
  await page.locator("#catalog-retry").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(metadataRequests).toBe(2);
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "ready",
    requests: 2,
    executions: 2,
    initializations: 1,
    metadataRefreshes: 1,
  });
});

test("catalog validation derives its release version from loaded pipeline timestamps", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  let catalogResponses = 0;
  await page.route("**/data/opportunities.js*", async route => {
    catalogResponses += 1;
    const response = await route.fetch();
    let body = await response.text();
    if (catalogResponses === 1) {
      const generatedAt = body.match(/"generated_at":"([^"]+)"/)?.[1];
      expect(generatedAt).toBeTruthy();
      for (const field of [
        "detail_enrichment_generated_at",
        "document_evidence_generated_at",
        "catalog_audit_generated_at",
        "link_health_generated_at",
        "merged_at",
      ]) {
        body = body.replace(
          new RegExp(`"${field}":"[^"]+"`, "g"),
          `"${field}":"${generatedAt}"`,
        );
      }
    }
    await route.fulfill({ response, body, contentType: "text/javascript" });
  });
  await openFundingFinderShell(page);
  await page.locator("#query").fill("membrane separation");
  await page.locator("#find-funding").click();
  await expect(page.locator("#catalog-error")).toBeVisible();
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "failed",
    requests: 1,
    executions: 1,
    initializations: 0,
  });
  await page.locator("#catalog-retry").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(catalogResponses).toBe(2);
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "ready",
    requests: 2,
    executions: 2,
    initializations: 1,
    metadataRefreshes: 1,
  });
});

test("catalog validation preserves same-second pipeline timestamp precision", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  let latestTimestamp = "";
  let catalogResponses = 0;
  const catalogUrls = [];
  await page.route("**/data/opportunities.js*", async route => {
    catalogResponses += 1;
    const requestUrl = new URL(route.request().url());
    catalogUrls.push(requestUrl);
    const response = await route.fetch();
    let body = await response.text();
    if (!requestUrl.searchParams.has("recovery")) {
      const precise = latestTimestamp.match(/^(.*\.)(\d+)(Z)$/);
      expect(precise).toBeTruthy();
      const previousFraction = (BigInt(precise[2]) - 1n)
        .toString()
        .padStart(precise[2].length, "0");
      const staleTimestamp = `${precise[1]}${previousFraction}${precise[3]}`;
      expect(staleTimestamp).not.toBe(latestTimestamp);
      expect(body).toContain(latestTimestamp);
      body = body.replaceAll(latestTimestamp, staleTimestamp);
    }
    await route.fulfill({ response, body, contentType: "text/javascript" });
  });
  await openFundingFinderShell(page);
  latestTimestamp = await page.evaluate(() => (
    globalThis.GRANT_CATALOG_METADATA.pipeline_generated_at
  ));
  await page.locator("#query").fill("hydrogen catalysis");
  await page.locator("#find-funding").click();
  await expect(page.locator("#catalog-error")).toBeVisible();
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "failed",
    requests: 1,
    executions: 1,
    initializations: 0,
  });
  await page.locator("#catalog-retry").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  expect(catalogResponses).toBe(2);
  expect(catalogUrls[0].searchParams.has("recovery")).toBe(false);
  expect(catalogUrls[1].searchParams.has("recovery")).toBe(true);
  expect(catalogUrls[1].searchParams.get("v")).toBe(catalogUrls[0].searchParams.get("v"));
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot())).toMatchObject({
    state: "ready",
    requests: 2,
    executions: 2,
    initializations: 1,
    metadataRefreshes: 1,
  });
});

test("Back and Forward restore catalog-dependent URLs before and after readiness without eager clean-page execution", async ({ page }) => {
  mockHybrid(page);
  await installConnection(page, { saveData: true, effectiveType: "4g" });
  const gate = deferred();
  await page.route("**/data/opportunities.js*", async route => {
    await gate.promise;
    await route.continue();
  });
  await openFundingFinderShell(page);
  await page.evaluate(() => {
    history.pushState(null, "", "?q=carbon%20capture&status=open");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.locator("#query")).toHaveValue("carbon capture");
  await expect(page.locator("#search-status")).toHaveText("Preparing funding catalog…");
  await page.goBack();
  await expect(page.locator("#query")).toHaveValue("");
  expect(await page.evaluate(() => Boolean(globalThis.GRANT_CATALOG))).toBe(false);
  await page.goForward();
  await expect(page.locator("#query")).toHaveValue("carbon capture");
  gate.resolve();
  await expect(page.locator("#results .result-card").first()).toBeVisible({ timeout: 45_000 });
  await page.evaluate(() => {
    history.pushState(null, "", "?q=membrane&status=open&status=forecasted");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.locator("#query")).toHaveValue("membrane");
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await page.goBack();
  await expect(page.locator("#query")).toHaveValue("carbon capture");
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  expect(await page.evaluate(() => globalThis.FUNDING_CATALOG_LOADER.getSnapshot().initializations)).toBe(1);
});

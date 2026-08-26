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

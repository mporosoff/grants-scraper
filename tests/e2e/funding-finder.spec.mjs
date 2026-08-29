import { expect, test } from "@playwright/test";
import {
  csvRows,
  downloadText,
  mockHybrid,
  mockAlerts,
  mockOpenAiBroadening,
  openFundingFinder,
  runFundingSearch,
  waitForHybridSettled,
  watchRuntimeErrors,
} from "./helpers.mjs";

test("watchlist pursuit state stays local and saved-search alerts send only typed public criteria", async ({ page }) => {
  mockHybrid(page);
  const alertCalls = mockAlerts(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openFundingFinder(page);
  await runFundingSearch(page, "hydrogen catalysis");
  const card = page.locator("#results .result-card").first();
  await card.locator("[data-save]").click();
  await page.locator("#saved-panel > summary").click();
  await page.locator("[data-pursuit-status]").selectOption("pursuing");
  await page.locator("[data-pursuit-note]").fill("Draft due Friday");

  await expect(page.locator("#alerts-panel")).toHaveAttribute("open", "");
  await page.locator("#alert-new-matches").click();
  const dialog = page.getByRole("dialog", { name: "Save this search as an email alert" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("current Strong matches become the starting baseline");
  await dialog.locator("#alert-email").fill("researcher@example.edu");
  await dialog.locator("#alert-submit").click();
  await expect(dialog.locator("#alert-dialog-status")).toContainText("Verification email requested for researcher@example.edu");
  await expect(dialog.locator("#alert-email")).toHaveValue("researcher@example.edu");
  await expect(dialog.locator("#alert-email")).toHaveAttribute("readonly", "");
  await expect(dialog.locator("#alert-submit")).toHaveText("Send verification email again");
  expect(alertCalls).toHaveLength(1);
  expect(alertCalls[0].subscription.definition).toMatchObject({
    query: "hydrogen catalysis", currentness: "current_only",
    strong_contract_version: "funding-search-v2-strong-1", include_potential: false,
  });
  expect(alertCalls[0].baseline_opportunity_ids).toEqual(expect.any(Array));
  expect(alertCalls[0].baseline_opportunity_ids.length).toBeGreaterThan(0);
  const serialized = JSON.stringify(alertCalls[0]);
  expect(serialized).not.toMatch(/Draft due Friday|profile_text|cv_text|orcid_text|chat|uploaded/i);
  await page.keyboard.press("Escape");
  await page.reload();
  await page.locator("#saved-panel > summary").click();
  await expect(page.locator("[data-pursuit-status]")).toHaveValue("pursuing");
  await expect(page.locator("[data-pursuit-note]")).toHaveValue("Draft due Friday");
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Unit C alert dialog locks the page, traps focus, scrolls internally, and restores state on mobile", async ({ page }) => {
  mockHybrid(page);
  mockAlerts(page);
  await page.setViewportSize({ width: 320, height: 480 });
  await openFundingFinder(page);
  await runFundingSearch(page, "hydrogen catalysis");
  const invoker = page.locator("#alert-new-matches");
  await invoker.scrollIntoViewIfNeeded();
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await invoker.click();
  const dialog = page.getByRole("dialog", { name: "Save this search as an email alert" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("#alert-email")).toBeFocused();
  expect(await page.evaluate(() => ({
    rootLocked: document.documentElement.classList.contains("alert-dialog-open"),
    bodyLocked: document.body.classList.contains("alert-dialog-open"),
    position: document.body.style.position,
    top: document.body.style.top,
    rootOverflow: document.documentElement.style.overflow,
  }))).toEqual({
    rootLocked: true,
    bodyLocked: true,
    position: "fixed",
    top: `-${scrollBefore}px`,
    rootOverflow: "hidden",
  });
  const mobileGeometry = await dialog.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
      width: rect.width, height: rect.height,
      clientHeight: element.clientHeight, scrollHeight: element.scrollHeight,
      overflowY: getComputedStyle(element).overflowY,
    };
  });
  expect(mobileGeometry.left).toBeGreaterThanOrEqual(0);
  expect(mobileGeometry.right).toBeLessThanOrEqual(320);
  expect(mobileGeometry.top).toBeGreaterThanOrEqual(0);
  expect(mobileGeometry.bottom).toBeLessThanOrEqual(480);
  expect(mobileGeometry.scrollHeight).toBeGreaterThan(mobileGeometry.clientHeight);
  expect(["auto", "scroll"]).toContain(mobileGeometry.overflowY);
  await dialog.evaluate(element => { element.scrollTop = element.scrollHeight; });
  expect(await dialog.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  for (const viewport of [{ width: 320, height: 320 }, { width: 480, height: 320 }]) {
    await page.setViewportSize(viewport);
    const bounds = await dialog.evaluate(element => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    });
    expect(bounds.left).toBeGreaterThanOrEqual(0);
    expect(bounds.right).toBeLessThanOrEqual(viewport.width);
    expect(bounds.top).toBeGreaterThanOrEqual(0);
    expect(bounds.bottom).toBeLessThanOrEqual(viewport.height);
  }
  await page.setViewportSize({ width: 320, height: 480 });

  const closeButton = dialog.locator(".alert-dialog-close");
  const cancelButton = dialog.locator(".alert-cancel");
  await closeButton.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(cancelButton).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(closeButton).toBeFocused();
  await page.locator("#query").focus();
  expect(await page.evaluate(() => document.querySelector(".alert-dialog")?.contains(document.activeElement))).toBe(true);

  await dialog.locator("#alert-email").fill("mobile-researcher@example.edu");
  await dialog.locator("#alert-submit").click();
  await expect(dialog.locator("#alert-dialog-status")).toContainText("Verification email requested for mobile-researcher@example.edu");
  await expect(dialog.locator("#alert-email")).toHaveValue("mobile-researcher@example.edu");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(invoker).toBeFocused();
  await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(Math.round(scrollBefore));
  expect(await page.evaluate(() => ({
    rootLocked: document.documentElement.classList.contains("alert-dialog-open"),
    bodyLocked: document.body.classList.contains("alert-dialog-open"),
    position: document.body.style.position,
    rootOverflow: document.documentElement.style.overflow,
  }))).toEqual({ rootLocked: false, bodyLocked: false, position: "", rootOverflow: "" });

  await page.setViewportSize({ width: 390, height: 600 });
  await invoker.click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(invoker).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Unit C alert dialog preserves its recovery state and restores focus after a failed submission", async ({ page }) => {
  mockHybrid(page);
  mockAlerts(page, { status: 503, errorCode: "alerts_unavailable" });
  await page.setViewportSize({ width: 390, height: 520 });
  await openFundingFinder(page);
  await runFundingSearch(page, "hydrogen catalysis");
  const invoker = page.locator("#alert-new-matches");
  await invoker.click();
  const dialog = page.getByRole("dialog", { name: "Save this search as an email alert" });
  await dialog.locator("#alert-email").fill("failure-researcher@example.edu");
  await dialog.locator("#alert-submit").click();
  await expect(dialog.locator("#alert-dialog-status")).toContainText("Email alert delivery is unavailable");
  await expect(dialog.locator("#alert-email")).toHaveValue("failure-researcher@example.edu");
  expect(await page.evaluate(() => document.body.style.position)).toBe("fixed");
  expect(await page.evaluate(() => document.querySelector(".alert-dialog")?.contains(document.activeElement))).toBe(true);
  await dialog.locator(".alert-dialog-close").click();
  await expect(dialog).toBeHidden();
  await expect(invoker).toBeFocused();
  expect(await page.evaluate(() => document.body.style.position)).toBe("");
});

test("saved-item write rejection restores durable UI state across every mutation", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const originalSetItem = Storage.prototype.setItem;
    const originalRemoveItem = Storage.prototype.removeItem;
    Storage.prototype.setItem = function setItem(key, value) {
      if (key === "funding-finder.saved.v1" && globalThis.__rejectSavedWrites) {
        throw new DOMException("Deterministic storage rejection", "QuotaExceededError");
      }
      return originalSetItem.call(this, key, value);
    };
    Storage.prototype.removeItem = function removeItem(key) {
      if (key === "funding-finder.saved.v1" && globalThis.__rejectSavedWrites) {
        throw new DOMException("Deterministic storage rejection", "QuotaExceededError");
      }
      return originalRemoveItem.call(this, key);
    };
  });
  mockHybrid(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openFundingFinder(page);
  await runFundingSearch(page, "hydrogen catalysis");
  const cards = page.locator("#results .result-card");
  await expect(cards.nth(1)).toBeVisible();
  await cards.first().locator("[data-save]").click();
  await expect(cards.first().locator("[data-save]")).toHaveAttribute("aria-pressed", "true");
  await page.locator("#saved-panel > summary").click();
  await expect(page.locator("#saved-count")).toHaveText("(1)");

  await page.evaluate(() => {
    const items = JSON.parse(localStorage.getItem("funding-finder.saved.v1"));
    items[0].pursuit_status = "pursuing";
    items[0].note = "Durable update from another tab";
    localStorage.setItem("funding-finder.saved.v1", JSON.stringify(items));
    globalThis.__rejectSavedWrites = true;
  });
  await cards.first().locator("[data-save]").click();
  await expect(cards.first().locator("[data-save]")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#saved-status")).toContainText("last saved version is still shown");
  await expect(page.locator("#saved-count")).toHaveText("(1)");
  await expect(page.locator("[data-pursuit-status]")).toHaveValue("pursuing");
  await expect(page.locator("[data-pursuit-note]")).toHaveValue("Durable update from another tab");

  await page.locator("[data-pursuit-status]").selectOption("submitted");
  await expect(page.locator("[data-pursuit-status]")).toHaveValue("pursuing");
  await page.locator("[data-pursuit-note]").evaluate(element => {
    element.value = "Uncommitted note";
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("[data-pursuit-note]")).toHaveValue("Durable update from another tab");
  await expect(page.locator("[data-pursuit-note]")).toBeFocused();

  await page.locator("[data-remove-saved]").click();
  await expect(page.locator("#saved-count")).toHaveText("(1)");
  await page.locator("#clear-saved").click();
  await expect(page.locator("#saved-count")).toHaveText("(1)");

  await cards.nth(1).locator("[data-save]").click();
  await expect(cards.nth(1).locator("[data-save]")).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("#saved-count")).toHaveText("(1)");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("funding-finder.saved.v1")).length)).toBe(1);
  await testInfo.attach("ff-bug-011-storage-rejection-390px.png", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

const alertErrorCases = [
  {
    name: "429 rate_limited JSON response",
    status: 429,
    errorCode: "rate_limited",
    message: "Too many alert requests. Wait before trying again.",
  },
  {
    name: "429 non-JSON response",
    status: 429,
    responseBody: "not-json private provider body",
    message: "Too many alert requests. Wait before trying again.",
  },
  {
    name: "400 invalid_request JSON response",
    status: 400,
    errorCode: "invalid_request",
    message: "Check the alert details and try again.",
  },
  {
    name: "403 origin_not_allowed JSON response",
    status: 403,
    errorCode: "origin_not_allowed",
    message: "Email alert delivery is unavailable. Retry later.",
  },
  {
    name: "503 alerts_unavailable JSON response",
    status: 503,
    errorCode: "alerts_unavailable",
    message: "Email alert delivery is unavailable. Retry later.",
  },
  {
    name: "503 non-JSON response",
    status: 503,
    responseBody: "not-json private provider body",
    message: "Email alert delivery is unavailable. Retry later.",
  },
  {
    name: "202 malformed accepted response",
    status: 202,
    responseBody: "not-json private provider body",
    message: "The email alert service returned an invalid response. Retry later.",
  },
];

for (const fixture of alertErrorCases) {
  test(`alert dialog gives bounded recovery guidance for ${fixture.name}`, async ({ page }) => {
    mockHybrid(page);
    mockAlerts(page, fixture);
    await openFundingFinder(page);
    await runFundingSearch(page, "hydrogen catalysis");
    await expect(page.locator("#alerts-panel")).toHaveAttribute("open", "");
    await page.locator("#alert-new-matches").click();
    const dialog = page.getByRole("dialog", { name: "Save this search as an email alert" });
    await dialog.locator("#alert-email").fill("researcher@example.edu");
    await dialog.locator("#alert-submit").click();
    await expect(dialog.locator("#alert-dialog-status")).toContainText(fixture.message);
    await expect(dialog.locator("#alert-dialog-status")).not.toContainText(/researcher@example\.edu|provider body|suppressed|exists/i);
    await page.setViewportSize({ width: 320, height: 720 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("Funding Finder loads with a usable catalog and no uncaught runtime errors", async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  await openFundingFinder(page);
  await expect(page.locator("[data-app-version]")).toContainText("Funding Finder v1.3.0");
  await expect(page.locator("#search-form")).toBeVisible();
  await expect(page.locator("#sort")).toBeAttached();
  await expect(page.locator("#sort")).toBeEnabled();
  expect(errors).toEqual([]);
});

test("Funding Finder lazy-loads evidence-qualified Hajim reverse matches with one accessible panel", async ({ page }) => {
  const requested = [];
  page.on("request", request => requested.push(request.url()));
  await page.goto("/match_explorer.html?focus=353936");
  const card = page.locator('#results .result-card[data-opportunity-id="353936"]');
  await expect(card).toBeVisible();
  expect(requested.some(url => /hajim_faculty_directory|faculty_matches/.test(url))).toBe(false);

  const trigger = card.getByRole("button", { name: "Find relevant Hajim faculty" });
  await trigger.click();
  await expect(card.locator(".hajim-match-panel")).toBeVisible();
  await expect(card.locator(".hajim-match-panel h4")).toBeFocused();
  await expect(card.locator(".hajim-faculty-match", { hasText: "Anson Kahng" })).toContainText("Computer Science");
  await expect(card.locator(".hajim-faculty-match", { hasText: "Anson Kahng" })).toContainText("Source checked 2026-08-28");
  await expect(card.locator(".hajim-faculty-match", { hasText: "Benjamin E. Partridge" })).toBeVisible();
  expect(requested.some(url => /hajim_faculty_directory\.js/.test(url))).toBe(true);
  expect(requested.some(url => /faculty_matches\.js/.test(url))).toBe(true);

  await card.locator("[data-hajim-scope]").selectOption("primary");
  await expect(card.locator(".hajim-faculty-match", { hasText: "Benjamin E. Partridge" })).toHaveCount(0);
  await card.locator("[data-hajim-close]").click();
  await expect(trigger).toBeFocused();
  await expect(card.locator(".hajim-match-panel")).toHaveCount(0);
});

test("Hajim reverse-panel ownership recovers across rerenders, stale nodes, and consecutive cards", async ({ page }) => {
  await page.goto("/match_explorer.html?focus=353936");
  const card = page.locator('#results .result-card[data-opportunity-id="353936"]');
  const trigger = card.getByRole("button", { name: "Find relevant Hajim faculty" });
  await trigger.click();
  await expect(card.locator(".hajim-match-panel h4")).toBeFocused();

  await card.locator("[data-save]").click();
  await expect(card.locator(".hajim-match-panel")).toHaveCount(0);
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await expect(card.locator(".hajim-match-panel h4")).toBeFocused();

  await card.locator(".hajim-match-panel").evaluate(panel => panel.remove());
  await trigger.click();
  await expect(card.locator(".hajim-match-panel")).toHaveCount(1);
  await expect(card.locator(".hajim-match-panel h4")).toBeFocused();
  await card.locator("[data-hajim-close]").click();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await page.goto("/match_explorer.html");
  await page.locator("#browse-all").click();
  const cards = page.locator("#results .result-card");
  await expect(cards).toHaveCount(20);
  const firstTrigger = cards.nth(0).getByRole("button", { name: "Find relevant Hajim faculty" });
  const secondTrigger = cards.nth(1).getByRole("button", { name: "Find relevant Hajim faculty" });
  await firstTrigger.click();
  await expect(cards.nth(0).locator(".hajim-match-panel h4")).toBeFocused();
  await secondTrigger.click();
  await expect(page.locator(".hajim-match-panel")).toHaveCount(1);
  await expect(firstTrigger).toHaveAttribute("aria-expanded", "false");
  await expect(cards.nth(1).locator(".hajim-match-panel h4")).toBeFocused();
  await cards.nth(1).locator("[data-hajim-close]").click();
  await expect(secondTrigger).toBeFocused();
});

test("a failed Hajim asset can retry without affecting ordinary Funding Finder actions", async ({ page }) => {
  let graphRequests = 0;
  await page.route("**/data/faculty_matches.js*", route => {
    graphRequests += 1;
    if (graphRequests === 1) return route.abort("failed");
    return route.fallback();
  });
  await page.goto("/match_explorer.html?focus=353936");
  const card = page.locator('#results .result-card[data-opportunity-id="353936"]');
  await card.getByRole("button", { name: "Find relevant Hajim faculty" }).click();
  await expect(card.locator(".hajim-match-body")).toContainText("temporarily unavailable");
  const retry = card.locator("[data-hajim-retry]");
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(card.locator(".hajim-faculty-match", { hasText: "Anson Kahng" })).toBeVisible();
  expect(graphRequests).toBe(2);
  await card.locator("[data-save]").click();
  await expect(card.locator("[data-save]")).toHaveAttribute("aria-pressed", "true");
  await page.locator("#query").fill("catalysis");
  await page.locator("#find-funding").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible();
});

test("primary search submits with Enter while AI refinement stays visible and truthfully disabled", async ({ page }) => {
  mockHybrid(page);
  await openFundingFinder(page);
  const query = page.locator("#query");
  const find = page.locator("#find-funding");
  const upload = page.locator(".nofo-upload-button");
  const [queryBox, findBox, uploadBox] = await Promise.all([
    query.boundingBox(),
    find.boundingBox(),
    upload.boundingBox(),
  ]);
  expect(queryBox).not.toBeNull();
  expect(findBox.x).toBeGreaterThan(queryBox.x);
  expect(uploadBox.x).toBeGreaterThan(findBox.x);

  const refine = page.locator("#ai-refine");
  await expect(refine).toBeVisible();
  await expect(refine).toBeDisabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Run a funding search and enter or save");
  await query.fill("catalysis science");
  await query.press("Enter");
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await waitForHybridSettled(page);
  await expect(page.locator("#results-heading")).toContainText(/\d+ opportunities · \d+ strong · \d+ potential/);
  await expect(refine).toBeDisabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Enter or save an AI provider key");
  await page.locator(".provider-setup > summary").click();
  await page.locator("#k-key").fill("sk-layout-test");
  await expect(refine).toBeEnabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Ready to refine");
});

test("primary search and AI action stack without horizontal overflow from tablet through 320 px", async ({ page }) => {
  mockHybrid(page);
  await openFundingFinder(page);
  for (const width of [820, 700, 600, 541, 540, 390, 320]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const [queryBox, findBox, uploadBox] = await Promise.all([
      page.locator("#query").boundingBox(),
      page.locator("#find-funding").boundingBox(),
      page.locator(".nofo-upload-button").boundingBox(),
    ]);
    expect(findBox.y).toBeGreaterThan(queryBox.y);
    expect(uploadBox.y).toBeGreaterThan(findBox.y);
    for (const box of [queryBox, findBox, uploadBox]) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
    }
    await expect(page.locator("#ai-refine")).toBeVisible();
  }
});

test("provider failure preserves the search, filters, results, key, and retry control", async ({ page }) => {
  mockHybrid(page);
  let providerCalls = 0;
  await page.route("https://api.openai.com/v1/responses", route => {
    providerCalls += 1;
    return route.fulfill({
      status: 401,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify({ error: { code: "invalid_api_key", message: "provider-secret-diagnostic" } }),
    });
  });
  await openFundingFinder(page);
  await page.locator("#filter-panel > summary").click();
  await page.locator("#status-forecasted").uncheck();
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  const originalHeading = await page.locator("#results-heading").textContent();
  await page.locator(".provider-setup > summary").click();
  await page.locator("#k-key").fill("sk-preserved-test-key");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("provider rejected this API key");
  await expect(page.locator("#ai-status")).not.toContainText(/provider-secret-diagnostic|sk-preserved-test-key/);
  expect(providerCalls).toBe(1);
  await expect(page.locator("#query")).toHaveValue("catalysis science");
  await expect(page.locator("#status-forecasted")).not.toBeChecked();
  await expect(page.locator("#k-key")).toHaveValue("sk-preserved-test-key");
  await expect(page.locator("#results-heading")).toHaveText(originalHeading);
  await expect(page.locator("#ai-refine")).toBeEnabled();
});

test("an alert focus link starts a result search and reveals its exact opportunity", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-08-28T12:00:00Z"));
  mockHybrid(page);
  await page.goto("/match_explorer.html?focus=361187");
  const card = page.locator('[data-opportunity-id="361187"]');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toHaveClass(/chat-target/);
  await expect(page.locator("#results-mode")).not.toContainText("Ready when you are");
});

test("Strong and Potential membership survives sorting, filters trigger one semantic cycle, and core actions work", async ({ page }) => {
  const calls = mockHybrid(page);
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await expect.poll(() => calls.embed.length).toBe(1);
  await expect.poll(() => calls.rerank.length).toBe(1);

  await expect(page.locator("#results-mode")).toHaveText("Strong + potential catalog");
  const resultHeading = await page.locator("#results-heading").textContent();
  const tierCounts = resultHeading.match(/(\d+) strong.*?(\d+) potential/);
  const strongCount = Number(tierCounts?.[1] || 0);
  const potentialCount = Number(tierCounts?.[2] || 0);
  expect(strongCount).toBeGreaterThan(0);
  expect(potentialCount).toBeGreaterThan(0);

  const firstCsv = await downloadText(page, "#export-csv");
  expect(firstCsv).toContain('"Strong"');
  expect(firstCsv).toContain('"Potential"');
  const firstRows = csvRows(firstCsv).sort();

  for (const sort of ["deadline", "agency", "title"]) {
    await page.locator("#sort").selectOption(sort);
    await expect.poll(() => calls.embed.length).toBe(1);
    await expect.poll(() => calls.rerank.length).toBe(1);
    const sortedCsv = await downloadText(page, "#export-csv");
    expect(csvRows(sortedCsv).sort()).toEqual(firstRows);
  }

  await page.locator("#filter-panel > summary").click();
  await page.locator("#status-posted").uncheck();
  await expect.poll(() => calls.embed.length, { timeout: 30_000 }).toBe(2);
  await expect.poll(() => calls.rerank.length, { timeout: 30_000 }).toBe(2);
  await waitForHybridSettled(page);
  const filteredCsv = await downloadText(page, "#export-csv");
  expect(csvRows(filteredCsv).sort()).not.toEqual(firstRows);
  await expect(page.locator("#results .result-card .badge.forecasted").first()).toBeVisible();

  const rerankedPassages = calls.rerank[1].candidates.map(item => item.passage_id);
  const ineligibleParents = await page.evaluate(ids => {
    const parents = new Map(globalThis.GRANT_CATALOG.opportunities.map(record => [String(record.opportunity_id), record]));
    const children = new Map(Object.entries(globalThis.SUBTOPIC_CATALOG?.records || {}).flatMap(([parentId, entry]) => (
      (entry.subtopics || []).map(record => [String(record.id), parentId])
    )));
    return ids.filter(id => {
      const [kind, value] = id.split(":", 2);
      const record = kind === "parent" ? parents.get(value) : parents.get(String(children.get(value) || ""));
      return record && record.status !== "forecasted";
    });
  }, rerankedPassages);
  expect(ineligibleParents).toEqual([]);

  const card = page.locator("#results .result-card").first();
  await expect(card.locator("h3 a")).toHaveAttribute("href", /^https?:\/\//);
  await card.locator("details.record-details > summary").click();
  await expect(card.locator("details.record-details")).toHaveAttribute("open", "");
  const save = card.locator("[data-save]");
  await save.click();
  await expect(save).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("[data-calendar]:not([disabled])").first()).toBeVisible();

  const query = await page.locator("#query").inputValue();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.goto("/team_match.html?gate4-nav=1");
  await page.goBack();
  await expect(page.locator("#query")).toHaveValue(query);
  await expect(page.locator("#status-posted")).not.toBeChecked();
  await expect(page.locator("#results .result-card").first()).toBeVisible();
});

test("sidecar failure preserves parent search, browsing, and filters with a visible warning", async ({ page }) => {
  const calls = mockHybrid(page);
  await openFundingFinder(page, { sidecarFailure: true });
  await runFundingSearch(page, "DE-FOA-0003600");
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await expect(page.locator("#topic-layer-warning")).toContainText(/topic details.*temporarily unavailable/i);
  await expect(page.locator("#potential-status")).toContainText(/needs the topic layer/i);
  expect(calls.embed).toHaveLength(0);
  await page.locator("#filter-panel > summary").click();
  await page.locator("#clear-filters").click();
  await page.locator("#status-forecasted").uncheck();
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await page.locator("#query").fill("");
  await page.locator("#find-funding").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible();
});

test("Retry-After keeps Strong results visible and disables retry until the interval expires", async ({ page }) => {
  const calls = mockHybrid(page, { failEmbedCalls: 1, retryAfter: 10 });
  await openFundingFinder(page);
  await runFundingSearch(page, "DE-FOA-0003600");
  await expect(page.locator("#potential-status")).toContainText(/temporarily limited/i, { timeout: 30_000 });
  await expect(page.locator("#results .badge.open").first()).toBeVisible();
  const retry = page.locator("#retry-potential");
  await expect(retry).toBeDisabled();
  await expect(retry).toBeEnabled({ timeout: 12_000 });
  await retry.click();
  await expect.poll(() => calls.embed.length).toBe(2);
  await expect(page.locator("#potential-status")).toContainText("Potential matching completed", { timeout: 30_000 });
  await expect(page.locator("#results-mode")).toHaveText("Strong + potential catalog");
});

test("AI broadening renders a newly retrieved candidate across actions, review, chat focus, CSV, and clear", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  const ai = await mockOpenAiBroadening(page);
  await openFundingFinder(page, { evaluation: true });
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  const originalCount = await page.locator("#result-count").textContent();
  const originalPageIds = await page.locator("#results .result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));

  await page.locator(".provider-setup > summary").click();
  await page.locator("#k-key").fill("sk-gate4-browser-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("Shortlisted", { timeout: 30_000 });
  expect(ai.calls).toBe(2);
  expect(ai.candidate?.workflow_tier).toBe("ai_candidate");
  await expect(page.locator("#results-mode")).toHaveText("AI-refined shortlist", { timeout: 30_000 });
  const candidate = page.locator(`[data-opportunity-id="${ai.candidate.id}"]`);
  await expect(candidate).toBeVisible();
  await expect(candidate.getByText("AI-expanded candidate", { exact: true })).toBeVisible();
  await candidate.locator("[data-save]").click();
  await expect(candidate.locator("[data-save]")).toHaveAttribute("aria-pressed", "true");
  await candidate.locator("details.record-details > summary").click();
  await expect(candidate.locator("details.record-details")).toHaveAttribute("open", "");

  const aiCsv = await downloadText(page, "#export-csv");
  expect(aiCsv).toContain('"AI-candidate"');
  await page.locator("#evaluation-tools > summary").click();
  await page.locator("#review-candidates").click();
  await expect(page.locator(`[data-opportunity-id="${ai.candidate.id}"]`)).toBeVisible();
  await page.locator(`[data-opportunity-id="${ai.candidate.id}"] [data-chat-record]`).click();
  await expect(page.locator("#result-assistant")).toBeVisible();
  await expect(page.locator(`[data-opportunity-id="${ai.candidate.id}"]`)).toBeVisible();
  await page.locator("#clear-ai").click();
  await expect(page.locator("#result-count")).toHaveText(originalCount);
  await expect.poll(() => page.locator("#results .result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId))).toEqual(originalPageIds);
});

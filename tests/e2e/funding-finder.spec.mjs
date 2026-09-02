import { expect, test } from "@playwright/test";
import {
  configurePersonalProvider,
  csvRows,
  downloadText,
  mockHybrid,
  mockAlerts,
  mockFrozenFundingSearchPackage,
  mockOpenAiBroadening,
  openFundingFinder,
  runFundingSearch,
  waitForHybridSettled,
} from "./helpers.mjs";

const frozenFocusOpportunityId = "363616";

test.beforeEach(async ({ page }) => {
  await mockFrozenFundingSearchPackage(page);
});

async function mockNofoExtraction(page, text) {
  await page.route("**/assets/nofo.js*", async route => {
    const response = await route.fetch();
    const source = await response.text();
    const extracted = {
      name: "matched-notice.pdf",
      text,
      pageCount: 2,
      pagesRead: 2,
      wordCount: text.split(/\s+/).filter(Boolean).length,
      truncated: false,
    };
    const patched = source.replace(
      /    extract,\r?\n/,
      `    extract: async () => (${JSON.stringify(extracted)}),\n`,
    );
    if (patched === source) throw new Error("NOFO extraction mock did not attach");
    await route.fulfill({ response, body: patched, contentType: "application/javascript" });
  });
}

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

  await expect(page.locator("#alerts-panel")).not.toHaveAttribute("open", "");
  await page.locator("#alerts-panel > summary").click();
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
  await expect(page.locator("#alerts-panel")).not.toHaveAttribute("open", "");
  await page.locator("#alerts-panel > summary").click();
  await expect(page.locator("#alerts-panel")).toHaveAttribute("open", "");
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
  await expect(page.locator("#alerts-panel")).not.toHaveAttribute("open", "");
  await page.locator("#alerts-panel > summary").click();
  await expect(page.locator("#alerts-panel")).toHaveAttribute("open", "");
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

test("primary search submits with Enter while hosted AI refinement stays visible and truthfully gated", async ({ page }) => {
  mockHybrid(page);
  await openFundingFinder(page);
  const query = page.locator("#query");
  const find = page.locator("#find-funding");
  expect(await page.locator("#nofo-drop-zone").evaluate(node => {
    const order = [...node.children].map(child => child.id || child.getAttribute("for"));
    const positions = [order.indexOf("query"), order.indexOf("nofo-file"), order.indexOf("find-funding")];
    return positions.every(position => position >= 0)
      && positions[0] < positions[1]
      && positions[1] < positions[2];
  })).toBe(true);
  await query.focus();
  await page.keyboard.press("Tab");
  await expect(page.locator("#nofo-file")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(find).toBeFocused();

  const refine = page.locator("#ai-refine");
  await expect(refine).toBeVisible();
  await expect(refine).toBeDisabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Run a funding search with a topic or enabled profile");
  await expect(page.locator("#k-provider")).toHaveValue("hosted");
  await expect(page.locator("#provider-state")).toContainText("Hosted AI ready");
  await query.fill("catalysis science");
  await query.press("Enter");
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await waitForHybridSettled(page);
  await expect(page.locator("#result-tier-counts")).toContainText(/\d+ strong match(?:es)? · \d+ potential match(?:es)?/i);
  await expect(refine).toBeEnabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Ready to refine the current search with hosted AI");
  await configurePersonalProvider(page, "sk-layout-test");
  await expect(refine).toBeEnabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Ready to refine the current search with your connected provider");
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
    expect(uploadBox.y).toBeGreaterThan(queryBox.y);
    expect(findBox.y).toBeGreaterThan(uploadBox.y);
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
  const originalHeading = await page.locator("#result-tier-counts").textContent();
  await configurePersonalProvider(page, "sk-preserved-test-key");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("provider rejected this API key");
  await expect(page.locator("#ai-status")).not.toContainText(/provider-secret-diagnostic|sk-preserved-test-key/);
  expect(providerCalls).toBe(1);
  await expect(page.locator("#query")).toHaveValue("catalysis science");
  await expect(page.locator("#status-forecasted")).not.toBeChecked();
  await expect(page.locator("#k-key")).toHaveValue("sk-preserved-test-key");
  await expect(page.locator("#result-tier-counts")).toHaveText(originalHeading);
  await expect(page.locator("#ai-refine")).toBeEnabled();
});

test("an alert focus link starts a result search and reveals its exact opportunity", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-09-01T12:00:00Z"));
  mockHybrid(page);
  await page.goto(`/match_explorer.html?focus=${encodeURIComponent(frozenFocusOpportunityId)}`);
  const card = page.locator(`[data-opportunity-id="${frozenFocusOpportunityId}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toHaveClass(/chat-target/);
  await expect(page.locator("#result-tier-counts")).toContainText(/\d+ strong match(?:es)? · \d+ potential match(?:es)?/i);
});

test("Strong and Potential membership survives sorting, filters trigger one semantic cycle, and core actions work", async ({ page }) => {
  const calls = mockHybrid(page);
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await expect.poll(() => calls.embed.length).toBe(1);
  await expect.poll(() => calls.rerank.length).toBe(1);

  await expect(page.locator("#result-tier-counts")).toContainText(/\d+ strong match(?:es)? · \d+ potential match(?:es)?/i);
  const resultHeading = await page.locator("#result-tier-counts").textContent();
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
  await runFundingSearch(page, "hydrogen catalysis");
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
  await runFundingSearch(page, "hydrogen catalysis");
  await expect(page.locator("#potential-status")).toContainText(/temporarily limited/i, { timeout: 30_000 });
  await expect(page.locator("#results .badge.open").first()).toBeVisible();
  const retry = page.locator("#retry-potential");
  await expect(retry).toBeDisabled();
  await expect(retry).toBeEnabled({ timeout: 12_000 });
  await retry.click();
  await expect.poll(() => calls.embed.length).toBe(2);
  await waitForHybridSettled(page);
  await expect(page.locator("#result-tier-counts")).toContainText(/\d+ strong match(?:es)? · \d+ potential match(?:es)?/i);
});

test("refinement awaits the one pending Potential request before capturing its ordinary baseline", async ({ page }) => {
  const hybrid = mockHybrid(page, { rerankDelayMs: 4_000, maxRankings: 1 });
  const ai = await mockOpenAiBroadening(page);
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await configurePersonalProvider(page, "sk-pending-baseline-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("Waiting for the ordinary Potential search");
  expect(ai.calls).toBe(0);
  await expect(page.locator("#ai-status")).toContainText("AI added", { timeout: 30_000 });
  expect(hybrid.embed).toHaveLength(1);
  expect(hybrid.rerank).toHaveLength(1);
  expect(ai.calls).toBe(2);
  await expect(page.locator("#result-tier-counts")).toContainText(/\d+ strong match(?:es)? · \d+ potential match(?:es)? · \d+ AI-identified match(?:es)?/i);
  await page.locator("#restore-ai-refinement").click();
  await expect(page.locator("#result-tier-counts")).not.toContainText(/AI-identified/i);
});

test("generic-only and stale AI responses leave the ordinary baseline untouched", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  const generic = await mockOpenAiBroadening(page, {
    planTerms: ["research", "science", "technology", "health", "energy"],
  });
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  const baselineHeading = await page.locator("#result-tier-counts").textContent();
  const baselineIds = await page.locator("#results .result-card").evaluateAll(cards => (
    cards.map(card => card.dataset.opportunityId)
  ));
  await configurePersonalProvider(page, "sk-generic-plan-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("no additional evidence-qualified opportunities");
  expect(generic.calls).toBe(1);
  await expect(page.locator("#restore-ai-refinement")).toBeHidden();
  await expect(page.locator("#result-tier-counts")).toHaveText(baselineHeading);
  await expect.poll(() => page.locator("#results .result-card").evaluateAll(cards => (
    cards.map(card => card.dataset.opportunityId)
  ))).toEqual(baselineIds);

  await page.unroute("https://api.openai.com/v1/responses");
  const stale = await mockOpenAiBroadening(page, { planDelayMs: 500 });
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("Step 1 of 2");
  await page.locator("#query").fill("a changed search that invalidates refinement");
  await expect(page.locator("#ai-status")).toContainText("cleared because the search criteria changed");
  await expect(page.locator("#ai-refine")).toBeDisabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Run Find funding again");
  await expect.poll(() => stale.calls).toBe(1);
  await page.waitForTimeout(650);
  expect(stale.calls).toBe(1);
  await expect(page.locator("#restore-ai-refinement")).toBeHidden();
  await expect(page.locator("#result-tier-counts")).toHaveText(baselineHeading);
  await expect.poll(() => page.locator("#results .result-card").evaluateAll(cards => (
    cards.map(card => card.dataset.opportunityId)
  ))).toEqual(baselineIds);
});

test("refinement sends only enabled profile context and honors the explicit CV-for-AI control", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  const ai = await mockOpenAiBroadening(page);
  await openFundingFinder(page);
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill(
    "We develop heterogeneous catalysts and electrochemical reactors for carbon dioxide conversion.",
  );
  await page.locator("#expertise-keywords").fill(
    "reaction engineering, catalysis, electrochemical conversion, porous materials",
  );
  await page.locator("#cv-file").setInputFiles("tests/fixtures/browser_cv.txt");
  await expect(page.locator("#cv-status")).toContainText(/words/);
  await page.locator("#include-cv-ai").uncheck();
  await page.locator("#use-profile").check();
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await page.locator(".provider-setup > summary").click();
  await page.locator("#k-provider").selectOption("anthropic");
  await page.locator("#k-key").fill("sk-ant-provider-choice-mock");
  await expect(page.locator("#ai-refine")).toBeEnabled();
  await page.locator("#k-provider").selectOption("openai");
  await page.locator("#k-key").fill("sk-profile-boundary-mock");
  await page.locator("#ai-refine").click();
  await expect.poll(() => ai.calls).toBeGreaterThanOrEqual(1);
  const context = ai.requests[0].researcher_profile;
  expect(context.research_description).toContain("heterogeneous catalysts");
  expect(context.expertise_keywords).toContain("reaction engineering");
  expect(context.cv_excerpt).toBeUndefined();
});

test("refinement keeps both calls and provenance bound to its starting provider", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  const ai = await mockOpenAiBroadening(page, { planDelayMs: 500 });
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await configurePersonalProvider(page, "sk-provider-snapshot-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("Step 1 of 2");
  await page.locator("#k-provider").selectOption("anthropic");
  await expect(page.locator("#ai-status")).toContainText("AI added", { timeout: 30_000 });
  expect(ai.calls).toBe(2);
  await expect(page.locator("#k-provider")).toHaveValue("anthropic");
  await expect(page.locator("#result-tier-counts")).toContainText(/AI-identified/i);
});

test("editing an imported ORCID clears stale refinement and restores ordinary results", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  await page.route("https://api.crossref.org/works?*", route => route.fulfill({
    status: 200,
    headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
    body: JSON.stringify({
      message: {
        "total-results": 1,
        items: [{
          title: ["Catalytic reaction engineering for carbon conversion"],
          author: [{
            given: "Josiah",
            family: "Carberry",
            ORCID: "https://orcid.org/0000-0002-1825-0097",
          }],
          subject: ["Catalysis", "Reaction engineering"],
          published: { "date-parts": [[2026]] },
        }],
      },
    }),
  }));
  await mockOpenAiBroadening(page);
  await openFundingFinder(page);
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill("Catalytic reaction engineering and carbon conversion.");
  await page.locator("#orcid-id").fill("0000-0002-1825-0097");
  await page.locator("#import-orcid").click();
  await expect(page.locator("#orcid-status")).toContainText("publications imported");
  await page.locator("#use-profile").check();
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  const baselineHeading = await page.locator("#result-tier-counts").textContent();
  await configurePersonalProvider(page, "sk-orcid-invalidation-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("AI added", { timeout: 30_000 });

  await page.locator("#orcid-id").fill("0000-0001-5109-3700");
  await expect(page.locator("#ai-status")).toContainText("cleared because the search criteria changed");
  await expect(page.locator("#restore-ai-refinement")).toBeHidden();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Run Find funding again");
  await expect(page.locator("#result-tier-counts")).toHaveText(baselineHeading);
  await expect(page.locator("#orcid-status")).toContainText("Select “Import ORCID”");
});

test("uploaded notice focus blocks refinement until the PDF is removed", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  await mockNofoExtraction(
    page,
    "[Page 1] Funding Opportunity 26-518 supports chemical, bioengineering, energy, and transport systems. [Page 2] Applicants should verify all requirements in the official notice.",
  );
  await openFundingFinder(page);
  await configurePersonalProvider(page, "sk-upload-focus-mock");
  await page.locator("#nofo-file").setInputFiles({
    name: "matched-notice.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 deterministic extraction mock"),
  });
  await expect(page.locator("#nofo-upload-status")).toContainText("Matched opportunity number 26-518");
  await expect(page.locator("#results .result-card")).toHaveCount(1);
  await expect(page.locator("#ai-refine")).toBeDisabled();
  await expect(page.locator("#ai-refine-requirement")).toContainText("Remove the uploaded PDF");
  await expect(page.locator("#nofo-chat-context [data-nofo-remove]")).toBeVisible();

  await page.locator("#nofo-chat-context [data-nofo-remove]").click();
  await expect(page.locator("#search-status")).toContainText("uploaded PDF was removed");
  await expect(page.locator("#ai-refine")).toBeEnabled();
});

test("rerunning changed criteria clears stale chat focus while preserving the conversation", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  const ai = await mockOpenAiBroadening(page, { chatResultAction: "focus" });
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await configurePersonalProvider(page, "sk-focus-invalidation-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("AI added", { timeout: 30_000 });
  await page.locator("#open-results-chat").click();
  await page.locator("#chat-input").fill("Focus the result list on one supplied opportunity.");
  await page.locator("#chat-submit").click();
  await expect.poll(() => ai.chatRequests.length).toBe(1);
  await expect(page.locator("#results .result-card")).toHaveCount(1);
  const conversationCount = await page.locator("#chat-messages .message").count();
  await page.locator("#toggle-chat-size").click();

  await page.locator("#sort").selectOption("agency");
  await expect.poll(() => page.locator("#results .result-card").count()).toBeGreaterThan(1);
  await expect(page.locator("#restore-ai-refinement")).toBeHidden();
  await expect(page.locator("#chat-messages .message")).toHaveCount(conversationCount);
  await expect(page.locator("#query")).toHaveValue("catalysis science");
  await expect(page.locator("#k-key")).toHaveValue("sk-focus-invalidation-mock");
});

test("AI refinement adds locally Strong records and exact restoration preserves the ordinary baseline", async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  const ai = await mockOpenAiBroadening(page);
  await openFundingFinder(page, { evaluation: true });
  await page.locator("#profile-builder > summary").click();
  await page.locator("#research-profile").fill(
    "A populated but disabled profile that must not affect AI expansion.",
  );
  await page.locator("#expertise-keywords").fill("biomaterials, tissue engineering");
  await expect(page.locator("#use-profile")).not.toBeChecked();
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  const originalCount = await page.locator("#result-tier-counts").textContent();
  const originalPageIds = await page.locator("#results .result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  const originalCsv = await downloadText(page, "#export-csv");
  const originalSort = await page.locator("#sort").inputValue();

  await configurePersonalProvider(page, "sk-gate4-browser-mock");
  await page.locator("#ai-refine").click();
  await expect(page.locator("#ai-status")).toContainText("AI added", { timeout: 30_000 });
  expect(ai.calls).toBe(2);
  expect(ai.requests[0].researcher_profile).toBeNull();
  expect(ai.candidate?.workflow_tier).toBe("strong");
  expect(ai.candidate?.ai_identified).toBe(true);
  expect(ai.candidate?.ai_discovery_phrases.length).toBeGreaterThan(0);
  await expect(page.locator("#result-tier-counts")).toContainText(/AI-identified/i, { timeout: 30_000 });
  const candidate = page.locator(`[data-opportunity-id="${ai.candidate.id}"]`);
  await expect(candidate).toBeVisible();
  await expect(candidate.getByText("AI identified", { exact: true })).toBeVisible();
  await expect(candidate.getByText("Strong match", { exact: true })).toBeVisible();
  await expect(page.locator("#restore-ai-refinement")).toBeVisible();
  await expect(page.locator("#ai-refine")).toBeDisabled();
  const refinedCsv = await downloadText(page, "#export-csv");
  for (const row of csvRows(originalCsv)) expect(csvRows(refinedCsv)).toContain(row);
  expect(refinedCsv).toContain('"Strong","Yes"');
  await candidate.locator("[data-save]").click();
  await expect(candidate.locator("[data-save]")).toHaveAttribute("aria-pressed", "true");
  await candidate.locator("details.record-details > summary").click();
  await expect(candidate.locator("details.record-details")).toHaveAttribute("open", "");

  await page.locator("#open-results-chat").click();
  await page.locator("#chat-input").fill("Compare the bounded active results.");
  await page.locator("#chat-submit").click();
  await expect.poll(() => ai.chatRequests.length).toBe(1);
  await expect(page.locator("#chat-messages")).toContainText("mock answer is grounded");
  expect(ai.chatRequests[0].current_results.length).toBeLessThanOrEqual(20);
  expect(ai.chatRequests[0].current_results.some(item => (
    item.id === ai.candidate.id
      && item.workflow_tier === "strong"
      && item.ai_identified === true
  ))).toBe(true);
  const conversationBeforeRestore = await page.locator("#chat-messages .message").count();
  await page.locator("#toggle-chat-size").click();

  await page.locator("#restore-ai-refinement").click();
  await expect(page.locator("#ai-status")).toContainText("Original results restored exactly");
  await expect(page.locator("#restore-ai-refinement")).toBeHidden();
  await expect(page.locator("#ai-refine")).toBeFocused();
  await expect(page.locator("#result-tier-counts")).toHaveText(originalCount);
  await expect(page.locator("#sort")).toHaveValue(originalSort);
  await expect.poll(() => page.locator("#results .result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId))).toEqual(originalPageIds);
  expect(await downloadText(page, "#export-csv")).toBe(originalCsv);
  await expect(page.locator("#saved-count")).toHaveText("(1)");
  await expect(page.locator("#k-key")).toHaveValue("sk-gate4-browser-mock");
  await expect(page.locator("#research-profile")).toHaveValue(
    "A populated but disabled profile that must not affect AI expansion.",
  );
  await expect(page.locator("#expertise-keywords")).toHaveValue("biomaterials, tissue engineering");
  await expect(page.locator("#use-profile")).not.toBeChecked();

  await page.locator("#open-results-chat").click();
  await expect(page.locator("#chat-messages .message")).toHaveCount(conversationBeforeRestore);
  await page.locator("#chat-input").fill("Recheck the restored ordinary context.");
  await page.locator("#chat-submit").click();
  await expect.poll(() => ai.chatRequests.length).toBe(2);
  expect(ai.chatRequests[1].current_results.length).toBeLessThanOrEqual(20);
  expect(ai.chatRequests[1].current_results.some(item => item.id === ai.candidate.id)).toBe(false);
});

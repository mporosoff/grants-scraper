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

  await page.locator("#alert-new-matches").click();
  const dialog = page.getByRole("dialog", { name: "Alert me to new Strong matches" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("current Strong matches become the starting baseline");
  await dialog.locator("#alert-email").fill("researcher@example.edu");
  await dialog.locator("#alert-submit").click();
  await expect(dialog.locator("#alert-dialog-status")).toContainText("Check your email");
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

test("Funding Finder loads with a usable catalog and no uncaught runtime errors", async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  await openFundingFinder(page);
  await expect(page.locator("[data-app-version]")).toContainText("Funding Finder v1.3.0");
  await expect(page.locator("#search-form")).toBeVisible();
  await expect(page.locator("#sort")).toBeAttached();
  await expect(page.locator("#sort")).toBeEnabled();
  expect(errors).toEqual([]);
});

test("Strong and Potential membership survives sorting, filters trigger one semantic cycle, and core actions work", async ({ page }) => {
  const calls = mockHybrid(page);
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await expect.poll(() => calls.embed.length).toBe(1);
  await expect.poll(() => calls.rerank.length).toBe(1);

  await expect(page.locator("#results-mode")).toHaveText("Strong + potential catalog");
  const statusText = await page.locator("#search-status").textContent();
  const tierCounts = statusText.match(/(\d+) strong.*?(\d+) potential/);
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

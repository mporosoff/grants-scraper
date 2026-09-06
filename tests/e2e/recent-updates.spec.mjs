import { expect, test } from "@playwright/test";
import {
  configurePersonalProvider, mockAlerts, mockAwards, mockHybrid, mockOpenAiBroadening,
  openFundingFinder, runFundingSearch, waitForHybridSettled,
} from "./helpers.mjs";
import { closeFundingRefine } from "./public-tool-workflow.mjs";
import {
  buildAwardSnapshot, publicSnapshot, snapshotPage, snapshotSourceBatch,
} from "../../workers/award-api/src/snapshot.js";

async function closeChat(page) {
  await page.locator('#result-assistant [data-shell-drawer-close]').click();
  await expect(page.locator('#result-assistant')).toBeHidden();
}

async function sendQuestion(page, ai, question, count) {
  await page.locator('#chat-input').fill(question);
  await page.locator('#chat-submit').click();
  await expect.poll(() => ai.chatRequests.length).toBe(count);
  await expect(page.locator('#chat-submit')).toBeEnabled();
}

for (const width of [1280, 390, 320]) {
  test(`Ask AI bounds requests, keeps follow-up scope, and supports card menus at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    mockHybrid(page, { maxRankings: 0 });
    const ai = await mockOpenAiBroadening(page);
    await openFundingFinder(page);
    await expect(page.locator('#open-results-chat')).toBeDisabled();
    await page.locator('#browse-all').click();
    await expect(page.locator('#results .result-card').first()).toBeVisible();
    await expect(page.locator('#open-results-chat')).toBeDisabled();
    await expect(page.locator('#chat-scope-hint')).toContainText('Run a search or apply a non-default filter');
    await page.locator('#query').fill('research');
    await expect(page.locator('#open-results-chat')).toBeDisabled();
    await runFundingSearch(page, 'research');
    await waitForHybridSettled(page);
    const counts = (await page.locator('#result-tier-counts').textContent()).match(/(\d+) strong.*?(\d+) potential/);
    expect(Number(counts[1]) + Number(counts[2])).toBeGreaterThan(10);
    await configurePersonalProvider(page, 'sk-browser-validation-mock');
    await closeFundingRefine(page);
    await page.locator('#open-results-chat').click();
    await expect(page.locator('#chat-summary')).toContainText('10 most relevant');
    await sendQuestion(page, ai, 'Compare the supplied opportunities.', 1);
    const ids = ai.chatRequests[0].current_results.map(item => item.id);
    expect(ids).toHaveLength(10);
    expect(new Set(ids).size).toBe(10);
    await sendQuestion(page, ai, 'Which of those has the nearest deadline?', 2);
    expect(ai.chatRequests[1].current_results.map(item => item.id)).toEqual(ids);
    await closeChat(page);
    await page.locator('#sort').selectOption('title');
    await page.locator('#open-results-chat').click();
    await sendQuestion(page, ai, 'Compare their eligibility requirements.', 3);
    expect(ai.chatRequests[2].current_results.map(item => item.id)).toEqual(ids);
    await closeChat(page);
    const card = page.locator('#results .result-card').first();
    const cardId = await card.getAttribute('data-opportunity-id');
    await card.locator('[data-card-more]').click();
    await page.locator(`[data-chat-record="${cardId}"]`).click();
    await sendQuestion(page, ai, 'Summarize this opportunity.', 4);
    expect(ai.chatRequests[3].current_results.map(item => item.id)).toEqual([cardId]);
    if (width < 500) {
      await page.setViewportSize({ width, height: 400 });
      await page.locator('#chat-input').focus();
      for (const selector of ['#chat-input', '#chat-submit']) {
        await expect(page.locator(selector)).toBeInViewport();
        const box = await page.locator(selector).boundingBox();
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
        expect(box.y + box.height).toBeLessThanOrEqual(401);
      }
      await page.screenshot({ path: testInfo.outputPath('short-viewport-chat.png') });
      await page.locator('#result-assistant .provider-setup > summary').click();
      await page.locator('#chat-input').focus();
      for (const selector of ['#chat-input', '#chat-submit']) {
        await expect(page.locator(selector)).toBeInViewport({ ratio: 1 });
      }
    }
  });
}

test('a non-default filter enables Ask AI and restoring default browsing disables it', async ({ page }) => {
  mockHybrid(page, { maxRankings: 0 });
  await openFundingFinder(page);
  await page.locator('#browse-all').click();
  await expect(page.locator('#open-results-chat')).toBeDisabled();
  await page.locator('#filter-team-ready').click();
  await expect(page.locator('#results .result-card').first()).toBeVisible();
  await expect(page.locator('#open-results-chat')).toBeEnabled();
  await page.locator('#filter-team-ready').click();
  await expect(page.locator('#open-results-chat')).toBeDisabled();
});

test('saved opportunity alerts work before searching and enforce the selected public-ID boundary', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const calls = mockAlerts(page);
  await page.addInitScript(() => localStorage.setItem('funding-finder.saved.v1', JSON.stringify(
    Array.from({ length: 26 }, (_, index) => ({
      opportunity_id: `saved-${index}`, title: `Saved opportunity ${index}`,
      note: 'PRIVATE VALIDATION NOTE', pursuit_status: 'pursuing',
    })),
  )));
  await page.goto('/match_explorer.html');
  await page.locator('[data-workspace-open]').first().click();
  await page.locator('#alert-saved-opportunities').click();
  const dialog = page.getByRole('dialog', { name: 'Watch saved opportunities', exact: true });
  const options = dialog.locator('input[name="saved-opportunity"]');
  await expect(options).toHaveCount(26);
  await expect(dialog.locator('input[name="saved-opportunity"]:checked')).toHaveCount(25);
  await dialog.locator('#alert-email').fill('browser-validation@example.edu');
  await options.last().check();
  await dialog.locator('#alert-submit').click();
  await expect(dialog.locator('#alert-dialog-status')).toContainText(/25/);
  expect(calls).toHaveLength(0);
  for (const option of await options.all()) await option.uncheck();
  await dialog.locator('#alert-submit').click();
  await expect(dialog.locator('#alert-dialog-status')).toContainText(/Choose|Select/i);
  expect(calls).toHaveLength(0);
  await options.nth(0).check();
  await options.nth(25).check();
  await dialog.locator('#alert-submit').click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].subscription.definition.opportunity_ids).toEqual(['saved-0', 'saved-25']);
  expect(JSON.stringify(calls)).not.toMatch(/PRIVATE|pursuing|profile|chat/);
  await expect(dialog.locator('#alert-dialog-status')).toContainText('Verification email requested');
  await page.keyboard.press('Escape');
  await expect(page.locator('#alert-saved-opportunities')).toBeFocused();
});

test('specific team topics support alternatives, explicit replacement, and Team Match handoff', async ({ page }) => {
  mockHybrid(page);
  await openFundingFinder(page);
  await runFundingSearch(page, 'DEVCOM');
  await page.locator('#filter-team-ready').click();
  await page.locator('[data-opportunity-team][data-opportunity-team-broad="true"]').first().click();
  const panel = page.locator('#team-builder');
  await expect(panel.getByText('Choose a specific opportunity topic', { exact: true })).toBeVisible();
  await panel.locator('[data-opportunity-team-scope]').first().click();
  await expect(panel.locator('[data-opportunity-team-remove]').first()).toBeVisible();
  const variants = panel.locator('[data-opportunity-team-variant]');
  if (await variants.count() > 1) await variants.last().click();
  const remove = panel.locator('[data-opportunity-team-remove]').first();
  const memberId = await remove.getAttribute('data-opportunity-team-remove');
  await remove.click();
  await expect(panel.locator(`[data-opportunity-team-remove="${memberId}"]`)).toHaveCount(0);
  const replacements = panel.locator('[data-opportunity-team-replacement]');
  await expect(replacements.locator(`option[value="${memberId}"]`)).toContainText('Previously selected');
  await replacements.selectOption(memberId);
  await panel.locator('[data-opportunity-team-add-replacement]').click();
  await expect(panel.locator(`[data-opportunity-team-remove="${memberId}"]`)).toBeVisible();
  const memberNames = await panel.locator('[data-opportunity-team-remove]').evaluateAll(nodes => nodes.map(node => node.getAttribute('aria-label').replace(/^Remove /, '').replace(/ from this proposed team$/, '')).sort());
  await panel.getByRole('link', { name: 'Continue in Team Match', exact: true }).click();
  await expect(page).toHaveURL(/team_match\.html/);
  for (const name of memberNames) await expect(page.getByRole('button', { name: `Remove ${name} from team`, exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('#team-hint')).toContainText(`all ${memberNames.length} selected researchers`);
  await page.reload();
  for (const name of memberNames) await expect(page.getByRole('button', { name: `Remove ${name} from team`, exact: true })).toBeVisible({ timeout: 30_000 });
});

test('award sorting spans the full snapshot and survives paging, shared reload, and history', async ({ page }) => {
  mockAwards(page, { resultCountPerSource: 0 });
  const records = Array.from({ length: 32 }, (_, index) => ({
    source: index % 2 ? 'NSF' : 'NIH', award_id: `validation-${index}`,
    title: `Project ${String(31 - index).padStart(2, '0')}`,
    award_date: `2025-${String(index % 12 + 1).padStart(2, '0')}-${String(Math.floor(index / 12) + 1).padStart(2, '0')}`,
    institution: { name: 'Validation University' }, principal_investigators: [],
    abstract: 'Public synthetic research award for browser validation.',
  }));
  let snapshot;
  const calls = [];
  await page.route(/\/awards\/snapshots(?:\/|$)/, async route => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'content-type' } });
      return;
    }
    const body = route.request().postDataJSON();
    const path = new URL(route.request().url()).pathname;
    calls.push({ path, body });
    let payload;
    if (path.endsWith('/snapshots')) {
      snapshot = buildAwardSnapshot({
        snapshotId: 'a'.repeat(64), queryId: 'b'.repeat(64),
        asOf: '2026-09-06T00:00:00Z', expiresAt: '2027-09-06T00:00:00Z', request: body,
        sourcePayloads: Object.fromEntries(body.sources.map(source => {
          const results = records.filter(record => record.source === source);
          return [source, { source, results, has_more: false, total_count: results.length }];
        })),
      });
      payload = publicSnapshot(snapshot);
    } else if (path.endsWith('/page')) {
      payload = snapshotPage(snapshot, { page: body.page, pageSize: body.page_size, sort: body.sort, facet: body.facet });
    } else if (path.endsWith('/batch')) {
      payload = snapshotSourceBatch(snapshot, body);
    } else throw new Error(`Unexpected snapshot request: ${path}`);
    await route.fulfill({ status: 200, headers: { 'Access-Control-Allow-Origin': '*' }, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await page.goto('/funded_awards.html');
  await page.locator('#ii-topic').fill('browser validation');
  await page.locator('#ii-search').click();
  await expect(page.locator('#ii-awards .ii-award-card')).toHaveCount(10);
  const visibleIds = () => page.locator('#ii-awards .ii-award-card').evaluateAll(nodes => nodes.map(node => node.dataset.evidenceId));
  const dateOrder = (a, b) => b.award_date.localeCompare(a.award_date);
  for (const sort of ['oldest', 'title', 'agency', 'newest']) {
    await page.locator('#ii-sort').selectOption(sort);
    await expect(page.locator('#ii-sort')).toBeEnabled();
    const ordered = [...records].sort(sort === 'title' ? (a, b) => a.title.localeCompare(b.title)
      : sort === 'oldest' ? (a, b) => -dateOrder(a, b)
      : sort === 'agency' ? (a, b) => a.source.localeCompare(b.source) || dateOrder(a, b)
      : dateOrder);
    expect(await visibleIds()).toEqual(ordered.slice(0, 10).map(record => `${record.source}:${record.award_id}`));
    await page.locator('#ii-card-next').click();
    await expect(page.locator('#ii-card-page-label')).toContainText('Page 2');
    expect(await visibleIds()).toEqual(ordered.slice(10, 20).map(record => `${record.source}:${record.award_id}`));
    await page.goBack();
    await expect(page.locator('#ii-card-page-label')).toContainText('Page 1');
    await expect(page.locator('#ii-sort')).toHaveValue(sort);
    await page.goForward();
    await expect(page.locator('#ii-card-page-label')).toContainText('Page 2');
    expect(await visibleIds()).toEqual(ordered.slice(10, 20).map(record => `${record.source}:${record.award_id}`));
    await page.reload();
    await expect(page.locator('#ii-card-page-label')).toContainText('Page 2');
    await expect(page.locator('#ii-sort')).toHaveValue(sort);
    expect(await visibleIds()).toEqual(ordered.slice(10, 20).map(record => `${record.source}:${record.award_id}`));
  }
  expect(calls.filter(call => call.path.endsWith('/snapshots'))).toHaveLength(1);
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

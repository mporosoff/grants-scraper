import { expect, test } from "@playwright/test";

import { mockAwards, openAiStructuredResponse, watchRuntimeErrors } from "./helpers.mjs";

async function openSearch(page, options = {}) {
  const calls = mockAwards(page, options);
  const runtimeErrors = watchRuntimeErrors(page);
  await page.goto("/funded_awards.html");
  await expect(page.locator("#ii-search")).toBeEnabled();
  return { calls, runtimeErrors };
}

async function searchTopic(page, topic = "catalysis", agency = "NSF") {
  await page.locator("#ii-agency").selectOption(agency);
  await page.locator("#ii-topic").fill(topic);
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-output")).toBeVisible();
}

for (const count of [0, 1, 9, 10, 11, 25, 26, 50, 51]) {
  test(`snapshot pagination handles exactly ${count} matching awards`, async ({ page }) => {
    const { runtimeErrors } = await openSearch(page, { resultCountPerSource: count });
    await searchTopic(page, `count-${count}`);
    await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(Math.min(10, count));
    if (count) {
      await expect(page.locator("#ii-card-page-label")).toContainText(`Awards 1–${Math.min(10, count)} of ${count}`);
      await expect(page.locator("#ii-metrics .ii-metric").first()).toContainText(String(count));
    } else {
      await expect(page.locator("#ii-card-page-label")).toContainText("No awards matched");
    }
    if (count > 10) {
      await page.locator("#ii-card-next").click();
      await expect(page).toHaveURL(/ii_page=2/);
      await expect(page.locator("#ii-card-page-label")).toContainText("Page 2");
    } else {
      await expect(page.locator("#ii-card-next")).toBeDisabled();
    }
    expect(runtimeErrors).toEqual([]);
  });
}

test("topic and program-officer filters create one immutable snapshot request", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("electrocatalysis");
  await page.locator("#ii-program-officer").fill("Alex Officer");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  const create = calls.find(call => call.sources?.[0] === "NSF" && call.criteria?.topic === "electrocatalysis");
  expect(create).toEqual({ sources: ["NSF"], criteria: { topic: "electrocatalysis", program_officer: "Alex Officer" } });
  await expect(page).toHaveURL(/ii_topic=electrocatalysis/);
  await expect(page).toHaveURL(/ii_snapshot=/);
  expect(runtimeErrors).toEqual([]);
});

test("program filtering requires one source before a snapshot is created", async ({ page }) => {
  const { calls } = await openSearch(page);
  await page.locator("#ii-program").fill("BES");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-status")).toContainText("Choose NSF, NIH, or DOE");
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(0);
});

test("each agency hydrates independently in batches no larger than 25", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: { NSF: 26, NIH: 26, DOE: 26 } });
  await searchTopic(page, "catalysis", "all");
  await expect(page.locator("#ii-metrics .ii-metric").first()).toContainText("78");
  for (const source of ["NSF", "NIH", "DOE"]) {
    const button = page.locator(`[data-ii-load-source="${source}"]`);
    await expect(button).toContainText(`Load up to 25 more ${source} awards`);
    await button.click();
    await expect(page.locator("#ii-status")).toContainText(`Loaded remaining 1 ${source} award`);
    await expect(button).toHaveCount(0);
  }
  const batchCalls = calls.filter(call => call.source && Number.isInteger(call.offset));
  expect(batchCalls.map(call => [call.source, call.offset])).toEqual([["NSF", 25], ["NIH", 25], ["DOE", 25]]);
  expect(runtimeErrors).toEqual([]);
});

test("numbered navigation, page size, and history keep one stable view", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 51 });
  await searchTopic(page, "paging");
  await page.locator('[data-ii-page-number="5"]').click();
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 41–50 of 51 · Page 5 of 6");
  await page.locator("#ii-page-size").selectOption("25");
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 26–50 of 51 · Page 2 of 3");
  await expect(page).toHaveURL(/ii_page_size=25/);
  await page.goBack();
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 5 of 6");
  await expect(page.locator("#ii-page-size")).toHaveValue("10");
  expect(runtimeErrors).toEqual([]);
});

test("investigator and program drill-downs filter the same snapshot and clear in one action", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: { NSF: 3, NIH: 2, DOE: 4 } });
  await searchTopic(page, "cross-agency", "all");
  const createCount = calls.filter(call => Array.isArray(call.sources)).length;
  await page.locator("#ii-investigators").selectOption({ label: "Marc Porosoff (4)" });
  await expect(page.locator("#ii-active-facet")).toContainText("Marc Porosoff");
  await expect(page.locator("#ii-metrics .ii-metric").first()).toContainText("4");
  await expect(page).toHaveURL(/ii_facet=investigator/);
  await expect(page.locator("#ii-programs option")).toHaveCount(4);
  await page.locator("#ii-clear-facet").click();
  await expect(page.locator("#ii-active-facet")).toBeHidden();
  await expect(page.locator("#ii-metrics .ii-metric").first()).toContainText("9");
  await page.locator("#ii-programs").selectOption({ label: "NIH · R01 (2)" });
  await expect(page.locator("#ii-active-facet")).toContainText("NIH · R01");
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(createCount);
  expect(runtimeErrors).toEqual([]);
});

test("failed-source retry creates a successor without discarding successful cards", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { failNih: true, resultCountPerSource: { NSF: 2, NIH: 0, DOE: 2 } });
  await searchTopic(page, "partial", "all");
  await expect(page.locator("#ii-source-status")).toContainText("NIH is temporarily unavailable");
  await expect(page.locator("#ii-card-page-label")).toContainText("at least 4 available");
  await page.locator("#ii-programs").selectOption({ label: "NSF · Plasma Physics (2)" });
  await expect(page.locator("#ii-active-facet")).toBeVisible();
  const retainedIds = await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId).sort());
  const previousUrl = page.url();
  await page.locator('[data-ii-retry-source="NIH"]').click();
  await expect(page.locator("#ii-status")).toContainText("NIH recovered in successor snapshot");
  const afterIds = await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId).sort());
  expect(afterIds).toEqual(expect.arrayContaining(retainedIds));
  expect(afterIds.length).toBe(5);
  await expect(page.locator("#ii-programs option", { hasText: "NIH · R01" })).toHaveCount(1);
  await expect(page.locator("#ii-active-facet")).toBeHidden();
  expect(page.url()).not.toBe(previousUrl);
  expect(runtimeErrors).toEqual([]);
});

test("a new snapshot replaces full-result facets instead of retaining the prior search", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page);
  await searchTopic(page, "first", "all");
  await expect(page.locator("#ii-programs option", { hasText: "NSF · Plasma Physics" })).toHaveCount(1);
  await searchTopic(page, "second", "NIH");
  await expect(page.locator("#ii-awards .ii-award-card[data-source='NIH']")).toHaveCount(1);
  await expect(page.locator("#ii-programs option", { hasText: "NIH · R01" })).toHaveCount(1);
  await expect(page.locator("#ii-programs option", { hasText: "NSF · Plasma Physics" })).toHaveCount(0);
  expect(runtimeErrors).toEqual([]);
});

test("ROR keyboard selection puts canonical identity in snapshot criteria", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page);
  await page.locator("#ii-institution").fill("Caltech");
  await expect(page.locator("#ii-institution-options [role='option']")).toHaveCount(1);
  await page.locator("#ii-institution").press("ArrowDown");
  await page.locator("#ii-institution").press("Enter");
  await expect(page.locator("#ii-institution")).toHaveValue("California Institute of Technology");
  await page.locator("#ii-search").click();
  const create = calls.find(call => Array.isArray(call.sources));
  expect(create.criteria).toMatchObject({ institution: "California Institute of Technology", institution_id: "https://ror.org/05dxps055" });
  expect(runtimeErrors).toEqual([]);
});

test("questions use full server aggregates and bounded hydrated evidence", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: { NSF: 26, NIH: 26, DOE: 26 } });
  await page.goto("/funded_awards.html?ii=1&ii_institution=University+of+Rochester");
  await expect(page.locator("#ii-output")).toBeVisible();
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("How many awards are in this result?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-direct-answer")).toContainText("78 normalized matching awards");
  await expect(page.locator("#ii-answer-limitations")).toContainText("78 normalized awards informed the server aggregate");
  expect(runtimeErrors).toEqual([]);
});

test("optional provider translation remains strict and feeds the snapshot request", async ({ page }) => {
  const providerCalls = [];
  await page.route("https://api.openai.com/v1/responses", async route => {
    providerCalls.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(openAiStructuredResponse({ agency: "DOE", program: "BES", topic: "", pi: "", program_officer: "", year_start: "2020", year_end: "2026", answer_intent: "count", narrative_needed: false })),
    });
  });
  const { calls, runtimeErrors } = await openSearch(page);
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-provider").selectOption("openai");
  await page.locator("#ii-key").fill("sk-unit-b-provider-test");
  await page.locator("#ii-save-key").click();
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-question").fill("How many DOE BES awards were funded from 2020 through 2026?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Agency: DOE");
  await expect(page.locator("#ii-direct-answer")).toBeVisible();
  expect(providerCalls).toHaveLength(1);
  expect(providerCalls[0].text.format.type).toBe("json_schema");
  expect(calls.find(call => Array.isArray(call.sources))).toMatchObject({ sources: ["DOE"], criteria: { program_office: "SC-32", year_start: 2020, year_end: 2026 } });
  expect(runtimeErrors).toEqual([]);
});

test("Funded Award Intelligence is keyboard-operable and contained at 390 px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 11 });
  await searchTopic(page, "mobile");
  await page.locator("#ii-card-next").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 2 of 2");
  const overflow = await page.locator("#institutional-intelligence").evaluate(element => element.scrollWidth - element.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(runtimeErrors).toEqual([]);
});

test("legacy Institutional Intelligence links redirect to Funded Awards", async ({ page }) => {
  mockAwards(page);
  await page.goto("/match_explorer.html?ii=1&ii_institution=Massachusetts+Institute+of+Technology");
  await expect(page).toHaveURL(/funded_awards\.html/);
  await expect(page.locator("#ii-institution")).toHaveValue("Massachusetts Institute of Technology");
});

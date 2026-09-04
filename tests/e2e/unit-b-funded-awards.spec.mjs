import { expect, test } from "@playwright/test";

import { chooseInvestigator, mockAwards, openAiStructuredResponse, watchRuntimeErrors } from "./helpers.mjs";

const NSF_PROGRAM_LABEL = "NSF · Mathematical and Physical Sciences › Plasma Physics";
const NIH_PROGRAM_LABEL = "NIH · National Heart, Lung, and Blood Institute › R01";
const NIH_WORKER_PROGRAM_LABEL = "NIH · R01";

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
  await expect(page.locator("#ii-status")).toContainText("Choose NSF, NIH, DOE, or DoD");
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(0);
});

test("each agency respects its source-specific 25-record hydration boundary", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: { NSF: 26, NIH: 26, DOE: 26, DOD: 26 } });
  await searchTopic(page, "catalysis", "all");
  await expect(page.locator("#ii-metrics .ii-metric").first()).toContainText("103");
  for (const source of ["NSF", "NIH", "DOE"]) {
    const button = page.locator(`[data-ii-load-source="${source}"]`);
    await expect(button).toContainText(`Load up to 25 more ${source} awards`);
    await button.click();
    await expect(page.locator("#ii-status")).toContainText(`Loaded the remaining 1 ${source} award`);
    await expect(button).toHaveCount(0);
  }
  await expect(page.locator('[data-ii-load-source="DOD"]')).toHaveCount(0);
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

test("Back and Forward restore the scroll and focus owned by each snapshot page", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 51 });
  await searchTopic(page, "history-view-state");
  const pageOneScroll = await page.evaluate(() => {
    document.querySelector("#ii-topic").focus();
    const y = Math.min(420, document.documentElement.scrollHeight - window.innerHeight);
    window.scrollTo(0, y);
    return y;
  });
  await expect.poll(() => page.evaluate(() => history.state?.focusId)).toBe("ii-topic");
  await expect.poll(() => page.evaluate(() => history.state?.scrollY)).toBe(pageOneScroll);
  await page.evaluate(() => document.querySelector('[data-ii-page-number="2"]').click());
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 2 of 6");
  const pageTwoScroll = await page.evaluate(() => {
    document.querySelector("#ii-card-next").focus();
    const y = Math.min(760, document.documentElement.scrollHeight - window.innerHeight);
    window.scrollTo(0, y);
    return y;
  });
  await expect.poll(() => page.evaluate(() => history.state?.focusId)).toBe("ii-card-next");
  await expect.poll(() => page.evaluate(() => history.state?.scrollY)).toBe(pageTwoScroll);

  await page.goBack();
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 1 of 6");
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("ii-topic");
  await expect.poll(() => page.evaluate(y => Math.abs(window.scrollY - y), pageOneScroll)).toBeLessThan(3);
  await page.goForward();
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 2 of 6");
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("ii-card-next");
  await expect.poll(() => page.evaluate(y => Math.abs(window.scrollY - y), pageTwoScroll)).toBeLessThan(3);
  expect(runtimeErrors).toEqual([]);
});

test("snapshot navigation controls stay locked until one requested view is committed", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 51, snapshotPageDelayMs: 350 });
  await searchTopic(page, "atomic-navigation");
  await page.locator('[data-ii-page-number="2"]').click();
  await expect(page.locator("#ii-card-page-numbers button").first()).toBeDisabled();
  await expect(page.locator("#ii-page-size")).toBeDisabled();
  await expect(page.locator("#ii-investigators")).toBeDisabled();
  await expect(page.locator("#ii-programs")).toBeDisabled();
  await expect(page.locator("#ii-clear-facet")).toBeDisabled();
  await expect(page.locator("#ii-clear")).toBeDisabled();
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 2 of 6");
  await expect(page.locator("#ii-page-size")).toBeEnabled();
  await expect(page.locator("#ii-card-page-numbers button").first()).toBeEnabled();
  expect(runtimeErrors).toEqual([]);
});

test("failed facet and page-size requests restore the committed view controls", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 2, snapshotPageFailAtCalls: [3, 4] });
  await searchTopic(page, "view-control-rollback", "NIH");
  await page.locator("#ii-programs").selectOption({ label: `${NIH_WORKER_PROGRAM_LABEL} (2)` });
  await expect(page.locator("#ii-active-facet")).toContainText(NIH_WORKER_PROGRAM_LABEL);
  const committedUrl = page.url();
  const committedProgram = await page.locator("#ii-programs").inputValue();

  await chooseInvestigator(page, "Stephen Dewhurst");
  await expect(page.locator("#ii-status")).toHaveClass(/error-text/);
  await expect(page.locator("#ii-investigators")).toHaveValue("all");
  await expect(page.locator("#ii-programs")).toHaveValue(committedProgram);
  await expect(page.locator("#ii-active-facet")).toContainText(NIH_WORKER_PROGRAM_LABEL);
  expect(page.url()).toBe(committedUrl);

  await page.locator("#ii-page-size").selectOption("25");
  await expect(page.locator("#ii-status")).toHaveClass(/error-text/);
  await expect(page.locator("#ii-page-size")).toHaveValue("10");
  await expect(page.locator("#ii-programs")).toHaveValue(committedProgram);
  expect(page.url()).toBe(committedUrl);
  expect(runtimeErrors.filter(error => !error.includes("503 (Service Unavailable)"))).toEqual([]);
});

test("a failed facet preserves its evidence answer and a committed facet clears it", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 2, snapshotPageFailAtCalls: [3] });
  await page.locator("#ii-institution").fill("University of Rochester");
  await searchTopic(page, "facet-answer-commit", "NIH");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("How many awards are in this result?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  const committedAnswer = await page.locator("#ii-direct-answer").textContent();

  await page.locator("#ii-programs").selectOption({ label: `${NIH_WORKER_PROGRAM_LABEL} (2)` });
  await expect(page.locator("#ii-status")).toHaveClass(/error-text/);
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer")).toHaveText(committedAnswer);
  await expect(page.locator("#ii-question-plan")).toBeVisible();

  await page.locator("#ii-programs").selectOption({ label: `${NIH_WORKER_PROGRAM_LABEL} (2)` });
  await expect(page.locator("#ii-active-facet")).toContainText(NIH_WORKER_PROGRAM_LABEL);
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  await expect(page.locator("#ii-question-plan")).toBeHidden();
  expect(runtimeErrors.filter(error => !error.includes("503 (Service Unavailable)"))).toEqual([]);
});

test("provider synthesis retains the evidence signature captured before later hydration", async ({ page }) => {
  const providerCalls = [];
  let releaseUpdate;
  let updateFulfilled = false;
  const updateGate = new Promise(resolve => { releaseUpdate = resolve; });
  await page.route("https://api.openai.com/v1/responses", async route => {
    providerCalls.push(route.request().postDataJSON());
    const call = providerCalls.length;
    if (call === 3) await updateGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(openAiStructuredResponse(call === 1
        ? { agency: "all", program: "", topic: "signature-race", pi: "", program_officer: "", year_start: "", year_end: "", answer_intent: "narrative", narrative_needed: true }
        : { claims: [{ text: call === 2 ? "Initial evidence summary." : "Updated evidence summary.", evidence_ids: ["NSF:2605508"] }] })),
    });
    if (call === 3) updateFulfilled = true;
  });
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 26 });
  await page.locator("#ii-institution").fill("University of Rochester");
  await searchTopic(page, "signature-race", "all");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-provider").selectOption("openai");
  await page.locator("#ii-key").fill("sk-signature-race-test");
  await page.locator("#ii-save-key").click();
  await page.locator("#ii-question").fill("Summarize these awards.");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-direct-answer")).toContainText("Initial evidence summary.");

  await page.locator('[data-ii-load-source="NSF"]').click();
  await expect(page.locator("#ii-update-answer")).toBeVisible();
  await page.locator("#ii-update-answer").click();
  await expect.poll(() => providerCalls.length).toBe(3);
  await page.locator('[data-ii-load-source="NIH"]').click();
  releaseUpdate();
  await expect.poll(() => updateFulfilled).toBe(true);
  await expect(page.locator("#ii-direct-answer")).toContainText("Updated evidence summary.");
  await expect(page.locator("#ii-update-answer")).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test("draft filters never relabel an active snapshot during page, size, facet, share, or reload navigation", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 26 });
  await searchTopic(page, "committed-criteria", "all");
  const committedSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");

  await page.locator("#ii-topic").fill("unsubmitted-draft");
  await page.locator("#ii-agency").selectOption("NIH");
  await page.locator('[data-ii-page-number="2"]').click();
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 2");
  let activeUrl = new URL(page.url());
  expect(activeUrl.searchParams.get("ii_snapshot")).toBe(committedSnapshot);
  expect(activeUrl.searchParams.get("ii_topic")).toBe("committed-criteria");
  expect(activeUrl.searchParams.get("ii_agency")).toBeNull();
  await expect(page.locator("#ii-topic")).toHaveValue("unsubmitted-draft");
  await expect(page.locator("#ii-agency")).toHaveValue("NIH");

  await page.locator("#ii-page-size").selectOption("25");
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 1");
  activeUrl = new URL(page.url());
  expect(activeUrl.searchParams.get("ii_topic")).toBe("committed-criteria");
  expect(activeUrl.searchParams.get("ii_agency")).toBeNull();
  await page.locator("#ii-programs").selectOption({ label: `${NIH_PROGRAM_LABEL} (26)` });
  await expect(page.locator("#ii-active-facet")).toContainText(NIH_PROGRAM_LABEL);
  activeUrl = new URL(page.url());
  expect(activeUrl.searchParams.get("ii_topic")).toBe("committed-criteria");
  expect(activeUrl.searchParams.get("ii_agency")).toBeNull();
  const sharedUrl = page.url();

  await page.goto(sharedUrl);
  await expect(page.locator("#ii-output")).toBeVisible();
  await expect(page.locator("#ii-topic")).toHaveValue("committed-criteria");
  await expect(page.locator("#ii-agency")).toHaveValue("all");
  await expect(page.locator("#ii-active-facet")).toContainText(NIH_PROGRAM_LABEL);
  expect(new URL(page.url()).searchParams.get("ii_snapshot")).toBe(committedSnapshot);
  expect(runtimeErrors).toEqual([]);
});

test("replacement search commits only after its initial snapshot bundle succeeds", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: 2, snapshotCreateDelayMs: 900 });
  await searchTopic(page, "atomic-first", "all");
  const firstUrl = page.url();
  const firstSnapshot = new URL(firstUrl).searchParams.get("ii_snapshot");

  await page.locator("#ii-topic").fill("atomic-second");
  await page.locator("#ii-search").click();
  await expect.poll(() => calls.filter(call => Array.isArray(call.sources)).length).toBe(2);
  expect(page.url()).toBe(firstUrl);
  await expect(page.locator("#ii-output")).toBeVisible();
  await expect(page.locator("#ii-topic")).toHaveValue("atomic-second");
  await expect(page.locator("#ii-search")).toBeDisabled();

  await expect.poll(() => new URL(page.url()).searchParams.get("ii_snapshot")).not.toBe(firstSnapshot);
  await expect(page.locator("#ii-search")).toBeEnabled();
  expect(new URL(page.url()).searchParams.get("ii_topic")).toBe("atomic-second");
  expect(runtimeErrors).toEqual([]);
});

test("failed creation and initial-page replacements retain one coherent owner before success and history restoration", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, {
    resultCountPerSource: 2,
    failSnapshotCreateForTopics: ["fail-create"],
    failSnapshotInitialPageForTopics: ["fail-initial-page"],
  });
  await page.locator("#ii-institution").fill("University of Rochester");
  await searchTopic(page, "stable-owner", "NSF");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("How many awards are in this result?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  const stableUrl = page.url();
  const stableSnapshot = new URL(stableUrl).searchParams.get("ii_snapshot");
  const stableEvidence = await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId));

  for (const topic of ["fail-create", "fail-initial-page"]) {
    await page.locator("#ii-topic").fill(topic);
    await page.locator("#ii-search").click();
    await expect(page.locator("#ii-search")).toBeEnabled();
    await expect(page.locator("#ii-status")).toHaveClass(/error-text/);
    expect(page.url()).toBe(stableUrl);
    expect(await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId))).toEqual(stableEvidence);
    await expect(page.locator("#ii-topic")).toHaveValue(topic);
    await expect(page.locator("#ii-question-answer")).toBeVisible();
  }

  await page.locator("#ii-topic").fill("successful-owner");
  await page.locator("#ii-agency").selectOption("NIH");
  await page.locator("#ii-search").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("ii_snapshot")).not.toBe(stableSnapshot);
  const successfulUrl = page.url();
  await expect(page.locator("#ii-awards .ii-award-card[data-source='NIH']")).toHaveCount(2);
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  await expect(page.locator("#ii-question-plan")).toBeHidden();

  await page.goBack();
  await expect.poll(() => new URL(page.url()).searchParams.get("ii_snapshot")).toBe(stableSnapshot);
  await expect(page.locator("#ii-topic")).toHaveValue("stable-owner");
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  expect(await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId))).toEqual(stableEvidence);
  await page.goForward();
  await expect(page).toHaveURL(successfulUrl);
  await expect(page.locator("#ii-topic")).toHaveValue("successful-owner");
  await expect(page.locator("#ii-awards .ii-award-card[data-source='NIH']")).toHaveCount(2);
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  expect(runtimeErrors.filter(error => !error.includes("503 (Service Unavailable)"))).toEqual([]);
});

test("an expired snapshot is rebuilt before the requested page is restored", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: 26, snapshotPageExpireAtCall: 2 });
  await searchTopic(page, "expiry-recovery");
  const originalSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  await page.locator('[data-ii-page-number="2"]').click();
  await expect(page.locator("#ii-card-page-label")).toContainText("Page 2 of 3");
  await expect(page.locator("#ii-status")).toContainText("search was refreshed");
  const refreshedSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  expect(refreshedSnapshot).not.toBe(originalSnapshot);
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(2);
  expect(runtimeErrors.filter(error => !error.includes("410 (Gone)"))).toEqual([]);
  expect(runtimeErrors.some(error => error.includes("410 (Gone)"))).toBe(true);
});

test("an expired snapshot is rebuilt before source hydration resumes at the requested offset", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: 51, snapshotBatchExpireAtCall: 1 });
  await searchTopic(page, "hydration-expiry");
  const originalSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  await page.locator('[data-ii-load-source="NSF"]').click();
  await expect(page.locator("#ii-status")).toContainText("search was refreshed before more details loaded");
  await expect(page.locator("#ii-status")).toContainText("Full details are available for 50 of 51");
  const rebuiltSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  expect(rebuiltSnapshot).not.toBe(originalSnapshot);
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(2);
  expect(calls.filter(call => call.source === "NSF" && Number.isInteger(call.offset))).toHaveLength(2);
  expect(runtimeErrors.filter(error => !error.includes("410 (Gone)"))).toEqual([]);
});

test("a fallback source-batch controller and ownership guard prevent late hydration after Back", async ({ page }) => {
  await page.addInitScript(() => {
    let configured;
    Object.defineProperty(globalThis, "FUNDING_AWARD_API_CONFIG", {
      configurable: true,
      get: () => configured,
      set: value => { configured = Object.freeze({ ...value, timeoutMs: 80 }); },
    });
  });
  const { calls, runtimeErrors } = await openSearch(page, {
    resultCountPerSource: 51,
    snapshotBatchDelaysMs: [120, 60],
  });
  await searchTopic(page, "batch-back-ownership");
  await page.locator('[data-ii-load-source="NSF"]').click();
  await expect(page.locator("#ii-status")).toContainText("NSF details could not be loaded");
  await page.locator('[data-ii-load-source="NSF"]').click();
  await page.goBack();
  await expect(page).not.toHaveURL(/ii_snapshot=/);
  await expect(page.locator("#ii-output")).toBeHidden();
  await expect(page.locator("#ii-status")).toHaveText("");
  await page.waitForTimeout(180);
  await expect(page.locator("#ii-status")).toHaveText("");
  expect(calls.filter(call => call.source === "NSF" && Number.isInteger(call.offset))).toHaveLength(2);
  expect(runtimeErrors).toEqual([]);
});

test("history restoration cannot mix a newer snapshot question into an older snapshot", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: 2 });
  await page.locator("#ii-institution").fill("University of Rochester");
  await searchTopic(page, "older-snapshot");
  const olderSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("How many awards are in this result?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer")).toContainText("2 matching awards");
  const newerSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  expect(newerSnapshot).not.toBe(olderSnapshot);
  await page.goBack();
  await expect.poll(() => new URL(page.url()).searchParams.get("ii_snapshot")).toBe(olderSnapshot);
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 1–2 of 2");
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  await expect(page.locator("#ii-question-plan")).toBeHidden();
  await expect(page.locator("#ii-question")).toHaveValue("");
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(2);
  expect(runtimeErrors).toEqual([]);
});

test("an in-flight newer-snapshot narrative cannot repopulate restored history", async ({ page }) => {
  const providerCalls = [];
  let releaseNarrative;
  let narrativeFulfilled = false;
  const narrativeGate = new Promise(resolve => { releaseNarrative = resolve; });
  await page.route("https://api.openai.com/v1/responses", async route => {
    providerCalls.push(route.request().postDataJSON());
    const translation = providerCalls.length === 1;
    if (!translation) await narrativeGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(openAiStructuredResponse(translation
        ? { agency: "NSF", program: "", topic: "", pi: "", program_officer: "", year_start: "", year_end: "", answer_intent: "narrative", narrative_needed: true }
        : { claims: [{ text: "Delayed summary for the newer snapshot.", evidence_ids: ["NSF:2605508"] }] })),
    });
    if (!translation) narrativeFulfilled = true;
  });
  const { runtimeErrors } = await openSearch(page, { resultCountPerSource: 2 });
  await page.locator("#ii-institution").fill("University of Rochester");
  await searchTopic(page, "older-snapshot");
  const olderSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-provider").selectOption("openai");
  await page.locator("#ii-key").fill("sk-history-generation-test");
  await page.locator("#ii-save-key").click();
  await page.locator("#ii-question").fill("Summarize these awards.");
  await page.locator("#ii-ask-button").click();
  await expect.poll(() => providerCalls.length).toBe(2);
  await expect.poll(() => new URL(page.url()).searchParams.get("ii_snapshot")).not.toBe(olderSnapshot);
  await page.goBack();
  await expect.poll(() => new URL(page.url()).searchParams.get("ii_snapshot")).toBe(olderSnapshot);
  releaseNarrative();
  await expect.poll(() => narrativeFulfilled).toBe(true);
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  await expect(page.locator("#ii-question-plan")).toBeHidden();
  await expect(page.locator("#ii-question")).toHaveValue("");
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
  await page.locator("#ii-programs").selectOption({ label: `${NIH_PROGRAM_LABEL} (2)` });
  await expect(page.locator("#ii-active-facet")).toContainText(NIH_PROGRAM_LABEL);
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(createCount);
  expect(runtimeErrors).toEqual([]);
});

test("failed-source retry creates a successor without discarding successful cards", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page, { failNih: true, resultCountPerSource: { NSF: 2, NIH: 0, DOE: 2 } });
  await searchTopic(page, "partial", "all");
  await expect(page.locator("#ii-source-status")).toContainText("NIH: temporarily unavailable");
  await expect(page.locator("#ii-card-page-label")).toContainText("of at least 4");
  await page.locator("#ii-programs").selectOption({ label: `${NSF_PROGRAM_LABEL} (2)` });
  await expect(page.locator("#ii-active-facet")).toBeVisible();
  const retainedIds = await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId).sort());
  const previousUrl = page.url();
  await page.locator('[data-ii-retry-source="NIH"]').click();
  await expect(page.locator("#ii-status")).toContainText("NIH is available again");
  const afterIds = await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.dataset.evidenceId).sort());
  expect(afterIds).toEqual(expect.arrayContaining(retainedIds));
  expect(afterIds.length).toBe(5);
  await expect(page.locator("#ii-programs option", { hasText: NIH_PROGRAM_LABEL })).toHaveCount(1);
  await expect(page.locator("#ii-active-facet")).toBeHidden();
  expect(page.url()).not.toBe(previousUrl);
  expect(runtimeErrors).toEqual([]);
});

test("an expired snapshot is rebuilt before a failed source retry creates its successor", async ({ page }) => {
  const { calls, runtimeErrors } = await openSearch(page, {
    failNih: true,
    resultCountPerSource: { NSF: 2, NIH: 0, DOE: 2 },
    snapshotRetryExpireAtCall: 1,
  });
  await searchTopic(page, "expired-partial", "NIH");
  const originalSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  await expect(page.locator("#ii-source-status")).toContainText("NIH: temporarily unavailable");
  await page.locator('[data-ii-retry-source="NIH"]').click();
  await expect(page.locator("#ii-status")).toContainText("search was refreshed before NIH became available again");
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 1–1 of 1");
  const successorSnapshot = new URL(page.url()).searchParams.get("ii_snapshot");
  expect(successorSnapshot).not.toBe(originalSnapshot);
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(2);
  expect(calls.filter(call => call.source === "NIH" && call.snapshot_id && !Number.isInteger(call.offset))).toHaveLength(2);
  expect(runtimeErrors.filter(error => !error.includes("410 (Gone)"))).toEqual([]);
});

test("a new snapshot replaces full-result facets instead of retaining the prior search", async ({ page }) => {
  const { runtimeErrors } = await openSearch(page);
  await searchTopic(page, "first", "all");
  await expect(page.locator("#ii-programs option", { hasText: NSF_PROGRAM_LABEL })).toHaveCount(1);
  await searchTopic(page, "second", "NIH");
  await expect(page.locator("#ii-awards .ii-award-card[data-source='NIH']")).toHaveCount(1);
  await expect(page.locator("#ii-programs option", { hasText: NIH_WORKER_PROGRAM_LABEL })).toHaveCount(1);
  await expect(page.locator("#ii-programs option", { hasText: NSF_PROGRAM_LABEL })).toHaveCount(0);
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
  await expect(page.locator("#ii-direct-answer")).toContainText("78 matching awards");
  await expect(page.locator("#ii-answer-limitations")).toContainText("78 awards were counted");
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

test("question translation locks newer searches until its owned snapshot is committed", async ({ page }) => {
  let releaseTranslation;
  const translationGate = new Promise(resolve => { releaseTranslation = resolve; });
  const providerCalls = [];
  await page.route("https://api.openai.com/v1/responses", async route => {
    providerCalls.push(route.request().postDataJSON());
    await translationGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(openAiStructuredResponse({ agency: "NSF", program: "", topic: "question-owned", pi: "", program_officer: "", year_start: "", year_end: "", answer_intent: "count", narrative_needed: false })),
    });
  });
  const { calls, runtimeErrors } = await openSearch(page, { resultCountPerSource: 26 });
  await page.locator("#ii-institution").fill("University of Rochester");
  await searchTopic(page, "manual-owner", "NSF");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-provider").selectOption("openai");
  await page.locator("#ii-key").fill("sk-question-lock-test");
  await page.locator("#ii-save-key").click();
  await page.locator("#ii-question").fill("How many question-owned NSF awards are there?");
  await page.locator("#ii-ask-button").click();
  await expect.poll(() => providerCalls.length).toBe(1);
  await expect(page.locator("#ii-search")).toBeDisabled();
  await expect(page.locator("#ii-clear")).toBeDisabled();
  await expect(page.locator("#ii-card-next")).toBeDisabled();
  const createCountWhileTranslating = calls.filter(call => Array.isArray(call.sources)).length;
  await page.locator("#ii-form").evaluate(form => form.dispatchEvent(new SubmitEvent("submit", { bubbles: true, cancelable: true })));
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(createCountWhileTranslating);
  releaseTranslation();
  await expect(page.locator("#ii-direct-answer")).toBeVisible();
  expect(calls.filter(call => Array.isArray(call.sources))).toHaveLength(createCountWhileTranslating + 1);
  expect(calls.filter(call => Array.isArray(call.sources)).at(-1)).toMatchObject({ sources: ["NSF"], criteria: { topic: "question-owned" } });
  await expect(page.locator("#ii-search")).toBeEnabled();
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

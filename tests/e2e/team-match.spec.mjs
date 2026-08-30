import { expect, test } from "@playwright/test";
import {
  addDepartmentResearcher,
  mockHybrid,
  openTeamMatch,
  watchRuntimeErrors,
} from "./helpers.mjs";

function lastName(name) {
  return String(name).trim().split(/\s+/).at(-1);
}

async function assertNoHorizontalOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client);
}

test("Team Match supports Hajim search, external researchers, team size, history, keyboard, and mobile workflows", async ({ page }) => {
  await page.addInitScript(() => {
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    globalThis.setTimeout = (callback, delay, ...args) => (
      nativeSetTimeout(callback, delay === 25 ? 350 : delay, ...args)
    );
  });
  mockHybrid(page);
  const errors = watchRuntimeErrors(page);
  await openTeamMatch(page);
  await expect(page.locator("[data-app-version]")).toContainText("Funding Finder v1.3.0");
  await expect(page.locator("#pi-grid [data-member-entry]")).toHaveCount(0);
  await expect(page.locator("#add-researcher")).toBeVisible();

  await page.locator("#add-researcher").click();
  await expect(page.locator("#researcher-search")).toBeFocused();
  await page.locator("#researcher-search").fill("Marc D. Porosoff");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  const firstLabel = "Marc D. Porosoff";
  await expect(page.locator("#researcher-picker-status")).toContainText(`${firstLabel} was added`);
  await expect(page.getByRole("button", { name: `Remove ${firstLabel} from team` })).toBeVisible();

  const second = await addDepartmentResearcher(page, 0);
  await expect(page.locator("#selected-terms .st-card")).toHaveCount(2);
  await expect(page.locator("#count")).toContainText("fit every selected researcher");

  await page.locator("#add-external-researcher").click();
  await expect(page.locator("#external-researcher-form")).toBeVisible();
  await page.locator("#external-name").fill("Gate Four Researcher");
  await page.locator("#external-keywords").fill("catalysis, electrochemistry, chemical engineering, carbon capture");
  await page.getByRole("button", { name: /Save researcher/i }).click();
  await expect(page.getByRole("button", { name: "Remove Gate Four Researcher from team" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add saved Gate Four Researcher to team" })).toHaveCount(0);
  const selectedMembers = await page.locator("#pi-grid [data-member-entry]").evaluateAll(entries => entries.map(entry => entry.dataset.memberEntry));
  expect(new Set(selectedMembers).size).toBe(3);

  const fourth = await addDepartmentResearcher(page, 0);
  await expect(page.locator("#pi-grid [data-member-entry]")).toHaveCount(4);
  await expect(page.locator("#add-researcher")).toBeHidden();
  await expect(page.locator("#add-external-researcher")).toBeHidden();
  await page.getByRole("button", { name: `Remove ${fourth.label} from team` }).click();
  await expect(page.locator("#add-researcher")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ forcedColors: "active" });
  await assertNoHorizontalOverflow(page);
  await page.emulateMedia({ forcedColors: "none", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 320, height: 720 });
  await assertNoHorizontalOverflow(page);

  await page.locator("#view .team-result-card").first().scrollIntoViewIfNeeded();
  const priorScroll = await page.evaluate(() => window.scrollY);
  expect(priorScroll).toBeGreaterThan(0);
  await page.goto("/match_explorer.html?gate4-team-history=1");
  await page.goBack();
  await expect(page.getByRole("button", { name: `Remove ${firstLabel} from team` })).toBeVisible();
  await expect(page.getByRole("button", { name: `Remove ${second.label} from team` })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove Gate Four Researcher from team" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY), { timeout: 5_000 }).toBeGreaterThan(0);
  expect(errors.filter(error => !error.includes("Failed to load resource"))).toEqual([]);
});

test("the Hajim directory is lazy, bounded, keyboard operable, and separate from external entry", async ({ page }) => {
  mockHybrid(page);
  let directoryRequests = 0;
  page.on("request", request => {
    if (/data\/hajim-faculty-directory\.js/.test(request.url())) directoryRequests += 1;
  });
  await openTeamMatch(page);
  expect(directoryRequests).toBe(0);
  await page.locator("#add-researcher").click();
  await expect.poll(() => directoryRequests).toBe(1);
  await page.locator("#researcher-search").fill("engineering");
  await expect(page.locator("#researcher-options [role=option]")).toHaveCount(12);
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#researcher-search")).toHaveAttribute("aria-activedescendant", /researcher-option-0/);
  await page.keyboard.press("Escape");
  await expect(page.locator("#researcher-options")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.locator("#researcher-picker")).toBeHidden();
  await expect(page.locator("#add-researcher")).toBeFocused();
  await page.locator("#add-external-researcher").click();
  await expect(page.locator("#external-researcher-form")).toBeVisible();
});

test("directory failure leaves the external researcher workflow usable", async ({ page }) => {
  mockHybrid(page);
  await page.route("**/data/hajim-faculty-directory.js*", route => route.fulfill({
    status: 503,
    contentType: "text/javascript",
    body: "",
  }));
  await openTeamMatch(page);
  await page.locator("#add-researcher").click();
  await expect(page.locator("#researcher-picker-status")).toContainText(/could not be loaded/i);
  await page.locator("#add-external-researcher").click();
  await page.locator("#external-name").fill("Outside Collaborator");
  await page.locator("#external-keywords").fill("quantum sensing, microfluidic transport, laser diagnostics");
  await page.getByRole("button", { name: /Save researcher/i }).click();
  await expect(page.getByRole("button", { name: "Remove Outside Collaborator from team" })).toBeVisible();
});

test("enhanced ordering can reorder only locally eligible every-member-fit results", async ({ page }) => {
  const calls = mockHybrid(page, { reverseRerank: true, rerankDelayMs: 900 });
  await openTeamMatch(page);
  const first = await addDepartmentResearcher(page, 0);
  const second = await addDepartmentResearcher(page, 0);
  await expect(page.locator("#team-hybrid-status")).toContainText(/Finding enhanced ordering|Enhanced ordering is applied/);
  const localIds = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  expect(localIds.length).toBeGreaterThan(0);
  await expect(page.locator("#team-hybrid-status")).toContainText(/Enhanced ordering is applied/, { timeout: 30_000 });
  await expect.poll(() => calls.embed.length).toBe(1);
  await expect.poll(() => calls.rerank.length).toBe(1);
  const enhancedIds = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  expect([...enhancedIds].sort()).toEqual([...localIds].sort());

  const expected = [lastName(first.label), lastName(second.label)].sort();
  const fitNames = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => (
    [...card.querySelectorAll(".team-overlap .pi .name")].map(node => node.textContent.trim()).sort()
  )));
  expect(fitNames.length).toBeGreaterThan(0);
  for (const names of fitNames) expect(names).toEqual(expected);
  await expect(page.locator("#researcher-picker-status")).toContainText("was added");
  await expect(page.locator("#team-hybrid-status")).toContainText("Enhanced ordering");
});

test("Team Match sidecar failure keeps parent-level matching and disables enhanced ordering", async ({ page }) => {
  const calls = mockHybrid(page);
  await openTeamMatch(page, { sidecarFailure: true });
  await addDepartmentResearcher(page, 0);
  await addDepartmentResearcher(page, 0);
  await expect(page.locator("#team-topic-layer-status")).toContainText(/Parent-level team matching still works/i);
  await expect(page.locator("#view .team-result-card").first()).toBeVisible();
  expect(calls.embed).toHaveLength(0);
  expect(calls.rerank).toHaveLength(0);
  await expect(page.locator("#team-hybrid-status")).toContainText(/local team-fit order.*temporarily unavailable/i);
});

test("enhanced-ordering failure leaves local team-fit results usable with a nontechnical message", async ({ page }) => {
  const calls = mockHybrid(page, { failEveryEmbed: true, retryAfter: 1 });
  await openTeamMatch(page);
  await addDepartmentResearcher(page, 0);
  await addDepartmentResearcher(page, 0);
  const localIds = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  expect(localIds.length).toBeGreaterThan(0);
  await expect(page.locator("#team-hybrid-status")).toContainText(/Showing the local team-fit order.*temporarily limited/i, { timeout: 30_000 });
  expect(calls.embed).toHaveLength(1);
  const fallbackIds = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  expect(fallbackIds).toEqual(localIds);
});

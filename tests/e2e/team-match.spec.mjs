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

test("Team Match supports directory, browser-only, team-size, history, and mobile workflows", async ({ page }) => {
  const navigationUrls = [];
  page.on("request", request => {
    if (request.isNavigationRequest()) navigationUrls.push(request.url());
  });
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
  await expect(page.locator("#faculty-search-status")).toContainText("Search by name", { timeout: 30_000 });
  await page.locator("#show-faculty-suggestions").click();
  await expect(page.locator('#faculty-suggestions [role="option"]:not([aria-disabled="true"])').first()).toBeVisible();
  const first = await addDepartmentResearcher(page, "Alexander A. Shestopalov");
  const firstValue = first.value;
  const firstLabel = first.label;
  await expect(page.locator("#external-status")).toContainText(`${firstLabel} was added from the`);

  const second = await addDepartmentResearcher(page, "Allison J. Lopatkin");
  await expect(page.locator("#selected-terms .st-card")).toHaveCount(2);
  await expect(page.locator("#count")).toContainText("fit every selected researcher");

  await page.locator("#add-researcher").click();
  await expect(page.locator("#missing-researcher")).toHaveJSProperty("tagName", "BUTTON");
  await expect(page.locator("#missing-researcher")).not.toHaveAttribute("href", /.+/);
  await page.locator("#missing-researcher").click();
  await expect(page).toHaveURL(/faculty_interests\.html\?mode=add&return=team_match/);
  await expect(page.getByRole("radio", { name: /Add a missing researcher/ })).toBeChecked();
  await page.locator("#display-name").fill("Gate Four Researcher");
  await page.locator("#research-claims").fill("catalysis\nelectrochemistry\nchemical engineering\ncarbon capture");
  await page.locator("#add-locally").click();
  await expect(page).toHaveURL(/team_match\.html/);
  expect(page.url()).not.toContain("ext-gate-four-researcher");
  await expect(page.getByRole("button", { name: "Remove Gate Four Researcher from team", exact: true })).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => new URL(page.url()).searchParams.get("handoff")).toBeNull();
  await page.reload();
  await expect(page.getByRole("button", { name: "Remove Gate Four Researcher from team", exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#external-status")).toBeHidden();
  await expect(page.locator("#researcher-choice option", { hasText: "Gate Four Researcher" })).toHaveCount(0);
  const selectedMembers = await page.locator("#pi-grid [data-member-entry]").evaluateAll(entries => entries.map(entry => entry.dataset.memberEntry));
  expect(new Set(selectedMembers).size).toBe(3);

  await page.locator("#add-researcher").click();
  await page.locator("#missing-researcher").click();
  await expect(page.getByRole("radio", { name: /Add a missing researcher/ })).toBeChecked();
  await page.locator("#display-name").fill("Gate Five Researcher");
  await page.locator("#research-claims").fill("catalysis\nelectrochemistry\nreaction engineering");
  await page.locator("#add-locally").click();
  await expect(page).toHaveURL(/team_match\.html/);
  expect(page.url()).not.toContain("ext-gate-five-researcher");
  await expect(page.getByRole("button", { name: "Remove Gate Four Researcher from team", exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Remove Gate Five Researcher from team", exact: true })).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => new URL(page.url()).searchParams.get("handoff")).toBeNull();
  await expect(page.getByRole("button", { name: `Remove ${firstLabel} from team` })).toBeVisible();
  await expect(page.getByRole("button", { name: `Remove ${second.label} from team` })).toBeVisible();
  await page.getByRole("button", { name: "Remove Gate Five Researcher from team", exact: true }).click();
  await expect(page.locator("#pi-grid [data-member-entry]")).toHaveCount(3);

  const fourth = await addDepartmentResearcher(page, "Astrid M. Müller");
  await expect(page.locator("#pi-grid [data-member-entry]")).toHaveCount(4);
  await expect(page.locator("#add-researcher")).toBeHidden();
  await page.getByRole("button", { name: `Remove ${fourth.label} from team` }).click();
  await expect(page.locator("#add-researcher")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await page.setViewportSize({ width: 320, height: 720 });
  await assertNoHorizontalOverflow(page);

  await page.locator("#view .team-result-card").first().scrollIntoViewIfNeeded();
  const priorScroll = await page.evaluate(() => window.scrollY);
  expect(priorScroll).toBeGreaterThan(0);
  await page.goto("/match_explorer.html?gate4-team-history=1");
  await page.goBack();
  await expect(page.getByRole("button", { name: `Remove ${firstLabel} from team` })).toBeVisible();
  await expect(page.getByRole("button", { name: `Remove ${second.label} from team` })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove Gate Four Researcher from team", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY), { timeout: 5_000 }).toBeGreaterThan(0);
  const handoffTokens = navigationUrls.map(url => new URL(url).searchParams.get("handoff")).filter(Boolean);
  expect(handoffTokens).toHaveLength(4);
  expect(handoffTokens.every(token => /^[a-f0-9]{32}$/.test(token))).toBe(true);
  expect(handoffTokens[0]).toBe(handoffTokens[1]);
  expect(handoffTokens[2]).toBe(handoffTokens[3]);
  expect(handoffTokens[2]).not.toBe(handoffTokens[0]);
  expect(navigationUrls.some(url => /ext-gate-(?:four|five)-researcher|[?&]locals?=/.test(url))).toBe(false);
  expect(errors.filter(error => !error.includes("Failed to load resource"))).toEqual([]);
});

test("a deferred four-person team cannot lose a member through Configure", async ({ page }) => {
  mockHybrid(page);
  const errors = watchRuntimeErrors(page);
  await openTeamMatch(page);
  const selectedIdentities = [];
  for (const name of [
    "Alexander A. Shestopalov",
    "Allison J. Lopatkin",
    "Astrid M. Müller",
    "Zachary Robinson",
  ]) {
    const added = await addDepartmentResearcher(page, name);
    selectedIdentities.push({ kind: "directory", id: added.value });
  }
  await expect(page.locator("#pi-grid [data-member-entry]")).toHaveCount(4);
  await expect(page.locator("#add-researcher")).toBeHidden();
  await page.evaluate(identities => {
    history.replaceState({
      fundingFinderTeamMatch: {
        selected: [],
        selectedIdentities: identities,
        themeState: {},
        filter: "",
        scrollY: 0,
      },
    }, "");
  }, selectedIdentities);

  await page.route("**/data/opportunity_teams.js*", route => route.fulfill({
    status: 503,
    contentType: "text/javascript",
    body: "",
  }));
  await page.reload();
  await expect(page.locator("#external-status")).toContainText("saved team is preserved", { timeout: 30_000 });
  await expect(page.locator("#add-researcher")).toBeVisible();
  await page.locator("#add-researcher").click();
  await expect(page.locator("#faculty-search-status")).toContainText("preserved four-person team", { timeout: 30_000 });
  await expect(page.locator("#missing-researcher")).toBeDisabled();
  await expect(page.locator("#missing-researcher")).toHaveAttribute("title", /already has four researchers/);
  expect(await page.evaluate(() => sessionStorage.getItem("funding-finder.team-handoff.v1"))).toBeNull();
  expect(errors.filter(error => !error.includes("Failed to load resource"))).toEqual([]);
});

test("enhanced ordering can reorder only locally eligible every-member-fit results", async ({ page }) => {
  const calls = mockHybrid(page, { reverseRerank: true, rerankDelayMs: 900 });
  await openTeamMatch(page);
  const first = await addDepartmentResearcher(page, "Alexander A. Shestopalov");
  const second = await addDepartmentResearcher(page, "Allison J. Lopatkin");
  await expect(page.locator("#team-hybrid-status")).toContainText(/Finding enhanced ordering/);
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
  await expect(page.locator("#researcher-picker-status")).toHaveText("");
  await expect(page.locator("#team-hybrid-status")).toContainText("Enhanced ordering");
});

test("Team Match sidecar failure keeps parent-level matching and disables enhanced ordering", async ({ page }) => {
  const calls = mockHybrid(page);
  await openTeamMatch(page, { sidecarFailure: true });
  await addDepartmentResearcher(page, "Alexander A. Shestopalov");
  await addDepartmentResearcher(page, "Allison J. Lopatkin");
  await expect(page.locator("#team-topic-layer-status")).toContainText(/Parent-level team matching still works/i);
  await expect(page.locator("#view .team-result-card").first()).toBeVisible();
  expect(calls.embed).toHaveLength(0);
  expect(calls.rerank).toHaveLength(0);
  await expect(page.locator("#team-hybrid-status")).toContainText(/local team-fit order.*temporarily unavailable/i);
});

test("enhanced-ordering failure leaves local team-fit results usable with a nontechnical message", async ({ page }) => {
  const calls = mockHybrid(page, { failEveryEmbed: true, retryAfter: 1 });
  await openTeamMatch(page);
  await addDepartmentResearcher(page, "Alexander A. Shestopalov");
  await addDepartmentResearcher(page, "Allison J. Lopatkin");
  const localIds = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  expect(localIds.length).toBeGreaterThan(0);
  await expect(page.locator("#team-hybrid-status")).toContainText(/Showing the local team-fit order.*temporarily limited/i, { timeout: 30_000 });
  expect(calls.embed).toHaveLength(1);
  const fallbackIds = await page.locator("#view .team-result-card").evaluateAll(cards => cards.map(card => card.dataset.opportunityId));
  expect(fallbackIds).toEqual(localIds);
});

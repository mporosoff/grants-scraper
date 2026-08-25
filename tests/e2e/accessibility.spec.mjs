import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
  addDepartmentResearcher,
  mockAwards,
  mockAlerts,
  mockHybrid,
  openFundingFinder,
  openTeamMatch,
  runFundingSearch,
  waitForHybridSettled,
} from "./helpers.mjs";

async function scan(page, label, testInfo) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const serious = result.violations.filter(item => ["serious", "critical"].includes(item.impact));
  const lower = result.violations.filter(item => !["serious", "critical"].includes(item.impact));
  await testInfo.attach(`axe-${label}.json`, {
    body: Buffer.from(JSON.stringify({
      label,
      serious,
      lower,
      incomplete: result.incomplete,
    }, null, 2)),
    contentType: "application/json",
  });
  console.log(`a11y ${label}: serious=${serious.length} lower=${lower.length} incomplete=${result.incomplete.length}`);
  expect(serious, `${label} serious/critical axe violations`).toEqual([]);
  return { lower, incomplete: result.incomplete };
}

test("Funding Finder has no serious or critical violations across critical states", async ({ page, context }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  mockHybrid(page);
  await openFundingFinder(page);
  await expect(page.getByLabel("Search funding opportunities")).toBeVisible();
  await expect(page.locator("#search-status")).toHaveAttribute("aria-live", "polite");
  expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  await scan(page, "funding-initial", testInfo);

  const helpButton = page.getByRole("button", { name: "Help" });
  await helpButton.click();
  const helpDialog = page.getByRole("dialog");
  await expect(helpDialog).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.querySelector("#help-guide")?.contains(document.activeElement))).toBe(true);
  await scan(page, "funding-help-open", testInfo);
  await page.keyboard.press("Escape");
  await expect(helpDialog).toBeHidden();
  await expect(helpButton).toBeFocused();

  await runFundingSearch(page, "catalysis science");
  await waitForHybridSettled(page);
  await scan(page, "funding-strong-potential", testInfo);
  mockAlerts(page);
  await page.locator("#alert-new-matches").click();
  const alertDialog = page.getByRole("dialog", { name: "Alert me to new Strong matches" });
  await expect(alertDialog).toBeVisible();
  await expect(alertDialog.locator("#alert-email")).toBeFocused();
  await scan(page, "funding-alert-dialog", testInfo);
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(page.locator("#alert-new-matches")).toBeFocused();
  const chatButton = page.locator("#open-results-chat");
  await chatButton.click();
  await expect(page.locator("#result-assistant")).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.querySelector("#result-assistant")?.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.locator("#result-assistant")).toBeHidden();
  await expect(chatButton).toBeFocused();

  const fallback = await context.newPage();
  await fallback.emulateMedia({ reducedMotion: "reduce" });
  mockHybrid(fallback, { failEveryEmbed: true, retryAfter: 10 });
  await openFundingFinder(fallback);
  await runFundingSearch(fallback, "DE-FOA-0003600");
  await expect(fallback.locator("#potential-status")).toContainText(/temporarily limited/i, { timeout: 30_000 });
  await expect(fallback.locator("#retry-potential")).toBeDisabled();
  await scan(fallback, "funding-potential-fallback", testInfo);
  await fallback.close();
});

test("Team Match has no serious or critical violations across picker, results, and fallback states", async ({ page, context }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  mockHybrid(page);
  await openTeamMatch(page);
  await page.locator("#add-researcher").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#researcher-picker")).toBeVisible();
  await expect(page.getByLabel("Choose a researcher")).toBeVisible();
  await scan(page, "team-picker-open", testInfo);
  await page.locator("#add-researcher").click();
  await addDepartmentResearcher(page, 0);
  await addDepartmentResearcher(page, 0);
  await expect(page.locator("#view .team-result-card").first()).toBeVisible();
  await expect(page.locator("#team-hybrid-status")).toContainText(/Enhanced ordering is applied/, { timeout: 30_000 });
  await scan(page, "team-two-person-results", testInfo);

  const fallback = await context.newPage();
  await fallback.emulateMedia({ reducedMotion: "reduce" });
  mockHybrid(fallback, { failEveryEmbed: true, retryAfter: 1 });
  await openTeamMatch(fallback);
  await addDepartmentResearcher(fallback, 0);
  await addDepartmentResearcher(fallback, 0);
  await expect(fallback.locator("#team-hybrid-status")).toContainText(/local team-fit order.*temporarily limited/i, { timeout: 30_000 });
  await scan(fallback, "team-enhanced-fallback", testInfo);
  await fallback.close();
});

test("Funded Awards has no serious or critical violations and fits narrow mobile layouts", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  mockAwards(page);
  await page.goto("/funded_awards.html");
  await expect(page.locator("#award-search-form")).toBeVisible();
  await scan(page, "awards-initial-mobile", testInfo);
  await page.locator("#award-query").fill("warm dense matter");
  await page.locator("#award-institution").fill("University of Rochester");
  await page.locator("#search-awards").click();
  await expect(page.locator(".award-card").first()).toBeVisible();
  await scan(page, "awards-results-mobile", testInfo);
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const statusPill = page.locator(".header-context-pill");
  await expect(statusPill).toHaveText("NSF + NIH + DOE awards");
  expect(await statusPill.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
});

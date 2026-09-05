import { expect, test } from "@playwright/test";
import {
  mockHybrid,
  openFundingFinder,
  runFundingSearch,
} from "./helpers.mjs";

test.beforeEach(async ({ page }) => {
  mockHybrid(page);
});

test("search lands on compact results with utilities reachable through More", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis");
  await expect(page.locator("#personal-workspace")).not.toHaveAttribute("open", "");
  await expect(page.locator("#open-results-chat")).toHaveText("Ask AI");
  await expect(page.locator("#filter-team-ready")).toHaveText("Team options only");
  await page.locator('[data-shell-menu="results"]').click();
  await expect(page.locator("#export-csv")).toBeVisible();
  await expect(page.locator("#export-ics")).toHaveCount(0);
});

test("Team Builder replaces the closed context without reusing the prior proposal", async ({ page }) => {
  await openFundingFinder(page);
  await page.locator("#browse-all").click();
  await page.locator("#filter-team-ready").click();
  const triggers = page.locator("#results [data-opportunity-team]");
  await expect.poll(() => triggers.count()).toBeGreaterThanOrEqual(2);
  await triggers.nth(0).click();
  await expect(page.locator("#team-builder")).toBeVisible();
  const firstPanelId = await page.locator(".opportunity-team-panel").getAttribute("id");
  await page.locator("#team-builder [data-shell-drawer-close]").click();
  await expect(triggers.nth(0)).toBeFocused();
  await triggers.nth(1).click();
  await expect(page.locator(".opportunity-team-panel")).toHaveCount(1);
  await expect(page.locator(`#${firstPanelId}`)).toHaveCount(0);
  await expect(triggers.nth(0)).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Escape");
  await expect(triggers.nth(1)).toBeFocused();
  await expect(page.locator(".opportunity-team-panel")).toHaveCount(0);
});

test("Funded Awards opens directly on the working search without the redundant banner", async ({ page }) => {
  const runtimeErrors = [];
  page.on("pageerror", error => runtimeErrors.push(error.message));
  await page.goto("/funded_awards.html");
  await expect(page.locator("#ii-heading")).toHaveText(
    "Find funded projects and understand the result set",
  );
  await expect(page.locator("#ii-form")).toBeVisible();
  await expect(page.locator(".ii-shell-heading")).toHaveCount(0);
  await expect(page.getByText("Funded Award Intelligence", { exact: true })).toHaveCount(0);
  expect(runtimeErrors).toEqual([]);
});

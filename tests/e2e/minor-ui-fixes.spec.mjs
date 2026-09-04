import { expect, test } from "@playwright/test";
import {
  mockHybrid,
  openFundingFinder,
  runFundingSearch,
} from "./helpers.mjs";

test.beforeEach(async ({ page }) => {
  mockHybrid(page);
});

test("search lands on saved opportunities with all three blue result actions visible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openFundingFinder(page);
  await runFundingSearch(page, "catalysis");

  await expect.poll(() => page.locator("#saved-panel").evaluate(element => {
    const top = Math.round(element.getBoundingClientRect().top);
    return top >= 72 && top <= 90;
  })).toBe(true);
  const geometry = await page.evaluate(() => {
    const saved = document.querySelector("#saved-panel").getBoundingClientRect();
    const toolbar = document.querySelector("#results-toolbar").getBoundingClientRect();
    return {
      savedTop: saved.top,
      toolbarTop: toolbar.top,
      toolbarBottom: toolbar.bottom,
      viewportHeight: window.innerHeight,
    };
  });
  expect(geometry.toolbarTop).toBeGreaterThanOrEqual(geometry.savedTop);
  expect(geometry.toolbarBottom).toBeLessThanOrEqual(geometry.viewportHeight);
  await expect(page.locator("#export-csv")).toHaveClass(/\bprimary\b/);
  await expect(page.locator("#filter-team-ready")).toHaveClass(/\bprimary\b/);
  await expect(page.locator("#open-results-chat")).toHaveClass(/\bprimary\b/);
  await expect(page.locator("#export-ics")).toHaveCount(0);
});

test("more than one opportunity team can remain open without reusing the prior panel", async ({ page }) => {
  await openFundingFinder(page);
  await page.locator("#browse-all").click();
  await expect(page.locator("#filter-team-ready")).toBeEnabled();
  await page.locator("#filter-team-ready").click();

  const triggers = page.locator("#results [data-opportunity-team]");
  await expect.poll(() => triggers.count()).toBeGreaterThanOrEqual(2);
  await triggers.nth(0).click();
  await expect(page.locator(".opportunity-team-panel")).toHaveCount(1);
  const firstPanelId = await triggers.nth(0).getAttribute("aria-controls");
  await triggers.nth(1).click();
  await expect(page.locator(".opportunity-team-panel")).toHaveCount(2);
  const secondPanelId = await triggers.nth(1).getAttribute("aria-controls");
  expect(secondPanelId).not.toBe(firstPanelId);
  await expect(triggers.nth(0)).toHaveAttribute("aria-expanded", "true");
  await expect(triggers.nth(1)).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(`#${firstPanelId}`)).toBeVisible();
  await expect(page.locator(`#${secondPanelId}`)).toBeVisible();

  await page.locator(`#${firstPanelId} [data-opportunity-team-close]`).click();
  await expect(page.locator(`#${firstPanelId}`)).toHaveCount(0);
  await expect(page.locator(`#${secondPanelId}`)).toBeVisible();
  await expect(triggers.nth(0)).toHaveAttribute("aria-expanded", "false");
  await expect(triggers.nth(1)).toHaveAttribute("aria-expanded", "true");
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

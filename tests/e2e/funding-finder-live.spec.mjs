import { expect, test } from "@playwright/test";
import {
  openFundingFinder,
} from "./helpers.mjs";

test("the daily Funding Finder catalog loads as a usable application package", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await openFundingFinder(page);
  await expect(page.locator("[data-app-version]")).toContainText("Funding Finder v1.3.0");
  await expect(page.locator("#search-form")).toBeVisible();
  await expect(page.locator("#sort")).toBeAttached();
  await expect(page.locator("#sort")).toBeEnabled();
  await page.locator("#browse-all").click();
  await expect(page.locator("#results .result-card").first()).toBeVisible();
  await expect(page.locator("#search-status")).toContainText(/showing|opportunit/i);
  expect(pageErrors).toEqual([]);
});

import { expect, test } from "@playwright/test";
import { mockAwards, mockHybrid } from "./helpers.mjs";

test("legacy Institutional Intelligence bookmarks remain compatible with Funded Awards", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page);
  await page.goto("/match_explorer.html?ii=1&ii_institution=Massachusetts+Institute+of+Technology&ii_ror=https%3A%2F%2Fror.org%2F042nb2s44");
  await expect(page).toHaveURL(/funded_awards\.html\?ii=1/);
  await expect(page.locator("#institutional-intelligence")).toBeVisible();
  await expect(page.locator("#ii-institution")).toHaveValue("Massachusetts Institute of Technology");
});

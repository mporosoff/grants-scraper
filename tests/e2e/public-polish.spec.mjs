import { expect, test } from "@playwright/test";
import { mockAwards, mockHybrid, openFundingFinder, runFundingSearch } from "./helpers.mjs";

test("Funding Finder retains its hero and Team Builder contains text at phone widths and enlarged text", async ({ page }) => {
  mockHybrid(page);
  await page.setViewportSize({ width: 320, height: 780 });
  await openFundingFinder(page);
  const title = await page.locator("#page-title").textContent();
  const before = await page.locator("#funding-search").evaluate(node => getComputedStyle(node).backgroundImage);
  await runFundingSearch(page, "catalysis");
  await expect(page.locator("#page-title")).toHaveText(title);
  await expect(page.locator(".search-introduction")).toBeVisible();
  expect(await page.locator("#funding-search").evaluate(node => getComputedStyle(node).backgroundImage)).toBe(before);
  await page.locator("#clear-search").click();
  await page.locator("#browse-all").click();
  await expect(page.locator("#filter-team-ready")).toBeVisible();
  await page.locator("#filter-team-ready").click();
  await page.locator("[data-opportunity-team]").first().click();
  await expect(page.locator("#team-builder")).toBeVisible();
  for (const width of [320, 390]) for (const size of [16, 24]) {
    await page.setViewportSize({ width, height: 780 });
    await page.evaluate(size => document.documentElement.style.setProperty("font-size", `${size}px`, "important"), size);
    const overflow = await page.locator("#team-builder").evaluate(dialog => {
      const bounds = dialog.getBoundingClientRect();
      return [...dialog.querySelectorAll("h4, h5, .badge, .opportunity-team-role-state, .opportunity-team-member, .opportunity-team-heading")].filter(node => node.getClientRects().length).filter(node => {
        const box = node.getBoundingClientRect();
        return box.left < bounds.left || box.right > bounds.right + 1 || node.scrollWidth > node.clientWidth + 1;
      }).map(node => node.className || node.tagName);
    });
    expect(overflow).toEqual([]);
  }
});

test("Researcher institution supports keyboard ROR selection, draft isolation and browser-local retention", async ({ page }) => {
  mockAwards(page);
  await page.goto("/faculty_interests.html?mode=add");
  await page.locator("#institution-name").fill("Caltech");
  await expect(page.locator("#institution-options [role='option']")).toHaveCount(1);
  await page.locator("#institution-name").press("ArrowDown");
  await page.locator("#institution-name").press("Enter");
  await expect(page.locator("#institution-name")).toHaveValue("California Institute of Technology");
  await expect(page.locator("#institution-ror-id")).toHaveValue("https://ror.org/05dxps055");
  await page.locator('[name="request_type"][value="profile_correction"]').check();
  await expect(page.locator("#institution-name")).toHaveValue("");
  await page.locator('[name="request_type"][value="new_researcher_nomination"]').check();
  await expect(page.locator("#institution-ror-id")).toHaveValue("https://ror.org/05dxps055");
  await page.locator("#display-name").fill("Institution Workflow Researcher");
  await page.locator("#research-claims").fill("catalysis\nreaction engineering\nhydrogen conversion");
  await page.locator("#add-locally").click();
  const saved = await page.evaluate(() => FUNDING_TEAM_RESEARCHERS.load(localStorage).profiles);
  expect(saved[0].institution).toEqual({ name: "California Institute of Technology", ror_id: "https://ror.org/05dxps055" });
  await expect(page.locator("#institution-name")).toHaveValue("");
});

test("Researcher review sends only optional institution metadata and clears a ROR identity when edited", async ({ page }) => {
  mockAwards(page); let submitted;
  await page.route("**/submissions", async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ json: { submission_id: "test-receipt", status_url: "https://example.edu/status" } });
  });
  await page.goto("/faculty_interests.html?mode=add");
  await page.locator("#institution-name").fill("Caltech");
  await page.locator("#institution-options [role='option']").click();
  await page.locator("#institution-name").fill("Different Institution");
  await expect(page.locator("#institution-ror-id")).toHaveValue("");
  await page.locator("#display-name").fill("Reviewed Researcher");
  await page.locator("#research-claims").fill("Catalysis");
  await page.locator("#source-urls").fill("https://example.edu/researcher");
  await page.locator("#review-consent").check();
  await page.locator("#submit-request").click();
  await expect(page.locator("#receipt")).toBeVisible();
  expect(submitted.proposed_profile.institution).toEqual({ name: "Different Institution", ror_id: "" });
  expect(submitted.proposed_profile).not.toHaveProperty("auto_proposable");
});

test("Late ROR responses and lookup failures cannot overwrite a different researcher draft", async ({ page }) => {
  let requests = 0;
  await page.route("**/institutions/search?*", async route => {
    requests += 1;
    await new Promise(resolve => setTimeout(resolve, 650));
    await route.fulfill({ json: { institutions: [{ id: "https://ror.org/05dxps055", canonical_name: "California Institute of Technology" }] } }).catch(() => {});
  });
  await page.goto("/faculty_interests.html?mode=add");
  await page.locator("#institution-name").fill("Caltech");
  await expect.poll(() => requests).toBe(1);
  await page.locator('[name="request_type"][value="profile_correction"]').check();
  await page.waitForTimeout(800);
  await expect(page.locator("#institution-options")).toBeHidden();
  await expect(page.locator("#institution-name")).toHaveValue("");
  await page.unroute("**/institutions/search?*");
  await page.route("**/institutions/search?*", route => route.fulfill({ status: 503, json: { error: "unavailable" } }));
  await page.locator("#institution-name").fill("Example University");
  await expect(page.locator("#institution-status")).toContainText("temporarily unavailable");
  await expect(page.locator("#institution-name")).toHaveValue("Example University");
  await expect(page.locator("#institution-ror-id")).toHaveValue("");
});

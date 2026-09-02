import { expect, test } from "@playwright/test";
import {
  mockAwards,
  mockAlerts,
  mockFrozenAwardCatalog,
} from "./helpers.mjs";

// Snapshot-native standalone coverage lives in unit-b-funded-awards.spec.mjs.
// These tests retain the exact-opportunity and cross-product compatibility surface.

test("standalone paging and investigator handoff retain the submitted year range", async ({ page }) => {
  await mockFrozenAwardCatalog(page);
  const calls = mockAwards(page, {
    hasMoreBySource: { NSF: [0] },
    resultCountPerSource: { NSF: 1 },
  });
  await page.goto("/funded_awards.html?opportunity=363616&institution=University+of+Rochester&year_start=2024&year_end=2026");
  await expect.poll(() => calls.at(-1)?.criteria?.year_start).toBe(2024);
  await page.locator("#year-start").evaluate(element => { element.value = "1999"; });
  await page.locator("#year-end").evaluate(element => { element.value = "2000"; });

  await page.locator("#award-next").click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(25);
  expect(calls.at(-1).criteria).toMatchObject({ year_start: 2024, year_end: 2026 });
  await page.locator("#award-previous").click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(0);
  expect(calls.at(-1).criteria).toMatchObject({ year_start: 2024, year_end: 2026 });

  await page.locator("[data-award-pi='Vasily Karasiev']").click();
  await expect.poll(() => calls.findLast(call => call.criteria?.pi === "Vasily Karasiev")?.criteria).toMatchObject({
    pi: "Vasily Karasiev",
    institution: "University of Rochester",
    year_start: 2024,
    year_end: 2026,
  });
  await expect(page.locator("#ii-year-start")).toHaveValue("2024");
  await expect(page.locator("#ii-year-end")).toHaveValue("2026");
});

test("the Funded Awards status badge remains complete inside a narrow mobile header", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.goto("/funded_awards.html");
  const pill = page.locator(".header-context-pill");
  await expect(pill).toHaveText("NSF · NIH · DOE");
  await expect(pill).toHaveAttribute("aria-label", "NSF, NIH, and DOE award sources available");
  const geometry = await pill.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return {
      left: bounds.left,
      right: bounds.right,
      viewportWidth: window.innerWidth,
      contentWidth: element.scrollWidth,
      visibleWidth: element.clientWidth,
    };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth);
  expect(geometry.contentWidth).toBeLessThanOrEqual(geometry.visibleWidth);
});

test("the frozen NIH example opens its exact opportunity mapping", async ({ page }) => {
  await mockFrozenAwardCatalog(page);
  const awardCalls = mockAwards(page);
  await page.goto("/funded_awards.html?opportunity=361187");
  await expect(page.locator("#selected-opportunity-heading")).toContainText("Lasker Clinical Research Scholar");
  await expect(page.locator("#selected-mapping-note")).toContainText("exact NIH opportunity number PAR-26-114");
  await expect(page.locator(".award-card[data-source='NIH']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["NIH"]);
  expect(awardCalls[0].criteria.opportunity_number).toBe("PAR-26-114");
});

test("the frozen DOE example opens its exact PAMS FOA without a program-equivalence claim", async ({ page }) => {
  await mockFrozenAwardCatalog(page);
  const awardCalls = mockAwards(page);
  await page.goto("/funded_awards.html?opportunity=361526");
  await expect(page.locator("#selected-opportunity-heading")).toContainText("The Genesis Mission");
  await expect(page.locator("#selected-mapping-note")).toContainText("exact DOE Office of Science FOA DE-FOA-0003612");
  await expect(page.locator(".award-card[data-source='DOE']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["DOE"]);
  expect(awardCalls[0].criteria.opportunity_number).toBe("DE-FOA-0003612");
  expect(awardCalls[0].limit).toBe(10);
  await expect(page.locator("#watch-selected-program")).toBeHidden();
});

test("the frozen NSF CBET example opens its reviewed current and predecessor program group", async ({ page }) => {
  await mockFrozenAwardCatalog(page);
  const awardCalls = mockAwards(page);
  await page.goto("/funded_awards.html?opportunity=363616");
  await expect(page.locator("#selected-opportunity-heading")).toContainText("Chemical, Bioengineering, Energy, and Transport Systems");
  await expect(page.locator("#selected-mapping-note")).toContainText("reviewed predecessor program-element codes");
  await expect(page.locator(".award-card[data-source='NSF']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["NSF"]);
  expect(awardCalls[0].criteria.program_codes).toEqual([
    "366Y00", "367Y00", "369Y00", "370Y00",
    "140100", "764400", "141700", "140300",
    "723600", "149100", "534200", "534500",
    "764300", "117900", "140700", "144300", "141500", "140600",
  ]);
  const alertCalls = mockAlerts(page);
  await expect(page.locator("#watch-selected-program")).toBeVisible();
  await page.locator("#watch-selected-program").click();
  await expect(page.getByRole("dialog", { name: "Watch this program" })).toContainText("controlled NSF program identity");
  await page.locator("#alert-email").fill("researcher@example.edu");
  await page.locator("#alert-submit").click();
  await expect.poll(() => alertCalls.length).toBe(1);
  expect(alertCalls[0].subscription.definition).toEqual({ program_id: "nsf:cbet" });
});

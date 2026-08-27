import { expect, test } from "@playwright/test";
import {
  mockAwards,
  mockAlerts,
  mockHybrid,
  openFundingFinder,
  runFundingSearch,
} from "./helpers.mjs";

// Snapshot-native standalone coverage lives in unit-b-funded-awards.spec.mjs.
// These tests retain the exact-opportunity and cross-product compatibility surface.

test("standalone paging and investigator handoff retain the submitted year range", async ({ page }) => {
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
  await expect.poll(() => calls.at(-1)?.criteria?.pi).toBe("Vasily Karasiev");
  expect(calls.at(-1).criteria).toMatchObject({
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

test("eligible Funding Finder results open Funded Awards in a new tab with the exact NIH opportunity selected", async ({ page, context }) => {
  await page.clock.setFixedTime(new Date("2026-08-28T12:00:00Z"));
  mockHybrid(page);
  const awardCalls = mockAwards(context);
  await openFundingFinder(page);
  await runFundingSearch(page, "PAR-26-114");
  const card = page.locator('[data-opportunity-id="361187"]');
  await expect(card).toBeVisible();
  const link = card.locator("[data-funded-awards]");
  await expect(link).toHaveAttribute("target", "_blank");
  const [awardsPage] = await Promise.all([
    page.waitForEvent("popup"),
    link.click(),
  ]);
  await expect(awardsPage.locator("#selected-opportunity-heading")).toContainText("Lasker Clinical Research Scholar");
  await expect(awardsPage.locator("#selected-mapping-note")).toContainText("exact NIH opportunity number PAR-26-114");
  await expect(awardsPage.locator(".award-card[data-source='NIH']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["NIH"]);
  expect(awardCalls[0].criteria.opportunity_number).toBe("PAR-26-114");
});

test("an eligible DOE Office of Science result opens the exact PAMS FOA search without a program-equivalence claim", async ({ page, context }) => {
  mockHybrid(page);
  const awardCalls = mockAwards(context);
  await openFundingFinder(page);
  await runFundingSearch(page, "DE-FOA-0003612");
  const card = page.locator('[data-opportunity-id="361526"]');
  await expect(card).toBeVisible();
  const [awardsPage] = await Promise.all([
    page.waitForEvent("popup"),
    card.locator("[data-funded-awards]").click(),
  ]);
  await expect(awardsPage.locator("#selected-opportunity-heading")).toContainText("The Genesis Mission");
  await expect(awardsPage.locator("#selected-mapping-note")).toContainText("exact DOE Office of Science FOA DE-FOA-0003612");
  await expect(awardsPage.locator(".award-card[data-source='DOE']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["DOE"]);
  expect(awardCalls[0].criteria.opportunity_number).toBe("DE-FOA-0003612");
  expect(awardCalls[0].limit).toBe(10);
  await expect(awardsPage.locator("#watch-selected-program")).toBeHidden();
});

test("the reviewed NSF CBET parent opens its exact current and predecessor program group", async ({ page, context }) => {
  mockHybrid(page);
  const awardCalls = mockAwards(context);
  await openFundingFinder(page);
  await runFundingSearch(page, "26-518");
  const card = page.locator('[data-opportunity-id="363616"]');
  await expect(card).toBeVisible();
  const [awardsPage] = await Promise.all([
    page.waitForEvent("popup"),
    card.locator("[data-funded-awards]").click(),
  ]);
  await expect(awardsPage.locator("#selected-opportunity-heading")).toContainText("Chemical, Bioengineering, Energy, and Transport Systems");
  await expect(awardsPage.locator("#selected-mapping-note")).toContainText("reviewed predecessor program-element codes");
  await expect(awardsPage.locator(".award-card[data-source='NSF']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["NSF"]);
  expect(awardCalls[0].criteria.program_codes).toEqual([
    "366Y00", "367Y00", "369Y00", "370Y00",
    "140100", "764400", "141700", "140300",
    "723600", "149100", "534200", "534500",
    "764300", "117900", "140700", "144300", "141500", "140600",
  ]);
  const alertCalls = mockAlerts(awardsPage);
  await expect(awardsPage.locator("#watch-selected-program")).toBeVisible();
  await awardsPage.locator("#watch-selected-program").click();
  await expect(awardsPage.getByRole("dialog", { name: "Watch this program" })).toContainText("controlled NSF program identity");
  await awardsPage.locator("#alert-email").fill("researcher@example.edu");
  await awardsPage.locator("#alert-submit").click();
  await expect.poll(() => alertCalls.length).toBe(1);
  expect(alertCalls[0].subscription.definition).toEqual({ program_id: "nsf:cbet" });
});

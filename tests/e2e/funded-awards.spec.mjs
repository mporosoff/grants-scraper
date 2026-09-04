import { expect, test } from "@playwright/test";
import {
  mockAwards,
  mockAlerts,
  mockFrozenFundingCatalog,
  mockHybrid,
  openFundingFinder,
  runFundingSearch,
} from "./helpers.mjs";

// Snapshot-native standalone coverage lives in unit-b-funded-awards.spec.mjs.
// These tests retain the exact-opportunity and cross-product compatibility surface.

async function openFrozenAwardFromFundingFinder(page, context, opportunityId, query) {
  await page.clock.setFixedTime(new Date("2026-09-01T12:00:00Z"));
  await mockFrozenFundingCatalog(context);
  mockHybrid(page);
  const awardCalls = mockAwards(context);
  await openFundingFinder(page);
  await runFundingSearch(page, query);

  const card = page.locator(`[data-opportunity-id="${opportunityId}"]`);
  await expect(card).toBeVisible();
  const link = card.locator("[data-funded-awards]");
  await expect(link).toHaveAttribute("href", new RegExp(`funded_awards\\.html\\?opportunity=${opportunityId}$`));
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener");
  const [awardsPage] = await Promise.all([
    page.waitForEvent("popup"),
    link.click(),
  ]);
  await awardsPage.waitForLoadState("domcontentloaded");
  return { awardsPage, awardCalls };
}

test("standalone paging and investigator handoff retain the submitted year range", async ({ page }) => {
  await mockFrozenFundingCatalog(page);
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
  await expect(pill).toHaveText("NSF · NIH · DOE · DoD");
  await expect(pill).toHaveAttribute("aria-label", "NSF, NIH, DOE, and DoD award sources available");
  await expect(pill.locator(".header-context-row-break")).toBeHidden();
  const geometry = await pill.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    const agencies = [...element.querySelectorAll(".header-context-agency")].map(agency => {
      const agencyBounds = agency.getBoundingClientRect();
      return {
        centerX: agencyBounds.left + agencyBounds.width / 2,
        top: agencyBounds.top,
      };
    });
    return {
      left: bounds.left,
      right: bounds.right,
      viewportWidth: window.innerWidth,
      contentWidth: element.scrollWidth,
      visibleWidth: element.clientWidth,
      agencies,
    };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth);
  expect(geometry.contentWidth).toBeLessThanOrEqual(geometry.visibleWidth);
  expect(geometry.agencies).toHaveLength(4);
  expect(Math.abs(geometry.agencies[0].centerX - geometry.agencies[2].centerX)).toBeLessThanOrEqual(1);
  expect(Math.abs(geometry.agencies[1].centerX - geometry.agencies[3].centerX)).toBeLessThanOrEqual(1);
  expect(Math.abs(geometry.agencies[0].top - geometry.agencies[1].top)).toBeLessThanOrEqual(1);
  expect(Math.abs(geometry.agencies[2].top - geometry.agencies[3].top)).toBeLessThanOrEqual(1);
  expect(geometry.agencies[2].top).toBeGreaterThan(geometry.agencies[0].top);
});

test("the frozen NIH example opens its exact opportunity mapping", async ({ page, context }) => {
  const { awardsPage, awardCalls } = await openFrozenAwardFromFundingFinder(page, context, "361187", "PAR-26-114");
  await expect(awardsPage.locator("#selected-opportunity-heading")).toContainText("Lasker Clinical Research Scholar");
  await expect(awardsPage.locator("#selected-mapping-note")).toContainText("exact NIH opportunity number PAR-26-114");
  await expect(awardsPage.locator(".award-card[data-source='NIH']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["NIH"]);
  expect(awardCalls[0].criteria.opportunity_number).toBe("PAR-26-114");
});

test("the frozen DOE example opens its exact PAMS FOA without a program-equivalence claim", async ({ page, context }) => {
  const { awardsPage, awardCalls } = await openFrozenAwardFromFundingFinder(page, context, "361526", "DE-FOA-0003612");
  await expect(awardsPage.locator("#selected-opportunity-heading")).toContainText("The Genesis Mission");
  await expect(awardsPage.locator("#selected-mapping-note")).toContainText("exact DOE Office of Science FOA DE-FOA-0003612");
  await expect(awardsPage.locator(".award-card[data-source='DOE']")).toHaveCount(1);
  await expect.poll(() => awardCalls.length).toBe(1);
  expect(awardCalls[0].sources).toEqual(["DOE"]);
  expect(awardCalls[0].criteria.opportunity_number).toBe("DE-FOA-0003612");
  expect(awardCalls[0].limit).toBe(10);
  await expect(awardsPage.locator("#watch-selected-program")).toBeHidden();
});

test("the frozen NSF CBET example opens its reviewed current and predecessor program group", async ({ page, context }) => {
  const { awardsPage, awardCalls } = await openFrozenAwardFromFundingFinder(page, context, "363616", "26-518");
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

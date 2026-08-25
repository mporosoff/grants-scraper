import { expect, test } from "@playwright/test";
import {
  mockAwards,
  mockAlerts,
  mockHybrid,
  openFundingFinder,
  runFundingSearch,
  watchRuntimeErrors,
} from "./helpers.mjs";

test("standalone native topic search renders source records, provenance, institution summary, and history", async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html");
  await page.locator("#award-query").fill("mitral valve prolapse");
  await page.locator("#award-institution").fill("University of Rochester");
  await page.locator("#remember-institution").check();
  await page.locator("#search-awards").click();
  await expect(page.locator(".award-card")).toHaveCount(2);
  await expect(page.locator("#institution-summary")).toContainText("2 funded projects in this result page");
  await expect(page.locator(".award-abstract").first()).toBeVisible();
  await expect(page.getByText("Direct NSF source field").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /View contact on official award page/ }).first()).toBeVisible();
  await expect(page).toHaveURL(/q=mitral\+valve\+prolapse/);
  expect(calls[0].criteria).toMatchObject({
    topic: "mitral valve prolapse",
    institution: "University of Rochester",
  });
  expect(calls[0].sources).toEqual(["NSF", "NIH"]);

  await page.locator("[data-award-pi='Stephen Dewhurst']").click();
  await expect(page).toHaveURL(/pi=Stephen\+Dewhurst/);
  await page.goBack();
  await expect(page).not.toHaveURL(/pi=/);
  await expect(page.locator(".award-card")).toHaveCount(2);
  expect(errors).toEqual([]);
});

test("a failed award source degrades independently", async ({ page }) => {
  mockAwards(page, { failNih: true });
  await page.goto("/funded_awards.html?q=warm+dense+matter&institution=University+of+Rochester");
  await expect(page.locator(".award-card[data-source='NSF']")).toHaveCount(1);
  await expect(page.locator(".award-card[data-source='NIH']")).toHaveCount(0);
  await expect(page.locator("#award-source-status")).toContainText("NIH temporarily unavailable");
  await expect(page.locator("#award-status")).toContainText("available sources are shown");
});

test("pagination controls restore their result state after loading clears", async ({ page }) => {
  mockAwards(page, { hasMoreAtOffsets: [0] });
  await page.goto("/funded_awards.html");
  await page.locator("#award-query").fill("warm dense matter");
  await page.locator("#award-agency").selectOption("NSF");
  await page.locator("#search-awards").click();
  await expect(page.locator(".award-card")).toHaveCount(1);
  await expect(page.locator("#award-previous")).toBeDisabled();
  await expect(page.locator("#award-next")).toBeEnabled();

  await page.locator("#award-next").click();
  await expect(page).toHaveURL(/offset=25/);
  await expect(page.locator("#award-previous")).toBeEnabled();
  await expect(page.locator("#award-next")).toBeDisabled();

  await page.locator("#award-previous").click();
  await expect(page).not.toHaveURL(/offset=/);
  await expect(page.locator("#award-previous")).toBeDisabled();
  await expect(page.locator("#award-next")).toBeEnabled();
});

test("institution-only shared URLs execute and restore across browser history", async ({ page }) => {
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html?institution=University+of+Rochester");
  await expect(page.locator(".award-card")).toHaveCount(2);
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].criteria).toEqual({ institution: "University of Rochester" });

  await page.locator("#clear-award-search").click();
  await expect(page).not.toHaveURL(/institution=/);
  await expect(page.locator(".award-card")).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/institution=University\+of\+Rochester/);
  await expect(page.locator(".award-card")).toHaveCount(2);
  await expect.poll(() => calls.length).toBe(2);
  await page.goForward();
  await expect(page).not.toHaveURL(/institution=/);
  await expect(page.locator(".award-card")).toHaveCount(0);
});

test("eligible Funding Finder results open Funded Awards in a new tab with the exact NIH opportunity selected", async ({ page, context }) => {
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

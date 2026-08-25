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
  await page.locator("#ii-topic").fill("mitral valve prolapse");
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-search").click();
  await expect(page.locator(".ii-award-card")).toHaveCount(3);
  await expect(page.locator("#ii-metrics")).toContainText("3Projects returned");
  await page.locator(".ii-award-abstract").first().evaluate(element => { element.open = true; });
  await expect(page.locator(".ii-award-abstract").first().locator("p")).toHaveCount(2);
  await expect(page.locator(".ii-award-abstract").first()).toContainText("CO₂");
  expect(await page.locator(".ii-award-abstract").first().locator("p").nth(1).evaluate(element =>
    Number.parseFloat(getComputedStyle(element).marginTop),
  )).toBeGreaterThan(0);
  await expect(page.getByRole("link", { name: /View source query/ })).toHaveCount(0);
  await expect(page.getByText("Direct NSF source field").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /View on official record/ }).first()).toBeVisible();
  await expect(page).toHaveURL(/ii_topic=mitral\+valve\+prolapse/);
  expect(calls[0].criteria).toMatchObject({
    topic: "mitral valve prolapse",
    institution: "University of Rochester",
  });
  expect(calls[0].sources).toEqual(["NSF", "NIH", "DOE"]);
  expect(calls[0].limit).toBe(10);

  await page.locator("[data-ii-pi='Stephen Dewhurst']").click();
  await expect(page).toHaveURL(/ii_pi=Stephen\+Dewhurst/);
  await page.goBack();
  await expect(page).not.toHaveURL(/ii_pi=/);
  await expect(page.locator(".ii-award-card")).toHaveCount(3);
  expect(errors).toEqual([]);
});

test("missing award values remain missing while explicit zero stays visible", async ({ page }, testInfo) => {
  mockAwards(page, {
    awardOverridesBySource: {
      NSF: { award_year: null, total_award: null },
      NIH: { award_year: "", total_award: 0 },
      DOE: { award_year: 2019, total_award: 1150000 },
    },
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/funded_awards.html");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  const nsf = page.locator(".ii-award-card[data-source='NSF'] .ii-award-kicker");
  const nih = page.locator(".ii-award-card[data-source='NIH'] .ii-award-kicker");
  const doe = page.locator(".ii-award-card[data-source='DOE'] .ii-award-kicker");
  await expect(nsf).toContainText("Year not listed");
  await expect(nsf).toContainText("Amount not listed");
  await expect(nsf).not.toContainText("$0");
  await expect(nih).toContainText("Year not listed");
  await expect(nih).toContainText("$0");
  await expect(doe).toContainText("2019");
  await expect(doe).toContainText("$1,150,000");
  await expect(page.locator("#ii-metrics")).toContainText("2019Award years");
  await expect(page.locator("#ii-metrics")).not.toContainText(/\b0(?:–|Award years)/);

  await page.goto("/funded_awards.html?opportunity=363616");
  const legacyNsf = page.locator(".award-card[data-source='NSF']");
  await expect(legacyNsf).toContainText("Award amountNot listed");
  await expect(legacyNsf).not.toContainText("Award year 0");
  await expect(page.locator("#program-summary")).toContainText("Years not listed");
  await testInfo.attach("ff-bug-001-missing-values-390px.png", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("investigator drill-down replaces an exact opportunity request and round-trips through history", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("funding-finder.awards.institution.v1", "University of Rochester");
  });
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html?opportunity=361187&year_start=2020&year_end=2026");
  await expect(page.locator("#selected-opportunity")).toBeVisible();
  await expect(page.locator("[data-award-pi='Stephen Dewhurst']")).toBeVisible();
  expect(calls[0].criteria.opportunity_number).toBe("PAR-26-114");

  await page.locator("[data-award-pi='Stephen Dewhurst']").click();
  await expect.poll(() => calls.length).toBe(2);
  expect(calls[1].sources).toEqual(["NIH"]);
  expect(calls[1].criteria).toEqual({
    institution: "University of Rochester",
    pi: "Stephen Dewhurst",
    year_start: 2020,
    year_end: 2026,
  });
  await expect(page).not.toHaveURL(/opportunity=/);
  await expect(page).toHaveURL(/ii_pi=Stephen\+Dewhurst/);
  await expect(page.locator("#selected-opportunity")).toBeHidden();
  await expect(page.locator("#watch-selected-program")).toBeHidden();
  await expect(page.locator("#ii-pi")).toHaveValue("Stephen Dewhurst");
  await expect(page.locator("#ii-agency")).toHaveValue("NIH");

  await page.goBack();
  await expect(page).toHaveURL(/opportunity=361187/);
  await expect.poll(() => calls.at(-1)?.criteria?.opportunity_number).toBe("PAR-26-114");
  await expect(page.locator("#selected-opportunity")).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/ii_pi=Stephen\+Dewhurst/);
  await expect.poll(() => calls.at(-1)?.criteria?.pi).toBe("Stephen Dewhurst");
  expect(calls.at(-1).criteria).not.toHaveProperty("opportunity_number");
  await expect(page.locator("#selected-opportunity")).toBeHidden();
});

test("multi-source pagination reports independent source offsets on mobile", async ({ page }) => {
  mockAwards(page, { resultCountPerSource: { NSF: 2, NIH: 1, DOE: 3 } });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/funded_awards.html?ii=1&ii_topic=catalysis&ii_offset=10");
  await expect(page.locator(".ii-award-card")).toHaveCount(6);
  await expect(page.locator("#ii-page-label")).toHaveText("6 results on this page · each source is paged independently after its first 10 results");
  await expect(page.locator("#ii-page-label")).not.toContainText(/Results 11/);
  await expect(page.locator("#ii-page-label")).toHaveAttribute("aria-live", "polite");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 320, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("partial award results distinguish unsupported and rate-limited sources", async ({ page }) => {
  mockAwards(page, {
    sourceFailures: {
      NIH: { status: "unsupported", code: "unsupported_criteria" },
      DOE: { status: "unavailable", code: "source_rate_limited" },
    },
  });
  await page.goto("/funded_awards.html");
  await page.locator("#ii-topic").fill("warm dense matter");
  await page.locator("#ii-search").click();
  await expect(page.locator(".ii-award-card[data-source='NSF']")).toHaveCount(1);
  await expect(page.locator("#ii-source-status")).toContainText("NIH does not support this filter combination");
  await expect(page.locator("#ii-source-status")).toContainText("DOE is rate limited. Wait before retrying.");
  await expect(page.locator("#ii-status")).toContainText("1 public project returned from available sources");
  await expect(page.locator("#ii-status")).toContainText("does not support this filter combination");
  await expect(page.locator("#ii-status")).toContainText("Wait before retrying");
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

test("a failed award source degrades independently", async ({ page }) => {
  mockAwards(page, { failNih: true });
  await page.goto("/funded_awards.html?q=warm+dense+matter&institution=University+of+Rochester");
  await expect(page.locator(".ii-award-card[data-source='NSF']")).toHaveCount(1);
  await expect(page.locator(".ii-award-card[data-source='NIH']")).toHaveCount(0);
  await expect(page.locator(".ii-award-card[data-source='DOE']")).toHaveCount(1);
  await expect(page.locator("#ii-source-status")).toContainText("NIH is temporarily unavailable. Retry later.");
  await expect(page.locator("#ii-status")).toContainText("returned from available sources");
});

test("an underfilled normalized page disables Next even when a source reports more raw records", async ({ page }) => {
  mockAwards(page, { hasMoreAtOffsets: [0] });
  await page.goto("/funded_awards.html");
  await page.locator("#ii-topic").fill("warm dense matter");
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-search").click();
  await expect(page.locator(".ii-award-card")).toHaveCount(1);
  await expect(page.locator("#ii-previous")).toBeDisabled();
  await expect(page.locator("#ii-next")).toBeDisabled();
});

test("pagination restores controls after loading and scrolls each new page to the results heading", async ({ page }) => {
  mockAwards(page, { hasMoreAtOffsets: [0], resultCountPerSource: 10 });
  await page.goto("/funded_awards.html");
  await page.locator("#ii-topic").fill("warm dense matter");
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-search").click();
  await expect(page.locator(".ii-award-card")).toHaveCount(10);
  await expect(page.locator("#ii-previous")).toBeDisabled();
  await expect(page.locator("#ii-next")).toBeEnabled();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.locator("#ii-next").click();
  await expect(page).toHaveURL(/ii_offset=10/);
  await expect(page.locator("#ii-previous")).toBeEnabled();
  await expect(page.locator("#ii-next")).toBeDisabled();
  await expect.poll(() => page.locator("#ii-output-heading").evaluate(element => Math.round(element.getBoundingClientRect().top))).toBeLessThan(120);
  await expect.poll(() => page.locator("#ii-output-heading").evaluate(element => Math.round(element.getBoundingClientRect().top))).toBeGreaterThanOrEqual(0);

  await page.locator("#ii-previous").click();
  await expect(page).not.toHaveURL(/ii_offset=/);
  await expect(page.locator("#ii-previous")).toBeDisabled();
  await expect(page.locator("#ii-next")).toBeEnabled();
});

test("principal investigator and program officer are first-class search modes", async ({ page }) => {
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html");
  await expect(page.getByText("Advanced: investigator or program officer")).toHaveCount(0);

  await page.locator("#ii-pi").fill("Stephen Dewhurst");
  await page.locator("#ii-agency").selectOption("NIH");
  await page.locator("#ii-search").click();
  await expect.poll(() => calls.at(-1)?.criteria?.pi).toBe("Stephen Dewhurst");
  await expect(page).toHaveURL(/ii_pi=Stephen\+Dewhurst/);

  await page.locator("#ii-pi").fill("");
  await page.locator("#ii-program-officer").fill("Vladimir Lukin");
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-search").click();
  await expect.poll(() => calls.at(-1)?.criteria?.program_officer).toBe("Vladimir Lukin");
  await expect(page).toHaveURL(/ii_program_officer=Vladimir\+Lukin/);
});

test("institution-only shared URLs execute and restore across browser history", async ({ page }) => {
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html?institution=University+of+Rochester");
  await expect(page.locator(".ii-award-card")).toHaveCount(3);
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].criteria).toEqual({ institution: "University of Rochester" });

  await page.locator("#ii-clear").click();
  await expect(page).not.toHaveURL(/institution=/);
  await expect(page.locator("#ii-output")).toBeHidden();
  await page.goBack();
  await expect(page).toHaveURL(/institution=University\+of\+Rochester/);
  await expect(page.locator(".ii-award-card")).toHaveCount(3);
  await expect.poll(() => calls.length).toBe(2);
  await page.goForward();
  await expect(page).not.toHaveURL(/institution=/);
  await expect(page.locator("#ii-output")).toBeHidden();
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

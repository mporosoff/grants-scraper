import { expect, test } from "@playwright/test";
import {
  mockAwards,
  mockHybrid,
  openFundingFinder,
  watchRuntimeErrors,
} from "./helpers.mjs";

async function openInstitutionalIntelligence(page) {
  await page.goto("/funded_awards.html");
  await expect(page.locator("#ii-form")).toBeVisible();
}

test("one unified search supports topic and program-officer queries without an institution", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await expect(page.locator("#award-search-form")).toBeHidden();
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("electrocatalysis");
  await page.locator("#ii-program-officer").fill("Alex Officer");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  expect(calls.at(-1).criteria).toMatchObject({ topic: "electrocatalysis", program_officer: "Alex Officer" });
  expect(calls.at(-1).criteria).not.toHaveProperty("institution");
  await expect(page).toHaveURL(/ii_topic=electrocatalysis/);
  await expect(page).toHaveURL(/ii_program_officer=Alex\+Officer/);
});

test("unified pagination stops on an exhausted page and returns to the result heading", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, { hasMoreAtOffsets: [0], resultCountPerSource: 10 });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-next")).toBeEnabled();
  await page.locator("#ii-next").click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(10);
  await expect(page.locator("#ii-next")).toBeDisabled();
  await expect(page.locator("#ii-output-heading")).toBeFocused();
  await expect(page).toHaveURL(/ii_offset=10/);
});

test("ROR aliases resolve to canonical institutions before normalized award queries", async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  const cases = [
    ["MIT", "Massachusetts Institute of Technology"],
    ["Caltech", "California Institute of Technology"],
    ["UVA", "University of Virginia"],
    ["RIT", "Rochester Institute of Technology"],
    ["UCLA", "University of California, Los Angeles"],
  ];
  for (const [index, [alias, canonical]] of cases.entries()) {
    await page.locator("#ii-institution").fill(alias);
    if (index === 0) {
      await expect(page.locator("#ii-institution-options [role='option']")).toHaveCount(2);
      await page.locator("#ii-institution").press("ArrowDown");
      await page.locator("#ii-institution").press("Enter");
      await expect(page.locator("#ii-institution")).toHaveValue(canonical);
    }
    await page.locator("#ii-search").click();
    await expect(page.locator("#ii-institution")).toHaveValue(canonical);
    await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
    await expect.poll(() => calls.at(-1)?.criteria?.institution).toBe(canonical);
    expect(calls.at(-1).criteria.institution_id).toMatch(/^https:\/\/ror\.org\/0[a-z0-9]{8}$/);
  }
  expect(errors).toEqual([]);
});

test("cross-agency summaries, investigator and program drill-downs, and history use authoritative awards", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  await expect(page.locator("#ii-metrics")).toContainText("3Projects returned");
  await expect(page.locator("#ii-metrics")).toContainText("3Unique investigators");
  await expect(page.getByRole("link", { name: /Official NSF record/ })).toHaveAttribute("target", "_blank");
  await expect(page.locator("a[href='mailto:vkarasev@example.edu']")).toBeVisible();
  await expect(page.locator("a[href='mailto:vlukin@nsf.gov']")).toBeVisible();
  expect(await page.locator("#ii-ask").evaluate((ask, awards) => Boolean(ask.compareDocumentPosition(awards) & Node.DOCUMENT_POSITION_FOLLOWING), await page.locator("#ii-awards").elementHandle())).toBe(true);
  expect(calls[0].sources).toEqual(["NSF", "NIH", "DOE"]);

  await page.locator("[data-ii-pi='Stephen Dewhurst']").click();
  await expect(page).toHaveURL(/ii_pi=Stephen\+Dewhurst/);
  await expect.poll(() => calls.at(-1)?.criteria?.pi).toBe("Stephen Dewhurst");
  await page.goBack();
  await expect(page).not.toHaveURL(/ii_pi=/);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);

  await page.getByRole("button", { name: "Office of Basic Energy Sciences · 1" }).click();
  await expect(page).toHaveURL(/ii_agency=DOE/);
  await expect(page).toHaveURL(/ii_program=BES/);
  await expect.poll(() => calls.at(-1)?.sources).toEqual(["DOE"]);
  expect(calls.at(-1).criteria).toMatchObject({
    institution: "University of Rochester",
    program_office: "SC-32",
  });
});

test("institution-only shared URLs restore and execute without an AI key", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("funding-finder.credentials.v1"));
  mockHybrid(page);
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html?ii=1&ii_institution=University+of+Virginia&ii_ror=https%3A%2F%2Fror.org%2F0153tk833&ii_topic=catalysis&ii_year_start=2020&ii_year_end=2026");
  await expect(page.locator("#institutional-intelligence")).toBeVisible();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].criteria).toMatchObject({
    institution: "University of Virginia",
    institution_id: "https://ror.org/0153tk833",
    topic: "catalysis",
    year_start: 2020,
    year_end: 2026,
  });
  await expect(page.locator("#ii-ai-state")).toContainText("Connect a provider");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("Who has DOE BES awards?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-key-setup")).toBeVisible();
  await expect(page.locator("#ii-key-status")).toContainText("Structured filters remain available without one");
});

test("one unavailable award source does not suppress the other institutional evidence", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page, { failNih: true });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("MIT");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(2);
  await expect(page.locator("#ii-source-status")).toContainText("NSF available");
  await expect(page.locator("#ii-source-status")).toContainText("NIH temporarily unavailable");
  await expect(page.locator("#ii-source-status")).toContainText("DOE available");
  await expect(page.locator("#ii-status")).toContainText("returned from available sources");
});

test("the natural-language translator reuses the saved Funding Finder provider and exposes its structured plan", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  const providerCalls = [];
  await page.route("https://api.openai.com/v1/responses", route => {
    providerCalls.push(route.request().postDataJSON());
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify({ output_text: JSON.stringify({ agency: "DOE", program: "BES", topic: "", pi: "", year_start: "", year_end: "" }) }),
    });
  });
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await expect(page.locator("#ii-ai-state")).toContainText("gpt-5.6-luna configured");
  await expect(page.locator("#ii-key-setup")).toBeHidden();
  await page.locator("#ii-question").fill("Who at this institution has received awards from DOE BES?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Agency: DOE");
  await expect(page.locator("#ii-question-plan")).toContainText("Program: BES");
  await expect.poll(() => calls.at(-1)?.criteria?.program_office).toBe("SC-32");
  expect(providerCalls).toHaveLength(1);
  expect(providerCalls[0].store).toBe(false);
  const providerInput = JSON.parse(providerCalls[0].input);
  expect(Object.keys(providerInput).sort()).toEqual(["current_filters", "institution", "question"]);
  expect(Object.keys(providerInput.current_filters).sort()).toEqual(["agency", "pi", "program", "program_officer", "topic", "year_end", "year_start"]);
  expect(JSON.stringify(providerInput)).not.toMatch(/profile|cv_text|orcid|saved|pursuit|document/i);
});

test("key setup inside Institutional Intelligence populates Funding Finder's shared local configuration", async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("ii-key-test-initialized")) return;
    localStorage.removeItem("funding-finder.credentials.v1");
    sessionStorage.setItem("ii-key-test-initialized", "1");
  });
  mockHybrid(page);
  mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-provider").selectOption("anthropic");
  await page.locator("#ii-key").fill("sk-ant-shared-test");
  await page.locator("#ii-save-key").click();
  await expect(page.locator("#ii-key-status")).toContainText("shared browser-local provider configuration");
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("funding-finder.credentials.v1")));
  expect(stored).toEqual({ keys: { anthropic: "sk-ant-shared-test" } });
  await openFundingFinder(page);
  await expect(page.locator("#k-provider")).toHaveValue("anthropic");
  await expect(page.locator("#k-key")).toHaveValue("sk-ant-shared-test");
});

test("Institutional Intelligence fits a narrow mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  mockHybrid(page);
  mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("MIT");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const input = await page.locator("#ii-institution").boundingBox();
  expect(input.x).toBeGreaterThanOrEqual(0);
  expect(input.x + input.width).toBeLessThanOrEqual(320);
});

test("legacy Funding Finder Institutional Intelligence links redirect to Funded Awards", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page);
  await page.goto("/match_explorer.html?ii=1&ii_institution=Massachusetts+Institute+of+Technology&ii_ror=https%3A%2F%2Fror.org%2F042nb2s44");
  await expect(page).toHaveURL(/funded_awards\.html\?ii=1/);
  await expect(page.locator("#institutional-intelligence")).toBeVisible();
  await expect(page.locator("#ii-institution")).toHaveValue("Massachusetts Institute of Technology");
});

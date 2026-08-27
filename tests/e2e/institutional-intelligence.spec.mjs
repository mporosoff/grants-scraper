import { expect, test } from "@playwright/test";
import {
  chooseInvestigator,
  mockAwards,
  mockHybrid,
  openAiStructuredResponse,
  openFundingFinder,
  watchRuntimeErrors,
} from "./helpers.mjs";

async function openInstitutionalIntelligence(page) {
  await page.goto("/funded_awards.html");
  await expect(page.locator("#ii-form")).toBeVisible();
}

async function chooseInstitution(page, query, canonical) {
  await page.locator("#ii-institution").fill(query);
  const option = page.locator("#ii-institution-options [role='option']").filter({ hasText: canonical }).first();
  await expect(option).toBeVisible();
  await option.click();
  await expect(page.locator("#ii-institution")).toHaveValue(canonical);
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

test("a program filter requires one agency before source requests are split", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-program").fill("BES");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-status")).toContainText("Choose NSF, NIH, or DOE before filtering by a program.");
  expect(calls).toHaveLength(0);
});

test("an overlong award-year range shows one validation error without source retries", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-year-start").fill("1989");
  await page.locator("#ii-year-end").fill("2100");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-status")).toContainText("Choose a year range of 50 years or fewer.");
  expect(calls).toHaveLength(0);
  await expect(page.getByRole("button", { name: "Load additional awards" })).toHaveCount(0);
});

test("generic additional loading preserves submitted source state and pages award cards ten at a time", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, { hasMoreAtOffsets: [0], resultCountPerSource: 25 });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeEnabled();
  await expect(page.locator("#ii-awards .ii-award-card:visible")).toHaveCount(10);
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 1–10 of 25");
  await page.getByRole("button", { name: "Next 10 awards" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 11–20 of 25");
  await expect(page.locator("#ii-awards .ii-award-card:visible")).toHaveCount(10);
  await expect(page.locator("#ii-awards .ii-award-card:visible").first()).toBeFocused();
  await page.locator("#ii-institution").fill("MIT");
  await page.locator("#ii-topic").fill("batteries");
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(25);
  expect(calls.at(-1).criteria.topic).toBe("catalysis");
  expect(calls.at(-1).criteria.institution).toBe("University of Rochester");
  await expect(page.locator("#ii-output-heading")).toHaveText("University of Rochester funded projects");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(50);
  await expect(page.locator("#ii-metrics")).toContainText("50Projects loaded");
  await expect(page.locator("#ii-metrics")).toContainText("1Investigator identities in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("1Distinct programs in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("2026Years represented in loaded awards");
  await expect(page.locator("#ii-awards .ii-award-card:visible")).toHaveCount(10);
  await expect(page.getByRole("button", { name: "Load additional awards" })).toHaveCount(0);
  await expect(page).not.toHaveURL(/ii_offset=/);
});

test("one generic additional-awards control advances available sources fairly without naming one", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, {
    hasMoreBySource: { NSF: [0], NIH: [0] },
    resultCountPerSource: 1,
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  const loadAdditional = page.getByRole("button", { name: "Load additional awards" });
  await expect(loadAdditional).toHaveCount(1);
  await expect(page.locator("#ii-pagination")).not.toContainText(/NSF|NIH|DOE/);
  await loadAdditional.click();
  await expect.poll(() => calls.length).toBe(4);
  expect(calls.at(-1)).toMatchObject({ sources: ["NSF"], offset: 25 });
  await loadAdditional.click();
  await expect.poll(() => calls.length).toBe(5);
  expect(calls.at(-1)).toMatchObject({ sources: ["NIH"], offset: 25 });
  await expect(loadAdditional).toHaveCount(0);
  await expect(page.locator("#ii-page-label")).toContainText("All available awards for this search are loaded");
});

test("superseding a source load clears its busy state for the replacement search", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, {
    hasMoreAtOffsets: [0],
    responseDelaysBySourceOffset: { "NSF:25": 250 },
    resultCountPerSource: 25,
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect.poll(() => calls.some(call => call.offset === 25)).toBe(true);
  await chooseInvestigator(page, "Vasily Karasiev");
  await expect.poll(() => calls.at(-1)?.criteria?.pi).toBe("Vasily Karasiev");
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeEnabled();
});

test("a later source failure retains already loaded projects and offers a bounded retry", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page, {
    hasMoreAtOffsets: [0],
    resultCountPerSource: 25,
    sourceFailuresByOffset: { "NSF:25": { status: "unavailable", code: "source_unavailable" } },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(25);
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(25);
  await expect(page.locator("#ii-source-status")).toContainText("25 previously loaded NSF projects were retained");
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeEnabled();
});

test("a retry that becomes unsupported retains projects and removes the retry action", async ({ page }) => {
  mockHybrid(page);
  let attempts = 0;
  mockAwards(page, {
    hasMoreAtOffsets: [0],
    resultCountPerSource: 25,
    sourceFailuresByOffset: {
      "NSF:25": () => attempts++ === 0
        ? { status: "unavailable", code: "source_unavailable" }
        : { status: "unsupported", code: "unsupported_filter" },
    },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeEnabled();
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect(page.getByRole("button", { name: "Load additional awards" })).toHaveCount(0);
  await expect(page.locator("#ii-source-status")).toContainText("25 previously loaded NSF projects were retained");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(25);
});

test("generic additional loading can advance across an empty normalized page within the bound", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, {
    hasMoreBySource: { NSF: [0, 25] },
    resultCountBySourceOffset: { "NSF:0": 25, "NSF:25": 0, "NSF:50": 1 },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-topic").fill("catalysis");
  await page.locator("#ii-search").click();
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(25);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(25);
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeEnabled();
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(50);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(26);
  await expect(page.getByRole("button", { name: "Load additional awards" })).toHaveCount(0);
});

test("a restored source page at the maximum offset cannot advance past the worker bound", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, { hasMoreAtOffsets: [1_000] });
  await page.goto("/funded_awards.html?ii=1&ii_agency=NSF&ii_topic=catalysis&ii_offset=1000");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  expect(calls.at(-1)?.offset).toBe(1_000);
  await expect(page.getByRole("button", { name: "Load additional awards" })).toHaveCount(0);
  await expect(page.locator("#ii-page-label")).toContainText("All available awards for this search are loaded");
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
    }
    const option = page.locator("#ii-institution-options [role='option']").filter({ hasText: canonical }).first();
    await expect(option).toBeVisible();
    await option.click();
    await expect(page.locator("#ii-institution")).toHaveValue(canonical);
    await page.locator("#ii-search").click();
    await expect(page.locator("#ii-institution")).toHaveValue(canonical);
    await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
    await expect.poll(() => calls.at(-1)?.criteria?.institution).toBe(canonical);
    expect(calls.at(-1).criteria.institution_id).toMatch(/^https:\/\/ror\.org\/0[a-z0-9]{8}$/);
  }
  expect(errors).toEqual([]);
});

test("ambiguous short acronyms require explicit keyboard selection and preserve Escape behavior", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("UVA");
  await expect(page.locator("#ii-institution-options [role='option']")).toHaveCount(2);
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-status")).toContainText("Choose the intended Research Organization Registry");
  expect(calls).toHaveLength(0);
  await expect(page.locator("#ii-registry-status")).toContainText("matches");
  await page.locator("#ii-institution").press("Escape");
  await expect(page.locator("#ii-institution-options")).toBeHidden();
  await page.locator("#ii-institution").fill("");
  await page.locator("#ii-institution").fill("UVA");
  await expect(page.locator("#ii-institution-options [role='option']")).toHaveCount(2);
  await expect(page.locator("#ii-institution-options")).toBeVisible();
  await page.locator("#ii-institution").press("ArrowDown");
  await expect(page.locator("#ii-institution")).toHaveAttribute("aria-activedescendant", /ii-institution-option-\d/);
  await page.locator("#ii-institution").press("Enter");
  await expect(page.locator("#ii-institution")).toHaveValue("University of Virginia");
  await expect(page.locator("#ii-registry-status")).toContainText("Resolved to University of Virginia");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
});

test("a registry outage preserves complete-name source search without trusting aliases", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await page.route("**/institutions/search?query=*", route => route.fulfill({
    status: 503,
    headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
    body: JSON.stringify({ error: { code: "source_unavailable" } }),
  }));
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("MIT");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-status")).toContainText("requires an explicit Research Organization Registry");
  expect(calls).toHaveLength(0);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-registry-status")).toContainText("complete typed name as an exact source search");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  expect(calls).toHaveLength(3);
  expect(calls.every(call => call.criteria.institution === "University of Rochester")).toBe(true);
  expect(calls.every(call => !Object.hasOwn(call.criteria, "institution_id"))).toBe(true);
});

test("cross-agency summaries, investigator and program drill-downs, and history use authoritative awards", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  await expect(page.locator("#ii-metrics")).toContainText("3Projects loaded");
  await expect(page.locator("#ii-metrics")).toContainText("3Investigator identities in loaded results");
  await expect(page.locator(".ii-award-card[data-source='DOE'] .ii-award-program")).toContainText("Office of Basic Energy Sciences › Catalysis Science");
  await expect(page.getByRole("link", { name: /Official NSF record/ })).toHaveAttribute("target", "_blank");
  await expect(page.locator("a[href='mailto:vkarasev@example.edu']")).toBeVisible();
  await expect(page.locator("a[href='mailto:vlukin@nsf.gov']")).toBeVisible();
  expect(await page.locator("#ii-ask").evaluate((ask, awards) => Boolean(ask.compareDocumentPosition(awards) & Node.DOCUMENT_POSITION_FOLLOWING), await page.locator("#ii-awards").elementHandle())).toBe(true);
  expect(calls.slice(0, 3).map(call => call.sources[0])).toEqual(["NSF", "NIH", "DOE"]);
  expect(calls.slice(0, 3).map(call => call.limit)).toEqual([25, 25, 10]);

  await chooseInvestigator(page, "Stephen Dewhurst");
  await expect(page).toHaveURL(/ii_pi=Stephen\+Dewhurst/);
  await expect.poll(() => calls.at(-1)?.criteria?.pi).toBe("Stephen Dewhurst");
  await page.goBack();
  await expect(page).not.toHaveURL(/ii_pi=/);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);

  await page.locator("#ii-programs").selectOption({ label: "DOE · Office of Basic Energy Sciences › Catalysis Science" });
  await expect(page).toHaveURL(/ii_agency=DOE/);
  await expect(page).toHaveURL(/ii_program=Catalysis\+Science/);
  await expect.poll(() => calls.at(-1)?.sources).toEqual(["DOE"]);
  expect(calls.at(-1).criteria).toMatchObject({
    institution: "University of Rochester",
    program: "Catalysis Science",
  });
});

test("Marc source variants form one identity and return two NSF plus one DOE award", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, {
    resultCountPerSource: { NSF: 2, NIH: 0, DOE: 1 },
    awardOverridesBySource: {
      NSF: { principal_investigators: [{ name: "Marc Porosoff", role: "Principal Investigator", email: null }] },
      DOE: { principal_investigators: [{ name: "Marc D Porosoff", role: "Principal Investigator", email: null }] },
    },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-year-start").fill("2019");
  await page.locator("#ii-year-end").fill("2026");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  const marcOption = page.locator("#ii-investigators option").filter({ hasText: /^Marc D\. Porosoff$/ });
  await expect(marcOption).toHaveCount(1);
  await expect(marcOption).not.toHaveAttribute("aria-label", /award|project/i);
  await chooseInvestigator(page, "Marc D. Porosoff");
  await expect(page).toHaveURL(/ii_pi=Marc\+D\.?\+Porosoff/);
  await expect(page).toHaveURL(/ii_pi_identity=1/);
  await expect(page.locator("#ii-awards .ii-award-card[data-source='NSF']")).toHaveCount(2);
  await expect(page.locator("#ii-awards .ii-award-card[data-source='DOE']")).toHaveCount(1);
  await expect(page.locator("#ii-investigator-variants")).toContainText("Marc Porosoff (NSF)");
  await expect(page.locator("#ii-investigator-variants")).toContainText("Marc D Porosoff (DOE)");
  await expect(page.locator("#ii-investigators")).toHaveValue(/.+/);
  await expect(page.locator("#ii-status")).toContainText("3 matching awards currently loaded across");
  const queriedNames = new Set(calls.slice(3).map(call => call.criteria.pi).filter(Boolean));
  expect(queriedNames.has("Marc Porosoff")).toBe(true);
  expect(queriedNames.has("Marc D Porosoff")).toBe(true);
  expect(calls.slice(3).every(call => call.criteria.year_start === 2019 && call.criteria.year_end === 2026)).toBe(true);
  await page.goBack();
  await expect(page).not.toHaveURL(/ii_pi_identity/);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  await page.goForward();
  await expect(page).toHaveURL(/ii_pi_identity=1/);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
});

test("submitted years survive Load more, investigator and program drill-downs, and history", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, {
    hasMoreBySource: { NSF: [0] },
    resultCountPerSource: { NSF: 1 },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-topic").fill("submitted catalysis");
  await page.locator("#ii-year-start").fill("2024");
  await page.locator("#ii-year-end").fill("2026");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-result-scope")).toContainText("Requested award years: 2024–2026");
  await page.locator("#ii-year-start").fill("1999");
  await page.locator("#ii-year-end").fill("2000");
  await page.getByRole("button", { name: "Load additional awards" }).click();
  expect(calls.at(-1).criteria).toMatchObject({ year_start: 2024, year_end: 2026, topic: "submitted catalysis" });

  await chooseInvestigator(page, "Vasily Karasiev");
  await expect(page.locator("#ii-investigators")).toHaveValue(/.+/);
  expect(calls.at(-1).criteria).toMatchObject({ year_start: 2024, year_end: 2026, topic: "submitted catalysis" });
  await expect(page.locator("#ii-status")).toContainText("matching award");
  await expect(page.locator("#ii-status")).toContainText("across 1 source for Vasily Karasiev");

  const programOptions = await page.locator("#ii-programs option").allTextContents();
  expect(programOptions.some(label => /\d+ (?:project|award)/i.test(label))).toBe(false);
  await page.locator("#ii-programs").selectOption({ label: "NSF · Mathematical and Physical Sciences › Plasma Physics" });
  expect(calls.at(-1).criteria).toMatchObject({
    year_start: 2024,
    year_end: 2026,
    topic: "submitted catalysis",
    program: "Plasma Physics",
  });
  await page.goBack();
  await expect(page).toHaveURL(/ii_pi_identity=1/);
  await expect.poll(() => calls.at(-1)?.criteria?.year_start).toBe(2024);
  expect(calls.at(-1).criteria.year_end).toBe(2026);
  await page.goBack();
  await expect(page).not.toHaveURL(/ii_pi_identity=1/);
  await expect.poll(() => calls.at(-1)?.criteria?.year_start).toBe(2024);
  expect(calls.at(-1).criteria.year_end).toBe(2026);
});

test("evidence-grounded question years become the submitted request state", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  await page.route("https://api.openai.com/v1/responses", route => route.fulfill({
    status: 200,
    headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
    body: JSON.stringify(openAiStructuredResponse({
      agency: "all",
      program: "",
      topic: "catalysis",
      pi: "",
      program_officer: "",
      year_start: "2024",
      year_end: "2026",
      answer_intent: "count",
      narrative_needed: false,
    })),
  }));
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("How many catalysis awards were funded from 2024 through 2026?");
  await page.locator("#ii-ask-button").click();
  await expect.poll(() => calls.length).toBe(3);
  expect(calls.every(call => call.criteria.year_start === 2024 && call.criteria.year_end === 2026)).toBe(true);
  await expect(page.locator("#ii-result-scope")).toContainText("Requested award years: 2024–2026");
});

test("submitting a new narrow year range recalculates every loaded-result metric", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page, { enforceYearFilters: true });
  await openInstitutionalIntelligence(page);
  await expect(page.locator("#ii-year-start")).toHaveValue("");
  await expect(page.locator("#ii-year-end")).toHaveValue("");
  await expect(page.locator("#ii-year-start")).toHaveAttribute("placeholder", "Any");
  await expect(page.locator("#ii-year-end")).toHaveAttribute("placeholder", "Any");
  await expect(page.locator("#ii-year-help")).toContainText("Leave both year fields blank to search all available years");
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-year-start").fill("2024");
  await page.locator("#ii-year-end").fill("2026");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(2);
  await expect(page.locator("#ii-metrics")).toContainText("2Projects loaded");
  await expect(page.locator("#ii-metrics")).toContainText("2Investigator identities in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("2Distinct programs in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("2026Years represented in loaded awards");
  await expect(page.locator("#ii-result-scope")).toContainText("Requested award years: 2024–2026");

  await page.locator("#ii-year-start").fill("2019");
  await page.locator("#ii-year-end").fill("2019");
  await expect(page.locator("#ii-metrics")).toContainText("2026Years represented in loaded awards");
  await expect(page.locator("#ii-result-scope")).toContainText("Requested award years: 2024–2026");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  await expect(page.locator("#ii-metrics")).toContainText("1Projects loaded");
  await expect(page.locator("#ii-metrics")).toContainText("1Investigator identities in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("1Distinct programs in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("2019Years represented in loaded awards");
  await expect(page.locator("#ii-result-scope")).toContainText("Requested award years: 2019–2019");
});

test("investigator identity pagination retains the selected identity and deduplicates loaded awards", async ({ page }) => {
  mockHybrid(page);
  const calls = mockAwards(page, {
    hasMoreBySource: { NSF: [0] },
    resultCountPerSource: { NSF: 1 },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-search").click();
  await chooseInvestigator(page, "Vasily Karasiev");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeVisible();
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(2);
  await expect(page.locator("#ii-investigator-variants")).toContainText("Vasily Karasiev · 2 awards");
  await expect(page).toHaveURL(/ii_pi_identity=1/);
  expect(calls.filter(call => call.sources[0] === "NSF" && call.offset === 25).length).toBeGreaterThan(0);
  const ids = await page.locator("#ii-awards .ii-award-card").evaluateAll(cards => cards.map(card => card.id));
  expect(new Set(ids).size).toBe(ids.length);
});

test("a partial investigator-variant failure retains matches and retries the same normalized page", async ({ page }) => {
  mockHybrid(page);
  let failedVariantOnce = false;
  const calls = mockAwards(page, {
    awardOverridesBySource: {
      NSF: { principal_investigators: [{ name: "Marc D. Porosoff", role: "Principal Investigator", email: null }] },
    },
    resultCountPerSource: { NSF: 1 },
    sourceFailures: {
      NSF: ({ body }) => {
        if (body.criteria.pi === "Marc Porosoff" && !failedVariantOnce) {
          failedVariantOnce = true;
          return { status: "unavailable", code: "source_unavailable" };
        }
        return null;
      },
    },
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-agency").selectOption("NSF");
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-search").click();
  await chooseInvestigator(page, "Marc D. Porosoff");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  await expect(page.locator("#ii-source-status")).toContainText("previously loaded NSF project was retained");
  await expect(page.getByRole("button", { name: "Load additional awards" })).toBeVisible();
  const firstVariantOffsets = calls.filter(call => call.criteria.pi && call.sources[0] === "NSF").map(call => call.offset);
  expect(new Set(firstVariantOffsets)).toEqual(new Set([0]));
  const callsBeforeRetry = calls.length;
  await page.locator("#ii-topic").fill("unsent edited topic");
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect(page.locator("#ii-source-status")).toContainText("NSF available");
  await expect(page.getByRole("button", { name: "Load additional awards" })).toHaveCount(0);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(1);
  expect(calls.filter(call => call.criteria.pi === "Marc Porosoff" && call.offset === 0)).toHaveLength(2);
  for (const retryCall of calls.slice(callsBeforeRetry)) {
    expect(retryCall.criteria.institution).toBe("University of Rochester");
    expect(retryCall.criteria).not.toHaveProperty("topic");
  }
});

test("institution-only shared URLs restore and execute without an AI key", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("funding-finder.credentials.v1"));
  mockHybrid(page);
  const calls = mockAwards(page);
  await page.goto("/funded_awards.html?ii=1&ii_institution=University+of+Virginia&ii_ror=https%3A%2F%2Fror.org%2F0153tk833&ii_topic=catalysis&ii_year_start=2020&ii_year_end=2026");
  await expect(page.locator("#institutional-intelligence")).toBeVisible();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  await expect.poll(() => calls.length).toBe(3);
  for (const call of calls) expect(call.criteria).toMatchObject({
      institution: "University of Virginia",
      institution_id: "https://ror.org/0153tk833",
      topic: "catalysis",
      year_start: 2020,
      year_end: 2026,
    });
  await expect(page.locator("#ii-ai-state")).toContainText("Connect a provider");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("Who has awards in the loaded public evidence?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-key-setup")).toBeVisible();
  await expect(page.locator("#ii-key-status")).toContainText("deterministic loaded-award evidence");
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer")).toContainText("investigator identities appear");
  await expect(page.locator("#ii-direct-answer table")).toContainText("InvestigatorAwards");
  await expect(page.locator("#ii-answer-limitations")).toContainText("Question translation was unavailable");
  expect(calls).toHaveLength(6);
});

test("institutional answers use scannable tables, source-balanced evidence, and links to paged cards", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("funding-finder.credentials.v1"));
  mockHybrid(page);
  const calls = mockAwards(page, { resultCountPerSource: { NSF: 25, NIH: 4, DOE: 4 } });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("Who has awards in the loaded public evidence?");
  await page.locator("#ii-question").press("Enter");
  await expect.poll(() => calls.length).toBe(3);
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer .ii-answer-table")).toContainText("InvestigatorAwards");
  await expect(page.locator("#ii-direct-answer")).not.toContainText("currently loaded award");
  await expect(page.locator("#ii-answer-evidence .ii-evidence-list > li")).toHaveCount(24);
  await expect(page.locator("#ii-answer-evidence")).toContainText("balanced across the loaded sources");
  const evidenceSources = await page.locator("#ii-answer-evidence [data-ii-evidence-link]").evaluateAll(links => (
    links.map(link => link.textContent.trim().split(":", 1)[0])
  ));
  expect(evidenceSources.slice(0, 3)).toEqual(["NSF", "NIH", "DOE"]);
  expect(evidenceSources.filter(source => source === "NIH")).toHaveLength(4);
  expect(evidenceSources.filter(source => source === "DOE")).toHaveLength(4);
  await expect(page.locator("#ii-answer-evidence .ii-evidence-heading").first()).toContainText("Investigator:");
  await expect(page.locator("#ii-awards .ii-award-card:visible")).toHaveCount(10);
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 1–10 of 33");

  const doeEvidence = page.locator("#ii-answer-evidence [data-ii-evidence-link^='DOE:']").first();
  const doeEvidenceId = await doeEvidence.getAttribute("data-ii-evidence-link");
  await doeEvidence.click();
  const doeCard = page.locator(`[data-evidence-id="${doeEvidenceId}"]`);
  await expect(doeCard).toBeVisible();
  await expect(doeCard).toBeFocused();
  await expect(page.locator("#ii-card-page-label")).toContainText("Awards 21–30 of 33");

  await page.locator("#ii-question").fill("Which programs funded catalysis?");
  await page.locator("#ii-question").press("Enter");
  await expect.poll(() => calls.length).toBe(6);
  const programLink = page.locator("#ii-direct-answer .ii-answer-table [data-ii-evidence-link]").first();
  await expect(programLink).toBeVisible();
  const programEvidenceId = await programLink.getAttribute("data-ii-evidence-link");
  await programLink.click();
  await expect(page.locator(`[data-evidence-id="${programEvidenceId}"]`)).toBeFocused();
});

test("question submission is single-flight while institution resolution is pending", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  const providerCalls = [];
  await page.route("https://api.openai.com/v1/responses", route => {
    providerCalls.push(route.request().postDataJSON());
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify(openAiStructuredResponse({
        agency: "all",
        program: "",
        topic: "",
        pi: "",
        program_officer: "",
        year_start: "",
        year_end: "",
        answer_intent: "investigators",
        narrative_needed: false,
      })),
    });
  });
  mockHybrid(page);
  const awardCalls = mockAwards(page, { institutionResponseDelayMs: 250 });
  const registryRequests = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname === "/institutions/search") registryRequests.push(request.url());
  });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  const question = page.locator("#ii-question");
  const askButton = page.locator("#ii-ask-button");
  await question.fill("Who has awards in the loaded public evidence?");
  await question.press("Enter");
  await expect(askButton).toBeDisabled();
  await question.press("Enter");
  await question.dispatchEvent("keydown", { key: "Enter", code: "Enter", repeat: true, bubbles: true, cancelable: true });
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(askButton).toBeEnabled();
  expect(registryRequests).toHaveLength(1);
  expect(providerCalls).toHaveLength(1);
  expect(awardCalls).toHaveLength(3);
});

test("one unavailable award source does not suppress the other institutional evidence", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page, { failNih: true });
  await openInstitutionalIntelligence(page);
  await chooseInstitution(page, "MIT", "Massachusetts Institute of Technology");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(2);
  await expect(page.locator("#ii-source-status")).toContainText("NSF available");
  await expect(page.locator("#ii-source-status")).toContainText("NIH is temporarily unavailable. Retry later.");
  await expect(page.locator("#ii-source-status")).toContainText("DOE available");
  await expect(page.locator("#ii-status")).toContainText("loaded from available sources");
  await expect(page.locator("#ii-metrics")).toContainText("2Projects loaded");
  await expect(page.locator("#ii-metrics")).toContainText("2Investigator identities in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("2Distinct programs in loaded results");
  await expect(page.locator("#ii-metrics")).toContainText("2019–2026Years represented in loaded awards");
});

test("the natural-language translator reuses the saved Funding Finder provider and exposes its structured plan", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  const providerCalls = [];
  await page.route("https://api.openai.com/v1/responses", route => {
    const providerCall = route.request().postDataJSON();
    providerCalls.push(providerCall);
    const requestedQuestion = JSON.parse(providerCall.input).question;
    const topicQuestion = requestedQuestion.includes("Artificial Intelligence Research");
    const program = topicQuestion ? "" : /CAREER|Faculty Early Career/.test(requestedQuestion) ? "CAREER" : "MRI";
    const topic = topicQuestion ? "Artificial Intelligence Research" : "";
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify(openAiStructuredResponse({
        agency: topicQuestion ? "all" : "NSF",
        program,
        topic,
        pi: "",
        program_officer: "",
        year_start: "",
        year_end: "",
        answer_intent: "awards",
        narrative_needed: false,
      })),
    });
  });
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await expect(page.locator("#ii-ai-state")).toContainText("gpt-5.6-luna configured");
  await expect(page.locator("#ii-key-setup")).toBeHidden();
  await page.locator("#ii-question").fill("What has Major Research Instrumentation received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Agency: NSF");
  await expect(page.locator("#ii-question-plan")).toContainText("Program: MRI");
  await expect.poll(() => calls.at(-1)?.criteria?.program).toBe("MRI");
  expect(calls.at(-1)?.criteria).not.toHaveProperty("pi");
  expect(providerCalls).toHaveLength(1);
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-answered-question")).toHaveText("What has Major Research Instrumentation received?");
  await expect(page.locator("#ii-direct-answer")).toContainText("matching award");
  expect(providerCalls[0].store).toBe(false);
  const providerInput = JSON.parse(providerCalls[0].input);
  expect(Object.keys(providerInput).sort()).toEqual(["current_filters", "institution", "question"]);
  expect(Object.keys(providerInput.current_filters).sort()).toEqual(["agency", "pi", "program", "program_officer", "topic", "year_end", "year_start"]);
  expect(JSON.stringify(providerInput)).not.toMatch(/profile|cv_text|orcid|saved|pursuit|document/i);
  await page.locator("#ii-question").fill("What has CAREER Program received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Program: CAREER");
  await expect.poll(() => calls.at(-1)?.criteria?.program).toBe("CAREER");
  expect(calls.at(-1)?.criteria).not.toHaveProperty("pi");
  expect(providerCalls).toHaveLength(2);
  await page.locator("#ii-question").fill("What has CAREER Award received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Program: CAREER");
  await expect.poll(() => providerCalls.length).toBe(3);
  expect(calls.at(-1)?.criteria).not.toHaveProperty("pi");
  await page.locator("#ii-question").fill("What has Faculty Early Career Development received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Program: CAREER");
  await expect.poll(() => providerCalls.length).toBe(4);
  expect(calls.at(-1)?.criteria).not.toHaveProperty("pi");
  await page.locator("#ii-question").fill("What has Artificial Intelligence Research received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Topic: Artificial Intelligence Research");
  await expect.poll(() => providerCalls.length).toBe(5);
  expect(calls.slice(-3).every(call => call.criteria.topic === "Artificial Intelligence Research" && !Object.hasOwn(call.criteria, "pi"))).toBe(true);
});

test("a failed question translation falls back to visible filters and a deterministic answer", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  let providerCalls = 0;
  await page.route("https://api.openai.com/v1/responses", route => {
    providerCalls += 1;
    return route.fulfill({
      status: 503,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify({ error: { message: "translation unavailable" } }),
    });
  });
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-agency").selectOption("DOE");
  await page.locator("#ii-program").fill("BES");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("Who has DOE BES awards?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Provider translation was unavailable");
  await expect(page.locator("#ii-direct-answer")).toContainText("Marc Porosoff");
  await expect(page.locator("#ii-answer-limitations")).toContainText("Question translation was unavailable");
  expect(providerCalls).toBe(1);
  expect(calls).toHaveLength(1);
  expect(calls[0]).toMatchObject({ sources: ["DOE"], criteria: { institution: "University of Rochester", program_office: "SC-32" } });
});

test("institutional questions cite loaded evidence and refresh only on explicit request", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  const providerInputs = [];
  await page.route("https://api.openai.com/v1/responses", route => {
    const input = JSON.parse(route.request().postDataJSON().input);
    providerInputs.push(input);
    const output = Object.hasOwn(input, "current_filters")
      ? {
          agency: "NSF",
          program: "",
          topic: "catalysis",
          pi: "",
          program_officer: "",
          year_start: "",
          year_end: "",
          answer_intent: "narrative",
          narrative_needed: true,
        }
      : providerInputs.length === 2
        ? { claims: [{ text: "<b>Catalysis</b> appears in the returned public project.", evidence_ids: ["NSF:2605508"] }] }
        : { claims: [{ text: "This fabricated citation must be rejected.", evidence_ids: ["NSF:UNKNOWN"] }] };
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify(openAiStructuredResponse(output)),
    });
  });
  mockHybrid(page);
  const calls = mockAwards(page, { hasMoreAtOffsets: [0] });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("What themes appear in the catalysis project abstracts?");
  await page.locator("#ii-ask-button").click();
  await expect.poll(() => providerInputs.length).toBe(2);
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer")).toContainText("<b>Catalysis</b> appears");
  await expect(page.locator("#ii-direct-answer b")).toHaveCount(0);
  await expect(page.locator("#ii-direct-answer a[href='#ii-evidence-NSF-2605508']")).toBeVisible();
  const evidencePayload = providerInputs[1];
  expect(Object.keys(evidencePayload).sort()).toEqual([
    "answer_intent", "evidence_truncated", "institution", "public_award_evidence", "question", "visible_filters",
  ]);
  expect(evidencePayload.public_award_evidence).toHaveLength(1);
  expect(JSON.stringify(evidencePayload)).not.toMatch(/profile|cv_text|orcid|saved_notes|pursuit|alert_data|provider_key/i);
  await page.getByRole("button", { name: "Load additional awards" }).click();
  await expect.poll(() => calls.at(-1)?.offset).toBe(25);
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(2);
  expect(providerInputs).toHaveLength(2);
  await expect(page.locator("#ii-update-answer")).toBeVisible();
  await page.locator("#ii-update-answer").click();
  await expect.poll(() => providerInputs.length).toBe(3);
  await expect(page.locator("#ii-update-answer")).toBeHidden();
  await expect(page.locator("#ii-direct-answer")).toContainText("2 normalized matching awards");
  await expect(page.locator("#ii-direct-answer")).not.toContainText("fabricated");
  await expect(page.locator("#ii-answer-limitations")).toContainText("failed evidence validation");
});

test("a failed narrative provider call degrades to the deterministic loaded-award answer", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  let providerCalls = 0;
  await page.route("https://api.openai.com/v1/responses", route => {
    providerCalls += 1;
    if (providerCalls > 1) {
      return route.fulfill({
        status: 503,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
        body: JSON.stringify({ error: { message: "temporary test outage" } }),
      });
    }
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify(openAiStructuredResponse({
        agency: "NSF",
        program: "",
        topic: "catalysis",
        pi: "",
        program_officer: "",
        year_start: "",
        year_end: "",
        answer_intent: "narrative",
        narrative_needed: true,
      })),
    });
  });
  mockHybrid(page);
  mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("Interpret the loaded catalysis award title.");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer")).toContainText("1 normalized matching award");
  await expect(page.locator("#ii-answer-limitations")).toContainText("Narrative synthesis was unavailable");
  expect(providerCalls).toBe(2);
});

test("deterministic DOE investigator answers disclose partial sources and remaining pages", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  let providerCalls = 0;
  await page.route("https://api.openai.com/v1/responses", route => {
    providerCalls += 1;
    return route.fulfill({
      status: 200,
      headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
      body: JSON.stringify(openAiStructuredResponse({
        agency: "all",
        program: "",
        topic: "",
        pi: "",
        program_officer: "",
        year_start: "",
        year_end: "",
        answer_intent: "investigators",
        narrative_needed: false,
      })),
    });
  });
  mockHybrid(page);
  mockAwards(page, { failNih: true, hasMoreBySource: { DOE: [0] } });
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("Who has awards in the loaded public evidence?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-direct-answer")).toContainText("Marc Porosoff");
  await expect(page.locator("#ii-answer-limitations")).toContainText("Unavailable or unsupported sources: NIH");
  await expect(page.locator("#ii-answer-limitations")).toContainText("Additional pages remain for DOE");
  await expect(page.locator("#ii-answer-limitations")).toContainText("not a complete institutional history");
  expect(providerCalls).toBe(1, "counts and investigator lists do not make a second provider call");
});

test("the question translator preserves an explicitly named University of Rochester investigator", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  await page.route("https://api.openai.com/v1/responses", route => route.fulfill({
    status: 200,
    headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
    body: JSON.stringify(openAiStructuredResponse({ agency: "all", program: "", topic: "", pi: "", program_officer: "", year_start: "", year_end: "", answer_intent: "awards", narrative_needed: false })),
  }));
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("What has Marc Porosoff been funded to do?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Investigator: Marc Porosoff");
  await expect.poll(() => calls.length).toBe(3);
  expect(calls.every(call => call.criteria.pi === "Marc Porosoff")).toBe(true);
  await expect(page.locator("#ii-investigators")).toContainText("Marc Porosoff");
  await page.locator("#ii-question").fill("Has Marc Porosoff received NSF funding?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Agency: NSF");
  await expect(page.locator("#ii-question-plan")).toContainText("Investigator: Marc Porosoff");
  await expect.poll(() => calls.length).toBe(4);
  expect(calls.at(-1).criteria.pi).toBe("Marc Porosoff");
  await page.locator("#ii-question").fill("Show awards for Professor Marc Porosoff.");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Investigator: Marc Porosoff");
  await expect.poll(() => calls.length).toBe(7);
  expect(calls.slice(-3).every(call => call.criteria.pi === "Marc Porosoff")).toBe(true);
  await page.locator("#ii-question").fill("Show awards for Professor Marc Porosoff from NSF.");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Agency: NSF");
  await expect(page.locator("#ii-question-plan")).toContainText("Investigator: Marc Porosoff");
  await expect.poll(() => calls.length).toBe(8);
  expect(calls.at(-1).criteria.pi).toBe("Marc Porosoff");
  await page.locator("#ii-question").fill("Did Dr. Marc Porosoff receive NSF funding?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).toContainText("Investigator: Marc Porosoff");
  await expect(page.locator("#ii-question-plan")).not.toContainText("Investigator: Dr.");
  await expect.poll(() => calls.length).toBe(9);
  expect(calls.at(-1).criteria.pi).toBe("Marc Porosoff");
});

test("the question translator does not mistake a selected ROR alias for an investigator", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  await page.route("https://api.openai.com/v1/responses", route => route.fulfill({
    status: 200,
    headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
    body: JSON.stringify(openAiStructuredResponse({ agency: "all", program: "", topic: "", pi: "", program_officer: "", year_start: "", year_end: "", answer_intent: "awards", narrative_needed: false })),
  }));
  mockHybrid(page);
  const calls = mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("Cold Spring Harbor");
  await expect(page.locator("#ii-institution-options [role='option']")).toHaveCount(1);
  await page.locator("#ii-institution").press("ArrowDown");
  await page.locator("#ii-institution").press("Enter");
  await expect(page.locator("#ii-institution")).toHaveValue("Cold Spring Harbor Laboratory");
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("What has Cold Spring Harbor received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).not.toContainText("Investigator:");
  await expect.poll(() => calls.length).toBe(3);
  expect(calls.every(call => !Object.hasOwn(call.criteria, "pi"))).toBe(true);
  expect(calls.every(call => call.criteria.institution === "Cold Spring Harbor Laboratory")).toBe(true);
  await page.goto("/funded_awards.html?ii=1&ii_institution=Cold+Spring+Harbor+Laboratory&ii_ror=https%3A%2F%2Fror.org%2F02ar0d825");
  await expect(page.locator("#ii-awards .ii-award-card")).toHaveCount(3);
  await page.locator("#ii-ask").evaluate(element => { element.open = true; });
  await page.locator("#ii-question").fill("What has Cold Spring Harbor received?");
  await page.locator("#ii-ask-button").click();
  await expect(page.locator("#ii-question-plan")).not.toContainText("Investigator:");
  await expect.poll(() => calls.length).toBe(9);
  expect(calls.slice(-3).every(call => !Object.hasOwn(call.criteria, "pi"))).toBe(true);
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
  mockAwards(page, { resultCountPerSource: { NSF: 12, NIH: 0, DOE: 0 } });
  await openInstitutionalIntelligence(page);
  await chooseInstitution(page, "MIT", "Massachusetts Institute of Technology");
  await page.locator("#ii-search").click();
  await expect(page.locator("#ii-awards .ii-award-card").first()).toBeVisible();
  await expect(page.locator("#ii-awards .ii-award-card:visible")).toHaveCount(10);
  await expect(page.getByRole("button", { name: "Next 10 awards" })).toBeVisible();
  await expect(page.locator(".ii-shell-heading")).toBeHidden();
  await expect(page.locator(".ii-registry-note")).toHaveCount(0);
  await expect(page.locator("#ii-investigators")).toBeVisible();
  await expect(page.locator("#ii-programs")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const input = await page.locator("#ii-institution").boundingBox();
  expect(input.x).toBeGreaterThanOrEqual(0);
  expect(input.x + input.width).toBeLessThanOrEqual(320);
  for (const selector of ["#ii-investigators", "#ii-programs", "#ii-card-next"]) {
    const box = await page.locator(selector).boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(320);
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
});

test("evidence-grounded answers remain keyboard-operable and contained at 390 px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 760 });
  await page.addInitScript(() => localStorage.setItem("funding-finder.credentials.v1", JSON.stringify({ keys: { openai: "sk-shared-test" } })));
  await page.route("https://api.openai.com/v1/responses", route => route.fulfill({
    status: 200,
    headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
    body: JSON.stringify(openAiStructuredResponse({
      agency: "DOE",
      program: "BES",
      topic: "",
      pi: "",
      program_officer: "",
      year_start: "",
      year_end: "",
      answer_intent: "investigators",
      narrative_needed: false,
    })),
  }));
  mockHybrid(page);
  mockAwards(page);
  await openInstitutionalIntelligence(page);
  await page.locator("#ii-institution").fill("University of Rochester");
  await page.locator("#ii-ask summary").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#ii-ask")).toHaveAttribute("open", "");
  await page.locator("#ii-question").fill("Who has DOE BES awards?");
  await page.locator("#ii-question").press("Shift+Enter");
  await expect(page.locator("#ii-question-answer")).toBeHidden();
  await page.locator("#ii-question").press("Enter");
  await expect(page.locator("#ii-question-answer")).toBeVisible();
  await expect(page.locator("#ii-direct-answer")).toContainText("Marc Porosoff");
  await expect(page.locator("#ii-answer-evidence a").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  for (const selector of ["#ii-question-answer", "#ii-direct-answer", "#ii-answer-evidence"]) {
    const box = await page.locator(selector).boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
});

test("legacy Funding Finder Institutional Intelligence links redirect to Funded Awards", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page);
  await page.goto("/match_explorer.html?ii=1&ii_institution=Massachusetts+Institute+of+Technology&ii_ror=https%3A%2F%2Fror.org%2F042nb2s44");
  await expect(page).toHaveURL(/funded_awards\.html\?ii=1/);
  await expect(page.locator("#institutional-intelligence")).toBeVisible();
  await expect(page.locator("#ii-institution")).toHaveValue("Massachusetts Institute of Technology");
});

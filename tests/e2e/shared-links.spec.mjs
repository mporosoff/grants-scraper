import { expect, test } from "@playwright/test";

import { mockAwards, mockHybrid } from "./helpers.mjs";

const PREVIEW_IMAGE = "https://mporosoff.github.io/grants-scraper/assets/social/funding-finder-link-preview.jpg";

async function expectPreviewMetadata(page) {
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", PREVIEW_IMAGE);
  await expect(page.locator('meta[property="og:image:url"]')).toHaveAttribute("content", PREVIEW_IMAGE);
  await expect(page.locator('meta[property="og:image:secure_url"]')).toHaveAttribute("content", PREVIEW_IMAGE);
  await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute("content", PREVIEW_IMAGE);
  await expect(page.locator('meta[property="og:url"]')).toHaveCount(0);
  await expect(page.locator('link[rel="canonical"]')).toHaveCount(1);
}

test("bare and parameterized Funding Finder links keep encoded state, fragments, and preview metadata", async ({ page, request }) => {
  mockHybrid(page);
  mockAwards(page);

  await page.goto("/");
  await expect(page).toHaveURL(/\/match_explorer\.html$/);
  await expectPreviewMetadata(page);

  const shared = "/?q=CO%E2%82%82%20capture%20%26%20catalysis%2Fseparations%3F&status=open&status=forecasted&from=2026-09-01&attachment=notice.v2.pdf#results";
  await page.goto(shared);
  await expect(page).toHaveURL(/\/match_explorer\.html\?/);
  await expect(page.locator("#query")).toHaveValue("CO₂ capture & catalysis/separations?");
  const state = await page.evaluate(() => ({
    q: new URL(location.href).searchParams.get("q"),
    statuses: new URL(location.href).searchParams.getAll("status"),
    from: new URL(location.href).searchParams.get("from"),
    attachment: new URL(location.href).searchParams.get("attachment"),
    hash: location.hash,
    posted: document.querySelector("#status-posted").checked,
    forecasted: document.querySelector("#status-forecasted").checked,
  }));
  expect(state).toEqual({
    q: "CO₂ capture & catalysis/separations?",
    statuses: [],
    from: "2026-09-01",
    attachment: "notice.v2.pdf",
    hash: "#results",
    posted: true,
    forecasted: true,
  });
  await expectPreviewMetadata(page);

  const image = await request.get("/assets/social/funding-finder-link-preview.jpg?shared=CO2%2Fcatalysis%3F");
  expect(image.status()).toBe(200);
  expect(image.headers()["content-type"]).toBe("image/jpeg");
  expect((await image.body()).byteLength).toBeGreaterThan(100_000);
});

test("Funded Awards and Team Match extension routes retain shared state and the common preview", async ({ page }) => {
  mockHybrid(page);
  mockAwards(page);

  await page.goto("/funded_awards.html?q=CO%E2%82%82%20conversion&agency=DOE&institution=University%20of%20Rochester&year_start=2019&year_end=2026&source_file=public.abstract.html#award-results");
  await expect(page.locator("#award-query")).toHaveValue("CO₂ conversion");
  await expect(page.locator("#award-agency")).toHaveValue("DOE");
  await expect(page.locator("#award-institution")).toHaveValue("University of Rochester");
  await expect(page).toHaveURL(/source_file=public\.abstract\.html/);
  await expect(page).toHaveURL(/#award-results$/);
  await expectPreviewMetadata(page);

  await page.goto("/team_match.html?team=Alice%20%26%20Bob&topic=CO%E2%82%82%2Fcatalysis%3F&export=team.csv#view");
  const teamState = await page.evaluate(() => ({
    team: new URL(location.href).searchParams.get("team"),
    topic: new URL(location.href).searchParams.get("topic"),
    exportName: new URL(location.href).searchParams.get("export"),
    hash: location.hash,
  }));
  expect(teamState).toEqual({
    team: "Alice & Bob",
    topic: "CO₂/catalysis?",
    exportName: "team.csv",
    hash: "#view",
  });
  await expectPreviewMetadata(page);
});

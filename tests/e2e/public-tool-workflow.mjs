// Shared user-facing transitions. No direct dialog/detail state mutation: the
// same helpers work when inner content moves without becoming a new state owner.
export async function openFundingRefine(page, section = "") {
  const dialog = page.locator("#refine-search");
  if (!(await dialog.isVisible())) {
    const searched = await page.locator("#open-refine-search").isVisible();
    await page.locator(searched ? "#open-refine-search" : section === "filter-panel" ? "#add-search-filters" : "#add-research-context").click();
  }
  await dialog.waitFor({ state: "visible" });
  if (section) {
    const disclosure = page.locator(`#${section}`);
    if (!(await disclosure.evaluate(node => node.open))) await disclosure.locator(":scope > summary").click();
  }
}

export async function closeFundingRefine(page) {
  const dialog = page.locator("#refine-search");
  if (await dialog.isVisible()) await dialog.getByRole("button", { name: "Close Refine Search", exact: true }).click();
  await dialog.waitFor({ state: "hidden" });
}

export async function openAwardAi(page) {
  const dialog = page.locator("#awards-ai");
  if (!(await dialog.isVisible())) await page.locator("#open-awards-ai").click();
  await dialog.waitFor({ state: "visible" });
}

export async function closeAwardAi(page) {
  const dialog = page.locator("#awards-ai");
  if (await dialog.isVisible()) await dialog.getByRole("button", { name: "Close Ask AI", exact: true }).click();
  await dialog.waitFor({ state: "hidden" });
}

export async function showAwardView(page, view) {
  await closeAwardAi(page);
  await page.locator(`[data-award-view="${view}"]`).click();
  await page.locator(`[data-award-view-panel="${view}"]`).waitFor({ state: "visible" });
}

export async function selectAwardFacet(page, view, option) {
  await showAwardView(page, view);
  await page.locator(`#ii-${view}`).selectOption(option);
}

export async function openAwardAdvanced(page) {
  await closeAwardAi(page);
  const disclosure = page.locator("#awards-advanced");
  if (!(await disclosure.locator("#ii-program-officer").isVisible())) await disclosure.locator(":scope > summary").click();
}

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [mainPage, teamPage, awardsPage, interestsPage, navigationScript, helpScript, navigationStyles] = await Promise.all([
  readFile(new URL("../../match_explorer.html", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
  readFile(new URL("../../funded_awards.html", import.meta.url), "utf8"),
  readFile(new URL("../../faculty_interests.html", import.meta.url), "utf8"),
  readFile(new URL("../../assets/site-nav.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/site-help.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/site-nav.css", import.meta.url), "utf8"),
]);

test("links all four researcher surfaces through shared navigation", () => {
  for (const page of [mainPage, teamPage, awardsPage, interestsPage]) {
    assert.match(page, /id="primary-navigation"/);
    assert.match(page, /href="\.\/match_explorer\.html"/);
    assert.match(page, /href="\.\/team_match\.html"/);
    assert.match(page, /href="\.\/funded_awards\.html"/);
    assert.match(page, /href="\.\/faculty_interests\.html"/);
    assert.match(page, /data-nav-toggle/);
    assert.match(page, /assets\/site-nav\.css/);
    assert.match(page, /assets\/site-nav\.js/);
  }
  for (const page of [mainPage, teamPage, awardsPage]) {
    assert.match(page, /data-help-open/);
    assert.match(page, /assets\/site-help\.js/);
    const navigationEnd = page.indexOf("</nav>");
    const helpButton = page.indexOf("data-help-open", navigationEnd);
    const navigationToggle = page.indexOf("data-nav-toggle", helpButton);
    assert.ok(navigationEnd >= 0 && helpButton > navigationEnd && navigationToggle > helpButton,
      "Help must remain a persistent header action outside the collapsible navigation");
  }
  assert.match(mainPage, /href="\.\/match_explorer\.html" aria-current="page"/);
  assert.match(teamPage, /href="\.\/team_match\.html" aria-current="page"/);
  assert.match(awardsPage, /href="\.\/funded_awards\.html" aria-current="page"/);
  assert.match(interestsPage, /href="\.\/faculty_interests\.html" aria-current="page"/);
});

test("mobile navigation is accessible and safely dismissible", () => {
  assert.doesNotThrow(() => new Function(navigationScript));
  assert.match(navigationScript, /aria-expanded/);
  assert.match(navigationScript, /event\.key === "Escape"/);
  assert.match(navigationScript, /pointerdown/);
  assert.match(navigationStyles, /@media \(max-width: 1220px\)/);
  assert.match(navigationStyles, /\.site-nav\s*\{[\s\S]*?position:\s*static[\s\S]*?margin-right:\s*auto/);
  assert.match(navigationStyles, /\.nav-toggle\s*\{[\s\S]*?display:\s*none/);
  assert.match(navigationStyles, /\.site-nav\.is-open\s*\{[\s\S]*?display:\s*flex/);
  assert.match(navigationStyles, /\.site-help-button\s*\{[\s\S]*?display:\s*inline-flex/);
  assert.match(navigationStyles, /@media \(max-width: 540px\)[\s\S]*?\.site-help-label\s*\{[\s\S]*?clip:\s*rect/);
  assert.match(navigationStyles, /@media \(max-width: 390px\)[\s\S]*?\.catalog-pill-copy\s*\{[\s\S]*?clip:\s*rect/);
  assert.match(navigationStyles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(navigationStyles, /@media \(forced-colors: active\)/);
  assert.doesNotMatch(navigationStyles, /content:\s*["']Current["']/);
  assert.doesNotMatch(navigationStyles, /a\[aria-current=["']page["']\]::after/);
  assert.match(mainPage, /aria-current="page"/);
  assert.match(teamPage, /aria-current="page"/);
  assert.match(awardsPage, /aria-current="page"/);
  assert.match(interestsPage, /aria-current="page"/);
});

test("shared Help explains the full workflow, hosted AI, and optional provider keys", () => {
  assert.doesNotThrow(() => new Function(helpScript));
  assert.match(helpScript, /Search is free\. Hosted AI is included\./);
  assert.match(helpScript, /Catalog search and Team Match do not use these models/);
  assert.match(helpScript, /learn a matching full phrase from the local catalog/);
  assert.match(helpScript, /Ambiguous acronyms are left unexpanded/);
  assert.match(helpScript, /Funding Finder's hosted AI powers optional terminology expansion/);
  assert.match(helpScript, /Upload and chat with a NOFO/);
  assert.match(helpScript, /Configure personalized email alerts/);
  assert.match(helpScript, /Existing Strong matches become the baseline and do not immediately generate email/);
  assert.match(helpScript, /secure <strong>Manage alerts<\/strong> link/);
  assert.match(helpScript, /There is no Funding Finder account or public alert dashboard/);
  assert.match(helpScript, /Explore Funded Awards/);
  assert.match(helpScript, /principal investigator, program officer, agency, or year/);
  assert.match(helpScript, /Use Institutional Intelligence/);
  assert.match(helpScript, /Research Organization Registry \(ROR\)/);
  assert.match(helpScript, /Ask about this institution/);
  assert.match(helpScript, /Create an OpenAI API key/);
  assert.match(helpScript, /https:\/\/platform\.openai\.com\/api-keys/);
  assert.match(helpScript, /https:\/\/developers\.openai\.com\/api\/docs\/quickstart/);
  assert.match(helpScript, /Create an Anthropic API key/);
  assert.match(helpScript, /https:\/\/platform\.claude\.com\/settings\/keys/);
  assert.match(helpScript, /https:\/\/platform\.claude\.com\/docs\/en\/manage-claude\/authentication/);
  assert.match(helpScript, /showModal/);
  assert.match(helpScript, /dialogBody\.scrollTop = 0/);
  assert.match(helpScript, /data-help-close/);
  assert.match(navigationStyles, /\.help-dialog::backdrop/);
  assert.match(navigationStyles, /\.help-provider-grid/);
  assert.match(navigationStyles, /max-height:\s*calc\(100dvh - 16px\)/);
});

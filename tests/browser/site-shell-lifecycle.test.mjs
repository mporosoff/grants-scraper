import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";
import { shellDom } from "../helpers/shell-dom.mjs";
const shell = await readFile(new URL("../../assets/site-shell.js", import.meta.url), "utf8");
const nav = await readFile(new URL("../../assets/site-nav.js", import.meta.url), "utf8");
function fixture(options) {
  const dom = shellDom(`<header class="site-header"><button id="hamburger" data-nav-toggle aria-controls="navigation" aria-expanded="false"></button><nav id="navigation"><button id="more" data-shell-menu="navigation" aria-controls="actions" aria-expanded="false">More</button><div id="actions" hidden><button id="route" data-workspace-open data-shell-focus="alert" data-shell-mirror="alert">Create alert</button><a id="link" href="./faculty_interests.html">Update researcher profile</a></div></nav><button id="workspace" data-workspace-open>Workspace</button></header><main id="results"><button id="card" data-card-more="one" data-shell-menu="card" aria-controls="site-action-list">More</button></main><dialog id="personal-workspace" data-shell-drawer><button id="close" data-workspace-close data-shell-initial-focus>Close</button><button id="alert" disabled>Alert</button></dialog><p id="status" data-shell-status="personal-workspace"></p><button id="outside">Outside</button>`, options);
  vm.createContext(dom.context);
  vm.runInContext(shell, dom.context);
  vm.runInContext(nav, dom.context);
  dom.get = id => dom.document.getElementById(id);
  dom.click = id => dom.dispatch("click", dom.get(id));
  dom.esc = () => dom.dispatch("keydown", dom.document.activeElement, { key: "Escape" });
  return dom;
}
test("nested mobile disclosure, Escape, outside click, Tab exit and terminal navigation have one owner", () => {
  const dom = fixture();
  dom.click("hamburger"); dom.click("more");
  assert.equal(dom.get("hamburger").getAttribute("aria-expanded"), "true");
  assert.equal(dom.get("more").getAttribute("aria-expanded"), "true");
  assert.equal(dom.document.activeElement.id, "link", "disabled canonical alert is mirrored");
  assert.equal(dom.esc().prevented, true);
  assert.equal(dom.document.activeElement.id, "more");
  assert.equal(dom.get("hamburger").getAttribute("aria-expanded"), "true");
  dom.click("more"); dom.dispatch("pointerdown", dom.get("outside"));
  assert.equal(dom.get("actions").hidden, true);
  assert.equal(dom.document.activeElement.id, "more");
  dom.click("more"); dom.get("outside").focus();
  assert.equal(dom.get("actions").hidden, true);
  assert.equal(dom.document.activeElement.id, "outside", "ordinary Tab departure is not trapped");
  dom.click("hamburger"); dom.click("more"); dom.click("link");
  assert.equal(dom.get("hamburger").getAttribute("aria-expanded"), "false");
  const count = [...dom.listeners.values()].reduce((n, entries) => n + entries.length, 0);
  vm.runInContext(shell, dom.context);
  assert.equal([...dom.listeners.values()].reduce((n, entries) => n + entries.length, 0), count);
});

test("without Popover support all dismissal paths hide menus and restore the appropriate focus", async () => {
  const dom = fixture({ popover: false });
  const closed = () => {
    assert.equal(dom.get("actions").hidden, true);
    assert.equal(dom.get("more").getAttribute("aria-expanded"), "false");
  };
  dom.click("more"); dom.esc(); closed();
  assert.equal(dom.document.activeElement.id, "more");
  dom.click("more"); dom.dispatch("pointerdown", dom.get("outside")); closed();
  dom.click("more"); dom.get("outside").focus(); closed();
  assert.equal(dom.document.activeElement.id, "outside");
  dom.click("more"); dom.click("link"); closed();
  dom.click("more"); dom.click("more"); closed();
  dom.click("more"); dom.click("workspace"); closed();
  dom.click("close");
  dom.click("more"); dom.document.body.scrollTop = 1; dom.dispatch("scroll", dom.document.body); closed();
  dom.context.SiteShell.registerMenu("card", () => [{ label: "Track", html: '<button id="watch">Alert</button>' }]);
  dom.click("card"); dom.click("watch");
  assert.equal(dom.document.activeElement.id, "card");
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(dom.get("watch"), null);
  dom.click("card"); dom.dispatch("funding-finder:before-results-render", dom.document.body);
  assert.equal(dom.get("site-action-list").hidden, true);
  dom.click("card"); dom.get("card").remove(); dom.mutate();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(dom.get("site-action-list").hidden, true);
  assert.equal(dom.get("watch"), null);
});
test("queued pre-open scroll events do not dismiss menus, but subsequent document and ancestor movement do", () => {
  for (const popover of [true, false]) for (const origin of ["document", "ancestor"]) {
    const dom = fixture({ popover });
    dom.context.scrollX = 0; dom.context.scrollY = 400;
    const ancestor = dom.get("navigation");
    ancestor.scrollLeft = 0; ancestor.scrollTop = 200;
    dom.click("more");
    const target = origin === "document" ? dom.document : ancestor;
    dom.dispatch("scroll", target);
    assert.equal(dom.get("actions").hidden, false, `${origin}: movement before opening is already accounted for`);
    assert.equal(dom.document.activeElement.id, "link");
    if (origin === "document") dom.context.scrollY += 10;
    else ancestor.scrollLeft += 10;
    dom.dispatch("scroll", target);
    assert.equal(dom.get("actions").hidden, true, `${origin}: actual later movement still dismisses`);
    assert.equal(dom.document.activeElement.id, "more");
  }
});
test("drawer alert route mirrors availability and returns to exact results opener, without another submission", () => {
  const dom = fixture();
  dom.get("alert").disabled = false;
  dom.click("more");
  assert.equal(dom.get("route").disabled, false);
  dom.click("route");
  assert.equal(dom.get("personal-workspace").open, true);
  assert.equal(dom.document.activeElement.id, "alert");
  assert.equal(dom.get("alert").scrolled, true);
  assert.equal(dom.get("personal-workspace").contains(dom.get("status")), true);
  dom.click("close");
  assert.equal(dom.document.activeElement.id, "more");
  assert.equal(dom.get("personal-workspace").contains(dom.get("status")), false);
  dom.click("workspace");
  assert.equal(dom.document.activeElement.id, "close");
  // Native Escape dispatches close; the controller owns cleanup/restoration.
  dom.get("personal-workspace").close();
  assert.equal(dom.document.activeElement.id, "workspace");
  dom.click("workspace");
  dom.dispatch("click", dom.get("personal-workspace"), { clientX: 300, clientY: 300 });
  assert.equal(dom.get("personal-workspace").open, false);
});

test("drawer switches clean up synchronously and stale native close events cannot detach reopened ownership", async () => {
  const dom = fixture({ deferredClose: true });
  const drawer = dom.document.createElement("dialog");
  drawer.id = "analysis";
  drawer.innerHTML = '<button id="analysis-close" data-shell-drawer-close>Close</button>';
  dom.document.body.append(drawer);
  let closes = 0;
  dom.click("workspace");
  dom.context.SiteShell.openDrawer(drawer, dom.get("card"), dom.get("analysis-close"), {
    context: "opportunity", onClose: () => closes++,
    resolveOpener: () => dom.get("card"),
  });
  assert.equal(dom.get("personal-workspace").open, false);
  assert.equal(dom.get("personal-workspace").contains(dom.get("status")), false);
  assert.equal(drawer.getAttribute("data-shell-context"), "opportunity");
  dom.context.SiteShell.closeDrawer(drawer, { restoreFocus: false });
  assert.equal(closes, 1);
  dom.context.SiteShell.openDrawer(drawer, dom.get("card"), dom.get("analysis-close"), { onClose: () => closes++, resolveOpener: () => dom.get("card") });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(drawer.open, true);
  assert.equal(closes, 1);
  dom.context.SiteShell.closeDrawer(drawer);
  const oldOpener = dom.get("card");
  oldOpener.after(dom.document.createElement("button"));
  oldOpener.remove();
  const replacement = dom.document.createElement("button");
  replacement.id = "card";
  dom.get("results").append(replacement);
  await Promise.resolve();
  assert.equal(dom.document.activeElement, replacement);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(closes, 2);
  assert.equal(dom.document.documentElement.classList.contains("shell-drawer-open"), false);
});
test("single card menu delegates original data, fits at 320px, and cleans up after action/rerender", async () => {
  const dom = fixture();
  dom.context.SiteShell.registerMenu("card", () => [{ label: "Track", html: '<button id="watch" data-watch-opportunity="one">Alert</button>' }]);
  dom.get("card").rect = { left: 280, right: 310, top: 445, bottom: 475, width: 30, height: 30 };
  dom.click("card");
  const menu = dom.get("site-action-list");
  assert.equal(dom.document.activeElement.id, "watch");
  assert.equal(dom.get("results").contains(menu), true);
  assert.ok(parseFloat(menu.style.left) >= 8);
  assert.ok(parseFloat(menu.style.left) + 280 <= 312);
  assert.ok(parseFloat(menu.style.top) + 200 <= 472);
  dom.click("watch");
  assert.equal(dom.context.SiteShell.actionOpener(dom.get("watch")), dom.get("card"));
  assert.equal(dom.document.activeElement.id, "card");
  assert.equal(dom.get("watch").getAttribute("data-watch-opportunity"), "one", "existing delegates retain their event target through propagation");
  await Promise.resolve();
  assert.equal(dom.get("results").contains(dom.get("watch")), true, "microtask checkpoints between native capture/bubble listeners cannot detach the action");
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(dom.get("watch"), null);
  dom.click("card"); dom.dispatch("funding-finder:before-results-render", dom.document.body);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(menu.hidden, true);
  assert.equal(dom.get("results").contains(menu), false);
  dom.click("card"); dom.get("card").remove(); dom.mutate();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(menu.hidden, true);
  assert.equal(menu.querySelectorAll("button").length, 0);
});

test("menus fit every release width and the smaller panned visual viewport during pinch zoom", () => {
  const dom = fixture();
  // The viewport listener is registered at initialization, so use the existing
  // window resize callback to exercise the same positioning function.
  const reposition = dom.windowListeners.find(item => item.type === "resize").callback;
  const menu = dom.get("actions");
  const viewport = { width: 320, height: 640, offsetLeft: 0, offsetTop: 0 };
  dom.context.visualViewport = viewport;
  menu.getBoundingClientRect = () => ({
    width: Math.min(280, parseFloat(menu.style.maxWidth)),
    height: Math.min(400, parseFloat(menu.style.maxHeight)),
  });
  dom.click("more");
  for (const width of [320, 360, 390, 430, 768, 1280, 160]) {
    Object.assign(viewport, { width, height: width === 160 ? 220 : 640, offsetLeft: width === 160 ? 70 : 0, offsetTop: 35 });
    dom.get("more").rect = { right: viewport.offsetLeft + width - 4, top: 600, bottom: 638 };
    reposition();
    const box = menu.getBoundingClientRect();
    assert.equal(menu.style.minWidth, `min(15rem, ${width - 16}px)`, "A layout-viewport minimum cannot override the visual-viewport maximum");
    assert.ok(parseFloat(menu.style.left) >= viewport.offsetLeft + 8);
    assert.ok(parseFloat(menu.style.left) + box.width <= viewport.offsetLeft + width - 8);
    assert.ok(parseFloat(menu.style.top) >= viewport.offsetTop + 8);
    assert.ok(parseFloat(menu.style.top) + box.height <= viewport.offsetTop + viewport.height - 8);
  }
});

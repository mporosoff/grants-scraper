/* Presentation only. Search, snapshots, identities and storage stay with their existing owners. */
(() => {
  "use strict";
  if (globalThis.PublicTools) return;
  const $ = id => document.getElementById(id);
  const shell = globalThis.SiteShell;
  if (!shell) return;

  // Sticky offsets follow the actual header and text-scaled team summary.
  if (globalThis.ResizeObserver) {
    const header = document.querySelector(".site-header");
    const summary = $("team-mobile-summary");
    const measure = () => {
      document.documentElement.style.setProperty("--public-header-height", `${header?.getBoundingClientRect().height || 0}px`);
      document.documentElement.style.setProperty("--team-summary-height", `${summary?.getBoundingClientRect().height || 0}px`);
    };
    const observer = new ResizeObserver(measure);
    if (header) observer.observe(header);
    if (summary) observer.observe(summary);
    measure();
  }

  const teamEditor = $("team-editor-content");
  if (teamEditor) {
    const sidebar = $("team-sidebar");
    const sheet = $("team-editor-sheet");
    const sheetBody = $("team-editor-sheet-body");
    const opener = $("edit-team");
    const mobile = matchMedia("(max-width: 800px)");
    const open = target => shell.openDrawer(sheet, opener, target || sheet.querySelector("[data-shell-close]"), {
      onClose: () => $("team-status-home").append($("external-status")),
    });
    function placeEditor() {
      const focused = document.activeElement;
      const editing = teamEditor.contains(focused);
      if (mobile.matches) {
        sheetBody.append(teamEditor);
        if (editing) open(focused);
      } else {
        const wasOpen = sheet.open;
        shell.closeDrawer(sheet, { restoreFocus: false });
        sidebar.append(teamEditor);
        if (wasOpen) (editing && !focused.disabled ? focused : sidebar).focus({ preventScroll: true });
      }
      document.documentElement.classList.add("team-sheet-ready");
    }
    opener.addEventListener("click", () => open());
    sheet.addEventListener("keydown", event => {
      if (event.key === "Escape" && event.target === $("faculty-search") && event.target.getAttribute("aria-expanded") === "true") {
        // The existing combobox handler owns this Escape; suppress native dialog cancellation only.
        event.preventDefault();
      }
    }, true);
    mobile.addEventListener("change", placeEditor);
    placeEditor();
  }

  const awardDialog = $("awards-ai");
  const awardOpener = $("open-awards-ai");
  function showAwardView(view) {
    const button = document.querySelector(`[data-award-view='${view}']`);
    if (!button) return;
    document.querySelectorAll("[data-award-view]").forEach(node => node.setAttribute("aria-pressed", node === button ? "true" : "false"));
    document.querySelectorAll("[data-award-view-panel]").forEach(node => { node.hidden = node.dataset.awardViewPanel !== view; });
  }
  function revealField(target) {
    for (let node = target?.parentElement; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
  }
  function syncAwardForm() {
    const advanced = $("awards-advanced");
    if (advanced && [...advanced.querySelectorAll("input")].some(input => input.value)) advanced.open = true;
  }
  function awardAiOpen() { return Boolean(awardDialog?.open); }
  function showAwardProjects({ closeAi = false } = {}) {
    if (closeAi) shell.closeDrawer(awardDialog, { restoreFocus: false });
    showAwardView("projects");
  }
  function resetAwardViews() {
    showAwardView("projects");
    $("ii-output-heading").textContent = "Funded award summary";
    $("ii-result-scope").textContent = "";
  }
  function restoreAwardFocus(id) {
    const target = $(id);
    if (!target) return;
    if (awardDialog?.contains(target) && !awardDialog.open) return awardOpener.focus({ preventScroll: true });
    const panel = target.closest("[data-award-view-panel]");
    if (panel) showAwardView(panel.dataset.awardViewPanel);
    revealField(target);
    target.focus({ preventScroll: true });
  }
  if (awardDialog) {
    awardOpener.addEventListener("click", () => shell.openDrawer(awardDialog, awardOpener, $("ii-question"), {
      onClose: () => $("awards-status-home").append($("ii-results-note")),
    }));
    document.querySelector(".public-view-switcher").addEventListener("click", event => {
      const button = event.target.closest("[data-award-view]");
      if (button) showAwardView(button.dataset.awardView);
    });
    // Native form validation runs before submit; reveal a collapsed invalid field
    // before the browser tries to focus it. Keep the original validation rules.
    $("ii-form").addEventListener("invalid", event => revealField(event.target), true);
  }
  globalThis.PublicTools = Object.freeze({
    updateTeamSummary(names, deferred) {
      const summary = $("team-selected-summary");
      if (summary) summary.textContent = deferred ? "Saved team awaiting directory" : names.length ? `${names.length} selected · ${names.join(" · ")}` : "No researchers selected";
    },
    syncAwardForm, awardAiOpen, showAwardProjects, resetAwardViews, restoreAwardFocus,
  });
})();

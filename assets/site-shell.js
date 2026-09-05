(() => {
  "use strict";
  if (globalThis.SiteShell) return;

  const providers = new Map();
  const actionOwners = new WeakMap();
  let activeMenu = null;
  let activeDrawer = null;
  const cardMenu = document.createElement("div");
  cardMenu.id = "site-action-list";
  cardMenu.className = "shell-action-list";
  cardMenu.hidden = true;
  cardMenu.setAttribute("popover", "manual");
  document.body.append(cardMenu);
  const focusable = root => [...root.querySelectorAll("a[href], button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex='0']")]
    .filter(node => !node.hidden && node.getClientRects().length);
  const restore = opener => {
    if (opener?.isConnected) opener.focus({ preventScroll: true });
  };

  function closeMenu({ restoreFocus = true } = {}) {
    if (!activeMenu) return;
    const { opener, menu } = activeMenu;
    activeMenu = null;
    opener.setAttribute("aria-expanded", "false");
    // Legacy browsers use the fixed-position fallback and do not recognize
    // :popover-open. Feature-detect before evaluating the native selector.
    if (typeof menu.hidePopover === "function" && menu.matches(":popover-open")) menu.hidePopover();
    menu.hidden = true;
    if (restoreFocus) restore(opener);
    // Keep the activated node attached through event propagation so existing
    // delegated product handlers see its original data and ancestor card.
    // A browser can run microtasks between capture and bubble listeners.
    // Detach in the next task, after the complete native click dispatch.
    if (menu === cardMenu) globalThis.setTimeout(() => {
      if (activeMenu?.menu !== cardMenu) {
        cardMenu.replaceChildren();
        document.body.append(cardMenu);
      }
    }, 0);
  }

  function positionMenu() {
    if (!activeMenu) return;
    const { opener, menu } = activeMenu;
    const viewport = globalThis.visualViewport;
    const width = viewport?.width || document.documentElement.clientWidth;
    const height = viewport?.height || globalThis.innerHeight;
    const leftEdge = viewport?.offsetLeft || 0;
    const topEdge = viewport?.offsetTop || 0;
    const gap = 8;
    menu.style.maxWidth = `${Math.max(0, width - 2 * gap)}px`;
    // Pinch zoom can make the visual viewport narrower than the CSS minimum.
    // Constrain both bounds so the minimum cannot override the maximum.
    menu.style.minWidth = `min(15rem, ${Math.max(0, width - 2 * gap)}px)`;
    menu.style.maxHeight = `${Math.max(0, height - 2 * gap)}px`;
    const anchor = opener.getBoundingClientRect();
    const box = menu.getBoundingClientRect();
    const left = Math.max(leftEdge + gap, Math.min(anchor.right - box.width, leftEdge + width - box.width - gap));
    const below = anchor.bottom + gap;
    const top = below + box.height <= topEdge + height - gap
      ? below : Math.max(topEdge + gap, Math.min(anchor.top - box.height - gap, topEdge + height - box.height - gap));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function openMenu(opener) {
    if (activeMenu?.opener === opener) return closeMenu();
    closeMenu({ restoreFocus: false });
    const provider = providers.get(opener.dataset.shellMenu);
    const menu = provider ? cardMenu : document.getElementById(opener.getAttribute("aria-controls"));
    if (!menu) return;
    if (provider) {
      const groups = provider(opener) || [];
      cardMenu.replaceChildren();
      for (const group of groups) {
        if (!group.html) continue;
        const section = document.createElement("div");
        section.className = "shell-action-group";
        section.setAttribute("role", "group");
        section.setAttribute("aria-label", group.label);
        const heading = document.createElement("p");
        heading.className = "shell-action-heading";
        heading.textContent = group.label;
        section.append(heading);
        section.insertAdjacentHTML("beforeend", group.html);
        cardMenu.append(section);
      }
      // One materialized card menu, in logical Tab/delegation order.
      opener.after(cardMenu);
    }
    menu.querySelectorAll("[data-shell-mirror]").forEach(command => {
      const canonical = document.getElementById(command.dataset.shellMirror);
      command.disabled = !canonical || canonical.disabled;
      command.title = canonical?.title || "";
    });
    menu.querySelectorAll("a, button").forEach(action => actionOwners.set(action, opener));
    menu.hidden = false;
    menu.setAttribute("popover", "manual");
    menu.setAttribute("aria-label", opener.getAttribute("aria-label") || "More actions");
    // A browser can deliver a scroll queued before the click after this menu
    // opens. Only subsequent movement should dismiss the newly opened menu.
    const scrollPositions = new Map([[document, [globalThis.scrollX, globalThis.scrollY]]]);
    for (let node = opener.parentElement; node; node = node.parentElement) {
      scrollPositions.set(node, [node.scrollLeft, node.scrollTop]);
    }
    activeMenu = { opener, menu, scrollPositions };
    opener.setAttribute("aria-expanded", "true");
    menu.showPopover?.();
    positionMenu();
    focusable(menu)[0]?.focus({ preventScroll: true });
  }

  function finishDrawer(dialog) {
    if (activeDrawer?.dialog !== dialog) return;
    const { opener, status, onClose, resolveOpener, closeOptions = {} } = activeDrawer;
    activeDrawer = null;
    if (status) dialog.after(status);
    document.documentElement.classList.remove("shell-drawer-open");
    opener?.setAttribute("aria-expanded", "false");
    dialog.removeAttribute("data-shell-context");
    onClose?.();
    if (closeOptions.restoreFocus !== false) {
      restore(resolveOpener?.() || opener);
      // A result render can replace the opener after its before-render event.
      queueMicrotask(() => {
        if (!activeDrawer && !opener?.isConnected) restore(resolveOpener?.());
      });
    }
  }

  function closeDrawer(dialog = activeDrawer?.dialog, options = {}) {
    if (!dialog || activeDrawer?.dialog !== dialog) return;
    activeDrawer.closeOptions = options;
    dialog.close();
    // Native close events are queued. Complete ownership now so another
    // drawer can open without losing the outgoing content's cleanup.
    finishDrawer(dialog);
  }

  function openDrawer(dialog, opener, target, options = {}) {
    if (!dialog) return;
    closeMenu({ restoreFocus: false });
    if (activeDrawer && activeDrawer.dialog !== dialog) closeDrawer(activeDrawer.dialog, { restoreFocus: false });
    if (!dialog.open) {
      // A single status node stays perceivable both inside an open modal and
      // outside it when closed; never create a second announcement owner.
      const status = [...document.querySelectorAll("[data-shell-status]")].find(node => node.dataset.shellStatus.split(/\s+/).includes(dialog.id));
      activeDrawer = { dialog, opener, status, onClose: options.onClose, resolveOpener: options.resolveOpener };
      if (status) dialog.append(status);
      document.documentElement.classList.add("shell-drawer-open");
      if (options.context) dialog.setAttribute("data-shell-context", options.context);
      opener?.setAttribute("aria-expanded", "true");
      try { dialog.showModal(); } catch (error) { finishDrawer(dialog); throw error; }
    }
    const initial = target || dialog.querySelector("[data-shell-initial-focus]") || focusable(dialog)[0];
    initial?.focus({ preventScroll: true });
    if (target) target.scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("click", event => {
    const target = event.target;
    const command = target.closest("a, button");
    const owner = actionOwners.get(command) || command;
    if (activeMenu?.menu.contains(target) && command && !command.disabled) closeMenu();
    const opener = target.closest("[data-shell-menu]");
    if (opener) { openMenu(opener); return; }
    const drawerOpener = target.closest("[data-workspace-open], [data-shell-drawer-open]");
    if (drawerOpener && !drawerOpener.disabled) {
      const dialog = document.getElementById(drawerOpener.dataset.shellDrawerOpen || "personal-workspace");
      const focus = drawerOpener.dataset.shellFocus ? document.getElementById(drawerOpener.dataset.shellFocus) : null;
      openDrawer(dialog, owner, focus);
      return;
    }
    const closer = target.closest("[data-workspace-close], [data-shell-drawer-close]");
    if (closer) closeDrawer(closer.closest("dialog[data-shell-drawer]"));
    if (target === activeDrawer?.dialog) {
      const box = target.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeDrawer(target);
    }
  }, true);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && activeMenu) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeMenu();
    }
  }, true);
  document.addEventListener("pointerdown", event => {
    if (activeMenu && !activeMenu.menu.contains(event.target) && !activeMenu.opener.contains(event.target)) closeMenu();
  }, true);
  document.addEventListener("focusin", event => {
    if (activeMenu && !activeMenu.menu.contains(event.target) && event.target !== activeMenu.opener) closeMenu({ restoreFocus: false });
  });
  document.addEventListener("close", event => {
    // Ignore an earlier close event if this dialog has already been reopened.
    if (!event.target.open) finishDrawer(event.target);
  }, true);
  document.addEventListener("funding-finder:before-results-render", () => {
    const opener = activeMenu?.opener;
    const id = opener?.dataset.cardMore;
    closeMenu();
    if (id) queueMicrotask(() => {
      const replacement = [...document.querySelectorAll("[data-card-more]")].find(node => node.dataset.cardMore === id);
      if (!opener.isConnected && document.activeElement === document.body) restore(replacement);
    });
  });
  globalThis.addEventListener("resize", positionMenu);
  globalThis.visualViewport?.addEventListener("resize", positionMenu);
  globalThis.visualViewport?.addEventListener("scroll", positionMenu);
  document.addEventListener("scroll", event => {
    if (!activeMenu || activeMenu.menu.contains(event.target)) return;
    const prior = activeMenu.scrollPositions.get(event.target);
    const current = event.target === document
      ? [globalThis.scrollX, globalThis.scrollY] : [event.target.scrollLeft, event.target.scrollTop];
    if (prior && prior[0] === current[0] && prior[1] === current[1]) return;
    closeMenu();
  }, true);
  const observer = new MutationObserver(() => {
    if (activeMenu && !activeMenu.opener.isConnected) closeMenu({ restoreFocus: false });
    if (activeDrawer && !activeDrawer.dialog.isConnected) finishDrawer(activeDrawer.dialog);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  globalThis.SiteShell = Object.freeze({
    registerMenu: (name, provider) => providers.set(name, provider),
    actionOpener: action => actionOwners.get(action) || action,
    closeMenu, openDrawer, closeDrawer,
  });
})();

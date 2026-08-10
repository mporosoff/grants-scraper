(() => {
  "use strict";

  const toggle = document.querySelector("[data-nav-toggle]");
  if (!toggle) return;

  const menuId = toggle.getAttribute("aria-controls");
  const menu = menuId ? document.getElementById(menuId) : null;
  const header = toggle.closest(".site-header");
  if (!menu || !header) return;

  function setOpen(open, returnFocus = false) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Close navigation menu" : "Open navigation menu");
    menu.classList.toggle("is-open", open);
    if (returnFocus) toggle.focus();
  }

  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  menu.addEventListener("click", event => {
    if (event.target.closest("a")) setOpen(false);
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false, true);
    }
  });

  document.addEventListener("pointerdown", event => {
    if (toggle.getAttribute("aria-expanded") === "true" && !header.contains(event.target)) {
      setOpen(false);
    }
  });

  const desktop = globalThis.matchMedia?.("(min-width: 821px)");
  desktop?.addEventListener?.("change", event => {
    if (event.matches) setOpen(false);
  });
})();

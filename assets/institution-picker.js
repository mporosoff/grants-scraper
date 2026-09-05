/* Optional ROR selection using the same public lookup service as Funded Awards. */
(() => {
  "use strict";
  if (globalThis.FUNDING_INSTITUTION_PICKER) return;
  function create({ input, idInput, list, status, onChange = () => {} }) {
    let sequence = 0, timer, controller, candidates = [], active = -1;
    const hide = () => {
      list.classList.add("hidden");
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    };
    function cancel() { sequence += 1; clearTimeout(timer); controller?.abort(); hide(); }
    function setValue(name = "", id = "") {
      cancel(); input.value = name; idInput.value = id;
      status.textContent = id ? "Selected from the Research Organization Registry (ROR)." : "Optional: search ROR or enter the institution’s complete name.";
    }
    function select(index) {
      const choice = candidates[index];
      if (!choice) return;
      setValue(choice.canonical_name, choice.id);
      onChange(); input.focus();
    }
    function highlight(index) {
      const options = [...list.querySelectorAll("[role='option']")];
      if (!options.length) return;
      active = Math.max(0, Math.min(options.length - 1, index));
      options.forEach((node, i) => node.setAttribute("aria-selected", String(i === active)));
      input.setAttribute("aria-activedescendant", options[active].id);
      options[active].scrollIntoView({ block: "nearest" });
    }
    async function search(query, requestSequence) {
      if (requestSequence !== sequence) return;
      controller = new AbortController();
      const requestController = controller;
      const timeout = setTimeout(() => requestController.abort(), 10000);
      status.textContent = "Searching the Research Organization Registry (ROR)…";
      try {
        const url = new URL(globalThis.FUNDING_AWARD_API_CONFIG.institutionSearchUrl);
        url.searchParams.set("query", query);
        const response = await fetch(url, { headers: { Accept: "application/json" }, credentials: "omit", signal: requestController.signal });
        const payload = await response.json();
        if (!response.ok || !Array.isArray(payload.institutions)) throw new Error("Lookup unavailable");
        if (requestSequence !== sequence) return;
        candidates = payload.institutions.filter(item => typeof item.canonical_name === "string" && item.canonical_name.trim() && item.canonical_name.length <= 300 && /^https:\/\/ror\.org\/0[a-z0-9]{8}$/.test(item.id)).slice(0, 8);
        list.textContent = "";
        candidates.forEach((item, index) => {
          const option = document.createElement("button");
          option.type = "button"; option.id = `${list.id}-${index}`;
          option.setAttribute("role", "option"); option.setAttribute("aria-selected", "false");
          option.dataset.institutionIndex = String(index);
          const location = [item.location?.city, item.location?.country].filter(value => typeof value === "string" && value.trim()).join(", ");
          option.textContent = item.canonical_name + (location ? ` · ${location}` : "");
          list.append(option);
        });
        list.classList.toggle("hidden", !candidates.length);
        input.setAttribute("aria-expanded", String(Boolean(candidates.length)));
        status.textContent = candidates.length ? "Choose the intended institution; a similar name does not establish affiliation." : "No ROR suggestion found. You can enter the institution’s complete name for review.";
      } catch (_error) {
        if (requestSequence !== sequence) return;
        hide();
        status.textContent = "ROR lookup is temporarily unavailable. You can still enter the institution’s complete name for review.";
      } finally { clearTimeout(timeout); }
    }
    input.addEventListener("input", () => {
      cancel(); idInput.value = ""; onChange();
      const query = input.value.trim().slice(0, 120);
      status.textContent = "Optional: type at least two characters to search ROR.";
      if (query.length >= 2) { const current = sequence; timer = setTimeout(() => search(query, current), 300); }
    });
    input.addEventListener("keydown", event => {
      if (list.classList.contains("hidden")) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault(); highlight(event.key === "ArrowDown" ? active + 1 : active < 0 ? candidates.length - 1 : active - 1);
      } else if (event.key === "Enter") { event.preventDefault(); if (active >= 0) select(active); }
      else if (event.key === "Escape") { event.preventDefault(); cancel(); }
    });
    input.addEventListener("blur", cancel);
    list.addEventListener("mousedown", event => event.preventDefault());
    list.addEventListener("click", event => { const option = event.target.closest("[data-institution-index]"); if (option) select(Number(option.dataset.institutionIndex)); });
    setValue(input.value, idInput.value);
    return Object.freeze({ setValue });
  }
  globalThis.FUNDING_INSTITUTION_PICKER = Object.freeze({ create });
})();

(() => {
  "use strict";

  const config = globalThis.FUNDING_ALERTS_CONFIG || {};
  const TYPE_LABELS = Object.freeze({
    opportunity: "Watch this opportunity",
    saved_search: "Save this search as an email alert",
    program: "Watch this program",
  });
  let dialog = null;
  let current = null;
  let restoreFocus = null;
  let lastEmail = "";
  let scrollLock = null;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"]/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    })[character]);
  }

  function boundedErrorCode(payload) {
    const code = typeof payload?.error?.code === "string"
      ? payload.error.code.trim().toLowerCase()
      : "";
    return ["alerts_unavailable", "invalid_request", "rate_limited", "service_unavailable"]
      .includes(code) ? code : "";
  }

  function errorMessage(code) {
    if (code === "rate_limited") {
      return "Too many alert requests. Wait before trying again.";
    }
    if (code === "invalid_request") {
      return "Check the alert details and try again.";
    }
    if (["alerts_unavailable", "service_unavailable"].includes(code)) {
      return "Email alert delivery is unavailable. Retry later. Funding Finder and saved items still work normally.";
    }
    if (code === "timeout") {
      return "The email alert request timed out. Retry later. Funding Finder and saved items still work normally.";
    }
    if (code === "invalid_response") {
      return "The email alert service returned an invalid response. Retry later. Funding Finder and saved items still work normally.";
    }
    return "The email alert service could not be reached. Retry later. Funding Finder and saved items still work normally.";
  }

  function setSubmitStatus(node, message, { error = false } = {}) {
    node.textContent = message;
    node.classList.toggle("error-text", error);
  }

  function lockBackgroundScroll() {
    if (scrollLock) return;
    const root = document.documentElement;
    const body = document.body;
    const scrollbarWidth = Math.max(0, window.innerWidth - root.clientWidth);
    scrollLock = {
      x: window.scrollX,
      y: window.scrollY,
      rootOverflow: root.style.overflow,
      bodyPosition: body.style.position,
      bodyTop: body.style.top,
      bodyLeft: body.style.left,
      bodyRight: body.style.right,
      bodyWidth: body.style.width,
      bodyOverflow: body.style.overflow,
      bodyPaddingRight: body.style.paddingRight,
    };
    root.classList.add("alert-dialog-open");
    body.classList.add("alert-dialog-open");
    root.style.overflow = "hidden";
    body.style.position = "fixed";
    body.style.top = `-${scrollLock.y}px`;
    body.style.left = `-${scrollLock.x}px`;
    body.style.right = "0";
    body.style.width = "100%";
    body.style.overflow = "hidden";
    if (scrollbarWidth) {
      body.style.paddingRight = `calc(${getComputedStyle(body).paddingRight} + ${scrollbarWidth}px)`;
    }
  }

  function unlockBackgroundScroll() {
    if (!scrollLock) return;
    const root = document.documentElement;
    const body = document.body;
    const saved = scrollLock;
    scrollLock = null;
    root.classList.remove("alert-dialog-open");
    body.classList.remove("alert-dialog-open");
    root.style.overflow = saved.rootOverflow;
    body.style.position = saved.bodyPosition;
    body.style.top = saved.bodyTop;
    body.style.left = saved.bodyLeft;
    body.style.right = saved.bodyRight;
    body.style.width = saved.bodyWidth;
    body.style.overflow = saved.bodyOverflow;
    body.style.paddingRight = saved.bodyPaddingRight;
    window.scrollTo(saved.x, saved.y);
  }

  function dialogFocusableElements() {
    if (!dialog) return [];
    return [...dialog.querySelectorAll('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])')]
      .filter(element => !element.disabled && !element.closest("[hidden], .hidden")
        && getComputedStyle(element).display !== "none" && getComputedStyle(element).visibility !== "hidden");
  }

  function restoreDialogState() {
    const target = restoreFocus;
    restoreFocus = null;
    unlockBackgroundScroll();
    if (target?.isConnected && !target.disabled) target.focus({ preventScroll: true });
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.className = "alert-dialog";
    dialog.setAttribute("aria-labelledby", "alert-dialog-title");
    dialog.innerHTML = `
      <form class="alert-dialog-card" id="alert-subscription-form">
        <div class="alert-dialog-heading">
          <div><p class="eyebrow">Personalized email alert</p><h2 id="alert-dialog-title"></h2></div>
          <button class="alert-dialog-close" type="button" aria-label="Close alert setup">×</button>
        </div>
        <p id="alert-dialog-summary"></p>
        <fieldset class="alert-trigger-fields hidden" id="alert-trigger-fields">
          <legend>Email me when</legend>
          <label><input type="checkbox" name="trigger" value="deadline_changed" checked> Deadline changes</label>
          <label><input type="checkbox" name="trigger" value="amended" checked> The opportunity is amended</label>
          <label><input type="checkbox" name="trigger" value="closing_reminders" checked> It is 30, 14, or 7 days from closing</label>
          <label><input type="checkbox" name="trigger" value="status_changed" checked> Status or closure changes</label>
        </fieldset>
        <div class="alert-field-grid">
          <label>Email address
            <input id="alert-email" name="email" type="email" autocomplete="email" maxlength="320" required placeholder="you@example.edu">
          </label>
          <label>Frequency
            <select id="alert-cadence" name="cadence">
              <option value="immediate">As changes happen</option>
              <option value="weekly">Weekly digest</option>
            </select>
          </label>
        </div>
        <p class="alert-management"><strong>After verification:</strong> every Funding Finder alert email includes a secure Manage alerts link where you can change frequency, pause or resume delivery, or unsubscribe.</p>
        <p class="alert-privacy"><strong>Stored for this alert:</strong> your email address, the watched ID or typed query and filters, cadence, verification state, and delivery history. Pursuit status and notes, profile/CV text, ORCID publication text, uploaded documents, and AI chat stay in this browser and are never sent to the Alerts Worker.</p>
        <p class="alert-search-baseline hidden" id="alert-search-baseline">The current Strong matches become the starting baseline. They will not trigger email; only a future new or newly qualifying Strong match can alert you. Potential matches are excluded.</p>
        <div class="alert-dialog-actions">
          <button class="button primary" id="alert-submit" type="submit">Send verification email</button>
          <button class="text-button hidden" id="alert-change-email" type="button">Use a different email</button>
          <button class="button secondary alert-cancel" type="button">Cancel</button>
        </div>
        <p class="alert-dialog-status" id="alert-dialog-status" role="status" aria-live="polite"></p>
      </form>`;
    document.body.append(dialog);
    dialog.querySelector(".alert-dialog-close").addEventListener("click", close);
    dialog.querySelector(".alert-cancel").addEventListener("click", close);
    dialog.querySelector("#alert-change-email").addEventListener("click", () => {
      const email = dialog.querySelector("#alert-email");
      email.readOnly = false;
      email.value = "";
      email.focus();
      dialog.querySelector("#alert-change-email").classList.add("hidden");
      dialog.querySelector("#alert-submit").textContent = "Send verification email";
      setSubmitStatus(
        dialog.querySelector("#alert-dialog-status"),
        "Enter the address that should receive the verification link.",
      );
    });
    dialog.addEventListener("cancel", event => {
      event.preventDefault();
      close();
    });
    dialog.addEventListener("keydown", event => {
      if (event.key !== "Tab") return;
      const focusable = dialogFocusableElements();
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    });
    dialog.addEventListener("click", event => {
      if (event.target === dialog) close();
    });
    dialog.addEventListener("close", restoreDialogState);
    dialog.querySelector("form").addEventListener("submit", submit);
    return dialog;
  }

  function close() {
    if (!dialog?.open) return;
    dialog.close();
  }

  function triggers() {
    return [...dialog.querySelectorAll('input[name="trigger"]:checked')]
      .map(input => input.value);
  }

  async function submit(event) {
    event.preventDefault();
    if (!current || !config.endpoint) return;
    const status = dialog.querySelector("#alert-dialog-status");
    const submitButton = dialog.querySelector("#alert-submit");
    const definition = { ...current.definition };
    if (current.type === "opportunity") {
      definition.triggers = triggers();
      if (!definition.triggers.length) {
        setSubmitStatus(status, "Choose at least one change to watch.", { error: true });
        return;
      }
    }
    const body = {
      email: dialog.querySelector("#alert-email").value,
      baseline_opportunity_ids: current.type === "saved_search"
        ? current.baselineOpportunityIds
        : [],
      subscription: {
        type: current.type,
        cadence: dialog.querySelector("#alert-cadence").value,
        definition,
      },
    };
    submitButton.disabled = true;
    setSubmitStatus(status, "Creating a safe baseline and preparing verification…");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), Number(config.requestTimeoutMs) || 10_000);
    try {
      const response = await fetch(`${String(config.endpoint).replace(/\/$/, "")}/subscriptions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "omit",
        referrerPolicy: "origin",
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const error = new Error("subscription unavailable");
        error.code = boundedErrorCode(payload)
          || (response.status === 429
            ? "rate_limited"
            : response.status >= 500 || [401, 403, 404, 405].includes(response.status)
                ? "service_unavailable"
                : "invalid_response");
        throw error;
      }
      if (payload?.status !== "verification_required") {
        const error = new Error("subscription invalid response");
        error.code = "invalid_response";
        throw error;
      }
      const email = dialog.querySelector("#alert-email");
      lastEmail = email.value;
      email.readOnly = true;
      dialog.querySelector("#alert-change-email").classList.remove("hidden");
      submitButton.textContent = "Send verification email again";
      setSubmitStatus(
        status,
        `Verification email requested for ${lastEmail}. The alert remains inactive until you use the link. Check spam or send it again if it does not arrive.`,
      );
    } catch (error) {
      setSubmitStatus(status, errorMessage(error?.name === "AbortError" ? "timeout" : error?.code), { error: true });
    } finally {
      clearTimeout(timeout);
      submitButton.disabled = false;
      if (dialog.open && !dialog.contains(document.activeElement)) {
        submitButton.focus({ preventScroll: true });
      }
    }
  }

  function open({
    type, definition, summary = "", focus = document.activeElement,
    baselineOpportunityIds = [],
  } = {}) {
    if (!TYPE_LABELS[type] || !definition || typeof definition !== "object") return false;
    ensureDialog();
    current = {
      type,
      definition: structuredClone(definition),
      baselineOpportunityIds: type === "saved_search"
        ? [...new Set(baselineOpportunityIds.map(String).filter(Boolean))]
        : [],
    };
    restoreFocus = focus?.isConnected ? focus : restoreFocus;
    dialog.querySelector("#alert-dialog-title").textContent = TYPE_LABELS[type];
    dialog.querySelector("#alert-dialog-summary").textContent = summary;
    dialog.querySelector("#alert-trigger-fields").classList.toggle("hidden", type !== "opportunity");
    dialog.querySelector("#alert-search-baseline").classList.toggle("hidden", type !== "saved_search");
    setSubmitStatus(dialog.querySelector("#alert-dialog-status"), "");
    dialog.querySelector("#alert-cadence").value = type === "saved_search" ? "weekly" : "immediate";
    const email = dialog.querySelector("#alert-email");
    email.value = lastEmail;
    email.readOnly = false;
    dialog.querySelector("#alert-change-email").classList.add("hidden");
    dialog.querySelector("#alert-submit").textContent = "Send verification email";
    if (!dialog.open) {
      lockBackgroundScroll();
      try {
        dialog.showModal();
      } catch (error) {
        restoreDialogState();
        throw error;
      }
    }
    email.focus({ preventScroll: true });
    return true;
  }

  globalThis.FUNDING_ALERTS = Object.freeze({ boundedErrorCode, errorMessage, open });
})();

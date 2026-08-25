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
          <button class="button secondary alert-cancel" type="button">Cancel</button>
        </div>
        <p class="alert-dialog-status" id="alert-dialog-status" role="status" aria-live="polite"></p>
      </form>`;
    document.body.append(dialog);
    dialog.querySelector(".alert-dialog-close").addEventListener("click", close);
    dialog.querySelector(".alert-cancel").addEventListener("click", close);
    dialog.addEventListener("cancel", event => {
      event.preventDefault();
      close();
    });
    dialog.addEventListener("click", event => {
      if (event.target === dialog) close();
    });
    dialog.querySelector("form").addEventListener("submit", submit);
    return dialog;
  }

  function close() {
    if (!dialog?.open) return;
    dialog.close();
    restoreFocus?.focus?.();
    restoreFocus = null;
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
      setSubmitStatus(status, "Check your email for a verification link. The alert remains inactive until you verify it.");
      dialog.querySelector("#alert-email").value = "";
    } catch (error) {
      setSubmitStatus(status, errorMessage(error?.name === "AbortError" ? "timeout" : error?.code), { error: true });
    } finally {
      clearTimeout(timeout);
      submitButton.disabled = false;
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
    restoreFocus = focus;
    dialog.querySelector("#alert-dialog-title").textContent = TYPE_LABELS[type];
    dialog.querySelector("#alert-dialog-summary").textContent = summary;
    dialog.querySelector("#alert-trigger-fields").classList.toggle("hidden", type !== "opportunity");
    dialog.querySelector("#alert-search-baseline").classList.toggle("hidden", type !== "saved_search");
    setSubmitStatus(dialog.querySelector("#alert-dialog-status"), "");
    dialog.querySelector("#alert-cadence").value = type === "saved_search" ? "weekly" : "immediate";
    dialog.showModal();
    dialog.querySelector("#alert-email").focus();
    return true;
  }

  globalThis.FUNDING_ALERTS = Object.freeze({ boundedErrorCode, errorMessage, open });
})();

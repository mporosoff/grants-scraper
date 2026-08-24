(() => {
  "use strict";

  const openers = [...document.querySelectorAll("[data-help-open]")];
  if (!openers.length) return;

  const dialog = document.createElement("dialog");
  dialog.className = "help-dialog";
  dialog.id = "help-guide";
  dialog.setAttribute("aria-labelledby", "help-guide-title");
  dialog.innerHTML = `
    <div class="help-dialog-header">
      <div>
        <p class="help-eyebrow">Funding Finder guide</p>
        <h2 id="help-guide-title">How to find, review, and discuss funding</h2>
      </div>
      <button class="help-close" type="button" data-help-close aria-label="Close help">&times;</button>
    </div>
    <div class="help-dialog-body">
      <section class="help-intro" aria-labelledby="help-start-title">
        <div>
          <span class="help-kicker">Start here</span>
          <h3 id="help-start-title">Search is free. Your own AI connection is optional.</h3>
          <p>Funding Finder searches the current public opportunity catalog. Strong matching and filters run in your browser; the site's hosted semantic service can add Potential matches. You do not need an account or your own API key.</p>
        </div>
        <ol class="help-steps">
          <li><span>1</span><div><strong>Describe what you want to fund</strong><small>Use a topic, method, population, goal, or opportunity number. You may also upload a funding-notice PDF.</small></div></li>
          <li><span>2</span><div><strong>Add context if it helps</strong><small>Optionally add a reusable profile, CV, or filters. You can leave the search blank when those provide enough context.</small></div></li>
          <li><span>3</span><div><strong>Find and review</strong><small>Open the official notice before acting on a deadline, eligibility rule, award amount, or submission requirement.</small></div></li>
        </ol>
      </section>

      <nav class="help-contents" aria-label="Help topics">
        <a href="#help-search">Search</a>
        <a href="#help-nofo">Uploaded notices</a>
        <a href="#help-results">Results</a>
        <a href="#help-teams">Team matcher</a>
        <a href="#help-api-keys">API keys</a>
        <a href="#help-privacy">Privacy</a>
        <a href="#help-troubleshooting">Troubleshooting</a>
      </nav>

      <section class="help-section" id="help-search">
        <div class="help-section-heading">
          <span class="help-section-number">01</span>
          <div><h3>Search the catalog</h3><p>Strong matching is local. Potential matching is a site-managed hosted second pass.</p></div>
        </div>
        <div class="help-grid">
          <div class="help-card">
            <h4>Write a useful query</h4>
            <ul>
              <li>Use a few concrete concepts, such as <em>PFAS water remediation</em> or <em>CO₂ electrocatalysis</em>.</li>
              <li>Exact opportunity numbers and distinctive titles receive the strongest priority.</li>
              <li>Common abbreviations, scientific word forms, and minor spelling variations are expanded conservatively.</li>
              <li>For an unfamiliar acronym such as <em>CFD</em>, search can learn a matching full phrase from the local catalog and use the enabled research profile, CV, or ORCID publications to disambiguate it. Ambiguous acronyms are left unexpanded.</li>
              <li>If results are too broad, add a method, use case, population, or material instead of more generic field names.</li>
            </ul>
          </div>
          <div class="help-card">
            <h4>Add only the context you need</h4>
            <ul>
              <li><strong>Profile:</strong> save a short research description and keywords on this device for reuse.</li>
              <li><strong>CV:</strong> extract a bounded excerpt in the browser; the original file is not retained.</li>
              <li><strong>ORCID:</strong> import public Crossref publication metadata linked to an ORCID iD and combine its topics with your description, keywords, or CV.</li>
              <li><strong>Filters:</strong> narrow by status, discipline, agency, eligibility, deadline, award size, instrument, and more.</li>
              <li><strong>Browse the catalog:</strong> leave the query blank or use Public catalog when you want to scan everything current.</li>
            </ul>
          </div>
        </div>
      </section>

      <section class="help-section" id="help-nofo">
        <div class="help-section-heading">
          <span class="help-section-number">02</span>
          <div><h3>Upload and chat with a NOFO, FOA, or other notice</h3><p>Drop a PDF directly onto the main search area or choose it from your device.</p></div>
        </div>
        <div class="help-callout">
          <p>The PDF is read locally and opened in a larger document-grounded chat workspace. Funding Finder tries to match its opportunity number or distinctive title to a catalog record so you can save it, add its deadline to your calendar, and open its official source.</p>
          <p>If the proposed catalog card is wrong, choose <strong>Not the right program</strong>. Document chat still works when no catalog match can be confirmed. Answers should cite PDF page numbers; always verify important details in the full notice.</p>
        </div>
      </section>

      <section class="help-section" id="help-results">
        <div class="help-section-heading">
          <span class="help-section-number">03</span>
          <div><h3>Review and organize results</h3><p>Use the result cards as a workspace, not as a substitute for the official notice.</p></div>
        </div>
        <div class="help-feature-list">
          <div><strong>Save</strong><span>Keep promising opportunities on this device.</span></div>
          <div><strong>Calendar</strong><span>Export deadlines to an ICS calendar file.</span></div>
          <div><strong>Matched topics</strong><span>See the specific solicitation topics or sub-programs that matched your search; expand the list only when needed.</span></div>
          <div><strong>Why this matched</strong><span>Open a short evidence-based explanation when that feature is enabled.</span></div>
          <div><strong>Export CSV</strong><span>Download the current result set for further review.</span></div>
          <div><strong>Official source</strong><span>Open the agency notice, FOA, or Grants.gov record.</span></div>
          <div><strong>Ask AI</strong><span>Discuss one opportunity or the leading results after connecting a provider.</span></div>
        </div>
        <p class="help-footnote">“Recently posted” uses the catalog's listed or first-seen date. “Relevance” combines the words and concepts in your query, profile, and filters. Recently posted and closing-soon labels help with timing but do not replace deadline verification.</p>
      </section>

      <section class="help-section" id="help-teams">
        <div class="help-section-heading">
          <span class="help-section-number">04</span>
          <div><h3>Find collaborative opportunities</h3><p>The Team matcher scores the live catalog for a group rather than simply combining separate searches.</p></div>
        </div>
        <div class="help-grid">
          <div class="help-card">
            <h4>Build a team</h4>
            <p>Select two to four researchers. Choose department faculty or save another researcher using specific research keywords, an ORCID publication import, or both.</p>
          </div>
          <div class="help-card">
            <h4>Steer the themes</h4>
            <p>Shared and complementary themes appear as interactive chips. Turn a theme off to refocus the ranking. Every displayed opportunity must be current and have linked evidence for everyone selected.</p>
          </div>
        </div>
            <p class="help-footnote">Results use graded research, theme, topic, agency-scope, and recency signals in one ranked list. A <strong>broad: verify fit</strong> label means an open-scope agency announcement was included with weaker evidence and deserves manual review.</p>
      </section>

      <section class="help-section help-api-section" id="help-api-keys">
        <div class="help-section-heading">
          <span class="help-section-number">05</span>
              <div><h3>What an API key is and why AI needs one</h3><p>A key is a private credential from an AI provider, not your account password.</p></div>
        </div>
        <div class="help-key-explanation">
          <p>Your provider key authorizes optional user-connected AI requests and associates those charges with your account. Local abbreviation handling and the site's hosted Potential ranking need no key from you. Your key is used only for optional AI terminology expansion, AI refinement, result chat, and uploaded-notice chat.</p>
          <p><strong>Catalog search and Team Match do not need your API key.</strong> The hosted Potential service uses a site-managed server-side key. Billing and availability for user-connected tools are controlled by the provider.</p>
        </div>
        <div class="help-provider-grid">
          <article class="help-provider-card">
            <span class="help-provider-name">OpenAI</span>
            <h4>Create an OpenAI API key</h4>
            <ol>
              <li>Sign in to the OpenAI API Platform.</li>
              <li>Open API keys and create a new secret key.</li>
              <li>Copy the key when it is shown, then paste it into Funding Finder with OpenAI selected.</li>
              <li>Review API billing and usage controls before making AI requests.</li>
            </ol>
            <div class="help-provider-links">
              <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">Create or manage OpenAI keys ↗</a>
              <a href="https://developers.openai.com/api/docs/quickstart" target="_blank" rel="noopener noreferrer">OpenAI API quickstart ↗</a>
              <a href="https://platform.openai.com/settings/organization/billing/overview" target="_blank" rel="noopener noreferrer">OpenAI billing ↗</a>
            </div>
          </article>
          <article class="help-provider-card anthropic">
            <span class="help-provider-name">Anthropic</span>
            <h4>Create an Anthropic API key</h4>
            <ol>
              <li>Sign in to the Claude Console.</li>
              <li>Open Settings → API keys and create a key.</li>
              <li>Choose an appropriate expiration, copy the key, and paste it into Funding Finder with Anthropic selected.</li>
              <li>Review Console billing and spend controls before making AI requests.</li>
            </ol>
            <div class="help-provider-links">
              <a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener noreferrer">Create or manage Anthropic keys ↗</a>
              <a href="https://platform.claude.com/docs/en/manage-claude/authentication" target="_blank" rel="noopener noreferrer">Anthropic authentication guide ↗</a>
              <a href="https://platform.claude.com/settings/billing" target="_blank" rel="noopener noreferrer">Anthropic billing ↗</a>
            </div>
          </article>
        </div>
        <div class="help-security-note">
          <strong>Treat every API key like a password.</strong>
          <span>Do not email it, paste it into a shared document, or save it on a shared computer. Use a project or workspace key with suitable limits where available, monitor usage, and revoke a key immediately if you think it was exposed.</span>
        </div>
      </section>

      <section class="help-section" id="help-privacy">
        <div class="help-section-heading">
          <span class="help-section-number">06</span>
          <div><h3>Know what stays local and what is sent</h3><p>Local search, hosted Potential ranking, and user-connected AI have distinct boundaries.</p></div>
        </div>
        <div class="help-grid">
          <div class="help-card">
            <h4>Stays in this browser</h4>
            <p>Strong matching, exact-identifier and acronym handling, filters, saved opportunities, profiles, researchers you add, extracted upload text, and chat state stay on the device. Invited-reviewer ratings also stay local until explicitly exported. Original CV and notice files are not retained.</p>
          </div>
          <div class="help-card">
            <h4>Hosted Potential matching</h4>
            <p>The submitted search text is sent to the Funding Finder Worker, which obtains a query embedding and reranks bounded public opportunity passages with the site's server-side key. Your CV, full profile, researcher names, and ORCID publication text are not sent.</p>
          </div>
          <div class="help-card">
            <h4>User-connected AI tools</h4>
            <p>When you explicitly use AI refinement or chat, your key goes directly to the selected provider with only the bounded result, profile/CV, question, or PDF context enabled for that request. Keys are excluded from URLs, exports, GitHub, and the funding catalog.</p>
          </div>
          <div class="help-card">
            <h4>URLs and anonymous measurement</h4>
            <p>Search criteria are stored in the page URL so a search can be shared and restored; they may therefore appear in browser history and copied links. A custom anonymous event sends a random session ID and broad usage category, not search text. The usage service aggregates network organization server-side. Cloudflare Web Analytics is loaded only when the page URL has no query parameters.</p>
          </div>
        </div>
        <p class="help-footnote">A key is tab-only unless you explicitly save it. A saved key remains in this browser profile's local storage until you remove it; anyone with access to that browser profile may be able to use it.</p>
      </section>

      <section class="help-section" id="help-troubleshooting">
        <div class="help-section-heading">
          <span class="help-section-number">07</span>
          <div><h3>Quick troubleshooting</h3><p>A few checks solve most problems.</p></div>
        </div>
        <details class="help-faq">
          <summary>My search returned nothing useful.</summary>
          <p>Remove restrictive filters, shorten the query to two or three concrete concepts, try a recognized synonym, or browse the public catalog. For an exact solicitation, search its opportunity number or upload its PDF.</p>
        </details>
        <details class="help-faq">
          <summary>Potential matches are unavailable or limited.</summary>
          <p>Strong local matches remain complete and usable. The hosted service may be updating, rate limited, over its daily budget, or temporarily unavailable; use the retry action when shown or return later.</p>
        </details>
        <details class="help-faq">
          <summary>The AI request failed.</summary>
          <p>For user-connected refinement or chat, confirm that the selected provider matches the key, re-enter an expired or revoked key, and check the provider account's billing, credits, usage limits, and service status. Strong local search remains available.</p>
        </details>
        <details class="help-faq">
          <summary>A catalog match or extracted fact looks wrong.</summary>
          <p>Reject an incorrect uploaded-notice match and rely on the linked official notice. Invited reviewers can use the separate evaluation mode. Machine-extracted summaries are aids, not authoritative program instructions.</p>
        </details>
        <details class="help-faq">
          <summary>How current is the catalog?</summary>
          <p>The status pill in the header shows catalog freshness. The version in the footer identifies the application release; it changes when the product changes, not whenever catalog data refreshes. Expired opportunities are filtered at runtime, while scheduled refreshes add and update records from the enabled public sources.</p>
        </details>
      </section>
    </div>
  `;

  document.body.append(dialog);

  let lastOpener = null;

  function openHelp(opener) {
    lastOpener = opener;
    document.documentElement.classList.add("help-open");
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    dialog.querySelector("[data-help-close]")?.focus();
  }

  function closeHelp() {
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
      document.documentElement.classList.remove("help-open");
      lastOpener?.focus();
    }
  }

  openers.forEach(opener => {
    opener.addEventListener("click", () => openHelp(opener));
  });

  dialog.addEventListener("click", event => {
    if (event.target === dialog || event.target.closest("[data-help-close]")) {
      closeHelp();
    }
  });

  dialog.addEventListener("close", () => {
    document.documentElement.classList.remove("help-open");
    lastOpener?.focus();
  });

  dialog.addEventListener("cancel", () => {
    document.documentElement.classList.remove("help-open");
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && dialog.hasAttribute("open") && typeof dialog.showModal !== "function") {
      closeHelp();
    }
  });
})();

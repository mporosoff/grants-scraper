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
        <h2 id="help-guide-title">How to search, review awards, build teams, and manage alerts</h2>
      </div>
      <button class="help-close" type="button" data-help-close aria-label="Close help">&times;</button>
    </div>
    <div class="help-dialog-body">
      <section class="help-intro" aria-labelledby="help-start-title">
        <div>
          <span class="help-kicker">Start here</span>
          <h3 id="help-start-title">Search is free. Hosted AI is included.</h3>
          <p>Funding Finder searches current public opportunities, Funded Awards explores historical NSF, NIH, and DOE projects, and Team Match finds calls for a group. Strong matching and structured award searches do not require an account or your own API key.</p>
        </div>
        <ol class="help-steps">
          <li><span>1</span><div><strong>Describe what you want to fund</strong><small>Use a topic, method, population, goal, or opportunity number. You may also upload a funding-notice PDF.</small></div></li>
          <li><span>2</span><div><strong>Add context if it helps</strong><small>Optionally add a reusable profile, CV, or filters. You can leave the search blank when those provide enough context.</small></div></li>
          <li><span>3</span><div><strong>Review, save, and choose alerts</strong><small>Open official sources before acting, then save locally or verify a broader saved-search alert. Narrow opportunity and controlled-program watches remain optional.</small></div></li>
        </ol>
      </section>

      <nav class="help-contents" aria-label="Help topics">
        <a href="#help-search">Search</a>
        <a href="#help-nofo">Uploaded notices</a>
        <a href="#help-results">Results</a>
        <a href="#help-alerts">Email alerts</a>
        <a href="#help-awards">Funded Awards</a>
        <a href="#help-institutions">Institutions</a>
        <a href="#help-teams">Team Match</a>
        <a href="#help-api-keys">Hosted AI</a>
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
          <div><strong>Ask AI</strong><span>Discuss one opportunity or the leading results using hosted AI or an optional personal provider.</span></div>
        </div>
        <p class="help-footnote">“Recently posted” uses the catalog's listed or first-seen date. “Relevance” combines the words and concepts in your query, profile, and filters. Recently posted and closing-soon labels help with timing but do not replace deadline verification.</p>
      </section>

      <section class="help-section" id="help-alerts">
        <div class="help-section-heading">
          <span class="help-section-number">04</span>
          <div><h3>Configure personalized email alerts</h3><p>Saved-search alerts are the primary way to follow your broader interests. Optional opportunity and controlled-program watches are available when you need a narrower alert.</p></div>
        </div>
        <div class="help-grid">
          <div class="help-card">
            <h4>Choose what to watch in the GUI</h4>
            <ul>
              <li><strong>Overall search and interests:</strong> open <em>Research profile, ORCID, CV, and search alerts</em>, run a typed Funding Finder search, then choose <em>Save this search as an email alert</em> in that pane. The alert follows future new Strong matches to the typed search and public filters across the catalog. Existing Strong matches become the baseline and do not immediately generate email.</li>
              <li><strong>One opportunity:</strong> choose <em>Email alert</em> on a result card or in Saved opportunities, then select deadline, amendment, reminder, and status triggers.</li>
              <li><strong>One program:</strong> choose <em>Program email alert</em> on an eligible result, or <em>Email alerts for this program</em> from an eligible Funded Awards deep link. Program watches use only controlled stable identities.</li>
            </ul>
          </div>
          <div class="help-card">
            <h4>Verify and manage delivery</h4>
            <ol>
              <li>Enter your email address and choose immediate delivery or a weekly digest.</li>
              <li>Open the verification email; the alert is inactive until that link is used.</li>
              <li>Use the secure <strong>Manage alerts</strong> link in any Funding Finder email to change frequency, pause or resume an alert, or unsubscribe.</li>
            </ol>
            <p class="help-footnote">There is no Funding Finder account or public alert dashboard. The private management link in your verified email is the safe way to administer subscriptions.</p>
          </div>
        </div>
      </section>

      <section class="help-section" id="help-awards">
        <div class="help-section-heading">
          <span class="help-section-number">05</span>
          <div><h3>Explore Funded Awards</h3><p>Use one Funded Award Intelligence search for normalized public NSF, NIH, and DOE Office of Science records without using the opportunity-vector corpus.</p></div>
        </div>
        <div class="help-grid">
          <div class="help-card">
            <h4>Search historical projects</h4>
            <p>Search by institution, research topic, program, principal investigator, program officer, agency, or year. Selecting an institution adds Research Organization Registry (ROR) identity resolution and institutional summaries; the same compact award cards and factual drill-downs are used for every search. Topic searches use each award source's native public search.</p>
          </div>
          <div class="help-card">
            <h4>Start from a current opportunity</h4>
            <p><strong>View funded awards ↗</strong> carries exact NSF or NIH identifiers, reviewed NSF parent mappings, or defensible DOE FOA/program mappings into Funded Awards. When equivalence is uncertain, the product offers a controlled source search instead of claiming an exact match.</p>
          </div>
        </div>
      </section>

      <section class="help-section" id="help-institutions">
        <div class="help-section-heading">
          <span class="help-section-number">06</span>
          <div><h3>Use Institutional Intelligence</h3><p>Aggregate the public funded-award evidence returned for a selected institution.</p></div>
        </div>
        <div class="help-grid">
          <div class="help-card">
            <h4>Resolve an institution</h4>
            <p>Use the optional institution field in Funded Award Intelligence and start typing a name, acronym, or alias. Autocomplete uses the open Research Organization Registry (ROR), while award requests preserve the canonical and source-specific institution identities used by NSF, NIH, and DOE.</p>
          </div>
          <div class="help-card">
            <h4>Filter or ask a question</h4>
            <p>Structured institution, agency, program, topic, investigator, and year filters work without AI. Optional <strong>Ask about this institution</strong> uses hosted AI to translate a natural-language question into visible structured filters; returned award records remain authoritative.</p>
          </div>
        </div>
      </section>

      <section class="help-section" id="help-teams">
        <div class="help-section-heading">
          <span class="help-section-number">07</span>
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
          <span class="help-section-number">08</span>
              <div><h3>Hosted AI and optional personal keys</h3><p>Funding Finder's tested hosted AI is included; a personal provider key is an advanced alternative.</p></div>
        </div>
        <div class="help-key-explanation">
          <p>Funding Finder's hosted AI powers optional terminology expansion, candidate assessment, result chat, uploaded-notice chat, and institution questions without putting a provider key in your browser. Each feature sends only its bounded context after you choose the AI action.</p>
          <p><strong>Catalog search and Team Match do not use these models.</strong> Advanced users may select OpenAI or Anthropic and supply a personal key; those requests and charges then use that provider account.</p>
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
          <span class="help-section-number">09</span>
          <div><h3>Know what stays local and what is sent</h3><p>Local search, hosted Potential ranking, hosted AI, verified email alerts, and public award retrieval have distinct boundaries.</p></div>
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
            <h4>Hosted AI tools</h4>
            <p>When you explicitly use AI refinement, chat, or an institution question, only the bounded result, enabled profile/CV excerpt, question, or PDF context needed for that request goes to Funding Finder's protected AI service. The service owns the provider key, fixed prompts, schemas, model routing, and request limits; prompts and responses are not stored by Funding Finder.</p>
          </div>
          <div class="help-card">
            <h4>Verified email alerts</h4>
            <p>The Alerts Worker stores the verified email address, exact watched opportunity or controlled program ID, or typed search and public filters, plus cadence and delivery history. Pursuit notes, profile and CV text, ORCID publication text, uploaded documents, AI chat, and provider keys are never sent to it.</p>
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
          <span class="help-section-number">10</span>
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
          <p>For hosted AI, wait briefly and try again; the service may be rate limited or temporarily unavailable. If you selected a personal provider, confirm that it matches the key and check that provider account. Strong local search remains available.</p>
        </details>
        <details class="help-faq">
          <summary>A catalog match or extracted fact looks wrong.</summary>
          <p>Reject an incorrect uploaded-notice match and rely on the linked official notice. Invited reviewers can use the separate evaluation mode. Machine-extracted summaries are aids, not authoritative program instructions.</p>
        </details>
        <details class="help-faq">
          <summary>I created an alert but cannot find its settings.</summary>
          <p>Open a Funding Finder verification or alert email and use its secure <strong>Manage alerts</strong> link. There is no signed-in dashboard. That private link lets you change frequency, pause or resume delivery, or unsubscribe without exposing your subscriptions publicly.</p>
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
    const dialogBody = dialog.querySelector(".help-dialog-body");
    if (dialogBody) dialogBody.scrollTop = 0;
    dialog.querySelector("[data-help-close]")?.focus();
    const requestedSection = String(opener?.dataset.helpSection || "");
    if (/^help-[a-z-]+$/.test(requestedSection)) {
      dialog.querySelector(`#${requestedSection}`)?.scrollIntoView({ block: "start" });
    }
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

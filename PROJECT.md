# Funding Finder — Product Plan

**Status:** Phase 1 and 1.5 complete; Phase 2 engineering complete with its human pilot deferred; Phase 3 deployed with its first production evidence batch successful; unified-search and result-aware-chat usability passes complete

**Next implementation phase:** Phase 3D — complete the returned-review and citation-landing dry run, then run the deferred multi-researcher pilot

**Canonical application:** https://mporosoff.github.io/grants-scraper/

**Repository:** https://github.com/mporosoff/grants-scraper

**Initial audience:** University of Rochester researchers, with a design that remains useful to any public user

**Last updated:** July 26, 2026

---

## 1. Product goal

Funding Finder is a public funding-opportunity search engine with an optional AI refinement layer.

The base product should provide the useful parts of the [Duke Research Funding database](https://researchfunding.duke.edu/search-results)—a broad catalog, keyword search, filters, sorting, result details, and export—in a faster and more approachable interface. AI is not the database and is not required to browse it.

The product answers two related questions:

1. **What funding opportunities are available?** Search the comprehensive catalog directly.
2. **Which of these are most relevant to my work?** Let AI expand a research description, rerank a bounded candidate set, explain the matches, and answer follow-up questions about that shortlist.

The system must not make a model call for ordinary search. It must not hide the catalog behind an API key.

---

## 2. Product decisions

### 2.1 One public application

GitHub Pages is the only active product surface:

https://mporosoff.github.io/grants-scraper/

There are no accounts, installations, faculty profiles, or user-managed opportunity files. The retained server experiment under `web/` is reference material, not a second product.

### 2.2 Comprehensive catalog, not a curated shortlist

The scheduled pipeline uses the official [Grants.gov daily XML database extract](https://www.grants.gov/xml-extract), not dozens of narrow keyword API calls.

Each refresh:

- downloads one complete official extract;
- streams it from the ZIP rather than unpacking a raw database into the repository;
- includes open posted and current forecasted opportunities;
- rejects past deadlines for both posted and forecasted records;
- removes stale undated forecasts, archived records, and duplicates;
- normalizes dates, awards, eligibility, agencies, instruments, and source links;
- incrementally enriches new and changed records from the official Grants.gov
  detail API;
- replaces a spacing-damaged NSF synopsis only when the linked official NSF
  funding page provides a valid authoritative synopsis, then rebuilds the
  search index;
- derives transparent discipline, topic, and warning facets;
- builds a compact BM25 keyword index; and
- publishes one versioned browser asset.

The July 26 build contains 1,465 open or current forecasted federal opportunities rather than the former 48-record engineering shortlist. It contains no record with a deadline before the catalog date. Sources outside Grants.gov will be added independently when they have a sustainable public ingestion path.

### 2.3 Search is the primary workflow

Anyone can use, without an API key:

- full-text keyword and opportunity-number search;
- open and forecasted status filters;
- discipline, topic, agency, eligibility, and funding-instrument facets;
- deadline and minimum per-award filters;
- preliminary-stage, limited-submission, early-career, and cost-share signals;
- a cited-FOA-evidence availability filter for deployment review;
- relevance, deadline, posted-date, award, agency, and title sorting;
- pagination and expandable record details;
- one-click official FOA, agency-notice, or Grants.gov record links; and
- CSV export of the complete current result set.

Search and filtering execute in the browser over the prebuilt index. They make zero AI calls and have no per-search infrastructure cost.

The public page begins with no opportunity cards. One guided workflow combines
keywords, optional profile/CV context, and optional filters; “Find funding” is
the only search action. This prevents the catalog, profile search, and AI
matching from appearing to be separate products. Profile/CV context and filters
are stacked as full-width sections in that workflow. Expanded filters use the
page scrollbar rather than a sticky nested scrolling pane.

### 2.4 AI is an optional first-class workflow

A user may choose OpenAI or Anthropic and enter one provider key. The same provider powers:

1. **Query expansion:** translate a natural-language research description into concrete search terms and synonyms.
2. **Bounded reranking:** compare at most 32 locally retrieved candidates and return at most 12 grounded recommendations.
3. **Chat with results:** answer questions over either the top 20 ordinary search results or the AI shortlist; connect every named opportunity back to its result card and official source; and focus the displayed list when explicitly requested.

AI settings sit inside that same workflow and become useful only after the
catalog search has results. “Refine these results with AI” reranks the bounded
candidate set, while “Chat with your results” appears with the result set on
desktop and mobile. Chat can expand into a large in-page workspace without
losing the current result state, uses readable limited-Markdown responses,
shows a visible working state, and supports Enter-to-send with Shift+Enter for
a new line. Provider responses receive a larger bounded output budget; if a
provider still returns malformed or truncated JSON, the application retries
once with a shorter-output instruction and then reports a plain-language error.
Neither AI action is a separate search source.

AI output is advisory. It must:

- use exact catalog record identifiers;
- distinguish source facts from inference;
- call missing data “not listed”;
- never invent deadlines, amounts, eligibility, or requirements; and
- direct users to the official notice for final verification.

### 2.5 Explicit device-local profiles, not a local funding database

The search catalog remains a published static asset. It is not copied into a
user-maintained browser database, and keyword searches remain shareable by
URL.

At the user's explicit request, the application can now remember a reusable
research profile on that device. The saved record contains:

- research description and expertise keywords;
- applicant context and career stage;
- extracted CV text and file metadata, bounded to 120,000 characters;
- the user's current filters, sort, selected provider (never its key), and
  profile-ranking preference; and
- Phase 2 usefulness labels and reason codes in a separate local record.

PDF, DOCX, TXT, and Markdown CVs are parsed in the browser. The original file
is never saved or uploaded by the application. The user can disable
profile use, remove the CV extract, clear the saved profile, or clear
evaluation labels at any time.

The AI shortlist and chat remain page-memory only and disappear on reload. An
API key is tab-only by default, but the user may explicitly save one key per
provider in a separate device-local credential record. The interface confirms
whether the current key is entered, saved, loaded, or removed and warns against
saving a key on a shared browser. Keys are never written to the profile,
review/evaluation records, `sessionStorage`, a URL, GitHub, or an application
database. The bounded CV excerpt is sent to the selected AI provider only when
the user leaves that option enabled and explicitly runs AI refinement or chat.

CSV and Phase 2 JSON are created only on explicit export. The evaluation JSON
excludes the API key, CV text, research description, and chat by default.

### 2.6 Document evidence and deployment learning

Phase 3 does not ask an AI model to guess what an FOA says. The scheduled
pipeline retrieves a bounded set of selected official PDF or HTML notices,
extracts readable text ephemerally, and commits only compact derived facts:

- a document URL, content hash, version number, and last-checked time;
- deadlines, per-award ranges, duration, expected awards, page limits, cost
  share, eligibility/review excerpts, application-component signals, and
  amendment/status signals when an extraction pattern has support;
- an exact page or HTML section, short source quote, and direct citation URL
  for every extracted fact; and
- an explicit human-review queue for document changes, conflicting dates,
  cancellation/supersession language, unreadable sources, and potential
  limited submissions.

Raw PDFs and HTML are never committed. Machine-extracted facts never replace
structured Grants.gov fields for deadline or award filtering. They expand
search and provide cited context for result details and optional AI chat.

Deployment review is also explicit rather than silent telemetry. Source
verdicts, coarse action counters, checklist answers, and optional notes
autosave under one separate device-local record. “Send review” attaches a
privacy-safe JSON file to the native share sheet on supported mobile devices;
on desktop it downloads the file and opens an addressed email to the project
owner. The export excludes API keys, profile/CV text, search text, Funding
Finder search URL/parameters, and chat. Returned files are kept in gitignored `evaluation/inbox/`
and aggregated into private Markdown, JSON, and CSV reports.

---

## 3. Architecture

```text
Official Grants.gov daily XML extract
                 |
                 | scheduled GitHub Action
                 v
Normalized current catalog + facets + BM25 index
                 |
                 | incremental official detail API enrichment
                 v
Deadline/award evidence + direct FOA and agency links
                 |
                 | bounded official PDF/HTML retrieval
                 v
Cited notice facts + document hash/version + review queue
                 |
                 v
          GitHub Pages app
          /             |              \
         /              |               \ optional, user initiated
        v               v                v
Zero-cost          Device-local       OpenAI or Anthropic
catalog and        profile, CV,       using a tab-only or
cited source       optional saved     explicitly device-saved key
facts              provider keys,          |
ranking            match labels,           +-- query expansion
                   source review            +-- rerank <= 32 candidates
                   and checklist            +-- chat over <= 20 results
                        |                        or <= 12 AI matches
                        v
             Explicit share/download/email
                        |
                        v
            Private gitignored inbox + report
```

There is no application server, search cluster, vector database, account
system, or central user database. GitHub Actions performs the expensive
ingestion work once per day; every visitor reuses the published result.
Device-local profile storage is optional and never becomes the funding
catalog or a shared institutional record.

---

## 4. User workflow

### Find funding in one workflow

1. Open the public URL.
2. Describe the work with a topic, method, population, goal, program name, or
   opportunity number.
3. Optionally add a research profile/CV and filters. These improve the same
   search; they do not launch separate searches.
4. Select “Find funding.” No catalog cards appear before this action.
5. Sort and inspect detailed results.
6. Open the best available official source in one click or export the result
   set.

### Save and reuse profile relevance

1. Enter a research description and expertise keywords, or upload a PDF,
   DOCX, TXT, or Markdown CV.
2. Choose applicant context and career stage.
3. Select “Use this profile in my funding searches.”
4. Optionally select “Save profile on this device.” Saving confirms
   persistence but does not launch a search.
5. Select the same “Find funding” action used for keyword/filter searches.
6. Remove the CV extract or clear the profile at any time.

### Add AI refinement

1. Run the combined catalog search.
2. Open the optional AI settings, choose a provider, and enter a key.
3. Keep the key tab-only or explicitly save it on this device.
4. Select “Refine these results with AI.”
5. Review the shortlist, scores, specific rationale, and caveats.
6. Ask grounded follow-up questions such as:
   - “Which allow a university to lead?”
   - “Keep only those closing after October.”
   - “Which require cost share?”
   - “Compare the top three on fit and timing.”
7. Return to the unmodified catalog at any time.

### Chat with ordinary results

1. Run any keyword or filtered catalog search.
2. Use “Ask about these results,” shown with the returned result set.
3. Ask about the top 20 current results without first running AI refinement.
4. Let chat narrow the displayed results only when explicitly requested.

### Verify an actual FOA

1. Open the primary official FOA directly from the result card.
2. Expand “cited evidence” to see extracted deadlines, funding, duration,
   page limits, cost share, review/eligibility excerpts, and application
   components that the current document supports.
3. Open the page/section citation beside any decisive fact.
4. Mark the cited evidence `accurate`, `incorrect`, or `couldn’t verify`, and
   identify the field checked.
5. Optionally focus “Chat with results” on that single FOA. AI receives only
   the compact cited facts and can return only supplied evidence identifiers;
   unsupported model citations are discarded.

### Return a deployment review

1. Use the site normally; only coarse action counts are kept locally.
2. Complete the short deployment checklist and optional non-confidential note.
3. Select “Send review.” On compatible mobile browsers, choose an app from the
   native share sheet. On desktop, attach the automatically downloaded JSON to
   the addressed email that opens.
4. Keep or clear the autosaved local review after sending.

---

## 5. Privacy, security, and cost boundary

Funding records are public. The catalog and its search index are committed to the public repository and served by GitHub Pages.

Ordinary and profile-ranked search send nothing to an AI provider and make
zero AI calls. A remembered profile and extracted CV text stay in that
browser's local storage; the original CV file is not retained. When a user
explicitly invokes refinement or chat:

- the browser sends the enabled profile context, a CV excerpt of at most
  12,000 characters, and a bounded selection of public opportunities directly
  to the selected provider;
- that provider’s billing, retention, and privacy terms apply;
- the application never proxies or receives the key;
- the key stays in the current tab unless the user explicitly saves it in
  browser local storage, and either way users should use a scoped key with a
  spending limit;
- a saved key is readable by anyone using that browser profile and should not
  be stored on a shared device; and
- users should not enter confidential or unpublished information.

The browser-only design cannot provide a secure institutional credential vault. A future institution-managed AI gateway would be a separate architectural decision.

Evaluation labels also stay on the device until explicit export or deletion.
The export uses a non-content comparison fingerprint and excludes profile text, CV
text, API keys, and chat so a pilot team can evaluate retrieval and reranking
without collecting those fields by default.

Phase 3 deployment review uses a separate local-storage key. It contains only
explicit source-verification choices, optional notes, checklist answers,
coarse viewport/capability fields, aggregate action counts, and public
opportunity/document identifiers. Nothing is transmitted automatically. The
share/download handoff excludes profile/CV text, API keys, search text, Funding
Finder search URL/parameters, and chat. The optional note is user-authored and therefore warns
reviewers not to include confidential research.

Official PDF and HTML notice bodies exist only in the memory of the scheduled
job while being parsed. The repository retains document hashes, HTTP
validators, bounded source quotes, extracted facts, citations, and limited
version history—not raw source files or full extracted text.

---

## 6. Phase 1 — Comprehensive federal opportunity search

**Status: complete**

Phase 1 now includes both the catalog foundation and the first optional refinement workflow:

- official complete Grants.gov XML ingestion;
- open posted and current forecasted records with no past deadlines;
- stale undated-forecast exclusion and explicit verification warnings;
- record-count and required-field health checks;
- daily scheduled refresh and failure alert;
- comprehensive browser search and BM25 index;
- Duke-style facets, sorting, details, pagination, and CSV export;
- visible record count, source, generated time, and stale-data warning;
- one guided search that combines keywords, optional profile/CV context, and
  filters;
- bounded two-call AI refinement;
- chat integrated with ordinary results or the AI shortlist;
- an empty initial result state until a user starts a search;
- explicit optional device-local API-key persistence with visible state and
  a removal control; and
- regression coverage for forecasts, expired records, ambiguous rolling language, indexing, generated assets, and workflow safeguards.

The provider adapters have deterministic contract tests for OpenAI Responses
and Anthropic Messages, including request shape, non-persistence, JSON parsing,
and error behavior. The complete refinement and chat flow is also exercised
with bounded mock responses in browser QA, so Phase 1 does not depend on a
paid credential merely to remain testable.

**Exit criterion: met.** The corrected comprehensive feed, automated refresh,
desktop/mobile public search, AI refinement contract, and chat workflow are
covered by production checks or repeatable regression tests.

---

## 7. Phase 1.5 — Trustworthy source evidence and one-click action

**Status: implemented**

Phase 1.5 closes the gap between finding a promising result and deciding
whether it is real, current, and worth opening. It does not use AI to guess
missing facts.

### 1.5A. Incremental official enrichment

- The daily workflow retains the complete Grants.gov XML extract as the
  catalog source and calls the unauthenticated official
  `fetchOpportunity` detail endpoint only for new or changed records.
- A compact versioned cache prevents all 1,465 records from being fetched on
  every run. Retries, pacing, and a per-run update ceiling contain failure and
  rate-limit risk.
- XML and detail-API deadlines and award values are compared. Conflicts are
  displayed for verification instead of silently choosing a value.
- Because Grants.gov can delete nonbreaking spaces from NSF prose, damaged
  NSF synopses are refreshed from the linked official NSF page, cached for 14
  days, and labeled with that source. Failed agency parsing never overwrites
  the Grants.gov text.
- Every enriched field carries its source, confidence, or verification status.

### 1.5B. Deadline and funding semantics

- Posted close dates and forecast estimated response dates remain official
  structured fields. Records with a structured date before the catalog date
  are excluded.
- Deadline time and timezone are preserved when Grants.gov supplies them.
- LOI, concept-paper, and preproposal language is surfaced as a preliminary
  stage. A date extracted from narrative text is explicitly marked
  machine-extracted and verification-required.
- “Per-award amount” means only award floor or ceiling. Total program funding
  is displayed separately and is never used for the per-award filter or
  largest-award sort.
- Missing amounts stay missing. Parsing unstructured notices to fill source
  gaps belongs to Phase 3 and will require document-level provenance.

### 1.5C. One-click official action

Every result card has a visible primary action:

1. open the direct official FOA/NOFO attachment when identification is
   defensible;
2. otherwise open the agency’s official announcement; or
3. otherwise open the Grants.gov opportunity record.

Direct attachments are selected conservatively. Explicit NOFO/FOA names are
high confidence; a sole plausible full-announcement PDF may be medium
confidence; FAQs, templates, appendices, and ambiguous attachment sets are not
presented as the FOA.

### Current evidence baseline

The July 26 catalog contains 1,465 current posted or forecasted opportunities:

- 447 have a defensible direct announcement attachment (249 high confidence,
  198 medium confidence);
- another 615 route directly to an official agency notice;
- the remaining 403 route to the official Grants.gov record;
- 233 preserve an official deadline time or timezone;
- 53 carry a preliminary-stage signal, including 3 narrative dates that are
  visibly marked for verification;
- 703 (48.0%) have an official per-award floor or ceiling;
- 986 (67.3%) have at least one structured funding amount; and
- zero have a past structured close date or a detected XML/detail-API deadline
  conflict in this build.

These are data-quality measurements, not claims that the underlying notices
are complete. Users are still told to verify the official announcement.

**Exit criterion: met.** Every result has one visible official path, deadline
and funding semantics are source-aware, enrichment is incremental and
repeatable, and missing evidence remains explicit.

---

## 8. Roadmap

### Phase 2 — Pilot validation and relevance quality

**Status: engineering implementation complete; human pilot deliberately deferred until Phase 3 deployment verification**

Phase 1 solved catalog coverage and established a bounded AI workflow. The next
risk is quality: whether deterministic retrieval finds the right candidates
and whether AI puts the genuinely useful opportunities near the top. Phase 2
creates the evidence and feedback loop needed to answer that before more
sources or infrastructure are added. It also adds a reusable researcher
profile and locally parsed CV so relevance is based on more than a one-off
keyword string.

#### 2A. Evaluation controls

- **Implemented:** locally persistent labels for `useful`, `not relevant`, and
  `needs verification`.
- **Implemented:** reason codes for topic, eligibility, career stage, deadline, award size,
  application burden, duplicate/already known, and insufficient source detail.
- **Implemented:** explicit removal controls and a separate device-local
  evaluation record.
- **Implemented:** export enough catalog, query, filter, retrieval-rank, AI-rank, model, and
  reason-code context to reproduce an evaluation without exporting the API key
  or research description by default.
- **Implemented:** reusable device-local profiles, applicant/career context,
  and browser-only PDF/DOCX/TXT/Markdown CV extraction. Raw CV files are not
  retained; a CV excerpt is included in AI calls only when enabled.

#### 2B. Reproducible quality harness

- **Implemented:** a versioned synthetic regression fixture and export schema
  separate from the production catalog. Consented human exports will remain
  separate from source control.
- **Implemented:** measure catalog retrieval independently from AI reranking:
  - recall within the 32-record candidate set;
  - precision and useful-result rate within the 12-record shortlist;
  - rank movement between BM25 retrieval and AI output; and
  - hard eligibility and expired-record error rates.
- **Implemented:** a reviewer can switch between the 12-record AI shortlist
  and the pre-reranking candidate set to label retrieval and ranking failures
  separately.
- **Implemented:** profile persistence, CV-parser, provider-contract, privacy,
  and evaluator regression tests.
- **Implemented:** provider/model and prompt versions in evaluation exports so
  comparisons are meaningful.
- **Pilot task:** add consented synonym, interdisciplinary, eligibility, and
  sparse-description cases based on real participant judgments.

#### 2C. Pilot

- **Deferred by product decision, not completed:** recruit 3–5 researchers
  across multiple disciplines only after the first Phase 3 document-evidence
  batch and handoff workflow pass deployment verification.
- **Then:** evaluate approximately 75–150
  researcher/opportunity pairs with the result-card controls.
- **Then:** test whether 32 candidates and 12 recommendations are the right
  cost/quality boundary.
- **After collection:** tune search weights, topic rules, prompts, and thresholds only from labeled
  evidence.
- **After collection:** publish a short pilot report identifying retrieval failures, reranking
  failures, source-data gaps, and the highest-value missing funding sources.

**Exit criterion (not yet met):** a reproducible benchmark and pilot report separate search
recall from AI ranking quality, identify the main failure modes, and provide
evidence for whether Phase 3 source-evidence work or Phase 4 source expansion
should be prioritized next.

This directly responds to the
[University at Albany funding-recommendation study](https://par.nsf.gov/servlets/purl/10566919).
That pilot showed why exact keyword/string matching is not enough: participant
feedback was mixed, and the system could return irrelevant or already-known
opportunities even when some recommendations were useful. Funding Finder will
therefore treat researcher-entered context and explicit usefulness feedback as
evaluation evidence, while measuring catalog retrieval separately from AI
reranking.

### Phase 3 — Better source evidence

**Status: deployed; first scheduled evidence batch successful; returned-review dry run still required**

Phase 3 is the “understand the actual FOA” layer. It remains a static,
low-cost architecture: GitHub Actions performs document work once and every
visitor reuses the compact output.

#### 3A. Official-document acquisition and versioning

- **Implemented:** select the Phase 1.5 primary notice first, and use an agency
  page only for records with structured-data gaps.
- **Implemented:** retrieve at most 45 new or due sources per scheduled run,
  with size, redirect, public-network, timeout, and pacing safeguards.
- **Implemented:** revalidate unchanged primary notices with
  ETag/Last-Modified after 14 days, lower-priority agency pages after 30 days,
  and prioritize newly changed opportunity signatures and never-processed
  sources over routine rechecks.
- **Implemented:** retain SHA-256, first/last seen timestamps, current version,
  and up to six prior version summaries.
- **Implemented:** mark cached opportunities that disappear from the current
  catalog rather than silently deleting their document history.
- **Implemented:** keep the previous usable evidence on transient refresh
  failures and surface bounded failure diagnostics.
- **Production verification (July 26, 2026):** the first scheduled batch
  processed 45 official notices, produced 524 cited facts across all 45
  records, and completed with zero document-request failures. The live
  catalog reported 792 eligible source updates still queued for later bounded
  runs.
- **Boundary:** raw PDFs/HTML and full extracted text are never committed.

#### 3B. Deterministic evidence extraction

- **Implemented:** parse selectable PDF text with pypdf and readable HTML by
  section; scanned/unreadable notices enter the review queue rather than OCR
  silently guessing.
- **Implemented:** normalize distinct LOI, concept-paper, white-paper,
  preapplication, preproposal, and full-application dates.
- **Implemented:** extract supported per-award ranges, expected awards, project
  duration, page limits, cost-share statements, review/eligibility excerpts,
  and common application-component signals.
- **Implemented:** surface cancellation, supersession, amendment/revision, and
  recurring/open-until-superseded language.
- **Implemented:** attach a stable evidence ID, document hash, exact PDF page or
  HTML section, short quote, and direct citation URL to every extracted fact.
- **Implemented:** never overwrite official structured dates or amounts with
  narrative extraction; use document text as searchable/citable evidence only.
- **Implemented:** create a human review queue for changed documents,
  structured/document date conflicts, limited-submission signals,
  cancellation/supersession language, and unreadable notices.

#### 3C. PI and AI workflow

- **Implemented:** retain the visible one-click official FOA/agency/Grants.gov
  action before the detail expander.
- **Implemented:** show notice-analysis state, document version, cited facts,
  quotes, and review-queue items on the result card.
- **Implemented:** include compact cited facts in CSV exports.
- **Implemented:** add “Ask AI about this FOA,” which focuses chat on one
  notice and offers deadline, funding/duration, and requirements questions.
- **Implemented:** AI can cite only exact evidence IDs supplied in its bounded
  context. Unknown IDs are discarded in the browser.
- **Implemented:** distinguish structured facts from machine-extracted
  verification-required evidence in prompts and the interface.

#### 3D. Deployment review, storage, return, and reporting

- **Implemented:** remove phase/deployment terminology from the normal search
  path and place invited-tester controls in one collapsed, clearly labeled
  “Help improve Funding Finder” area that does not affect searching.
- **Implemented:** autosave source verdicts (`accurate`, `incorrect`,
  `couldn’t verify`), checked field, optional note, deployment checklist, and
  coarse action counts in a separate device-local record.
- **Implemented:** include existing relevance labels in the Phase 3 handoff
  without profile/CV text, search text, chat, Funding Finder search URL
  parameters, or API keys.
- **Implemented:** one “Send review” action uses file sharing on compatible
  mobile browsers or downloads the JSON and opens an addressed desktop email.
- **Implemented:** retain a separate “Download copy” fallback and local clear
  control.
- **Implemented:** aggregate returned exports with
  `scripts/summarize_phase3_reviews.py` into private Markdown, JSON, and CSV.
  Input and report directories are gitignored.
- **Deployment gate completed:** the pipeline was published, its first bounded
  real-document batch succeeded, the generated catalog was committed, the
  refreshed GitHub Pages deployment succeeded, and the public asset returned
  the expected 45-document/524-fact diagnostics.
- **Deployment gate remaining:** manually verify one PDF page citation and one
  HTML section citation when an HTML source enters the batch, send one review
  package through each available handoff path, and reproduce it with the
  private aggregator. This gate occurs before the deferred Phase 2C researcher
  pilot.

**Exit criterion (not yet met):** decisive dates and requirements link to
verifiable source evidence in the deployed site, document changes remain
traceable, and at least one privacy-safe deployment review can be returned to
the owner and reproduced as a private report.

### Phase 4 — Expand the funding universe

Add one maintainable public source at a time, prioritizing gaps reported in the pilot:

1. SAM.gov and selected DOD/DARPA sources
2. ARPA-E eXCHANGE
3. DOE Office of Science
4. selected private foundations and associations
5. NSF Dear Colleague Letters
6. University of Rochester internal deadlines and limited submissions

Each source requires a documented public-use basis, stable ingestion route, health check, regression fixture, failure alert, and maintenance owner. Duke and Pivot-RP are product references, not scrape targets.

**Exit criterion:** each new source adds opportunities users actually value without silently degrading.

### Phase 5 — Optional service-backed capabilities

Only consider a server or managed third-party service after the public pilot demonstrates value. It would be required for:

- saved searches across devices;
- watchlists and pursuit status;
- automatic personalized alerts or email digests;
- shared departmental feedback;
- institutional identity and access controls; or
- centrally managed AI credentials and budgets.

For email digests, the daily catalog job should first create a compact change
feed keyed by stable opportunity ID: newly added, materially amended or
deadline-changed, and removed/closed. A fixed owner or small internal-recipient
digest can be sent directly after a successful GitHub Actions refresh through a
transactional email provider using encrypted repository secrets.

Public personalized digests require a small server-side subscription API and
database because a static GitHub Pages app cannot securely retain subscriber
addresses, preferences, or an email-provider credential. Store only explicit
saved-search criteria such as keywords, agencies, topics, eligibility, and
deadline horizon; keep CV text, AI chat, and the full device-local research
profile out of the subscription service. The sender must support confirmation,
unsubscribe, bounce handling, retry-safe send identifiers, and a durable send
log.

A Google Sheet and Apps Script may be acceptable for a short, manually managed
internal pilot, but they are not the production ingestion engine or subscriber
system of record. The authoritative full-catalog refresh remains GitHub
Actions; a managed database/serverless function plus a transactional email
provider is the maintainable path if the pilot justifies personalized alerts.

---

## 9. Product quality rules

- A user can always search the full catalog without AI.
- Record-count checks should fail closed rather than silently publish a tiny feed.
- Expired records must not be revived by incidental language such as “rolling assessment.”
- Undated recurring records must visibly ask the user to verify current status.
- Missing facts remain missing; neither deterministic rules nor AI may fabricate them.
- AI only receives a bounded candidate set and is never the retrieval database.
- Every result exposes one visible official action without making the user
  expand details first.
- Total program funding must never be presented or filtered as a per-award
  amount.
- Narrative deadline extraction must be labeled as machine-extracted and
  verification-required.
- Every document-derived fact must retain its source document hash, exact
  page/section, short quote, and direct citation URL.
- Document-derived dates and amounts must not silently replace structured
  Grants.gov values used for filtering or sorting.
- Raw official documents and full extracted notice text must not be committed.
- Deployment review must be explicit, device-local until handoff, and free of
  profile/CV text, API keys, search text, Funding Finder search URL parameters,
  and chat by default.
- API keys never enter source control, URLs, exports, profile storage, or
  review/evaluation storage. Optional browser credential storage requires an
  explicit save action and has a visible removal control.
- The application remains usable on current mobile and desktop browsers.
- Every added source has an identified maintenance strategy.

---

## 10. Explicit non-goals

- a 48-record discipline-specific shortlist;
- local storage as the funding database;
- AI calls for every keyword search;
- faculty scraping or preloaded faculty identities;
- user-managed JSON files;
- a Python installation for end users;
- scraping Duke, Pivot-RP, or other licensed databases;
- presenting inferred topics or AI rationales as official requirements; and
- building account infrastructure before the public search workflow is validated.

---

## 11. Project files

| Path | Purpose |
|---|---|
| `index.html` | GitHub Pages entry point |
| `match_explorer.html` | Public search and refinement interface |
| `assets/app.js` | Browser search, cited source evidence, review/export, profile ranking, AI matching, and chat |
| `assets/profile.js` | Device-local profile/feedback boundary and browser CV extraction |
| `assets/review.js` | Device-local Phase 3 deployment-review boundary and privacy-safe handoff package |
| `assets/ai-provider.js` | Testable OpenAI and Anthropic browser adapters |
| `assets/app.css` | Responsive visual design |
| `assets/vendor/` | Vendored PDF.js and Mammoth browser parsers plus licenses |
| `data/opportunities.js` | Generated catalog, facets, and BM25 index |
| `data/opportunity_enrichment.json` | Compact official-detail cache for incremental refresh |
| `data/document_evidence.json` | Compact document hash/version, citations, extracted facts, and review-queue cache |
| `scripts/build_catalog.py` | Complete XML ingestion, normalization, validation, and index build |
| `scripts/enrich_catalog.py` | Official detail enrichment, evidence reconciliation, and FOA selection |
| `scripts/extract_document_evidence.py` | Bounded official-notice retrieval, deterministic extraction, versioning, and citations |
| `scripts/evaluate_phase2.py` | Reproducible retrieval/reranking pilot evaluator |
| `scripts/summarize_phase3_reviews.py` | Private aggregation of returned deployment-review exports |
| `evaluation/README.md` | Consented Phase 2 export and aggregation workflow |
| `evaluation/PHASE3_REVIEW.md` | Phase 3 reviewer handoff, private storage, and reporting procedure |
| `scripts/pull_grants.py` | Earlier API normalizer retained for fixtures and reference |
| `tests/` | Pipeline and public-application regression checks |
| `.github/workflows/refresh-opportunities.yml` | Daily catalog refresh and owner alert |
| `docs/HOSTING.md` | Deployment, privacy, and data boundary |
| `web/` | Retained server experiment; not the canonical product |

---

## 12. Decision log

| Date | Decision |
|---|---|
| July 2026 | GitHub Pages remains the only active product surface. |
| July 2026 | Replace the 48-record keyword feed with the complete current Grants.gov daily extract. |
| July 2026 | Make deterministic public search the primary workflow and keep it free of AI calls. |
| July 2026 | Use AI only for bounded query expansion, reranking, and grounded chat over current results. |
| July 2026 | Replace separate keyword/profile/AI entry points with one guided search; show chat with the returned result set on desktop and mobile. |
| July 2026 | Reject past forecast deadlines and stale undated forecasts instead of treating every unarchived forecast as current. |
| July 2026 | Remove browser storage as a funding database; later allow explicit, isolated device-local provider-key storage with status and removal controls. |
| July 2026 | Treat Duke as a search/discovery design reference, not a data source. |
| July 2026 | Add a Phase 1.5 evidence layer before pilot work: incremental official detail enrichment, one-click source actions, and strict funding/deadline semantics. |
| July 2026 | Treat the Albany study as evidence that exact-keyword recommendations require researcher feedback and separate retrieval/reranking evaluation. |
| July 2026 | Make pilot validation and separate retrieval/reranking measurement the next implementation phase before expanding sources. |
| July 2026 | Add explicit device-local profile, extracted-CV, preference, and evaluation-label persistence while keeping raw CV files, API keys, AI shortlists, and chat out of storage. |
| July 2026 | Implement Phase 2A/2B controls and evaluator; require the 3–5 researcher pilot and report before declaring Phase 2 complete. |
| July 2026 | Defer the Phase 2C researcher pilot until Phase 3 source evidence and deployment-review handoff are deployed and verified; the pilot is deferred, not declared complete. |
| July 2026 | Retrieve and parse official notices only in bounded scheduled jobs; retain compact citations, hashes, facts, and version history while discarding raw documents and full text. |
| July 2026 | Keep structured Grants.gov dates and amounts authoritative for filters; treat all narrative notice extraction as verification-required evidence. |
| July 2026 | Collect no silent central telemetry. Autosave deployment review locally and return it only through explicit file share/download/email, then aggregate it in gitignored private folders. |
| July 2026 | Keep GitHub Actions as the authoritative daily refresh engine; do not move ingestion to Google Sheets. Build any automatic digest from a catalog change feed and a separate consent-based subscription service. |
| July 2026 | Start with an empty result state, integrate keywords/profile/CV/filters under one “Find funding” action, and move invited-tester evidence checks out of the normal user workflow. |
| July 2026 | Make result chat visibly interactive: add a large focused workspace, working indicator, keyboard send, safe rich formatting, exact result references, jump-to-result/source actions, and explicit result-list focusing. |
| July 2026 | Stack profile/CV and filters full-width, remove nested filter scrolling, and retry malformed AI structured responses once with a smaller-output instruction. |
| July 2026 | Repair Grants.gov synopsis spacing loss by preferring the linked official NSF synopsis only for damaged NSF prose, caching it, and rebuilding search terms. |

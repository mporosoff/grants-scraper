# Funding Finder — Product Plan

**Status:** Funding Finder v1.3.0 has passed residual-hardening Gates 1–3; Gate 4 real-browser validation and protected release verification are in progress

**Next implementation phase:** Complete the v1.3.0 Gate 4 protected release and live verification, then return to post-launch operations and explicitly accepted follow-up work; do not treat MEAS-10, archive/search retention, topic-change feed events, or a SAM.gov adapter as completed or scheduled without their recorded human/product triggers

**Canonical application:** https://mporosoff.github.io/grants-scraper/

**Repository:** https://github.com/mporosoff/grants-scraper

**Initial audience:** University of Rochester researchers, with a design that remains useful to any public user

**Last updated:** August 24, 2026

---

## 1. Product goal

Funding Finder is a public funding-opportunity search engine with an optional AI refinement layer.

The base product should provide the useful parts of the [Duke Research Funding database](https://researchfunding.duke.edu/search-results)—a broad catalog, keyword search, filters, sorting, result details, and export—in a faster and more approachable interface. AI is not the database and is not required to browse it.

The product answers three related questions:

1. **What funding opportunities are available?** Search the comprehensive catalog directly.
2. **Which of these are most relevant to my work?** Use deterministic keyword, profile, CV, ORCID-publication, and topic evidence first; optionally let AI rerank a bounded candidate set and answer follow-up questions.
3. **What does this funding notice require?** Drop a NOFO/FOA PDF into the main search box, connect it to a matching catalog record when possible, and ask document-grounded questions with page references.

Local Strong matching must not make a model call, and the catalog must never be
hidden behind an API key. A non-empty query may automatically use the
site-managed hosted semantic service for bounded Potential matching; that path
must be disclosed, budgeted, fail closed, and never receive CV/profile text,
researcher names, or full publication text.

---

## 2. Product decisions

### 2.1 One public application

GitHub Pages is the only active product surface:

https://mporosoff.github.io/grants-scraper/

There are no accounts, installations, private faculty accounts, or persistent user-managed opportunity files. A compact public, source-traceable Hajim faculty directory supports Team Match and a staged ten-scope opportunity-to-team pilot; it is a generated planning asset rather than a user profile system. An uploaded notice exists only in page memory. The retired server experiment remains available in Git history, not in the active product tree or CI.

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

After the Grants.gov evidence steps, verified public adapters add NSF upcoming
due dates and NYSERDA opportunities through the same normalized schema and
search index. NYSERDA uses the next open application round and retains later
round and concept-paper dates. Each enabled source has
currentness/actionability gates, plausible-count bounds, atomic replacement,
and a committed per-source cache. Most degraded sources retain only safe,
current snapshot rows; stricter sources publish zero when currentness cannot be
verified. Degradation exits visibly and opens or updates an owner-facing GitHub
issue. UR InfoReady is a disabled shell pending a stable permissioned route.

<!-- catalog-summary:start -->
The September 3, 2026 build contains 1,397 open or current forecasted funding
opportunities (1,079 posted and 318 forecasted) rather than the former 48-record
engineering shortlist. It contains no record with a deadline before the catalog date.
Current published sources are ARPA-H (10), DOE EERE Exchange (1), Grants.gov (1,324),
NASA ROSES (3), NYSERDA (37), U.S. National Science Foundation (1), VPR funding digest
(limited submissions & foundations) (21); additional sources are enabled only after a
sustainable public ingestion path and health bounds are verified.
<!-- catalog-summary:end -->

### 2.3 Search is the primary workflow

Anyone can use, without an API key:

- full-text keyword and opportunity-number search;
- browser-local NOFO/FOA PDF parsing and catalog-record matching;
- a one-click browse-all path when they do not yet have search terms;
- open and forecasted status filters;
- discipline, topic, agency, eligibility, and funding-instrument facets;
- deadline and minimum per-award filters;
- preliminary-stage, limited-submission, early-career, and cost-share signals;
- a cited-FOA-evidence availability filter for deployment review;
- relevance, deadline, posted-date, award, agency, and title sorting;
- pagination and expandable record details;
- a compact deadline/award/eligibility/contact overview with mailto POC links;
- device-local saved opportunities;
- compact matched-topic evidence and a collapsed deterministic “Why this match” explanation;
- per-opportunity and result-set calendar export;
- one-click official FOA, agency-notice, or Grants.gov record links; and
- CSV export of the complete current result set.

Search and filtering execute in the browser over the prebuilt index. They make zero AI calls and have no per-search infrastructure cost.

The parent opportunity remains the result unit. The optional topic sidecar is
loaded lazily, indexes only publishable `subject` children, rolls the strongest
child evidence up to its parent with no child-count bonus, and shows at most
three matched topics before deliberate expansion. Review-only children never
enter ordinary retrieval, rendering, or explanations.

`assets/app-config.js` is the single source for the visible application release
(`Funding Finder v1.1.0 · Updated Aug 21, 2026`) used by Funding Finder and Team
Matcher. Visible version numbering is introduced with v1.1.0 for the
topic-aware retrieval release; the earlier live production baseline remains
intentionally unnumbered, with no invented v1.0.0 release. The release date
changes only for a deliberate app release: patch versions cover bug fixes/small
UI updates, minor versions cover user-visible features, and major versions
cover intentional breaking product or schema experiences. The separate Catalog
status continues to report nightly data freshness.

The public page begins with no opportunity cards. One guided workflow combines
keywords, optional profile/CV context, and optional filters under “Find
funding.” The same first step accepts a dropped or selected funding-notice PDF,
which opens document chat and runs a catalog match without introducing a
separate product surface. Profile/CV context and filters are stacked as
full-width sections in that workflow. Expanded filters use the page scrollbar
rather than a sticky nested scrolling pane.

### 2.4 AI is an optional first-class workflow

A user may choose OpenAI or Anthropic and enter one provider key. The same provider powers:

1. **Alternative-phrase expansion:** translate the enabled search context into 5–16 independent, concrete scientific phrases and synonyms.
2. **Bounded additive assessment:** compare at most 32 new candidates that independently passed local Strong admission and add at most 12 without removing or reordering ordinary results.
3. **Chat with results:** answer questions over the top 20 active ordinary or additively refined results; preserve Strong/Potential tier and AI-identification provenance; connect every named opportunity back to its result card and official source; and focus the displayed list when explicitly requested.
4. **Chat with an uploaded notice:** answer questions over a page-marked, bounded PDF extract; cite supporting page numbers; and compare against an automatically matched catalog record when available.

AI settings sit inside that same workflow. “Refine these results with AI”
adds only locally evidence-qualified Strong matches and provides an exact
“Restore original results” action, while “Chat with your results” appears with
the result set on desktop and mobile. A dropped PDF opens “Chat with the NOFO”
and, when no key is configured, presents the provider/key form inside that chat
workspace. Chat can expand without losing the current result state, uses
readable limited-Markdown responses, shows a visible working state, and
supports Enter-to-send with Shift+Enter for a new line. Provider responses
receive a larger bounded output budget; if a provider still returns malformed
or truncated JSON, the application retries once with a shorter-output
instruction and then reports a plain-language error. None of these AI actions
is a separate search source.

AI output is advisory. It must:

- use exact catalog record identifiers;
- distinguish source facts from inference;
- call missing data “not listed”;
- never invent deadlines, amounts, eligibility, or requirements; and
- direct users to the official notice for final verification.

**Planned in Phase 3E:** document chat will let the user explicitly export an
already-generated answer or the current transcript as PDF or DOCX, without a
second model call, and will support cited governing/parent documents with
explicit provenance and precedence rather than assuming the uploaded notice is
the complete rule set.

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
  profile-search preference;
- Phase 2 usefulness labels and reason codes in a separate local record only
  when the dedicated `?evaluation=1` workflow is used;
- saved-opportunity snapshots in another compact device-local record.

PDF, DOCX, TXT, and Markdown CVs are parsed in the browser. The original file
is never saved or uploaded by the application. The user can disable
profile use, remove the CV extract, clear the saved profile, or clear
evaluation labels at any time.

Normal search no longer includes a permanent rating panel or rating-trained
reranking. Invited pilot participants use `?evaluation=1`; those labels remain
measurement evidence only and never alter the deterministic product ranking.

The additive AI refinement overlay, chat, and extracted uploaded-notice text remain page-memory
only and disappear on reload. The uploaded file itself is never stored; its
bounded text is sent to the selected provider only after the user asks a notice
question. An API key is tab-only by default, but the user may explicitly save
one key per
provider in a separate device-local credential record. The interface confirms
whether the current key is entered, saved, loaded, or removed and warns against
saving a key on a shared browser. Keys are never written to the profile,
review/evaluation records, `sessionStorage`, a URL, GitHub, or an application
database. The bounded CV excerpt is sent to the selected AI provider only when
the user leaves that option enabled and explicitly runs AI refinement or chat.

CSV and Phase 2 JSON are created only on explicit export. The evaluation JSON
includes the current search-box text, filters, rankings, and explicit ratings
needed to reproduce retrieval quality. It excludes the API key, saved
profile/expertise fields, CV text, and chat. Because search text can itself
describe research, pilot participants are told to use non-confidential wording
they are comfortable returning to the project team.

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

### 2.7 Topic-aware retrieval release

The v1.1.0 release enables the already-measured topic and deterministic
match-explanation paths. Its August 21 feature-branch dispatch retained all 446
stored subject children across 29 publishing parents: 236 are publishable and
210 inferred children remain review-only. Normal search admits only publishable
`subject` children, keeps the parent opportunity as the result unit, rolls up
only the strongest child with zero child-cardinality bonus, and exposes no
review-only child in ranking, rendering, or explanations.

MEAS-5 covered 48 queries across 11 disciplines: 10 movements were specificity
improvements, two were neutral/bounded, one (`space biology` → `Bionic
Electronics`) remains a bounded known lexical limitation, and none was a
confirmed regression. MEAS-9 completed all eight profile/CV/ORCID arms with the
real Crossref route, preserved the historical admission anchors, and found no
unsupported explanation. DEC-17 permits shipment without MEAS-10; no 3–5
researcher pilot occurred, and MEAS-10 remains explicitly unperformed
post-launch human validation.

Recurring scheduled classification uses only the dedicated GitHub Actions
secret `ANTHROPIC_API_KEY`, exposed to the document-evidence step alone. It
fails closed and records aggregate call and token usage. The cache-aware warm
feature dispatch made zero classifier/API calls and used zero tokens. The first
production refresh made 23 calls for exactly 23 candidate spans across three of
45 administrative documents; each span made one request, all usage was
reported, and there were no API errors or retries. Its separate 30-document
subtopic rotation made zero calls. No child ID or publication count changed, so
this was bounded revalidation rather than an unexpected volume spike. Compare
and the permanent rating/personalization surface remain absent; invited
evaluation mode is separate. Rollback requires only disabling the two browser
flags and removing scheduled `--enable-subtopics`: the sidecar is additive, the
parent catalog remains authoritative, the last successful site is recoverable
from git, and no database migration is involved.

P11 shipped on August 21, 2026 through history-preserving `main` merge
`bca8e03`, followed by successful production refresh `32509140933` in 8m1s and
bot commit `347ed9d`. Main CI, the refresh's post-generation gates, and final
Pages deployment all passed. The deployed `assets/app-config.js` and
`data/subtopics.js` bytes match final `main`; live Funding Finder and Team
Matcher smoke tests confirmed v1.1.0, topic-driven Genesis and ARL retrieval,
bounded explanations and team-topic evidence, the normal-mode evaluation
boundary, profile controls, and zero console errors. The highest issue number
remained #31; the known JHU workbook 403 updated existing degraded-source issue
#30, while generic failure issue #29 was untouched.

### 2.8 v1.2.1 production hardening

Catalog publication and hosted Potential matching are one release package.
Every scheduled production refresh rebuilds all current public document
vectors with one model contract, records a fixed-canary model-space
fingerprint, generates a current/previous Worker allowlist, runs all product
gates, deploys the compatibility Worker, and only then commits the complete
package. A failed vector build, integrity check, Worker deployment, or live
handshake leaves the prior live package authoritative.

The Worker has separate per-client embed and rerank limits, a global request
limit, daily token budgets, and a circuit breaker. It stores only operational
counters and never raw queries, candidate passages, names, profile/CV/ORCID
content, or publication text. Funding Finder distinguishes successful empty
Potential matching from service, budget, rate, and package failures. Team Match
retains local full-team ordering whenever enhanced ordering fails.

Membership is determined by query, currentness, and filters; sort only orders
within Strong and Potential tiers. Filter eligibility applies before BM25,
semantic top-k, fusion, and reranking. Team Match derives its bounded aggregate
query limit from the shared client contract and keeps every selected researcher
represented where possible without adding names.

The source pipeline also treats Grants.gov 2076/2099 dates as lifecycle
sentinels, gives catalog records precedence over duplicate VPR/Cindy email
records, enriches missing private-funder card fields from allowlisted public
links when possible, and keeps opportunity actions concise on narrow cards.

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
                 | verified NSF/NYSERDA source merge
                 | atomic snapshots + health alerts
                 v
Cross-source current catalog + rebuilt facets/index
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
                   saved items,             +-- rerank <= 32 candidates
                   source review
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

### Save opportunities and run a dedicated relevance evaluation

1. Select “Save” on any result to keep a compact device-local shortcut.
2. Normal search keeps rating controls absent.
3. Invited pilot participants open `match_explorer.html?evaluation=1`, label
   results locally, and explicitly export one evaluation file.
4. Evaluation labels do not change retrieval or ranking.

### Add AI refinement

1. Run the combined catalog search.
2. Open the optional AI settings, choose a provider, and enter a key.
3. Keep the key tab-only or explicitly save it on this device.
4. Select “Refine these results with AI.”
5. Review the newly added locally Strong matches, AI-identification badges,
   assessment rationale, and caveats without losing any ordinary result.
6. Ask grounded follow-up questions such as:
   - “Which allow a university to lead?”
   - “Keep only those closing after October.”
   - “Which require cost share?”
   - “Compare the top three on fit and timing.”
7. Select “Restore original results” to return to the exact ordinary baseline.

### Chat with ordinary results

1. Run any keyword or filtered catalog search.
2. Use “Chat with your results,” shown with the returned result set.
3. Ask about the top 20 current results without first running AI refinement.
4. Let chat narrow the displayed results only when explicitly requested.

### Chat with an uploaded NOFO

1. Drag a NOFO/FOA PDF into the main search box or choose it from the upload
   control.
2. Review the automatically matched catalog card when an opportunity number or
   distinctive title is found.
3. Use the card to save the opportunity, add its deadline to a calendar, or
   open the official source.
4. If no key is configured, enter and optionally save one in the chat prompt.
5. Ask document-grounded questions and verify the returned page references in
   the original notice.
6. **Planned in Phase 3E:** explicitly export a useful answer or current chat as
   PDF/DOCX, and distinguish rules stated by the notice from rules inherited
   from governing or supplemental documents. See Phase 3E for the preservation,
   privacy, provenance, and precedence requirements.

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
The export uses a non-content comparison fingerprint, includes the current
search text needed to reproduce retrieval, and excludes saved profile text, CV
text, API keys, and chat. Pilot instructions disclose the search-text field
before a participant returns the file.

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
- daily scheduled refresh with whole-job and per-source degradation alerts;
- comprehensive browser search and BM25 index;
- Duke-style facets, sorting, details, pagination, and CSV export;
- visible record count, source, generated time, and stale-data warning;
- one guided search that combines keywords, optional profile/CV context, and
  filters;
- bounded two-call AI refinement;
- chat integrated with the top 20 ordinary or additively refined results;
- an empty initial result state until a user starts a search;
- explicit optional device-local API-key persistence with visible state and
  a removal control;
- monitored NSF/NYSERDA ingestion with source-aware facets and provenance;
- atomic external-source refresh with still-current last-known-good fallback;
- direct saved-opportunity controls and a separate, explicit evaluation mode;
  and
- regression coverage for forecasts, expired records, ambiguous rolling
  language, source lifecycles, indexing, generated assets, and workflow
  safeguards.

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
- A compact versioned cache prevents the entire catalog from being fetched on
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

<!-- catalog-evidence:start -->
The September 3, 2026 catalog contains 1,397 current posted or forecasted opportunities:

- 287 have a defensible direct announcement attachment (195 high confidence, 92 medium
  confidence);
- another 619 use an official source page as their primary route;
- the remaining 491 use the official Grants.gov record as their primary route;
- 720 contain an agency notice URL across all route types;
- 419 preserve an official deadline time or timezone;
- 132 carry a preliminary-stage signal, including 1 narrative dates visibly marked for
  verification;
- 602 (43.1%) have an official per-award floor or ceiling;
- 864 (61.8%) have at least one structured funding amount; and
- zero have a past structured close date and zero have a detected XML/detail-API
  deadline conflict in this build.
<!-- catalog-evidence:end -->

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

- **Implemented:** locally persistent graded labels for `not relevant`,
  `partial`, `useful`, `strong`, and `needs verification`, shown directly on
  result cards.
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
- **Implemented:** measure catalog retrieval independently from AI assessment:
  - recall within the 32-record candidate set;
  - precision and useful-result rate within up to 12 additive records;
  - graded nDCG for both retrieval and AI assessment;
  - rank movement among locally qualified additions; and
  - hard eligibility and expired-record error rates.
- **Implemented:** evaluation exports distinguish the immutable ordinary baseline
  from locally qualified AI additions so retrieval and assessment failures can
  be labeled separately.
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

- **Implemented:** keep invited-tester controls out of normal search and expose
  them only through the dedicated `?evaluation=1` workflow.
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

#### 3E. Document-chat preservation and governing context — planned

This is future document-chat work. It does not change Phase 3D's state or the
current next implementation phase, and neither capability is implemented yet.

**Export useful chat output.** A NOFO-chat analysis can itself become a useful
working document; forcing the user to regenerate it later can change the answer
or lose a useful synthesis. The user must therefore be able to explicitly choose
at least **Export this answer** or **Export chat**, in either **PDF or DOCX**.

- Export the response already generated; never call a model again to recreate
  it.
- Preserve the user's question and AI answer, useful formatting, page/source
  citations and links, the matched opportunity/document identity, and the
  document version/hash where already available.
- Export only on explicit user action. Normal chat and uploaded-notice text
  remain page-memory only and may disappear on reload; export introduces no
  automatic server-side persistence.
- Include only visible chat content plus public/source metadata. Never export
  API keys or hidden profile/CV context.
- Library and implementation choices remain open; this section defines behavior,
  not a PDF/DOCX stack.

**Governing/parent document context.** “Chat with the NOFO” must not assume the
uploaded child notice contains every rule governing a proposal. The architecture
must eventually represent an agency-generic relationship such as:

```text
specific solicitation / NOFO
       ↓
applicable governing policy / guide
       ↓
applicable supplements / amendments
```

The relationship may contain zero, one, or multiple governing documents. Each
document needs explicit authority, provenance, applicability, and precedence;
the system must not silently concatenate sources into one unattributed answer.
Answers must distinguish and cite facts from the specific solicitation, facts
inherited from a governing document, and facts supplied by a supplement or
amendment. A useful answer can therefore say, conceptually, “The solicitation
does not state this directly; the applicable governing guide supplies the
general rule,” or “The guide gives the general rule, but this solicitation
modifies it; the solicitation-specific instruction controls.”

NSF is the first concrete case. The official
[PAPPG 24-1 page](https://www.nsf.gov/policies/pappg/24-1) identifies that guide
as effective for proposals submitted or due on or after May 20, 2024, identifies
later supplemental policy notices, and states that some program solicitations
modify the PAPPG's general provisions and that the solicitation guidelines must
then be followed. Phase 3E must preserve that authority/precedence relationship.
`PAPPG 24-1` is a motivating example, not a permanently hard-coded version: the
applicable PAPPG and supplements must eventually be resolved from the proposal
or solicitation's applicable date and official NSF guidance.

The same architecture must allow analogous agency proposal guides, general
terms/instructions, umbrella-program guidance, incorporated documents, and
supplements/amendments elsewhere without asserting that every agency uses the
same hierarchy. Complete schema and retrieval design are deferred to the future
implementation package.

### Phase 4 — Expand the funding universe

Add one maintainable public source at a time, prioritizing gaps reported in the pilot:

1. ~~DOE EERE Exchange and ARPA-E eXCHANGE~~ — enabled with NOFO-only parsing,
   health bounds, atomic snapshots, and last-known-good fallback
2. DOE Office of Science national-lab announcements and other DOE offices
3. selected private foundations and associations
4. NASA and NSF Dear Colleague Letters
5. University of Rochester internal deadlines and limited submissions, only
   after a stable permissioned InfoReady route is established
6. SAM.gov and selected DOD/DARPA contract sources only if users want them

Each source requires a documented public-use basis, stable ingestion route, health check, regression fixture, failure alert, and maintenance owner. Duke and Pivot-RP are product references, not scrape targets.

**Exit criterion:** each new source adds opportunities users actually value without silently degrading.

### Phase 5 — Optional service-backed capabilities

Static Atom feeds now cover the no-account alert case: the daily workflow
generates an all-opportunities feed plus topic and source-type feeds under
`feeds/`, without storing any personal data. A separate bundle in
`docs/weekly-alerts/` can run manually consented weekly saved-search digests
from a private GitHub repository. It reuses the production tokenizer and BM25
index, stores subscribers and watermarks only in that private repository, and
keeps SMTP credentials in encrypted repository secrets. The daily workflow
now also publishes a rolling change feed keyed by stable opportunity ID for
new, materially amended, deadline-changed, closing-soon, and removed/closed
events. The digest includes relevant unseen change events as well as new
matches.

A public self-service system still requires a server or managed third-party
service. Only consider that after the public pilot demonstrates value. It would
be required for:

- saved searches across devices;
- watchlists and pursuit status;
- self-service personalized alerts or email digests;
- shared departmental feedback;
- institutional identity and access controls; or
- centrally managed AI credentials and budgets.

The pilot bundle is still not a replacement for durable bounce, retry,
account, and unsubscribe infrastructure. The recommended self-service design,
data model, endpoint set, scheduled job, and deployment choices are documented
in `docs/EMAIL_ALERT_SERVICE_SETUP.md`.

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
- Unknown acronyms may expand only from phrases present in the local catalog;
  researcher context must disambiguate sparse candidates, and tied candidates
  remain literal rather than being guessed.
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
- Document-chat export preserves already-generated visible output; it must not
  regenerate the answer, and it must exclude API keys and hidden profile/CV
  context.
- Governing-document answers retain source-level provenance and explicit
  precedence; solicitation, governing-guide, and supplement/amendment facts
  must not be silently merged or cited as though they came from one document.
- The application remains usable on current mobile and desktop browsers.
- Every added source has an identified maintenance strategy.
- Opportunity-to-team proposals use only a specific parent, a currently
  publication-eligible child, or an official declared branch. Broad parents
  never receive an automatic team.
- Every proposed person and required role retains inspectable source evidence;
  adjacent or provisional replacement evidence cannot silently complete a
  missing role.
- Generated team membership never overrides current runtime catalog status,
  dates, or child publication eligibility.

---

## 10. Explicit non-goals

- a 48-record discipline-specific shortlist;
- local storage as the funding database;
- AI calls for every keyword search;
- private faculty accounts or untraceable scraped faculty identities;
- treating faculty-faculty similarity or team-permutation counts as proof of a
  high-quality opportunity team;
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
| `assets/app-config.js` | Shared Funding Finder release metadata and production feature flags |
| `assets/subtopic-runtime.js` | Lazy publishable-subject loading and parent-level child-score rollup |
| `assets/match-explain.js` | Local deterministic, evidence-bounded match explanations |
| `assets/profile.js` | Device-local profile/feedback boundary and browser CV extraction |
| `assets/nofo.js` | Browser-only NOFO PDF extraction, opportunity-number detection, and catalog matching |
| `assets/review.js` | Device-local Phase 3 deployment-review boundary and privacy-safe handoff package |
| `assets/ai-provider.js` | Testable OpenAI and Anthropic browser adapters |
| `assets/app.css` | Responsive visual design |
| `assets/vendor/` | Vendored PDF.js and Mammoth browser parsers plus licenses |
| `data/opportunities.js` | Generated catalog, facets, and BM25 index |
| `data/opportunity_enrichment.json` | Compact official-detail cache for incremental refresh |
| `data/document_evidence.json` | Compact document hash/version, citations, extracted facts, and review-queue cache |
| `data/subtopics.js` | Lazy public sidecar for publishable and review-gated subject-child records and their search index |
| `data/source_records.json` | Per-source records, first-seen dates, and refresh diagnostics |
| `scripts/build_catalog.py` | Complete XML ingestion, normalization, validation, and index build |
| `scripts/enrich_catalog.py` | Official detail enrichment, evidence reconciliation, and FOA selection |
| `scripts/extract_document_evidence.py` | Bounded official-notice retrieval, deterministic extraction, versioning, and citations |
| `scripts/program_areas.py` | Evidence-backed controlled vocabulary for official-notice discoverability |
| `scripts/sources/` | Multi-source adapters, validation, health gates, lifecycle, and merge |
| `scripts/build_feeds.py` | Static all/topic/source-type Atom feed generator |
| `scripts/alert_match.py` | Saved-search matcher shared with the private weekly-digest bundle |
| `scripts/update_catalog_docs.py` | Generated catalog baseline statistics in README and project documentation |
| `scripts/evaluate_phase2.py` | Reproducible retrieval/reranking pilot evaluator |
| `scripts/summarize_phase3_reviews.py` | Private aggregation of returned deployment-review exports |
| `evaluation/README.md` | Consented Phase 2 export and aggregation workflow |
| `evaluation/PHASE3_REVIEW.md` | Phase 3 reviewer handoff, private storage, and reporting procedure |
| `feeds/` | Generated public feed directory |
| `docs/weekly-alerts/` | Private-repository pilot bundle for consent-based weekly email digests |
| `scripts/pull_grants.py` | Earlier API normalizer retained for fixtures and reference |
| `tests/` | Pipeline and public-application regression checks |
| `.github/workflows/refresh-opportunities.yml` | Daily catalog refresh and owner alert |
| `docs/HOSTING.md` | Deployment, privacy, and data boundary |

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
| July 2026 | Add explicit device-local profile, extracted-CV, preference, and evaluation-label persistence while keeping raw CV files, API keys, AI result overlays, and chat out of storage. |
| July 2026 | Implement Phase 2A/2B controls and evaluator; require the 3–5 researcher pilot and report before declaring Phase 2 complete. |
| July 2026 | Defer the Phase 2C researcher pilot until Phase 3 source evidence and deployment-review handoff are deployed and verified; the pilot is deferred, not declared complete. |
| July 2026 | Retrieve and parse official notices only in bounded scheduled jobs; retain compact citations, hashes, facts, and version history while discarding raw documents and full text. |
| July 2026 | Keep structured Grants.gov dates and amounts authoritative for filters; treat all narrative notice extraction as verification-required evidence. |
| July 2026 | Collect no silent central telemetry. Autosave deployment review locally and return it only through explicit file share/download/email, then aggregate it in gitignored private folders. |
| July 2026 | Keep GitHub Actions as the authoritative daily refresh engine; do not move ingestion to Google Sheets. Build any automatic digest from a catalog change feed and a separate consent-based subscription service. |
| July 2026 | Generate catalog baselines from the published asset, keep browser tests with the canonical product, and retire the unused server experiment and faculty scraper from the active tree. |
| July 2026 | Start with an empty result state, integrate keywords/profile/CV/filters under one “Find funding” action, and move invited-tester evidence checks out of the normal user workflow. |
| July 2026 | Make result chat visibly interactive: add a large focused workspace, working indicator, keyboard send, safe rich formatting, exact result references, jump-to-result/source actions, and explicit result-list focusing. |
| July 2026 | Stack profile/CV and filters full-width, remove nested filter scrolling, and retry malformed AI structured responses once with a smaller-output instruction. |
| July 2026 | Repair Grants.gov synopsis spacing loss by preferring the linked official NSF synopsis only for damaged NSF prose, caching it, and rebuilding search terms. |
| July 2026 | Enable verified NSF and NYSERDA sources through atomic per-source snapshots and health alerts; keep InfoReady disabled until a stable permissioned route exists. |
| July 2026 | Add compact device-local saved opportunities and an optional, reversible preference re-ranker trained only after three graded ratings. |
| July 2026 | Include search text in explicit match-quality exports for reproducibility, disclose it before export, and continue excluding API keys, saved profile/CV text, and chat. |
| July 2026 | Enable NOFO-only ARPA-E and DOE EERE Exchange adapters; keep NASA NSPIRES disabled until a stable public list route exists. |
| July 2026 | Publish no-account Atom feeds and provide a fail-closed, consent-based weekly digest bundle for a separate private repository; keep public subscriber data out of GitHub Pages. |
| August 2026 | Resolve unfamiliar research acronyms locally by matching catalog phrases against enabled researcher context; require multiple expansion-term hits and fail closed on ambiguity. |
| August 20, 2026 | Plan explicit PDF/DOCX export of an already-generated document-chat answer or current transcript, preserving visible questions, answers, citations, links, formatting, and available document identity/version metadata without regeneration, hidden context, or automatic persistence. |
| August 20, 2026 | Plan agency-generic governing-document context with explicit provenance, applicability, and precedence; use NSF PAPPG 24-1 as the first dated example while resolving the applicable guide and supplements from official guidance rather than hard-coding one version. |
| August 21, 2026 | Accept DEC-17 and ship the topic layer before the unperformed MEAS-10 researcher pilot; authorize recurring, step-local, fail-closed Anthropic classification with auditable aggregate usage; introduce visible version numbering with Funding Finder v1.1.0 and leave the earlier production baseline unnumbered. |

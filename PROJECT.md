# Funding Finder — Product Plan

**Status:** Phase 1 complete; Phase 1.5 source-evidence and actionability layer implemented

**Next implementation phase:** Phase 2 — Pilot validation and relevance quality

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
- relevance, deadline, posted-date, award, agency, and title sorting;
- pagination and expandable record details;
- one-click official FOA, agency-notice, or Grants.gov record links; and
- CSV export of the complete current result set.

Search and filtering execute in the browser over the prebuilt index. They make zero AI calls and have no per-search infrastructure cost.

### 2.4 AI is an optional first-class workflow

A user may choose OpenAI or Anthropic and enter one provider key. The same provider powers:

1. **Query expansion:** translate a natural-language research description into concrete search terms and synonyms.
2. **Bounded reranking:** compare at most 32 locally retrieved candidates and return at most 12 grounded recommendations.
3. **Chat with results:** answer questions over either the top 20 ordinary search results or the AI shortlist and, when explicitly requested, narrow those results further.

Keyword search and “Describe your research” are equally visible entry points. The chat panel remains visible on desktop and mobile before the long result list; it is not hidden behind a successful reranking call.

AI output is advisory. It must:

- use exact catalog record identifiers;
- distinguish source facts from inference;
- call missing data “not listed”;
- never invent deadlines, amounts, eligibility, or requirements; and
- direct users to the official notice for final verification.

### 2.5 No application local storage

The search catalog is a published static asset, not a user-maintained local database. Search state is computed from the current page and the keyword query can be shared in the URL.

The provider selection, API key, research description, AI shortlist, and chat exist in page memory only. They disappear on reload or when the tab closes. The application does not write them to `localStorage`, `sessionStorage`, GitHub, or an application database.

CSV is created only when a user explicitly exports results and never includes the API key or research description.

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
                 v
          GitHub Pages app
          /              \
         /                \ optional, user initiated
        v                  v
Zero-cost browser       OpenAI or Anthropic
search and filters      using an in-memory user key
                            |
                            +-- query expansion
                            +-- rerank <= 32 candidates
                            +-- chat over <= 20 search results
                                or <= 12 AI matches
```

There is no application server, search cluster, vector database, account system, or central user database. GitHub Actions performs the expensive ingestion work once per day; every visitor reuses the published result.

---

## 4. User workflow

### Browse and search

1. Open the public URL.
2. Search by topic, method, program name, agency, or opportunity number.
3. Narrow with facets, dates, award size, or special-requirement signals.
4. Sort and inspect detailed results.
5. Open the best available official source in one click or export the result
   set.

### Add AI refinement

1. Describe the research or proposed project.
2. Choose a provider and enter a key for the current tab.
3. Ask AI to build and rank a best-fit shortlist.
4. Review the shortlist, scores, specific rationale, and caveats.
5. Ask grounded follow-up questions such as:
   - “Which allow a university to lead?”
   - “Keep only those closing after October.”
   - “Which require cost share?”
   - “Compare the top three on fit and timing.”
6. Return to the unmodified catalog at any time.

### Chat with ordinary results

1. Run any keyword or filtered catalog search.
2. Use the visible “Chat with results” panel.
3. Ask about the top 20 current results without first running AI refinement.
4. Let chat narrow the displayed results only when explicitly requested.

---

## 5. Privacy, security, and cost boundary

Funding records are public. The catalog and its search index are committed to the public repository and served by GitHub Pages.

Ordinary search sends no research description to an AI provider and makes zero AI calls. When a user explicitly invokes refinement or chat:

- the browser sends the research description and a bounded selection of public opportunities directly to the selected provider;
- that provider’s billing, retention, and privacy terms apply;
- the application never proxies, receives, or stores the key;
- the key remains visible to the running page in memory, so users should use a scoped key with a spending limit; and
- users should not enter confidential or unpublished information.

The browser-only design cannot provide a secure institutional credential vault. A future institution-managed AI gateway would be a separate architectural decision.

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
- equally prominent deterministic search and AI matching entry points;
- bounded two-call AI refinement;
- always-visible chat over ordinary results or the AI shortlist;
- mobile ordering that places AI matching and chat before filters and results;
- no browser persistence of API keys or research text; and
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

**Status: next to implement**

Phase 1 solved catalog coverage and established a bounded AI workflow. The next
risk is quality: whether deterministic retrieval finds the right candidates
and whether AI puts the genuinely useful opportunities near the top. Phase 2
creates the evidence and feedback loop needed to answer that before more
sources or infrastructure are added.

#### 2A. Evaluation controls

- Add in-session labels for `useful`, `not relevant`, and `needs verification`.
- Add reason codes for topic, eligibility, career stage, deadline, award size,
  application burden, duplicate/already known, and insufficient source detail.
- Keep labels in page memory and include them only in an explicit evaluation
  export; do not reintroduce browser storage.
- Export enough catalog, query, filter, retrieval-rank, AI-rank, model, and
  reason-code context to reproduce an evaluation without exporting the API key
  or research description by default.

#### 2B. Reproducible quality harness

- Create a versioned, consented benchmark fixture separate from the production
  catalog.
- Measure catalog retrieval independently from AI reranking:
  - recall within the 32-record candidate set;
  - precision and useful-result rate within the 12-record shortlist;
  - rank movement between BM25 retrieval and AI output; and
  - hard eligibility and expired-record error rates.
- Add regression cases for known synonym, interdisciplinary, eligibility, and
  sparse-description failures.
- Record provider/model and prompt versions so comparisons are meaningful.

#### 2C. Pilot

- Recruit 3–5 researchers across multiple disciplines.
- Evaluate approximately 75–150 researcher/opportunity pairs.
- Test whether 32 candidates and 12 recommendations are the right
  cost/quality boundary.
- Tune search weights, topic rules, prompts, and thresholds only from labeled
  evidence.
- Publish a short pilot report identifying retrieval failures, reranking
  failures, source-data gaps, and the highest-value missing funding sources.

**Exit criterion:** a reproducible benchmark and pilot report separate search
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

- Track amendment, superseded, archive, and recurring-program status more precisely.
- Retrieve and parse the linked official PDF/HTML notice when structured
  Grants.gov fields are incomplete.
- Normalize multiple LOI, concept-paper, preproposal, and full-proposal
  deadlines as distinct evidence-backed events.
- Extract high-value NOFO facts such as per-award ranges, project duration,
  page limits, review criteria, cost share, and application burden.
- Cite the exact source document and location for every machine-extracted fact.
- Make limited-submission detection an explicit review queue rather than an authoritative label.

**Exit criterion:** decisive dates and requirements link to verifiable source evidence.

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
- API keys never enter source control, URLs, exports, or browser storage.
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
| `assets/app.js` | Browser search, filters, source actions, export, AI matching, and chat |
| `assets/ai-provider.js` | Testable OpenAI and Anthropic browser adapters |
| `assets/app.css` | Responsive visual design |
| `data/opportunities.js` | Generated catalog, facets, and BM25 index |
| `data/opportunity_enrichment.json` | Compact official-detail cache for incremental refresh |
| `scripts/build_catalog.py` | Complete XML ingestion, normalization, validation, and index build |
| `scripts/enrich_catalog.py` | Official detail enrichment, evidence reconciliation, and FOA selection |
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
| July 2026 | Present search and AI matching as equal entry points; keep chat visible before the result list on mobile. |
| July 2026 | Reject past forecast deadlines and stale undated forecasts instead of treating every unarchived forecast as current. |
| July 2026 | Remove saved-search, embedding-cache, API-key, and research-text use of browser storage. |
| July 2026 | Treat Duke as a search/discovery design reference, not a data source. |
| July 2026 | Add a Phase 1.5 evidence layer before pilot work: incremental official detail enrichment, one-click source actions, and strict funding/deadline semantics. |
| July 2026 | Treat the Albany study as evidence that exact-keyword recommendations require researcher feedback and separate retrieval/reranking evaluation. |
| July 2026 | Make pilot validation and separate retrieval/reranking measurement the next implementation phase before expanding sources. |

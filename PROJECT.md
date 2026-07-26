# Funding Finder — Product Plan

**Status:** Phase 1 product correction implemented; production deployment verification pending

**Next implementation phase:** Phase 2 — Pilot validation and relevance quality

**Canonical application:** https://mporosoff.github.io/grants-scraper/

**Repository:** https://github.com/mporosoff/grants-scraper

**Initial audience:** University of Rochester researchers, with a design that remains useful to any public user

**Last updated:** July 25, 2026

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
- derives transparent discipline, topic, and warning facets;
- builds a compact BM25 keyword index; and
- publishes one versioned browser asset.

The July 26 build contains 1,465 open or current forecasted federal opportunities rather than the former 48-record engineering shortlist. It contains no record with a deadline before the catalog date. Sources outside Grants.gov will be added independently when they have a sustainable public ingestion path.

### 2.3 Search is the primary workflow

Anyone can use, without an API key:

- full-text keyword and opportunity-number search;
- open and forecasted status filters;
- discipline, topic, agency, eligibility, and funding-instrument facets;
- deadline and minimum-award filters;
- preliminary-stage, limited-submission, early-career, and cost-share signals;
- relevance, deadline, posted-date, award, agency, and title sorting;
- pagination and expandable record details;
- official source links; and
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
5. Open the official record or export the result set.

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

**Status: product correction implemented; production deployment verification pending**

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

**Exit criterion:** merge the correction, observe one successful scheduled production refresh, confirm Pages loads a catalog with zero past deadlines, and smoke-test desktop/mobile search, filters, export, one refinement, and chat with both ordinary and AI-refined results.

---

## 7. Roadmap

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

### Phase 3 — Better source evidence

- Track amendment, superseded, archive, and recurring-program status more precisely.
- Normalize LOI, concept-paper, preproposal, and full-proposal deadlines separately.
- Preserve deadline time and timezone when supplied.
- Extract high-value NOFO facts during the scheduled workflow.
- Attach provenance and confidence to machine-extracted fields.
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

## 8. Product quality rules

- A user can always search the full catalog without AI.
- Record-count checks should fail closed rather than silently publish a tiny feed.
- Expired records must not be revived by incidental language such as “rolling assessment.”
- Undated recurring records must visibly ask the user to verify current status.
- Missing facts remain missing; neither deterministic rules nor AI may fabricate them.
- AI only receives a bounded candidate set and is never the retrieval database.
- Every result retains an official source link.
- API keys never enter source control, URLs, exports, or browser storage.
- The application remains usable on current mobile and desktop browsers.
- Every added source has an identified maintenance strategy.

---

## 9. Explicit non-goals

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

## 10. Project files

| Path | Purpose |
|---|---|
| `index.html` | GitHub Pages entry point |
| `match_explorer.html` | Public search and refinement interface |
| `assets/app.js` | Browser search, filters, export, AI matching, and chat with results |
| `assets/app.css` | Responsive visual design |
| `data/opportunities.js` | Generated catalog, facets, and BM25 index |
| `scripts/build_catalog.py` | Complete XML ingestion, normalization, validation, and index build |
| `scripts/pull_grants.py` | Earlier API normalizer retained for fixtures and reference |
| `tests/` | Pipeline and public-application regression checks |
| `.github/workflows/refresh-opportunities.yml` | Daily catalog refresh and owner alert |
| `docs/HOSTING.md` | Deployment, privacy, and data boundary |
| `web/` | Retained server experiment; not the canonical product |

---

## 11. Decision log

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
| July 2026 | Make pilot validation and separate retrieval/reranking measurement the next implementation phase before expanding sources. |

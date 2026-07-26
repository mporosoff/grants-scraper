# GitHub Pages hosting and data boundary

## Decision

`mporosoff/grants-scraper` is the source of truth, and GitHub Pages is the only active product surface:

https://mporosoff.github.io/grants-scraper/

The application is public and browser-only. Users do not install Python, create an account, choose a faculty record, upload grant files, or provide an API key merely to search.

## Architecture

```text
Official Grants.gov daily XML extract
                |
                | scheduled GitHub Action
                v
Normalized catalog + facets + BM25 search index
                |
                | official detail API for new/changed records
                v
Deadline/award evidence + direct source actions
                |
                v
          GitHub Pages
          /      |      \
         v       v       v
Local catalog  Device-  Optional OpenAI or Anthropic request
and profile    local    using a key held in page memory
ranking        profile
```

The generated public asset is `data/opportunities.js`. It contains open posted
and current forecasted records, facet counts, evidence fields, official source
actions, and the term postings needed for local BM25 search. Records with past
posted or estimated forecast deadlines are rejected, and undated forecasts
must pass fiscal-year and recency checks.

`data/opportunity_enrichment.json` is a versioned compact cache of selected
facts from the unauthenticated official `fetchOpportunity` endpoint. The
workflow fetches only new or changed records, prunes removed identifiers,
paces requests, and caps updates per run. It does not store source PDFs.

## Cost boundary

Keyword search, profile ranking, filtering, sorting, pagination, detail
expansion, CSV export, CV parsing, and Phase 2 labeling execute locally and
make zero AI calls.

AI refinement is explicit and bounded:

- one call translates a research description into retrieval terms;
- local search selects at most 32 candidates;
- one call reranks those candidates into at most 12 matches; and
- later chat calls receive at most the top 20 ordinary results or the current 12-record AI shortlist plus recent conversation.

This avoids sending the full catalog to a model and avoids model cost for ordinary browsing.

## Public repository and site

The following are intentionally public:

- application source and documentation;
- normalized public funding records;
- deterministic topic, discipline, and warning signals;
- official source links;
- the generated search index; and
- automation logs that contain no credentials or private research text.

The repository must not contain:

- provider API keys;
- private or unpublished research descriptions;
- user chat history;
- exported user result files;
- exported pilot-evaluation files;
- raw daily XML archives; or
- unnecessary bulk source documents.

## Device-local and page-memory information

When the user leaves “remember” enabled, one browser-local profile record
contains the research description, expertise keywords, applicant/career
context, extracted CV text, and search preferences. Extracted CV text is
bounded to 120,000 characters. The original CV file is not retained. A
separate browser-local record contains Phase 2 labels and reason codes.

Both records are device-specific, removable from the interface, and never
sent to GitHub or a central database. They are a convenience and evaluation
boundary, not an institutional credential vault or a local copy of the
funding catalog. Shared search URLs take precedence over saved profile
ranking until the user activates it.

The API key, AI shortlist, and chat exist only in page memory. Reloading or
closing the tab removes them. They are never written to `localStorage`,
`sessionStorage`, cookies, a URL, exports, GitHub, or a central database.

When AI is invoked, the browser sends enabled profile context, at most 12,000
characters of extracted CV text, and a bounded set of public opportunity text
directly to the selected provider. The provider’s billing, privacy, and
retention terms apply. Users should use scoped keys with spending limits and
should not enter confidential research.

The explicit Phase 2 export excludes profile text, CV text, API keys, and chat
by default. It contains a non-content comparison fingerprint, catalog version,
filters, public opportunity metadata, retrieval/AI ranks, provider/model, and
reason codes.

## Opportunity refresh

`.github/workflows/refresh-opportunities.yml` runs daily:

1. Run regression tests against the application and last successful catalog.
2. Discover and download the latest official Grants.gov enhanced XML extract.
3. Stream, normalize, deduplicate, reject past deadlines, and remove stale undated forecasts.
4. Build facet counts and the compact BM25 search index.
5. Enrich new or changed records with official detail evidence and reconcile
   deadlines, awards, announcement attachments, and agency links.
6. Fail if record counts, identities, or required fields are implausible.
7. Retest the newly generated browser assets.
8. Commit a changed catalog and cache to the default branch for GitHub Pages.
9. Open or update one owner-alert issue if the refresh fails.

The last successful catalog remains available after a failure, and the page visibly warns when its generated timestamp is stale.

## Deployment verification

Phase 1 and Phase 1.5 release verification covers:

- observe one successful scheduled refresh;
- confirm the generated commit triggers GitHub Pages;
- confirm the page reports roughly the expected open and forecasted counts;
- search a known phrase and opportunity number;
- verify typed search text has readable contrast;
- verify AI matching and “Chat with results” appear before the result list on mobile;
- upload a TXT CV, activate profile ranking, reload, and confirm that the
  profile/CV extract/preferences return while the API key does not;
- confirm PDF.js and Mammoth are served locally and profile search makes no
  network request;
- label a result, select a reason, reload, and export a privacy-safe Phase 2
  evaluation file;
- run `scripts/evaluate_phase2.py` against the versioned synthetic fixture;
- exercise at least two facets and each sort mode;
- export a multi-record CSV;
- verify direct-FOA, agency-notice, and Grants.gov fallback actions;
- verify program-total funding does not affect per-award filtering or sorting;
- run the deterministic OpenAI and Anthropic adapter contract tests; and
- exercise refinement, ordinary-results chat, and a narrowing follow-up with
  bounded mock provider responses.

Paid-provider smoke tests are useful before changing a model or prompt, but
they are not the only way to verify the browser workflow.

## Deliberate limitations

Without a service layer, the application does not provide:

- saved searches or watchlists across devices;
- personalized automatic alerts or email;
- institutional AI credential management;
- central usage budgets;
- shared evaluation data;
- private access control; or
- administrative review workflows.

Those capabilities require an explicit service-backed architecture and are deferred until the public catalog and refinement workflow demonstrate value.

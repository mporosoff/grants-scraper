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
                v
          GitHub Pages
          /          \
         v            v
Local browser       Optional OpenAI or Anthropic request
search/filter       using a key held in page memory
```

The generated public asset is `data/opportunities.js`. It contains current posted and forecasted records, facet counts, and the term postings needed for local BM25 search.

## Cost boundary

Keyword search, filtering, sorting, pagination, detail expansion, and CSV export execute locally and make zero AI calls.

AI refinement is explicit and bounded:

- one call translates a research description into retrieval terms;
- local search selects at most 32 candidates;
- one call reranks those candidates into at most 12 matches; and
- later chat calls receive only the current shortlist and recent conversation.

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
- raw daily XML archives; or
- unnecessary bulk source documents.

## Page-memory information

The provider selection, API key, research description, AI shortlist, and chat exist only in the running page. The application does not write them to `localStorage`, `sessionStorage`, cookies, GitHub, or a central database.

Reloading or closing the tab removes this state. This is intentional: browser storage is neither a useful shared search backend nor a secure credential vault.

When AI is invoked, the browser sends the research description and a bounded set of public opportunity text directly to the selected provider. The provider’s billing, privacy, and retention terms apply. Users should use scoped keys with spending limits and should not enter confidential research.

## Opportunity refresh

`.github/workflows/refresh-opportunities.yml` runs daily:

1. Run regression tests against the application and last successful catalog.
2. Discover and download the latest official Grants.gov enhanced XML extract.
3. Stream, normalize, deduplicate, and filter current records.
4. Build facet counts and the compact BM25 search index.
5. Fail if record counts, identities, or required fields are implausible.
6. Retest the newly generated browser asset.
7. Commit a changed catalog to the default branch for GitHub Pages.
8. Open or update one owner-alert issue if the refresh fails.

The last successful catalog remains available after a failure, and the page visibly warns when its generated timestamp is stale.

## Deployment verification

Before declaring Phase 1 complete in production:

- observe one successful scheduled refresh;
- confirm the generated commit triggers GitHub Pages;
- confirm the page reports roughly the expected open and forecasted counts;
- search a known phrase and opportunity number;
- exercise at least two facets and each sort mode;
- export a multi-record CSV;
- verify an official link;
- run one OpenAI or Anthropic refinement with a scoped test key; and
- ask one narrowing follow-up question.

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

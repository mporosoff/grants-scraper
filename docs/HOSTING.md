# GitHub Pages hosting and data boundary

## Decision

`mporosoff/grants-scraper` is the source of truth, and GitHub Pages is the only active product surface:

https://mporosoff.github.io/grants-scraper/

The public interface is a static browser application backed by narrowly bounded Cloudflare services. Users do not install Python, create an account, choose a faculty record, upload a file, or provide an API key merely to search. A NOFO/FOA PDF upload is an optional page-memory path for document chat.

Team Match is also a public, self-canonical product route and is intentionally
indexable. Its metadata uses researcher/team language so it does not imply that
the tool is limited to faculty records.

Funded Awards is the third public, self-canonical route. It uses the same static
application shell and current-opportunity catalog, while a bounded Cloudflare
Worker normalizes public NSF Awards and NIH RePORTER responses. The Worker has
no source credential or durable user/account history; only successful
per-source responses enter its one-hour public cache.

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
                | bounded official PDF/HTML retrieval
                v
Cited facts + document hash/version + review queue
                |
                | validated NSF/NYSERDA adapters + source lifecycle
                v
Current cross-source catalog + last-known-good snapshots
                |
                v
          GitHub Pages
          /         |         \
         v          v          v
Local catalog   Device-local   Optional hosted AI request through
and cited       profile,      the protected Funding Finder gateway;
facts           optional      personal provider keys remain an
ranking         provider keys, advanced alternative
                and review
                    |
                    v
          Explicit file share/download/email
                    |
                    v
       Private gitignored inbox and reports
```

The generated public asset is `data/opportunities.js`. It contains open posted
and current forecasted records, facet counts, evidence fields, official source
actions, and the term postings needed for local hybrid search. The browser uses
those postings for BM25 relevance, typo-tolerant term resolution, term-coverage
checks, and catalog-derived topic similarity; query terms do not need to be
pre-enumerated. Records with past posted or estimated forecast deadlines are
rejected, and undated forecasts must pass fiscal-year and recency checks.

`data/opportunity_enrichment.json` is a versioned compact cache of selected
facts from the unauthenticated official `fetchOpportunity` endpoint. The
workflow fetches only new or changed records, prunes removed identifiers,
paces requests, and caps updates per run. It does not store source PDFs.

`data/document_evidence.json` is the Phase 3 cache. The workflow retrieves at
most 45 new, changed, or recheck-due official sources per run. It stores HTTP
validators, SHA-256, current/prior version summaries, short evidence quotes,
page/section citations, deterministic extracted facts, and a human-review
queue. Primary notices are revalidated after 14 days and lower-priority agency
pages after 30 days; new and changed sources are processed before routine
rechecks. Raw PDFs/HTML and full extracted text exist only in the job's memory and
are discarded. Cached records that disappear from the current catalog are
marked rather than silently erased so change history remains inspectable.

`data/source_records.json` is the committed last-known-good cache for enabled
non-Grants.gov adapters. NSF upcoming due dates and NYSERDA are enabled.
NYSERDA selects the next open round and preserves later application and
concept-paper dates. UR InfoReady is an intentionally disabled shell pending a
stable, permissioned ingestion route; no portal credential is embedded.
Healthy refreshes atomically replace that source's snapshot. Failed or
implausible refreshes retain only still-current cached records, exit nonzero
for monitoring, and open or update an owner-facing GitHub issue.

## Cost boundary

Strong keyword search, profile ranking, filtering, sorting, pagination, detail
expansion, citation display, CSV/review export, CV/NOFO parsing, catalog
matching, and local labeling execute locally. For a submitted non-empty query,
the site-managed enhanced-search Worker may obtain one query embedding and
rerank bounded public opportunity passages to produce Potential matches. It
receives the search text and public passages, not CV/profile text, researcher
names, or ORCID publication text.

Hosted AI use is explicit and bounded:

- one call translates a research description into retrieval terms;
- local search selects at most 32 candidates;
- one call reranks those candidates into at most 12 matches; and
- result-chat calls receive at most the top 10 active ordinary or AI-refined
  results plus at most 12,000 characters of recent conversation; and
- uploaded-notice chat calls receive a page-marked extract capped at 120,000
  characters, optional matched public catalog metadata, and at most 12,000
  characters of recent conversation.

The hosted AI gateway rejects fields outside each operation's bounded input
contract. In addition to per-minute client and global request limits, an atomic
daily coordinator applies weighted per-client and global ceilings before any
provider call. The gateway fails closed when the enable switch, limit
configuration, rate-limit bindings, daily coordinator, or required provider
bindings are unavailable.

Neither hosted Potential matching nor hosted AI sends the full catalog.
Blank-query browsing, local Strong matching, and filters have no model cost.
Funded Awards does not call an embedding or reranking provider. Standalone
research-topic searches use the agencies' native title/abstract criteria, and
current-opportunity links use exact source identifiers or committed NSF parent
program groups.

## Public repository and site

The following are intentionally public:

- application source and documentation;
- normalized public funding records;
- deterministic topic, discipline, and warning signals;
- official source links;
- compact document hashes, versions, quotes, extracted facts, citations, and
  review-queue signals;
- the generated search index; and
- automation logs that contain no credentials or private research text.

The repository must not contain:

- provider API keys;
- private or unpublished research descriptions;
- user chat history;
- exported user result files;
- exported pilot-evaluation files;
- returned Phase 3 deployment-review files and reports;
- raw daily XML archives; or
- raw official notices or full extracted notice text; or
- unnecessary bulk source documents.

## Device-local and page-memory information

When the user explicitly saves a profile, one browser-local profile record
contains the research description, expertise keywords, applicant/career
context, extracted CV text, and search preferences. Extracted CV text is
bounded to 120,000 characters. The original CV file is not retained. A
separate browser-local record contains Phase 2 labels and reason codes, a
third compact record stores saved-opportunity snapshots, and a fourth stores
only the personalization on/off choice. After three graded
ratings, the user may explicitly enable a deterministic device-local
preference model for Relevance sorting; it can be disabled or cleared at any
time and makes no network request.

All device-local records are removable from the interface and never
sent to GitHub or a central database. They are a convenience and evaluation
boundary, not an institutional credential vault or a local copy of the
funding catalog. Shared search URLs take precedence over saved profile and
preference ranking until the user activates them.

Search criteria are serialized into the Funding Finder page URL so browser
back/forward navigation, refresh, and copied links can restore a search. Those
criteria can therefore appear in browser history and in any shared URL. A
custom anonymous usage request contains only a random session identifier and a
broad usage category; it explicitly uses an origin-only referrer, and the
Worker resolves network organization server-side for aggregate reporting.
Cloudflare Web Analytics is loaded only on clean URLs. Funding Finder disables
that route whenever query parameters are present, so managed search criteria
are not included in analytics requests.

Funded Awards search criteria and selected current-opportunity identifiers are
also serialized into its URL. A browser-local default institution is applied
only on that device and enters a shared URL when it is part of a search.

The AI shortlist, chat, and any extracted uploaded-notice text exist only in
page memory. The original uploaded PDF is not retained. Its bounded extracted
text is sent through the protected Funding Finder AI gateway only after the
user asks a notice question. The gateway accepts only six fixed operations,
owns their prompts and response schemas, routes the evaluated models by
feature, validates output, rate-limits callers, and does not log or store
prompts or responses. An optional personal API key is tab-only by default. The
user may explicitly save one key per provider in a
separate `funding-finder.credentials.v1` local-storage record; the interface
shows whether the key is entered, saved, loaded, or removed. A saved key is
available to anyone using that browser profile, so it should not be used on a
shared device. Keys are never placed in the profile, evaluation/review records,
`sessionStorage`, cookies, URLs, exports, GitHub, or a central database.

When hosted AI is invoked, the browser sends enabled profile context, at most
12,000 characters of extracted CV text, and a bounded set of public opportunity
text to the gateway. The gateway sends that bounded operation to its selected
provider with storage disabled where supported. Users should not enter
confidential research. If a user explicitly selects a personal provider, that
provider's billing, privacy, and retention terms apply.

The explicit Phase 2 export excludes profile text, CV text, API keys, and chat.
It includes the current search text, a non-content comparison fingerprint,
catalog version, filters, public opportunity metadata, retrieval/AI ranks,
provider/model, ratings, and reason codes. Pilot instructions tell participants
to use only non-confidential search wording they are comfortable returning.

A separate Phase 3 local record contains explicit source verdicts, the field
checked, optional reviewer notes, deployment checklist answers, coarse
viewport/capability data, and aggregate action counts. No event is sent
automatically. The Phase 3 handoff excludes API keys, profile/CV text, search
text, Funding Finder search URL/parameters, and chat. On compatible mobile browsers it is shared as
an attached JSON file through the native share sheet. The desktop fallback
downloads the file and opens an addressed email. The owner stores returned
files under gitignored `evaluation/inbox/` and generates private reports under
gitignored `evaluation/reports/`.

## Opportunity refresh

`.github/workflows/refresh-opportunities.yml` runs daily, on manual dispatch,
and once when ingestion/evidence pipeline code reaches `main`:

1. Run regression tests against the application and last successful catalog.
2. Discover and download the latest official Grants.gov enhanced XML extract.
3. Stream, normalize, deduplicate, reject past deadlines, and remove stale undated forecasts.
4. Build facet counts and the compact BM25 search index.
5. Enrich new or changed records with official detail evidence and reconcile
   deadlines, awards, announcement attachments, and agency links.
6. Retrieve and parse a bounded set of new, changed, or due official notices;
   merge only compact citation-backed evidence and rebuild the search index.
7. Refresh enabled external sources, atomically replace healthy source
   snapshots, retain still-current last-known-good records on degradation, and
   rebuild all facets and indexes.
8. Fail visibly if source or whole-catalog health is implausible while keeping
   safe published data available.
9. Generate public all/topic/source-type Atom feeds from the final catalog.
10. Retest the newly generated browser assets and privacy contracts.
11. Commit a changed catalog, public feeds, and compact caches to the default
    branch for GitHub Pages.
12. Open or update an owner-alert issue for whole-job or source-level
    degradation.

The last successful catalog remains available after a failure, and the page visibly warns when its generated timestamp is stale.

## Deployment verification

Award-service changes deploy only from a committed protected `main` revision.
The dedicated workflow verifies the Worker contract, captures the prior Worker
version, deploys, checks health, runs one exact NSF and NIH smoke, verifies the
committed Funded Awards page on GitHub Pages, and restores the prior Worker when
a post-deploy gate fails.

Phase 1 through Phase 3 release verification covers:

- observe one successful scheduled refresh;
- confirm the generated commit triggers GitHub Pages;
- confirm the page reports roughly the expected open and forecasted counts;
- search a known phrase and opportunity number;
- verify typed search text has readable contrast;
- verify the initial page contains no opportunity cards and that keywords,
  profile/CV context, and filters all feed the same “Find funding” action;
- verify “Chat with your results” appears with the result set on mobile;
- drag an OCR-readable NOFO PDF into the search box, verify the in-chat key
  prompt, page-marked extraction, and matched save/calendar/source card;
- repeat with a notice that has no catalog match and confirm document chat still
  opens while related search results remain available;
- upload a TXT CV, explicitly save the profile, reload, and confirm that the
  profile/CV extract/preferences return;
- save a fake provider key, reload, confirm the interface reports it loaded,
  remove it, and confirm the credential record is gone;
- confirm PDF.js and Mammoth are served locally and profile search makes no
  network request;
- label a result, select a reason, reload, and export a privacy-safe Phase 2
  evaluation file;
- rate three opportunities, enable local personalization, and verify Relevance
  sorting changes with a visible explanation and can be turned off;
- save and remove an opportunity, reload, and confirm the compact saved list
  remains device-local;
- run `scripts/evaluate_phase2.py` against the versioned synthetic fixture;
- exercise at least two facets and each sort mode;
- export a multi-record CSV;
- verify direct-FOA, agency-notice, and Grants.gov fallback actions;
- observe a successful bounded document-evidence batch and inspect its
  processed/queued/failure counts;
- verify one PDF citation lands on the listed page and one HTML citation opens
  the listed section/anchor;
- verify extracted deadlines, awards, and requirements are labeled
  machine-extracted and do not replace structured filtering values;
- simulate a changed document and confirm version increment plus amendment
  review-queue behavior;
- mark one cited fact accurate/incorrect/unverifiable, reload, and confirm the
  source review returns without any automatic network submission;
- use “Ask AI about this FOA” with a mock response containing one valid and one
  invented evidence ID; render only the valid citation;
- send/download one Phase 3 review file, inspect its privacy boundary, place it
  in `evaluation/inbox/`, and run the private report aggregator;
- verify program-total funding does not affect per-award filtering or sorting;
- run the deterministic OpenAI and Anthropic adapter contract tests; and
- exercise refinement, ordinary-results chat, uploaded-NOFO chat, and a
  narrowing follow-up with bounded mock provider responses.

Paid-provider smoke tests are useful before changing a model or prompt, but
they are not the only way to verify the browser workflow.

## Deliberate limitations

Without an account and notification service layer, the application does not provide:

- saved searches or watchlists across devices;
- self-service personalized email subscriptions in the public application;
- institutional AI credential management;
- shared evaluation data;
- automatic central telemetry or anonymous review submission;
- private access control; or
- administrative review workflows.

Public Atom feeds require no service and are deployed under `feeds/`. A
separate private-repository bundle under `docs/weekly-alerts/` can support a
small, manually consented weekly-email pilot, but it is not a public
subscription service. Cross-device accounts, an in-page signup flow,
double-opt-in, automated unsubscribe, bounce handling, and central preference
management still require an explicit service-backed architecture.

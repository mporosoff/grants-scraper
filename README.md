# Funding Finder

A public funding-opportunity search engine with optional AI refinement.

Open the application:

https://mporosoff.github.io/grants-scraper/

## What it does

Anyone can search the comprehensive catalog without an account or API key. The browser provides:

- full-text search across current Grants.gov opportunities;
- one-click browsing of the complete current catalog without search terms;
- filters for status, discipline, topic, agency, eligibility, instrument,
  deadline, award size, cited-FOA availability, and special requirements;
- relevance and field-based sorting;
- one-click official FOA, agency-notice, or Grants.gov record actions;
- expandable page/section-cited FOA evidence, pagination, and CSV export; and
- visible catalog source, size, generated time, and freshness; and
- automatic dark-mode and Windows high-contrast support.

The page initially shows no opportunities. One guided workflow combines a
topic, optional profile/CV context, and optional filters under a single “Find
funding” action. Users can explicitly save a reusable researcher profile on
that device; saving it does not launch a competing search. Profile relevance
uses the local BM25 index and makes zero AI calls.

Ordinary and profile-ranked search make zero AI calls. A user may enter an
OpenAI or Anthropic key to:

1. expand the search with useful synonyms;
2. rerank at most 32 retrieved candidates into a shortlist of at most 12; and
3. ask grounded follow-up questions that can further narrow the shortlist.

“Ask about these results” appears with the returned result set and can answer
questions over the top 20 ordinary search results without requiring a prior AI
rerank. It uses the same responsive result workflow on desktop and mobile.

When the scheduled Phase 3 pipeline has analyzed an official notice, the
result card shows document version/change status and compact cited facts for
submission stages, funding, duration, page limits, cost share,
eligibility/review excerpts, and application components. Each fact opens the
exact PDF page or HTML section. “Ask AI about this FOA” focuses chat on a
single result; AI may cite only evidence identifiers that the browser supplied.

The original CV file is never retained. A bounded CV excerpt is sent only when
the user enables that option and explicitly runs AI refinement or chat. An API
key is tab-only unless the user explicitly saves it on that device. Saved keys
are isolated from profiles and reviewer data, have a visible saved/loaded
status and removal control, and never enter GitHub, URLs, exports, or an
application database. The shortlist and chat remain page-memory only.

Match-quality controls include `useful`, `not relevant`, and `needs
verification` labels with reason codes. The explicit evaluation export omits
API keys, profile text, CV text, and chat, and
`scripts/evaluate_phase2.py` measures retrieval recall separately from AI
reranking precision. Reviewers can switch from the 12-result shortlist to the
pre-reranking candidate set when labeling. The 3–5 researcher pilot is
deliberately deferred until the Phase 3 deployment batch and review handoff are
verified.

Invited testers can open the collapsed “Help improve Funding Finder” area to
mark cited evidence accurate, incorrect, or unverifiable, check
the field they inspected, and add a short non-confidential note. This progress
autosaves only on that device. “Send review” uses the native file share sheet
where available; otherwise it downloads a privacy-safe JSON file and opens an
addressed email to the project owner. Returned files can be aggregated into
private Markdown, JSON, and CSV reports.

## Data model

The daily workflow processes the official [Grants.gov XML database extract](https://www.grants.gov/xml-extract). It publishes open posted and current forecasted records plus a compact BM25 search index to `data/opportunities.js`. Past deadlines are rejected for both statuses, and stale undated forecasts are excluded.

An incremental second step enriches only new or changed records through the
official Grants.gov `fetchOpportunity` detail API. It reconciles structured
deadline and award evidence, preserves supplied deadline time/timezone, and
selects a direct announcement only when the attachment evidence is defensible.
When Grants.gov drops spacing from an NSF synopsis, the same step replaces
only that damaged prose with the synopsis from the linked official NSF funding
page and rebuilds the search index. Successful NSF text is cached for 14 days;
an unparseable agency page leaves the Grants.gov text unchanged.
Its compact cache is `data/opportunity_enrichment.json`.

A bounded third step retrieves selected official PDF or HTML notices. It uses
document hashes and HTTP validators to detect changes and avoid unnecessary
downloads, extracts readable text ephemerally, and publishes only short cited
facts and a human-review queue. Raw notices and full extracted text are never
committed. Machine-extracted dates and amounts do not replace structured
Grants.gov fields used by filters or sorting. Its compact cache is
`data/document_evidence.json`.

<!-- catalog-stats:start -->
This replaces the former 48-record Chemical and Sustainability Engineering feed. The
July 26, 2026 build contains 1,465 current federal opportunities (1,224 posted and 241
forecasted) with no deadline before the catalog date. It provides a direct official
announcement for 447 records, an agency-notice route for another 615, and the official
Grants.gov record for the remaining 403. Across all route types, 774 records also
contain an agency notice URL.
<!-- catalog-stats:end -->

Funding values are intentionally not conflated: award floor/ceiling drive
per-award display and filtering, while total program funding is a separate
fact. Missing evidence remains “not listed” until an official source can
support it.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Redirects GitHub Pages to the application |
| `match_explorer.html` | Public search and AI-refinement interface |
| `assets/app.js` | Search, cited source evidence, review/export, profile ranking, AI matching, and chat |
| `assets/profile.js` | Local profile/feedback storage and CV extraction |
| `assets/review.js` | Local Phase 3 deployment-review storage and privacy-safe handoff |
| `assets/credentials.js` | Explicit device-local provider-key save/load/clear boundary |
| `assets/ai-provider.js` | OpenAI and Anthropic request adapters |
| `assets/app.css` | Responsive application styles |
| `assets/vendor/` | Vendored PDF.js and Mammoth parsers and license notices |
| `data/opportunities.js` | Generated catalog and search index |
| `data/opportunity_enrichment.json` | Incremental official-detail cache |
| `data/document_evidence.json` | Incremental document hash/version, cited-fact, and review-queue cache |
| `scripts/build_catalog.py` | Official XML ingestion and catalog builder |
| `scripts/enrich_catalog.py` | Official detail reconciliation and FOA selection |
| `scripts/extract_document_evidence.py` | Official PDF/HTML retrieval, versioning, deterministic fact extraction, and citations |
| `scripts/evaluate_phase2.py` | Phase 2 retrieval/reranking evaluator |
| `scripts/summarize_phase3_reviews.py` | Private Phase 3 deployment-review aggregator |
| `evaluation/README.md` | Pilot export, privacy, and aggregation workflow |
| `evaluation/PHASE3_REVIEW.md` | Deployment-review storage, return, and reporting procedure |
| `PROJECT.md` | Product decisions, architecture, and roadmap |
| `tests/` | Pipeline and public-page regression checks |
| `docs/HOSTING.md` | Deployment and privacy boundary |

## Development

Install the small Python dependency set and run the regression suite:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Build from an existing official extract:

```powershell
python -m scripts.build_catalog --archive GrantsDBExtractYYYYMMDDv2.zip
```

Or discover and download the latest official extract:

```powershell
python -m scripts.build_catalog
```

Then enrich new or changed records:

```powershell
python -m scripts.enrich_catalog --catalog data/opportunities.js --cache data/opportunity_enrichment.json --max-updates 250
```

Then process a bounded set of new, changed, or due official notices:

```powershell
python -m scripts.extract_document_evidence --catalog data/opportunities.js --cache data/document_evidence.json --max-documents 45
```

To summarize review files returned to the project owner:

```powershell
python -m scripts.summarize_phase3_reviews evaluation/inbox --output-dir evaluation/reports
```

The scheduled workflow runs all three data steps daily, validates a plausible
catalog size, retests the generated assets, and commits the normalized browser
catalog plus compact caches. Raw XML archives, raw notices, full extracted
notice text, and returned review files are not committed.

See `PROJECT.md` for the completed Phase 1/1.5 scope, deferred Phase 2 pilot,
and Phase 3 implementation,
and `docs/HOSTING.md` for the deployment boundary.

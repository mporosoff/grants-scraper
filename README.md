# Funding Finder

A public funding-opportunity search engine with optional AI refinement.

Open the application:

https://mporosoff.github.io/grants-scraper/

## What it does

Anyone can search the comprehensive catalog without an account or API key. The browser provides:

- full-text search across current Grants.gov opportunities;
- filters for status, discipline, topic, agency, eligibility, instrument, deadline, award size, and special requirements;
- relevance and field-based sorting;
- one-click official FOA, agency-notice, or Grants.gov record actions;
- expandable evidence details, pagination, and CSV export; and
- visible catalog source, size, generated time, and freshness.

Users can also build a reusable researcher profile from a research
description, expertise keywords, applicant/career context, and an optional
PDF, DOCX, TXT, or Markdown CV. “Search with my profile” uses the local BM25
index and makes zero AI calls. When remembering is enabled, the profile,
bounded extracted CV text, filters, sort, and Phase 2 relevance labels are
saved only on that device.

Ordinary and profile-ranked search make zero AI calls. A user may enter an
OpenAI or Anthropic key to:

1. expand the search with useful synonyms;
2. rerank at most 32 retrieved candidates into a shortlist of at most 12; and
3. ask grounded follow-up questions that can further narrow the shortlist.

The always-visible “Chat with results” panel can also answer questions over the top 20 ordinary search results without requiring a prior AI rerank. On mobile, AI matching and chat appear before the filters and result list.

The original CV file is never retained. A bounded CV excerpt is sent only when
the user enables that option and explicitly runs AI matching or chat. The API
key, shortlist, and chat stay in page memory only; they are never written to
local storage, session storage, GitHub, URLs, exports, or an application
database.

Phase 2 result cards include `useful`, `not relevant`, and `needs
verification` labels with reason codes. The explicit evaluation export omits
API keys, profile text, CV text, and chat, and
`scripts/evaluate_phase2.py` measures retrieval recall separately from AI
reranking precision. Reviewers can switch from the 12-result shortlist to the
pre-reranking candidate set when labeling. The software is pilot-ready; the
3–5 researcher pilot is the remaining Phase 2 exit criterion.

## Data model

The daily workflow processes the official [Grants.gov XML database extract](https://www.grants.gov/xml-extract). It publishes open posted and current forecasted records plus a compact BM25 search index to `data/opportunities.js`. Past deadlines are rejected for both statuses, and stale undated forecasts are excluded.

An incremental second step enriches only new or changed records through the
official Grants.gov `fetchOpportunity` detail API. It reconciles structured
deadline and award evidence, preserves supplied deadline time/timezone, and
selects a direct announcement only when the attachment evidence is defensible.
Its compact cache is `data/opportunity_enrichment.json`.

This replaces the former 48-record Chemical and Sustainability Engineering
feed. The July 26 build contains 1,465 federal opportunities with no deadline
before the catalog date. It provides a direct official announcement for 447
records, an agency-notice route for another 615, and the official Grants.gov
record for the remaining 403.

Funding values are intentionally not conflated: award floor/ceiling drive
per-award display and filtering, while total program funding is a separate
fact. Missing evidence remains “not listed” until an official source can
support it.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Redirects GitHub Pages to the application |
| `match_explorer.html` | Public search and AI-refinement interface |
| `assets/app.js` | Search, profile ranking, feedback, export, AI matching, and chat |
| `assets/profile.js` | Local profile/feedback storage and CV extraction |
| `assets/ai-provider.js` | OpenAI and Anthropic request adapters |
| `assets/app.css` | Responsive application styles |
| `assets/vendor/` | Vendored PDF.js and Mammoth parsers and license notices |
| `data/opportunities.js` | Generated catalog and search index |
| `data/opportunity_enrichment.json` | Incremental official-detail cache |
| `scripts/build_catalog.py` | Official XML ingestion and catalog builder |
| `scripts/enrich_catalog.py` | Official detail reconciliation and FOA selection |
| `scripts/evaluate_phase2.py` | Phase 2 retrieval/reranking evaluator |
| `evaluation/README.md` | Pilot export, privacy, and aggregation workflow |
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

The scheduled workflow runs both steps daily, validates a plausible catalog
size, retests the generated assets, and commits the normalized browser catalog
and compact enrichment cache. Raw XML archives are not committed.

See `PROJECT.md` for the completed Phase 1/1.5 scope and Phase 2 implementation,
and `docs/HOSTING.md` for the deployment boundary.

# Funding Finder

A public funding-opportunity search engine with optional AI refinement.

Open the application:

https://mporosoff.github.io/grants-scraper/

## What it does

Anyone can search the comprehensive catalog without an account or API key. The browser provides:

- full-text search across current Grants.gov opportunities;
- filters for status, discipline, topic, agency, eligibility, instrument, deadline, award size, and special requirements;
- relevance and field-based sorting;
- expandable source details, pagination, and CSV export; and
- visible catalog source, size, generated time, and freshness.

Ordinary search makes zero AI calls. “Describe your research” is presented beside keyword search as a second, optional entry point. A user may enter an OpenAI or Anthropic key to:

1. expand the search with useful synonyms;
2. rerank at most 32 retrieved candidates into a shortlist of at most 12; and
3. ask grounded follow-up questions that can further narrow the shortlist.

The always-visible “Chat with results” panel can also answer questions over the top 20 ordinary search results without requiring a prior AI rerank. On mobile, AI matching and chat appear before the filters and result list.

The key, research description, shortlist, and chat stay in page memory only. They are not written to local storage, session storage, GitHub, or an application database, and they disappear when the page reloads.

## Data model

The daily workflow processes the official [Grants.gov XML database extract](https://www.grants.gov/xml-extract). It publishes open posted and current forecasted records plus a compact BM25 search index to `data/opportunities.js`. Past deadlines are rejected for both statuses, and stale undated forecasts are excluded.

This replaces the former 48-record Chemical and Sustainability Engineering feed. The July 26 build contains 1,465 federal opportunities with no deadline before the catalog date and is intended for broad public search.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Redirects GitHub Pages to the application |
| `match_explorer.html` | Public search and AI-refinement interface |
| `assets/app.js` | Search, facets, sorting, export, AI matching, and chat with results |
| `assets/app.css` | Responsive application styles |
| `data/opportunities.js` | Generated catalog and search index |
| `scripts/build_catalog.py` | Official XML ingestion and catalog builder |
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

The scheduled workflow runs the latter command daily, validates a plausible catalog size, retests the generated asset, and commits only the normalized browser catalog. Raw XML archives are not committed.

See `PROJECT.md` for the product plan and `docs/HOSTING.md` for the deployment boundary.

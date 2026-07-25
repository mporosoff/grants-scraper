# UR Grant Matcher

A public, faculty-first browser application for identifying funding
opportunities worth attention.

Open the application:

https://mporosoff.github.io/grants-scraper/

Faculty do not install Python or upload faculty/grant files. A user writes a
research description in their own words, chooses either OpenAI or Anthropic,
and supplies one key from that provider. The same provider runs both matching
stages.

## Current product model

- GitHub Pages is the canonical application.
- The application is public and has no accounts or central user database.
- The provider selection, API key, research text, named searches, result
  snapshots, and cached embeddings stay in that browser's local storage.
- Matching requests go directly from the browser to the selected AI provider.
- Results can be exported as CSV.
- The API key is not included in exports or committed to GitHub.

Local browser storage is convenient, not a secure credential vault. Use a
scoped key with a spending limit, avoid unpublished confidential research
details, and clear the key before leaving a shared device.

## What works now

- free-text faculty research descriptions;
- no faculty dropdowns or JSON-file workflows;
- one selectable AI provider and one locally saved key;
- two-stage matching with verdicts, scores, and visible rationales;
- browser-local named saved searches and result snapshots;
- result cards with funding, due dates, duration, expected awards,
  eligibility, submission warnings, and source links;
- CSV export; and
- mobile-friendly, installation-free use.

The current opportunity list is a small bundled calibration set. The next
milestone is an automatically refreshed Grants.gov feed published to GitHub
Pages by a scheduled GitHub Action.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Redirects GitHub Pages to the application |
| `match_explorer.html` | Canonical public application |
| `PROJECT.md` | Authoritative product decisions, privacy policy, and roadmap |
| `scripts/pull_grants.py` | Grants.gov ingestion and normalization |
| `tests/` | Static application and normalizer checks |
| `docs/` | Hosting and API validation notes |
| `legacy/scrape_faculty.py` | Retired faculty scraper |
| `web/` | Retained server-backed experiment; not the current product |

## Development

The public application is a standalone HTML file and requires no local server.
Developers can run the regression checks with:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The retained `web/` experiment has separate Node-based checks, but it is not
deployed as the canonical application.

See `PROJECT.md` for the complete plan and `docs/HOSTING.md` for the GitHub
Pages data and privacy boundary.

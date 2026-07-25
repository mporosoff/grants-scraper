# UR Grant Matcher

A faculty-first web application for finding funding opportunities worth
attention. Faculty describe their research in their own words, the application
maintains a shared Grants.gov opportunity feed, and every recommendation shows
the concrete reason it matched.

Source repository: <https://github.com/mporosoff/grants-scraper>

Faculty use a hosted URL. They do not install Python, clone the repository, or
handle model API keys.

Public browser demos:

- GitHub Pages Match Explorer: <https://mporosoff.github.io/grants-scraper/>
- hosted faculty application: <https://ur-grant-matcher.zing78.chatgpt.site/>

## What works now

- faculty-authored, editable research profiles
- durable profile, opportunity, and feedback storage
- live Grants.gov refresh for up to five research topics
- import of normalized `grants.json` from the Python ingestion pipeline
- ranked results with verdicts, visible rationale, eligibility warnings,
  deadlines, award ceilings, and source links
- useful/not-relevant feedback stored per faculty member
- filtered CSV export for follow-up and sharing
- a responsive, double-click-free web interface

The current matcher is deliberately labeled as a transparent lexical
baseline. It is useful for testing the complete workflow, but the next quality
upgrade is a server-side semantic retrieval and reranking stage evaluated
against faculty feedback.

The standalone match explorer supports bring-your-own-key experiments. A user
chooses either OpenAI or Anthropic and supplies one key; that same provider runs
both the shortlist and the deeper scoring pass. The hosted faculty application
does not expose shared production keys in its browser UI.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | GitHub Pages entry point for the Match Explorer |
| `web/` | Hosted application, APIs, database schema, migrations, and UI |
| `scripts/pull_grants.py` | Standalone Grants.gov ingestion and normalization tool |
| `match_explorer.html` | Standalone prototype with one selectable AI provider and one key |
| `legacy/scrape_faculty.py` | Retired faculty scraper |
| `docs/` | API validation and hosting decisions |

## Local development

Local setup is only for developers. Faculty use the hosted application.

```powershell
cd web
pnpm install
pnpm dev
```

Run the complete web build check:

```powershell
cd web
pnpm test
```

The bounded Python ingestion smoke test is still available when working on the
normalizer:

```powershell
python -m pip install -r requirements.txt
python scripts/pull_grants.py --search-term catalysis --max-opportunities 3
```

See `PROJECT.md` for product rationale and roadmap, `docs/HOSTING.md` for the
deployment boundary, and `docs/API_VALIDATION.md` for live Grants.gov findings.

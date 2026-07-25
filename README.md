# UR ChemE Grant Matcher

Early prototype of a grant recommendation system for the University of
Rochester Department of Chemical and Sustainability Engineering.

Source repository: <https://github.com/mporosoff/grants-scraper>

The product is intended to be a hosted web application. Faculty will open a
URL, enter and maintain their own research synopsis and general profile
information, and receive ranked funding recommendations with a visible reason
for every match. Faculty will not need to install Python or run scripts.

## Current state

Only the first data-ingestion prototype exists:

- `scripts/pull_grants.py` searches Grants.gov, fetches full opportunity
  details, and normalizes them into a screening-oriented JSON schema. Posted
  and forecasted records have been smoke-tested against the live API.
- `legacy/scrape_faculty.py` is the original faculty scraper. It is retained
  for reference but is no longer part of the planned product.
- No web application, database, matching engine, scheduler, or generated data
  exists yet.

## Faculty profile direction

Faculty profiles will be created through a short web form. At minimum, each
profile should contain:

- name and email
- academic title and career stage
- research synopsis written in the faculty member's own words
- research topics and methods
- application areas
- optional exclusions or topics they do not want matched
- optional group website and researcher identifiers

Publication data from OpenAlex may later be offered as an optional enrichment
or suggestion source. It should not replace faculty control of the profile.

## Planned product flow

1. Faculty creates or edits a profile in the web application.
2. Scheduled jobs ingest and normalize funding opportunities.
3. The matching service retrieves and ranks relevant opportunities.
4. The application explains the specific overlap behind each recommendation.
5. Faculty marks recommendations relevant or not relevant.
6. Feedback is used to evaluate and improve match quality.

## Prototype setup

The current Grants.gov script is a developer tool, not the faculty-facing
experience:

```powershell
python -m pip install -r requirements.txt
python scripts/pull_grants.py
```

It writes `grants.json` and `grants_raw.json` in the current directory. Use the
bounded form below for development:

```powershell
python scripts/pull_grants.py --search-term catalysis --max-opportunities 3
```

See `PROJECT.md` for the full product rationale, limitations, and roadmap.
See `docs/HOSTING.md` for the boundary between GitHub and the running service.
See `docs/API_VALIDATION.md` for the live Grants.gov findings.

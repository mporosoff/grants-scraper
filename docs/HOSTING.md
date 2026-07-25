# Hosting and deployment

## Decision

`mporosoff/grants-scraper` is the source of truth for application code,
documentation, tests, database migrations, and deployment configuration.

The running application is hosted as a private web site with a durable D1
database. GitHub is the development and review environment; it is not the
production database. Faculty open the deployed URL and do not install Python.

## Current topology

```text
GitHub repository
    |
    | review and tests
    v
Hosted web application  ---->  D1 application database
    |
    +----> Grants.gov public API
    |
    +----> future server-side semantic matching service
```

## What belongs in GitHub

- application and ingestion code
- automated tests
- database schema migrations
- deployment configuration
- non-sensitive documentation
- the static `match_explorer.html` design prototype

## What stays outside GitHub

- faculty profile contents
- normalized production opportunity records
- feedback and match history
- API keys, passwords, and signing secrets
- downloaded NOFO files and other generated datasets

These belong in the deployed database, hosting secret store, or future object
storage. They should never be committed to the repository.

## Access

The first deployment is an owner-only pilot. Sharing with additional faculty
is an explicit access-policy change, not a code change. Before a broader pilot,
confirm the University-approved access group, privacy expectations, data
retention, and support owner.

## GitHub Actions

GitHub Actions runs both the Python normalizer tests and the production web
build. Hosted runners are temporary and must not be treated as durable storage.

## Path to a shared pilot

1. Validate the complete workflow with the owner-only deployment.
2. Label a small set of good and bad faculty-opportunity pairs.
3. Add and evaluate server-side semantic retrieval and reranking.
4. Confirm University access, privacy, and operational ownership.
5. Expand access to a small faculty group and monitor feedback quality.
